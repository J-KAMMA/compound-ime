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
                                const RomajiParser& parse, const Choices* choices) {
  std::string raw;
  std::vector<bool> boundary(1, true);  // boundary[i]: i is an original chunk edge
  std::vector<bool> blocked(1, false);  // blocked[i]: i is inside an x?/l? small kana
  for (const Chunk& chunk : chunks) {
    const bool small = IsSmallKana(chunk);
    raw += chunk.raw;
    boundary.resize(raw.size() + 1, false);
    blocked.resize(raw.size() + 1, small);
    boundary[raw.size()] = true;
    blocked[raw.size()] = false;
  }
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

  // English candidates by start position: (end, cost).
  std::vector<std::vector<std::pair<size_t, int64_t>>> english(n);
  for (size_t i = 0; i < n; ++i) {
    if (blocked[i]) continue;
    for (size_t j = i + 1; j <= std::min(n, i + kMaxWordLength); ++j) {
      if (blocked[j]) continue;  // never split っ typed as xtu, ぅ as xu, ...
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
      const Lexicon::Place* place = lexicon.FindPlace(word);
      if (learned == 0 && !place && !lexicon.Contains(word)) continue;
      const int64_t length = kLengthBonus * static_cast<int64_t>(word.size());
      std::optional<int64_t> cost;
      if (ForeignCost(parse(word)) > 0) {
        cost = kSpanCost - length;
      } else if (word.size() >= kMinPlainWordLength &&
                 (lexicon.IsCurated(word) ||
                  // Unvetted words: only on the typed chunk edges.
                  (learned >= kPlainChoiceCount && boundary[i] && boundary[j]))) {
        cost = -length;
      } else if (place && boundary[i] && boundary[j] && BeforeParticleOrEnd(raw, j) &&
                 !InsideNormalSpelling(raw, i, j, *place)) {
        cost = -length;
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
      pieces.back().begin = b.from;  // merge adjacent English words
    } else {
      pieces.push_back({b.from, j, b.english});
    }
    j = b.from;
    s = b.state;
  }
  std::ranges::reverse(pieces);
  if (std::ranges::none_of(pieces, &Piece::english)) return {};
  return pieces;
}

}  // namespace jaen
