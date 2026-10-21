#include "jaen_detector.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <optional>
#include <string_view>
#include <unordered_map>

namespace jaen {
namespace {

constexpr size_t kMaxWordLength = 32;
constexpr size_t kMaxRawLength = 256;   // longer compositions are left alone
constexpr int64_t kForeignCost = 1000;  // per foreign chunk left in Japanese
constexpr int64_t kWeakForeignCost = 150;  // per rare-but-Japanese chunk (one word may beat it)
constexpr int64_t kSpanCost = 100;      // minus kLengthBonus per letter
constexpr int64_t kLengthBonus = 3;     // longer words win ("sheet|wo" over "shee|two")
constexpr int64_t kCutCost = 5;         // English edge inside an original chunk
constexpr int64_t kPhraseBonus = 20;    // a set phrase wins over its words read apart
constexpr int64_t kLeadingParticleCost = 30;  // 助詞で始まる語（deform）より、助詞と残りの語（de + form）
constexpr int64_t kStealCost = 50;     // a word ending in the s of shi, the c of chi, the t of tsu
constexpr size_t kMinCompoundLength = 8;  // opencode: 2語（open + code）のつながりを1語の英語と見る最小の長さ
constexpr size_t kMinCompoundPart = 4;    // つながりの各語の最小の長さ
constexpr int64_t kCompoundPenalty = 3;   // 2語ずつ取れる分け方より少し高い

// 日本語に読める略語（ai: あい、ui: うい、seo: せお）。打った並びが全部かなに読めるので、
// 英字が残る略語（api、url、html）と違い、検出器は印を見つけられない。略語の次に助詞が続き、
// そのあとが技術の語（つかう、どうにゅう ...）のとき（型 b、方式 cue）、または日本語の語としては使わない
// 並び（seo、ipo）に助詞か文の終わりが続くとき（方式 plain）だけ、英語にする。愛を感じる・会いに行く、は
// 日本語のまま。表は tools/data/acronyms.tsv と acronym-cues.tsv から tools/build_acronym_table.py が書く。
struct ReadableAcronym {
  std::string_view typed;
  bool plain;                  // 手がかりなしで、助詞か文の終わりが続けばよい
  std::string_view extra_cues;  // この略語だけの手がかり（かな、コンマ区切り）
};
// BEGIN GENERATED acronyms (tools/build_acronym_table.py)
constexpr ReadableAcronym kReadableAcronyms[] = {
    {"ai", false, ""},
    {"fifa", true, ""},
    {"gafa", true, ""},
    {"gui", false, "そうさ,ひょうじ,せってい,さくせい,かいはつ"},
    {"ide", false, "せってい,きどう,ぷらぐいん,いんすとーる"},
    {"ime", false, "きりかえ,せってい,にゅうりょく,へんかん"},
    {"ipo", true, ""},
    {"iso", false, "にんしょう,しゅとく,きかく,きじゅん,しんさ"},
    {"roi", false, "けいさん,さんしゅつ,とうし,さいだいか"},
    {"seo", true, ""},
    {"uae", true, ""},
    {"ui", false, "ひょうじ,でざいん,がめん,ぼたん,かいぜん,へんこう"},
};
constexpr std::string_view kAcronymCues =
    "つかう,つかっ,つかい,つかわ,どうにゅう,かつよう,かいはつ,がくしゅう,せいせい,とうさい,しつもん,そうだん,しんか,はってん,ふきゅう,ぎじゅつ,せいのう,せいど,かいとう,しゅつりょく,にゅうりょく,もでる,ちゃっと,がぞう,ぶんしょう,こーど,ようやく,ほんやく,じどうか,こうりつ,べんり,かしこ,まちがえ,さくせい,はんだん,よそく,かいせき,うばう,うばわ,おきかわ,たいおう,たいわ,かいわ,そうさ,せっけい,じっそう";
// END GENERATED acronyms
constexpr size_t kMaxAcronymLength = 4;   // kReadableAcronyms の打つ形の最大の長さ
constexpr size_t kAcronymCueWindow = 12;  // 助詞の次から読むかなの数（手がかりは、この先頭に合わせる）

bool IsAsciiAlpha(char c) { return (c | 0x20) >= 'a' && (c | 0x20) <= 'z'; }
char Lower(char c) { return IsAsciiAlpha(c) ? static_cast<char>(c | 0x20) : c; }
bool IsVowel(char c) { return std::string_view("aiueo").find(Lower(c)) != std::string_view::npos; }

bool IsAsciiDigit(char c) { return c >= '0' && c <= '9'; }

const ReadableAcronym* FindReadableAcronym(std::string_view word) {
  if (word.size() > kMaxAcronymLength) return nullptr;
  for (const ReadableAcronym& acronym : kReadableAcronyms) {
    if (acronym.typed.size() == word.size() &&
        std::ranges::equal(acronym.typed, word, [](char a, char b) { return a == Lower(b); })) {
      return &acronym;
    }
  }
  return nullptr;
}

// |text| starts with one of the comma separated kana stems in |cues|.
bool StartsWithCue(std::string_view text, std::string_view cues) {
  for (size_t start = 0; start < cues.size();) {
    size_t end = cues.find(',', start);
    if (end == std::string_view::npos) end = cues.size();
    const std::string_view cue = cues.substr(start, end - start);
    if (!cue.empty() && text.starts_with(cue)) return true;
    start = end + 1;
  }
  return false;
}

// Letters and ' (a word), or digits and letters with a letter in them (3d, mp3).
std::optional<std::string> Normalize(std::string_view word) {
  if (word.empty() || word.size() > kMaxWordLength ||
      !std::ranges::all_of(word, [](char c) { return IsAsciiAlpha(c) || IsAsciiDigit(c) || c == '\''; }) ||
      !(IsAsciiAlpha(word.front()) || IsAsciiDigit(word.front())) || std::ranges::none_of(word, IsAsciiAlpha)) {
    return std::nullopt;
  }
  std::string lower(word);
  std::ranges::transform(lower, lower.begin(), Lower);
  return lower;
}


int64_t ForeignWeight(const Chunk& chunk);
bool IsKanaForLoanword(const Chunk& chunk);

// A small kana typed with x?/l? (ぁ, っ, ゃ ...); "xn" for ん is not one.
bool IsSmallKana(const Chunk& chunk) {
  if (chunk.raw.empty() || (Lower(chunk.raw[0]) != 'x' && Lower(chunk.raw[0]) != 'l')) return false;
  static constexpr std::string_view kSmall[] = {"ぁ", "ぃ", "ぅ", "ぇ", "ぉ", "っ", "ゃ", "ゅ", "ょ", "ゎ", "ゕ", "ゖ"};
  return std::ranges::find(kSmall, std::string_view(chunk.conversion)) != std::end(kSmall);
}

int64_t ForeignCost(const std::vector<Chunk>& chunks) {
  int64_t cost = 0;
  for (size_t i = 0; i < chunks.size(); ++i) {
    cost += ForeignWeight(chunks[i]);
    // ん then a doubled-key っ ("meeting|ga" read as めえてぃんっが) hardly
    // occurs in Japanese; it is an English word ending in -ng/-nk/... before
    // a kana starting with the same consonant.
    if (i > 0 && chunks[i].conversion.starts_with("っ") && !IsSmallKana(chunks[i]) &&
        chunks[i - 1].conversion.ends_with("ん")) {
      cost += kWeakForeignCost;
    }
  }
  return cost;
}

}  // namespace

std::string NormalizeWord(std::string_view word) { return Normalize(word).value_or(""); }

void Lexicon::Add(std::string_view word, bool curated) {
  if (auto lower = Normalize(word)) words_[*std::move(lower)] |= curated;
}

bool Lexicon::Contains(std::string_view word) const {
  const auto lower = Normalize(word);
  return lower && words_.contains(*lower);
}

void Lexicon::AddPlace(std::string_view spelling, std::string_view surface,
                       std::string_view standard) {
  const auto lower = Normalize(spelling);
  if (!lower || surface.empty()) return;
  Place& place = places_[*lower];
  if (place.surface.empty()) place.surface = std::string(surface);
  if (const auto normal = Normalize(standard)) place.standards.push_back(*normal);
}

const Lexicon::Place* Lexicon::FindPlace(std::string_view spelling) const {
  const auto lower = Normalize(spelling);
  const auto it = lower ? places_.find(*lower) : places_.end();
  return it == places_.end() ? nullptr : &it->second;
}

void Lexicon::AddJoined(std::string_view word) {
  if (auto lower = Normalize(word)) joined_.insert(*std::move(lower));
}

bool Lexicon::IsJoined(std::string_view word) const {
  const auto lower = Normalize(word);
  return lower && joined_.contains(*lower);
}

void Lexicon::AddSignalOnly(std::string_view word) {
  if (auto lower = Normalize(word); lower && !words_.contains(*lower)) signal_only_.insert(*std::move(lower));
}

void Lexicon::AddNamed(std::string_view word) {
  if (auto lower = Normalize(word); lower && !words_.contains(*lower)) {
    signal_only_.insert(*lower);
    named_.insert(*std::move(lower));
  }
}

bool Lexicon::IsNamed(std::string_view word) const {
  const auto lower = Normalize(word);
  return lower && named_.contains(*lower);
}

void Lexicon::AddCommon(std::string_view word) {
  if (auto lower = Normalize(word)) common_.insert(*std::move(lower));
}

bool Lexicon::IsCommon(std::string_view word) const {
  const auto lower = Normalize(word);
  return lower && common_.contains(*lower);
}

bool Lexicon::IsSignalOnly(std::string_view word) const {
  const auto lower = Normalize(word);
  return lower && signal_only_.contains(*lower);
}

void Lexicon::AddPhrase(std::string_view phrase) {
  std::string joined;
  std::vector<size_t> spaces;
  for (size_t start = 0; start <= phrase.size();) {
    size_t end = phrase.find(' ', start);
    if (end == std::string_view::npos) end = phrase.size();
    const auto word = Normalize(phrase.substr(start, end - start));
    if (!word) return;
    if (!joined.empty()) spaces.push_back(joined.size());
    joined += *word;
    start = end + 1;
  }
  if (!spaces.empty() && joined.size() <= kMaxWordLength) phrases_[joined] = std::move(spaces);
}

const std::vector<size_t>* Lexicon::FindPhrase(std::string_view typed) const {
  const auto lower = Normalize(typed);
  // One word as written together ("login", "frontend", "takeout") is no phrase.
  if (!lower || words_.contains(*lower) || joined_.contains(*lower)) return nullptr;
  const auto it = phrases_.find(*lower);
  return it == phrases_.end() ? nullptr : &it->second;
}

bool Lexicon::IsCurated(std::string_view word) const {
  const auto lower = Normalize(word);
  const auto it = lower ? words_.find(*lower) : words_.end();
  return it != words_.end() && it->second;
}

namespace {
int64_t ForeignWeight(const Chunk& chunk) {
  if (chunk.conversion.empty() && (chunk.pending == "n" || chunk.pending == "N")) return 0;
  const std::string_view raw = chunk.raw;
  const char head = raw.empty() ? '\0' : Lower(raw[0]);
  const bool consonant_w = raw.size() == 3 && Lower(raw[1]) == 'w' && IsVowel(raw[2]) &&
                           IsAsciiAlpha(raw[0]) && !IsVowel(raw[0]) && head != 'w';
  // "two" read as とぉ is English ("seat|wo"); twu/dwu/kwa (トゥ, ドゥ, クァ) are
  // how loanwords are typed (タトゥー): only a weak sign.
  if ((consonant_w && Lower(raw[2]) == 'o') ||
      std::ranges::any_of(chunk.conversion + chunk.pending, IsAsciiAlpha)) {
    return kForeignCost;
  }
  // c not in ch (ca for か) is a weak sign too, but never typed for a
  // Japanese word's kana: "camera" is English, a Japanese typist types kamera.
  const bool c_key = !chunk.conversion.empty() && head == 'c' && (raw.size() < 2 || Lower(raw[1]) != 'h');
  return IsKanaForLoanword(chunk) || c_key ? kWeakForeignCost : 0;
}

// A chunk Japanese typists use now and then for a loanword's kana: a small
// kana typed with x/l (toxu for とぅ), v (vi for ゔぃ), q, or consonant+w+vowel
// other than wo (twu for とぅ). wi/we are not among them: loanwords like ウェブ
// are commonly typed that way.
bool IsKanaForLoanword(const Chunk& chunk) {
  const std::string_view raw = chunk.raw;
  if (raw.empty() || chunk.conversion.empty()) return false;
  const char head = Lower(raw[0]);
  const bool consonant_w = raw.size() == 3 && Lower(raw[1]) == 'w' && IsVowel(raw[2]) &&
                           Lower(raw[2]) != 'o' && IsAsciiAlpha(raw[0]) && !IsVowel(raw[0]) && head != 'w';
  return IsSmallKana(chunk) || consonant_w || head == 'v' || head == 'q';
}
}  // namespace

bool IsForeignChunk(const Chunk& chunk) { return ForeignWeight(chunk) > 0; }

namespace {
// "tokyo|ni": a particle (or nothing) follows a place name.
bool BeforeParticleOrEnd(std::string_view raw, size_t at) {
  static constexpr std::string_view kParticles[] = {"ni", "de", "he", "ha", "no", "wo", "ga", "kara",
                                                     "made", "to", "mo", "ya"};
  const std::string_view rest = raw.substr(at);
  return rest.empty() || std::ranges::any_of(kParticles, [&](std::string_view p) {
           return rest.size() >= p.size() && Normalize(rest.substr(0, p.size())) == std::string(p);
         });
}

// "hokkaido" inside "hokkaidou", "osaka" inside "oosaka".
bool InsideNormalSpelling(std::string_view raw, size_t begin, size_t end, const Lexicon::Place& place) {
  std::string lower(raw);
  std::ranges::transform(lower, lower.begin(), Lower);
  for (const std::string& normal : place.standards) {
    for (size_t at = lower.find(normal); at != std::string::npos; at = lower.find(normal, at + 1)) {
      if (at <= begin && end <= at + normal.size()) return true;
    }
  }
  return false;
}
}  // namespace


// ---- 文脈で決める段（|japanese| を渡されたとき）----
const ContextCosts& DefaultContextCosts() {
  static const ContextCosts costs{/*word_base=*/2500, /*per_letter=*/300, /*rare_extra=*/3000, /*common_bonus=*/800,
                                  /*run_start=*/2000, /*run_end=*/0, /*short_extra=*/1000, /*particle_extra=*/2000, /*one_letter_extra=*/3000, /*margin=*/2000, /*alone_margin=*/3500};
  return costs;
}

namespace {
constexpr uint32_t kEnglishState = 0x10000;  // 直前が英単語（品詞番号とは別の状態）
constexpr size_t kLatticeBeam = 30;

// 助詞の綴り（ローマ字で打った形）。英語の to、no、he、me でもあるが、日本語の助詞として読むほうを取らせる。
bool IsParticleSpelling(std::string_view word) {
  static constexpr std::string_view kParticles[] = {"ha", "ga", "wo", "ni", "no", "de", "to", "mo", "he", "ya", "ka", "wa", "ne", "yo"};
  return std::ranges::any_of(kParticles, [&](std::string_view p) { return Normalize(word) == std::string(p); });
}

struct EnglishEdge {
  size_t from = 0, to = 0;  // かなの位置（番号）
  int64_t cost = 0;
};
struct LatticeResult {
  int64_t cost = std::numeric_limits<int64_t>::max();
  std::vector<size_t> used;  // 使った英語の辺（edges の番号）
};

// かなの並び（off はかな1文字ごとのバイト位置と終わり）を、日本語の辞書の語と、渡された英語の辺で
// 読む一番安い費用。converter_readable_typo.inc の ReadingCost と同じ計算（語の費用＋接続の費用、
// 各位置で安い30状態、どの語も読まないかなは名詞 unknown_cost）に、英単語の辺を足したもの。
// after_english / before_english: 前後が英語のとき、文の頭・終わりの代わりに名詞とつなぐ。
// 英語から英語への切り替えは費用なし、日本語から英語へは名詞との接続の費用に run_start を足す。
LatticeResult RunLattice(const JapaneseModel& model, std::string_view kana, const std::vector<size_t>& off,
                         const std::vector<std::vector<JapaneseWord>>& words_at, const std::vector<EnglishEdge>& edges,
                         bool after_english, bool before_english, int run_start, int run_end) {
  struct Node {
    int64_t cost = 0;
    size_t prev_pos = 0;
    uint32_t prev_state = 0;
    int64_t edge = -1;
  };
  const size_t m = off.size() - 1;
  std::vector<size_t> index_of(kana.size() + 1, std::numeric_limits<size_t>::max());
  for (size_t k = 0; k <= m; ++k) index_of[off[k]] = k;
  std::vector<std::unordered_map<uint32_t, Node>> best(m + 1);
  const auto trans = [&](uint32_t state, uint16_t lid) {
    return static_cast<int64_t>(model.transition(state == kEnglishState ? model.noun : static_cast<uint16_t>(state), lid));
  };
  best[0][after_english ? kEnglishState : 0] = Node{};
  const auto relax = [&](size_t q, uint32_t state, const Node& node) {
    auto [it, added] = best[q].try_emplace(state, node);
    if (!added && node.cost < it->second.cost) it->second = node;
  };
  std::vector<std::vector<size_t>> edges_at(m + 1);
  for (size_t e = 0; e < edges.size(); ++e) edges_at[edges[e].from].push_back(e);
  for (size_t p = 0; p < m; ++p) {
    auto& here = best[p];
    if (here.empty()) continue;
    if (here.size() > kLatticeBeam) {
      std::vector<std::pair<int64_t, uint32_t>> order;
      for (const auto& [state, node] : here) order.emplace_back(node.cost, state);
      std::nth_element(order.begin(), order.begin() + kLatticeBeam, order.end());
      for (size_t k = kLatticeBeam; k < order.size(); ++k) here.erase(order[k].second);
    }
    for (const auto& [state, node] : here) {
      const int64_t leave = state == kEnglishState ? run_end : 0;  // 英語から日本語に戻る
      for (const JapaneseWord& w : words_at[p]) {
        const size_t q = off[p] + w.bytes <= kana.size() ? index_of[off[p] + w.bytes] : std::numeric_limits<size_t>::max();
        if (q == std::numeric_limits<size_t>::max()) continue;
        relax(q, w.rid, Node{node.cost + w.cost + trans(state, w.lid) + leave, p, state, -1});
      }
      relax(p + 1, model.noun, Node{node.cost + model.unknown_cost + trans(state, model.noun) + leave, p, state, -1});
      for (const size_t e : edges_at[p]) {
        const int64_t enter = state == kEnglishState ? 0 : trans(state, model.noun) + run_start;
        relax(edges[e].to, kEnglishState, Node{node.cost + edges[e].cost + enter, p, state, static_cast<int64_t>(e)});
      }
    }
  }
  LatticeResult result;
  uint32_t final_state = 0;
  for (const auto& [state, node] : best[m]) {
    int64_t end;
    if (before_english) {
      end = state == kEnglishState ? 0 : trans(state, model.noun) + run_start;
    } else {
      end = trans(state == kEnglishState ? model.noun : static_cast<uint16_t>(state), 0);
    }
    if (node.cost + end < result.cost) {
      result.cost = node.cost + end;
      final_state = state;
    }
  }
  if (result.cost == std::numeric_limits<int64_t>::max()) return result;
  size_t pos = m;
  uint32_t state = final_state;
  while (pos > 0) {
    const Node& node = best[pos].at(state);
    if (node.edge >= 0) result.used.push_back(static_cast<size_t>(node.edge));
    pos = node.prev_pos;
    state = node.prev_state;
  }
  std::ranges::reverse(result.used);
  return result;
}
}  // namespace

namespace {
struct ChunkMarks {
  std::string raw;
  std::vector<bool> boundary, blocked, no_start, no_end, unread, small_start;
  std::vector<bool> edge;  // 打った文字の区切りそのもの（boundary は、かなの塊の中の切れ目も含む）
  std::vector<std::string> kana, kana_all;
  std::vector<size_t> kana_at, kana_all_at;
};

// 打った文字の区切り（かなの塊の切れ目）と、そこで英語の語を切ってよいかの印、かなの並び。
ChunkMarks MarkChunks(const std::vector<Chunk>& chunks) {
  std::string raw;
  std::vector<bool> edge(1, true);
  std::vector<bool> boundary(1, true);  // boundary[i]: i is an original chunk edge
  std::vector<bool> blocked(1, false);  // blocked[i]: i is inside an x?/l? small kana
  std::vector<bool> no_start(1, false);  // no English word starts at i
  std::vector<bool> no_end(1, false);    // no English word ends at i
  std::vector<bool> unread;              // unread[k]: raw key k was left unread (no kana)
  std::vector<bool> small_start(1, false);  // small_start[i]: a loanword kana chunk (IsKanaForLoanword) starts at i
  std::vector<std::string> kana;        // the typed kana, one character each
  std::vector<size_t> kana_at(1, 0);    // kana_at[i]: kana count before raw edge i
  std::vector<std::string> kana_all;    // 文脈で決める段用: 上と同じで、最後の n（ん）も入れる
  std::vector<size_t> kana_all_at(1, 0);
  for (const Chunk& chunk : chunks) {
    const bool small = IsSmallKana(chunk);
    raw += chunk.raw;
    boundary.resize(raw.size() + 1, false);
    edge.resize(raw.size() + 1, false);
    edge[raw.size()] = true;
    // A doubled l (the っ of "shell|wo", chunk "llw") is no small kana typed with l: a word may end inside it.
    blocked.resize(raw.size() + 1, small && !(chunk.raw.size() >= 2 && Lower(chunk.raw[0]) == Lower(chunk.raw[1])));
    no_start.resize(raw.size() + 1, false);
    no_end.resize(raw.size() + 1, false);
    unread.resize(raw.size(), chunk.conversion.empty());
    small_start.resize(raw.size() + 1, false);
    small_start[raw.size() - chunk.raw.size()] = IsKanaForLoanword(chunk);
    boundary[raw.size()] = true;
    blocked[raw.size()] = false;
    // Chunks the romaji table formed across a word's last letter count their
    // inner edges as chunk edges too:
    const std::string_view r = chunk.raw;
    const size_t start = raw.size() - r.size();
    const auto consonant = [](char c) { return IsAsciiAlpha(c) && !IsVowel(c); };
    if (chunk.conversion.empty()) {
      // keys still waiting for more ("ts" of "set|shita", "xw" of "ux|wo",
      // "lw" of "mail|wo"): no kana is cut there.
      for (size_t k = 1; k < r.size(); ++k) boundary[start + k] = true;
    } else if (r.size() == 3 && consonant(r[0]) && Lower(r[0]) != 'w' && Lower(r[0]) != 'n' &&
               Lower(r[1]) == 'w' && Lower(r[2]) == 'o') {
      boundary[start + 1] = true;  // "two" read as とぉ: "seat|wo", "git|wo"
    } else if (r.size() == 3 && consonant(r[0]) && Lower(r[0]) != 's' && Lower(r[0]) != 'c' &&
               Lower(r[1]) == 'h' && IsVowel(r[2])) {
      boundary[start + 1] = true;  // "dhe" read as でぇ: "madrid|he"
    } else if (r.size() == 2 && Lower(r[0]) == 'x' && Lower(r[1]) == 'n' && chunk.conversion == "ん") {
      boundary[start + 1] = true;  // "xn" read as ん: "codex|ni", "tmux|ni"
      no_start[start + 1] = true;
    } else if (r.size() == 2 && Lower(r[0]) == 'n' && Lower(r[1]) == 'n') {
      boundary[start + 1] = true;  // "nn" read as ん: "berlin|ni", "darwin|no"
      no_start[start + 1] = true;  // but no word starts at its second n ("matijikan|ntt|e")
    }
    // A doubled key and a vowel read as っ+kana ("tte" って): a word may end
    // after the first key ("meeting|ga" in gga) but not before the vowel
    // ("ntt|e"). Longer chunks ("ppye" of "happy|ending") are left alone.
    if (chunk.conversion.starts_with("っ") && !small && r.size() == 3 && Lower(r[0]) == Lower(r[1]) &&
        IsVowel(r[2])) {
      no_end[start + 2] = true;
    }
    for (size_t at = 0; at < chunk.conversion.size();) {
      const unsigned char lead = chunk.conversion[at];
      const size_t len = lead < 0x80 ? 1 : lead < 0xE0 ? 2 : lead < 0xF0 ? 3 : 4;
      kana.push_back(chunk.conversion.substr(at, len));
      at += len;
    }
    kana_at.resize(raw.size() + 1, kana_at.back());
    kana_at[raw.size()] = kana.size();
    for (size_t at = 0; at < chunk.conversion.size();) {
      const unsigned char lead = chunk.conversion[at];
      const size_t len = lead < 0x80 ? 1 : lead < 0xE0 ? 2 : lead < 0xF0 ? 3 : 4;
      kana_all.push_back(chunk.conversion.substr(at, len));
      at += len;
    }
    if (chunk.conversion.empty() && (chunk.pending == "n" || chunk.pending == "N")) kana_all.push_back("ん");
    kana_all_at.resize(raw.size() + 1, kana_all_at.back());
    kana_all_at[raw.size()] = kana_all.size();
  }
  ChunkMarks marks;
  marks.raw = std::move(raw);
  marks.boundary = std::move(boundary);
  marks.edge = std::move(edge);
  marks.blocked = std::move(blocked);
  marks.no_start = std::move(no_start);
  marks.no_end = std::move(no_end);
  marks.unread = std::move(unread);
  marks.small_start = std::move(small_start);
  marks.kana = std::move(kana);
  marks.kana_all = std::move(kana_all);
  marks.kana_at = std::move(kana_at);
  marks.kana_all_at = std::move(kana_all_at);
  return marks;
}

}  // namespace

std::vector<Piece> SplitEnglish(const std::vector<Chunk>& chunks, const Lexicon& lexicon,
                                const RomajiParser& parse, const Choices* choices,
                                const ReadingCheck* is_reading,
                                const ReadingCheck* reads_naturally,
                                const JapaneseModel* japanese_model,
                                const ContextCosts* context_costs) {
  ChunkMarks marks = MarkChunks(chunks);
  const std::string& raw = marks.raw;
  const std::vector<bool>& boundary = marks.boundary;
  const std::vector<bool>& blocked = marks.blocked;
  const std::vector<bool>& no_start = marks.no_start;
  const std::vector<bool>& no_end = marks.no_end;
  const std::vector<bool>& unread = marks.unread;
  const std::vector<bool>& small_start = marks.small_start;
  const std::vector<std::string>& kana = marks.kana;
  const std::vector<size_t>& kana_at = marks.kana_at;
  const auto kana_text = [&](size_t a, size_t b) {
    std::string out;
    for (size_t k = a; k < b; ++k) out += kana[k];
    return out;
  };
  // A Japanese reading of 3+ kana that starts before the edges [ka, kb) and
  // ends inside, or starts inside and ends after, or holds them and runs past
  // one (ばせい over "base" in baseiwo, よごれ over "gore", にがて over "gate").
  const auto crosses_reading = [&](size_t ka, size_t kb) {
    constexpr size_t kLongest = 8;
    for (size_t a = ka >= kLongest ? ka - kLongest : 0; a <= ka; ++a) {
      for (size_t b = std::max(kb, a + 3); b <= kana.size() && b - a <= kLongest; ++b) {
        if ((a < ka || b > kb) && (*is_reading)(kana_text(a, b))) return true;
      }
    }
    for (size_t a = ka >= kLongest ? ka - kLongest : 0; a < ka; ++a) {
      for (size_t b = ka + 1; b < kb && b - a <= kLongest; ++b) {
        if (b - a >= 3 && (*is_reading)(kana_text(a, b))) return true;
      }
    }
    for (size_t a = ka + 1; a < kb; ++a) {
      for (size_t b = kb + 1; b <= kana.size() && b - a <= kLongest; ++b) {
        if (b - a >= 3 && (*is_reading)(kana_text(a, b))) return true;
      }
    }
    return false;
  };
  // Kana that reads as Japanese grammar rather than a word: を inside
  // (otowokesu: "woke"), a て-form ending (mattei: "matte"), or a reading
  // that runs in from before and leaves only a particle (kawade: "wade").
  const auto japanese_grammar = [&](size_t ka, size_t kb) {
    for (size_t k = ka; k < kb; ++k) {
      if (kana[k] == "を") return true;
    }
    if (kb - ka >= 2 && kana[kb - 1] == "て" && kana[kb - 2] == "っ") return true;
    static constexpr std::string_view kParticles[] = {"で", "に", "を", "は", "が", "と", "も", "へ", "の"};
    if (kb - ka >= 2 && std::ranges::find(kParticles, kana[kb - 1]) != std::end(kParticles)) {
      for (size_t a = ka >= 6 ? ka - 6 : 0; a < ka; ++a) {
        if (kb - 1 - a >= 2 && (*is_reading)(kana_text(a, kb - 1))) return true;
      }
    }
    return false;
  };
  // A loanword kana k (IsKanaForLoanword) joining the kana before it in a
  // Japanese reading of 3+ kana (うぉ of うぉれっと typed "ulo", ゔぃ of へゔぃめたる
  // typed "hevi"): the keys were typed for that kana. Not one starting at k:
  // "video" read as ゔぃでお is English.
  const auto small_in_reading = [&](size_t k) {
    if (!is_reading) return false;
    constexpr size_t kLongest = 8;
    for (size_t a = k >= kLongest ? k - kLongest : 0; a < k; ++a) {
      for (size_t b = std::max(k + 1, a + 3); b <= kana.size() && b - a <= kLongest; ++b) {
        if ((*is_reading)(kana_text(a, b))) return true;
      }
    }
    return false;
  };
  const size_t n = raw.size();
  if (n == 0 || n > kMaxRawLength) return {};
  const auto edge_cost = [&](size_t i) { return boundary[i] ? 0 : kCutCost; };

  // 日本語に読める略語（kReadableAcronyms）を [i, j) で英語にしてよいか。両端は打った文字の区切りの上。
  // 略語を含む日本語の読み（こういを の いを ではなく、行為 の こうい）の途中は、辞書があれば取らない。
  const auto acronym_taken = [&](const ReadableAcronym& acronym, size_t i, size_t j) {
    const size_t ka = kana_at[i];
    const size_t kb = kana_at[j];
    if (kb <= ka || (is_reading && crosses_reading(ka, kb))) return false;
    struct Particle { std::string_view key; std::string_view kana; };
    static constexpr Particle kParticles[] = {{"wo", "を"}, {"ga", "が"}, {"ha", "は"}, {"de", "で"},
                                              {"ni", "に"}, {"no", "の"}, {"to", "と"}, {"mo", "も"}};
    bool particle = false;
    if (j + 2 <= n && boundary[j + 2] && kb < kana.size() && kana_at[j + 2] == kb + 1) {
      for (const Particle& p : kParticles) {
        if (Lower(raw[j]) == p.key[0] && Lower(raw[j + 1]) == p.key[1] && kana[kb] == p.kana) particle = true;
      }
    }
    if (acronym.plain) {
      static constexpr std::string_view kStops[] = {"。", "、", "！", "？"};
      return particle || j == n ||
             (kb < kana.size() && std::ranges::find(kStops, std::string_view(kana[kb])) != std::end(kStops));
    }
    if (!particle) return false;
    const std::string after = kana_text(kb + 1, std::min(kana.size(), kb + 1 + kAcronymCueWindow));
    return StartsWithCue(after, kAcronymCues) || StartsWithCue(after, acronym.extra_cues);
  };

  // Occurrences of words the user turned back into Japanese; no English word
  // is taken inside one ("ogle" in "google"), but longer words still are.
  std::vector<std::pair<size_t, size_t>> japanese;
  if (choices && !choices->japanese.empty()) {
    for (size_t i = 0; i < n; ++i) {
      for (size_t j = i + 1; j <= std::min(n, i + kMaxWordLength); ++j) {
        if (choices->japanese.contains(NormalizeWord(std::string_view(raw).substr(i, j - i)))) {
          japanese.emplace_back(i, j);
        }
      }
    }
  }
  const auto inside_japanese = [&](size_t i, size_t j) {
    return std::ranges::any_of(japanese, [&](const auto& r) { return r.first <= i && j <= r.second; });
  };

  // A lexicon word of 3+ letters running over edge e of a span ("dog" over
  // the start of "gand" in dogandcat): a rarer word there is not taken.
  const auto word_across = [&](size_t e) {
    for (size_t a = e >= kMaxWordLength ? e - kMaxWordLength : 0; a < e; ++a) {
      for (size_t b = std::max(e + 1, a + 3); b <= std::min(n, a + kMaxWordLength); ++b) {
        // Only the second n of "nn" past the edge ("inn" over "berlin|ni").
        if (b == e + 1 && Lower(raw[e - 1]) == 'n' && Lower(raw[e]) == 'n') continue;
        if (lexicon.Contains(std::string_view(raw).substr(a, b - a))) return true;
      }
    }
    return false;
  };

  // English candidates by start position: (end, cost).
  std::vector<std::vector<std::pair<size_t, int64_t>>> english(n);
  for (size_t i = 0; i < n; ++i) {
    if (blocked[i] || no_start[i]) continue;
    for (size_t j = i + 1; j <= std::min(n, i + kMaxWordLength); ++j) {
      if (blocked[j] || no_end[j]) continue;  // never split っ typed as xtu, ぅ as xu, ...
      if (inside_japanese(i, j)) continue;
      // c or t before "ch" is the っ of っち ("nec" in necchuu, "pet" in
      // petchi): no English word ends there. Other doubled keys stay possible
      // edges ("blog" + "ga", "lunch" + "ha").
      if (j < n && (raw[j - 1] == 'c' || raw[j - 1] == 't') && raw.compare(j, 2, "ch") == 0) continue;
      const std::string_view word = std::string_view(raw).substr(i, j - i);
      int learned = 0;
      if (choices && !choices->english.empty()) {
        const auto it = choices->english.find(NormalizeWord(word));
        if (it != choices->english.end() && it->second >= kEnglishChoiceCount) {
          learned = it->second;
        }
      }
      // A set phrase on chunk edges ("seeyou", "madeinjapan") is one piece.
      // A listed word with digits (3d, 4k, mp3) is one piece like a set phrase:
      // "3d|purinnta-" (3Dプリンター), not "dpu" (DPU) after a ３.
      if (boundary[i] && boundary[j] && std::ranges::any_of(word, IsAsciiDigit) && lexicon.Contains(word)) {
        english[i].emplace_back(j, -kLengthBonus * static_cast<int64_t>(word.size()) - kPhraseBonus);
        continue;
      }
      if (boundary[i] && boundary[j] && lexicon.FindPhrase(word)) {
        english[i].emplace_back(j, -kLengthBonus * static_cast<int64_t>(word.size()) - kPhraseBonus);
        continue;
      }
      // Four or more keys in a row the table could not read ("jpyc" of
      // jpycdake): an unknown abbreviation or name, kept as typed.
      // The run is not taken when a listed word of 3+ letters is the run without its last
      // one or two keys (wsl|wo: the w of wo waits in the chunk "lw"; "wslw" is no name).
      bool listed_prefix = false;
      for (size_t k = 1; k <= 2 && word.size() >= 3 + k; ++k) {
        listed_prefix = listed_prefix || lexicon.Contains(word.substr(0, word.size() - k));
      }
      if (word.size() >= 4 && boundary[i] && boundary[j] && !listed_prefix &&
          std::all_of(unread.begin() + i, unread.begin() + j, [](bool u) { return u; })) {
        english[i].emplace_back(j, kSpanCost - kLengthBonus * static_cast<int64_t>(word.size()));  // as a word with a foreign sign: a listed word wins (chatgpt)
        continue;
      }
      // 日本語に読める略語（ai の あい）: 助詞と技術の語が続くとき、英語の語として取る（打った並びに印がないので、
      // 負の費用で日本語の読みに勝たせる。語は表示の形が先頭に出る: ai → AI）。
      if (learned == 0 && boundary[i] && boundary[j] && word.size() <= kMaxAcronymLength) {
        if (const ReadableAcronym* acronym = FindReadableAcronym(word); acronym && acronym_taken(*acronym, i, j)) {
          english[i].emplace_back(j, -kLengthBonus * static_cast<int64_t>(word.size()) - kPhraseBonus);
          continue;
        }
      }
      const Lexicon::Place* place = lexicon.FindPlace(word);
      const bool signal_only = learned == 0 && !place && !lexicon.Contains(word) && lexicon.IsSignalOnly(word);
      // 2語のつながり（opencode = open + code）: 一覧にない語でも、長さと切れ目の条件を満たし、
      // どちらの語も普通の英単語か厳選した語なら、下で「かなが日本語の読みでない」ことを確かめて取る。
      // 切れ目は打った文字の区切りで、各語のかなも日本語の読みでないこと（firefox + demo の「でも」は読み）。
      bool compound = false;
      if (learned == 0 && !place && is_reading && !signal_only && word.size() >= kMinCompoundLength &&
          boundary[i] && boundary[j] && !lexicon.Contains(word)) {
        const auto usable = [&](std::string_view part) {
          return lexicon.Contains(part) && (lexicon.IsCommon(part) || lexicon.IsCurated(part));
        };
        for (size_t cut = kMinCompoundPart; cut + kMinCompoundPart <= word.size() && !compound; ++cut) {
          const size_t e = i + cut;
          if (!boundary[e] || kana_at[e] <= kana_at[i] || kana_at[j] <= kana_at[e]) continue;
          if (!usable(word.substr(0, cut)) || !usable(word.substr(cut))) continue;
          compound = !(*is_reading)(kana_text(kana_at[i], kana_at[e])) && !(*is_reading)(kana_text(kana_at[e], kana_at[j]));
        }
      }
      if (learned == 0 && !place && !lexicon.Contains(word) && !signal_only && !compound) continue;
      // Its only sign is a small kana typed for a Japanese word ("lore" in
      // ato|ulo|retto, あとうぉれっと): no word.
      if (learned == 0) {
        const int64_t sign = ForeignCost(parse(word));
        bool typed_for_japanese = false;
        for (size_t p = i; p < j && !typed_for_japanese; ++p) {
          typed_for_japanese = small_start[p] && small_in_reading(kana_at[p]);
        }
        // A word starting at such a small kana ("lair" in fu|la|iru, ふぁいる)
        // takes it from its kana whatever else it has (the r left waiting).
        const bool starts_there = small_start[i] && small_in_reading(kana_at[i]);
        // 厳選した語（ブランド名など）が7文字以上なら、前の助詞とのかな（は + ぁ + ん）に取られない
        // （halangchain: langchain）。偶然の一致は、これだけ長いと起きにくい。
        const bool vetted_long = word.size() >= 7 && lexicon.IsCurated(word);
        if (!vetted_long && (starts_there || (sign > 0 && sign < kForeignCost && typed_for_japanese))) continue;
      }
      const int64_t length = kLengthBonus * static_cast<int64_t>(word.size());
      std::optional<int64_t> cost;
      if (compound) {
        if (kana_at[j] > kana_at[i] && !(*is_reading)(kana_text(kana_at[i], kana_at[j])) &&
            !crosses_reading(kana_at[i], kana_at[j]) && !japanese_grammar(kana_at[i], kana_at[j])) {
          // 1語ずつ取れる2語（commit + message）の分け方に負けるよう、少し高くする。
          cost = (ForeignCost(parse(word)) > 0 ? kSpanCost - length : -length) + kCompoundPenalty;
        }
      } else if (signal_only) {
        const bool named = word.size() >= 6 && lexicon.IsNamed(word);
        if (boundary[i] && boundary[j] && ForeignCost(parse(word)) > 0 && (named || (!word_across(i) && !word_across(j)))) {
          cost = kSpanCost - length;
        }
      } else if (const int64_t sign = ForeignCost(parse(word)); sign > 0) {
        // 弱い印（x? で打った小さい仮名など、日本語でも打つ形）だけの語は、打った文字の
        // 区切りに沿うときだけ英語にする。ねぇ を nexe と打ったとき、ne の途中から
        // exe を切り出して ん + EXE にしない。強い印（日本語の打ち方にない形）の語は
        // 今までどおり区切りの途中からも取る（seat|wo の two）。
        if (sign >= kForeignCost || (boundary[i] && boundary[j])) cost = kSpanCost - length;
      } else if (word.size() >= kMinPlainWordLength &&
                 (lexicon.IsCurated(word) ||
                  // Unvetted words: only on the typed chunk edges.
                  (learned >= kPlainChoiceCount && boundary[i] && boundary[j]))) {
        cost = -length;
      } else if (place && boundary[i] && boundary[j] && BeforeParticleOrEnd(raw, j) &&
                 !InsideNormalSpelling(raw, i, j, *place)) {
        cost = -length;
      } else if (is_reading && learned == 0 && !place &&
                 word.size() >= (lexicon.IsCurated(word) ? kMinCuratedUnreadWordLength : kMinUnreadWordLength) &&
                 boundary[i] && boundary[j] &&
                 kana_at[j] > kana_at[i] && (!(*is_reading)(kana_text(kana_at[i], kana_at[j])) ||
                  (reads_naturally && (lexicon.IsCommon(word) || lexicon.IsCurated(word)) &&
                   !(*reads_naturally)(kana_text(kana_at[i], kana_at[j])))) &&
                 !crosses_reading(kana_at[i], kana_at[j]) &&
                 !japanese_grammar(kana_at[i], kana_at[j])) {
        cost = -length;  // a word whose kana is no Japanese reading (remote: れもて)
      }
      // 助詞で始まる語（市役所 de form の "deform"）: 直前が日本語（助詞でない）で、
      // 助詞を打った鍵がそのまま 1 文字の仮名で、残りが 4 文字以上の別の語なら、
      // 助詞と残りの語に分けるほうを選びやすくする。よく使う語（design）、
      // 手で選んだ語、「default」のような助詞の後に来ない語はそのまま。
      if (cost && learned == 0 && !place && i > 0 && word.size() >= 6 && !unread[i - 1] &&
          kana_at[i] > 0 && !lexicon.IsCurated(word) && !lexicon.IsCommon(word)) {
        struct Particle { std::string_view key; std::string_view kana; };
        static constexpr Particle kLeading[] = {{"de", "で"}, {"ni", "に"}, {"wo", "を"}, {"ga", "が"},
                                                {"ha", "は"}, {"to", "と"}, {"mo", "も"}, {"no", "の"},
                                                {"ya", "や"}, {"he", "へ"}};
        static constexpr std::string_view kKeepWhole[] = {"default", "decode", "delimit", "denote", "devote"};
        static constexpr std::string_view kParticleKana[] = {"で", "に", "を", "は", "が", "と", "も", "へ", "の", "や"};
        const std::string lower = [&] {
          std::string s(word);
          std::ranges::transform(s, s.begin(), Lower);
          return s;
        }();
        for (const Particle& p : kLeading) {
          const size_t e = i + p.key.size();
          if (!lower.starts_with(p.key) || lower.size() - p.key.size() < 4 || e >= j || !boundary[e]) continue;
          if (kana_at[e] != kana_at[i] + 1 || kana[kana_at[i]] != p.kana) continue;
          if (std::ranges::find(kParticleKana, kana[kana_at[i] - 1]) != std::end(kParticleKana)) continue;
          if (std::ranges::find(kKeepWhole, lower) != std::end(kKeepWhole)) continue;
          if (lexicon.Contains(lower.substr(p.key.size()))) *cost += kLeadingParticleCost;
          break;
        }
      }
      // A word ending in the first letter of sh, ch or tsu, when the word
      // without it is a word too ("sets|hita": the s of shi), likely took it
      // from the kana after it: "set|shita" wins; "campus|ha" stays.
      if (cost && j < n && word.size() > 3 && lexicon.Contains(word.substr(0, word.size() - 1))) {
        const char last = Lower(raw[j - 1]);
        const char after = Lower(raw[j]);
        if (((last == 's' || last == 'c') && after == 'h') ||
            (last == 't' && after == 's' && j + 1 < n && Lower(raw[j + 1]) == 'u')) {
          *cost += kStealCost;
        }
      }
      if (cost) english[i].emplace_back(j, *cost + edge_cost(i) + edge_cost(j));
    }
  }
  if (!japanese_model && std::ranges::all_of(english, &std::vector<std::pair<size_t, int64_t>>::empty)) return {};

  // State 0: last piece English (or start); state 1: last piece Japanese.
  constexpr int64_t kInf = std::numeric_limits<int64_t>::max();
  struct Back { size_t from = 0; int state = 0; bool english = false; };
  std::vector<std::array<int64_t, 2>> best(n + 1, {kInf, kInf});
  std::vector<std::array<Back, 2>> back(n + 1);
  best[0][0] = 0;
  for (size_t i = 0; i < n; ++i) {
    for (int s = 0; s < 2; ++s) {
      if (best[i][s] == kInf) continue;
      const auto relax = [&](size_t j, int t, int64_t cost, bool is_english) {
        if (best[i][s] + cost < best[j][t]) {
          best[j][t] = best[i][s] + cost;
          back[j][t] = {i, s, is_english};
        }
      };
      for (const auto& [j, cost] : english[i]) relax(j, 0, cost, true);
      if (s == 1) continue;  // Japanese pieces are maximal
      for (size_t j = i + 1; j <= n; ++j) {
        if (j == n || !english[j].empty()) {
          relax(j, 1, ForeignCost(parse(std::string_view(raw).substr(i, j - i))), false);
        }
      }
    }
  }
  std::vector<Piece> pieces;
  int s = best[n][0] <= best[n][1] ? 0 : 1;
  for (size_t j = n; j > 0;) {
    const Back b = back[j][s];
    if (!pieces.empty() && b.english && pieces.back().english) {
      // Merge adjacent English words; a space between two words whose
      // concatenation is no word ("weekly report", not "down load").
      const size_t first_end = pieces.back().spaces.empty() ? pieces.back().end : pieces.back().spaces.back();
      const std::string_view joined = std::string_view(raw).substr(b.from, first_end - b.from);
      if (!lexicon.Contains(joined) && !lexicon.IsJoined(joined)) pieces.back().spaces.push_back(j);
      pieces.back().begin = b.from;
    } else {
      pieces.push_back({b.from, j, b.english});
    }
    // The spaces inside a set phrase ("see you"), in descending order.
    if (b.english) {
      if (const std::vector<size_t>* inside = lexicon.FindPhrase(std::string_view(raw).substr(b.from, j - b.from))) {
        for (size_t k = inside->size(); k-- > 0;) pieces.back().spaces.push_back(b.from + (*inside)[k]);
      }
    }
    j = b.from;
    s = b.state;
  }
  std::ranges::reverse(pieces);
  if (japanese_model && japanese_model->prefix_words && japanese_model->transition) {
    const ContextCosts& costs = context_costs ? *context_costs : DefaultContextCosts();
    // 英語にしていない日本語の部分（gap）ごとに、その部分だけを打ち直したものとして、一覧の語のつながり
    // （英語の「走り」）を英語にしてよいか決める。走りは、打った文字の区切りから区切りまでを一覧の語で
    // 隙間なく埋められる部分（語どうしの境は区切りの途中でもよい）。1語だけの走りが、ローマ字として
    // 日本語に読める英単語（made、take）にあたる。
    struct Run {
      size_t begin = 0, end = 0;  // gap の中の打った文字の位置
      std::vector<size_t> cuts;   // 語の境（begin より後、end より前）
    };
    const auto decide = [&](const Piece& gap, bool after_english, bool before_english) -> std::vector<Piece> {
      const size_t len = gap.end - gap.begin;
      const std::string sub = raw.substr(gap.begin, len);
      const ChunkMarks local = MarkChunks(parse(sub));
      if (local.raw != sub || local.kana_all.empty()) return {gap};
      // 各位置から始まる一覧の語（終わりの位置、費用）
      struct Word { size_t end; int64_t cost; };
      std::vector<std::vector<Word>> words_at(len);
      bool any_word = false;
      for (size_t y = 0; y < len; ++y) {
        for (size_t l = 1; l <= std::min(kMaxWordLength, len - y); ++l) {
          const std::string_view word = std::string_view(sub).substr(y, l);
          if (!IsAsciiAlpha(word.back())) break;
          if (inside_japanese(gap.begin + y, gap.begin + y + l)) continue;
          if (l == 1 && Lower(word[0]) != 'a' && Lower(word[0]) != 'i') continue;
          const bool listed = lexicon.Contains(word);
          if (!listed && !(lexicon.IsSignalOnly(word) && !lexicon.IsNamed(word))) continue;
          int64_t cost = costs.word_base + costs.per_letter * static_cast<int64_t>(l);
          if (l <= 2) cost += costs.short_extra;
          if (l == 1) cost += costs.one_letter_extra;
          if (l == 2 && IsParticleSpelling(word)) cost += costs.particle_extra;
          if (!listed) cost += costs.rare_extra;
          if (listed && (lexicon.IsCommon(word) || lexicon.IsCurated(word))) cost -= costs.common_bonus;
          words_at[y].push_back({y + l, cost});
          any_word = true;
        }
      }
      if (!any_word) return {gap};
      std::vector<Run> runs;
      std::vector<EnglishEdge> edges;
      constexpr int64_t kNone = std::numeric_limits<int64_t>::max();
      constexpr size_t kMaxEdges = 4000;
      for (size_t x = 0; x < len && edges.size() < kMaxEdges; ++x) {
        if (!local.edge[x] || local.blocked[x] || local.no_start[x] || words_at[x].empty()) continue;
        std::vector<int64_t> dp(len + 1, kNone);
        std::vector<size_t> prev(len + 1, 0);
        dp[x] = 0;
        for (size_t y = x; y < len; ++y) {
          if (dp[y] == kNone) continue;
          for (const Word& w : words_at[y]) {
            if (dp[y] + w.cost < dp[w.end]) {
              dp[w.end] = dp[y] + w.cost;
              prev[w.end] = y;
            }
          }
        }
        for (size_t e = x + 1; e <= len; ++e) {
          if (dp[e] == kNone || !local.edge[e] || local.blocked[e] || local.no_end[e] ||
              local.kana_all_at[e] <= local.kana_all_at[x]) {
            continue;
          }
          if (e - x <= 2) continue;  // 1〜2文字だけの走り（no、to）は、日本語の助詞のほうを取る
          Run run{x, e, {}};
          for (size_t at = prev[e]; at > x; at = prev[at]) run.cuts.push_back(at);
          std::ranges::reverse(run.cuts);
          // 走りの最初や最後が助詞の綴り（ha、no）や a は、日本語の助詞を英語に取り込んだ形（polka dot ha）
          const size_t first_end = run.cuts.empty() ? e : run.cuts.front();
          const size_t last_begin = run.cuts.empty() ? x : run.cuts.back();
          const std::string_view first_word = std::string_view(sub).substr(x, first_end - x);
          const std::string_view last_word = std::string_view(sub).substr(last_begin, e - last_begin);
          if (IsParticleSpelling(first_word) || IsParticleSpelling(last_word) ||
              (last_word.size() == 1 && Lower(last_word[0]) == 'a')) {
            continue;
          }
          runs.push_back(std::move(run));
          edges.push_back({local.kana_all_at[x], local.kana_all_at[e], dp[e]});
        }
      }
      if (edges.empty()) return {gap};
      std::string text;
      std::vector<size_t> off;
      for (const std::string& k : local.kana_all) {
        off.push_back(text.size());
        text += k;
      }
      off.push_back(text.size());
      std::vector<std::vector<JapaneseWord>> dictionary_words(off.size() - 1);
      for (size_t p = 0; p + 1 < off.size(); ++p) {
        japanese_model->prefix_words(std::string_view(text).substr(off[p]), &dictionary_words[p]);
      }
      const LatticeResult plain =
          RunLattice(*japanese_model, text, off, dictionary_words, {}, after_english, before_english, costs.run_start, costs.run_end);
      const LatticeResult mixed =
          RunLattice(*japanese_model, text, off, dictionary_words, edges, after_english, before_english, costs.run_start, costs.run_end);
      if (mixed.used.empty()) return {gap};
      // 英単語1語だけで、英語の隣でもない（日本語の文の中の1語）なら、日本語としても読めるので、決め手を厳しくする。
      const bool alone = mixed.used.size() == 1 && runs[mixed.used[0]].cuts.empty() && !after_english && !before_english;
      if (mixed.cost + (alone ? costs.alone_margin : costs.margin) >= plain.cost) return {gap};
      std::vector<Piece> result;
      size_t at = 0;
      for (const size_t e : mixed.used) {
        const Run& run = runs[e];
        if (run.begin > at) result.push_back({gap.begin + at, gap.begin + run.begin, false, {}});
        Piece piece{gap.begin + run.begin, gap.begin + run.end, true, {}};
        // 語の境のうち、つないだ形が単語でないところは空白で表示する（降順）
        std::vector<size_t> bounds{run.begin};
        bounds.insert(bounds.end(), run.cuts.begin(), run.cuts.end());
        bounds.push_back(run.end);
        for (size_t w = 1; w + 1 < bounds.size(); ++w) {
          const std::string_view joined = std::string_view(sub).substr(bounds[w - 1], bounds[w + 1] - bounds[w - 1]);
          if (!lexicon.Contains(joined) && !lexicon.IsJoined(joined)) piece.spaces.push_back(gap.begin + bounds[w]);
        }
        std::ranges::reverse(piece.spaces);
        result.push_back(std::move(piece));
        at = run.end;
      }
      if (at < len) result.push_back({gap.begin + at, gap.end, false, {}});
      return result;
    };
    std::vector<Piece> out;
    for (size_t k = 0; k < pieces.size(); ++k) {
      if (pieces[k].english) {
        out.push_back(pieces[k]);
        continue;
      }
      const bool after_english = !out.empty() && out.back().english;
      const bool before_english = k + 1 < pieces.size() && pieces[k + 1].english;
      for (Piece& piece : decide(pieces[k], after_english, before_english)) out.push_back(std::move(piece));
    }
    // 隣り合う英語をつなぐ。つないだ形が単語でなければ、つなぎ目に空白を入れる。
    pieces.clear();
    for (const Piece& piece : out) {
      if (!pieces.empty() && pieces.back().english && piece.english) {
        Piece& left = pieces.back();
        const size_t last_begin = left.spaces.empty() ? left.begin : left.spaces.front();
        const size_t first_end = piece.spaces.empty() ? piece.end : piece.spaces.back();
        const std::string_view joined = std::string_view(raw).substr(last_begin, first_end - last_begin);
        std::vector<size_t> spaces = piece.spaces;
        if (!lexicon.Contains(joined) && !lexicon.IsJoined(joined)) spaces.push_back(piece.begin);
        spaces.insert(spaces.end(), left.spaces.begin(), left.spaces.end());
        left.spaces = std::move(spaces);
        left.end = piece.end;
      } else {
        pieces.push_back(piece);
      }
    }
  }
  if (std::ranges::none_of(pieces, &Piece::english)) return {};
  return pieces;
}

}  // namespace jaen
