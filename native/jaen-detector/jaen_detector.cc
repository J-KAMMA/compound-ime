#include "jaen_detector.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <optional>
#include <string_view>

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
constexpr int64_t kStealCost = 50;      // a word ending in the s of shi, the c of chi, the t of tsu

bool IsAsciiAlpha(char c) { return (c | 0x20) >= 'a' && (c | 0x20) <= 'z'; }
char Lower(char c) { return IsAsciiAlpha(c) ? static_cast<char>(c | 0x20) : c; }
bool IsVowel(char c) { return std::string_view("aiueo").find(Lower(c)) != std::string_view::npos; }

std::optional<std::string> Normalize(std::string_view word) {
  if (word.empty() || word.size() > kMaxWordLength ||
      !std::ranges::all_of(word, [](char c) { return IsAsciiAlpha(c) || c == '\''; }) ||
      !IsAsciiAlpha(word.front())) {
    return std::nullopt;
  }
  std::string lower(word);
  std::ranges::transform(lower, lower.begin(), Lower);
  return lower;
}

int64_t ForeignWeight(const Chunk& chunk);

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
  if (consonant_w || std::ranges::any_of(chunk.conversion + chunk.pending, IsAsciiAlpha)) {
    return kForeignCost;
  }
  // Japanese typists do use these now and then (toxu for とぅ, vi for ゔぃ).
  // wi/we are not signs: loanwords like ウェブ are commonly typed that way.
  const bool small_kana = IsSmallKana(chunk);
  const bool rare_key = !chunk.conversion.empty() &&
                        (head == 'v' || head == 'q' || (head == 'c' && (raw.size() < 2 || Lower(raw[1]) != 'h')));
  return small_kana || rare_key ? kWeakForeignCost : 0;
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

std::vector<Piece> SplitEnglish(const std::vector<Chunk>& chunks, const Lexicon& lexicon,
                                const RomajiParser& parse, const Choices* choices,
                                const ReadingCheck* is_reading) {
  std::string raw;
  std::vector<bool> boundary(1, true);  // boundary[i]: i is an original chunk edge
  std::vector<bool> blocked(1, false);  // blocked[i]: i is inside an x?/l? small kana
  std::vector<bool> no_start(1, false);  // no English word starts at i
  std::vector<bool> no_end(1, false);    // no English word ends at i
  std::vector<std::string> kana;        // the typed kana, one character each
  std::vector<size_t> kana_at(1, 0);    // kana_at[i]: kana count before raw edge i
  for (const Chunk& chunk : chunks) {
    const bool small = IsSmallKana(chunk);
    raw += chunk.raw;
    boundary.resize(raw.size() + 1, false);
    blocked.resize(raw.size() + 1, small);
    no_start.resize(raw.size() + 1, false);
    no_end.resize(raw.size() + 1, false);
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
  }
  const auto kana_text = [&](size_t a, size_t b) {
    std::string out;
    for (size_t k = a; k < b; ++k) out += kana[k];
    return out;
  };
  // A Japanese reading of 3+ kana that starts before the edges [ka, kb) and
  // ends inside, or starts inside and ends after.
  const auto crosses_reading = [&](size_t ka, size_t kb) {
    constexpr size_t kLongest = 8;
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
  const size_t n = raw.size();
  if (n == 0 || n > kMaxRawLength) return {};
  const auto edge_cost = [&](size_t i) { return boundary[i] ? 0 : kCutCost; };

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
      if (boundary[i] && boundary[j] && lexicon.FindPhrase(word)) {
        english[i].emplace_back(j, -kLengthBonus * static_cast<int64_t>(word.size()) - kPhraseBonus);
        continue;
      }
      const Lexicon::Place* place = lexicon.FindPlace(word);
      const bool signal_only = learned == 0 && !place && !lexicon.Contains(word) && lexicon.IsSignalOnly(word);
      if (learned == 0 && !place && !lexicon.Contains(word) && !signal_only) continue;
      const int64_t length = kLengthBonus * static_cast<int64_t>(word.size());
      std::optional<int64_t> cost;
      if (signal_only) {
        if (boundary[i] && boundary[j] && ForeignCost(parse(word)) > 0 && !word_across(i) && !word_across(j)) {
          cost = kSpanCost - length;
        }
      } else if (ForeignCost(parse(word)) > 0) {
        cost = kSpanCost - length;
      } else if (word.size() >= kMinPlainWordLength &&
                 (lexicon.IsCurated(word) ||
                  // Unvetted words: only on the typed chunk edges.
                  (learned >= kPlainChoiceCount && boundary[i] && boundary[j]))) {
        cost = -length;
      } else if (place && boundary[i] && boundary[j] && BeforeParticleOrEnd(raw, j) &&
                 !InsideNormalSpelling(raw, i, j, *place)) {
        cost = -length;
      } else if (is_reading && learned == 0 && !place &&
                 word.size() >= kMinUnreadWordLength && boundary[i] && boundary[j] &&
                 kana_at[j] > kana_at[i] && !(*is_reading)(kana_text(kana_at[i], kana_at[j])) &&
                 !crosses_reading(kana_at[i], kana_at[j]) &&
                 !japanese_grammar(kana_at[i], kana_at[j])) {
        cost = -length;  // a word whose kana is no Japanese reading (remote: れもて)
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
  if (std::ranges::all_of(english, &std::vector<std::pair<size_t, int64_t>>::empty)) return {};

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
  if (std::ranges::none_of(pieces, &Piece::english)) return {};
  return pieces;
}

}  // namespace jaen
