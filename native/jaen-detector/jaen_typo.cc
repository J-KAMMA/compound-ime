#include "jaen_typo.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <map>

namespace jaen {
namespace {

constexpr size_t kMaxRawLength = 64;
constexpr double kAlpha = 0.5;       // add-alpha smoothing
constexpr double kVocabulary = 90;   // hiragana, ー and the end mark
constexpr double kVowelPenalty = 1;  // a missing vowel is a less common slip

bool IsLetter(char c) { return (c | 0x20) >= 'a' && (c | 0x20) <= 'z'; }

// QWERTY keys next to each lowercase letter (same row and the rows touching it).
std::string_view Neighbors(char c) {
  static constexpr std::array<std::string_view, 26> kNeighbors = {
      "qwsz",    "vghn",   "xdfv",   "serfcx", "wsdr",   "drtgvc", "ftyhbv", "gyujnb", "ujko",
      "huikmn",  "jiolm",  "kop",    "njk",    "bhjm",   "iklp",   "ol",     "wa",     "edft",
      "awedxz",  "rfgy",   "yhji",   "cfgb",   "qase",   "zsdc",   "tghu",   "asx"};
  const char lower = static_cast<char>(c | 0x20);
  return lower >= 'a' && lower <= 'z' ? kNeighbors[lower - 'a'] : std::string_view();
}

bool FinalN(const std::vector<Chunk>& chunks, size_t i) {
  const Chunk& c = chunks[i];
  return i + 1 == chunks.size() && c.conversion.empty() && (c.pending == "n" || c.pending == "N");
}

// Index of the first raw key in a chunk with unread letters, or npos.
size_t FirstUnread(const std::vector<Chunk>& chunks) {
  size_t at = 0;
  for (size_t i = 0; i < chunks.size(); ++i) {
    if (!FinalN(chunks, i) &&
        std::ranges::any_of(chunks[i].conversion + chunks[i].pending, IsLetter)) {
      return at;
    }
    at += chunks[i].raw.size();
  }
  return std::string::npos;
}

std::vector<std::string> Characters(std::string_view text) {
  std::vector<std::string> out;
  for (size_t i = 0; i < text.size();) {
    const auto b = static_cast<unsigned char>(text[i]);
    const size_t len = b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
    out.emplace_back(text.substr(i, len));
    i += len;
  }
  return out;
}

}  // namespace

KanaModel::KanaModel(std::span<const KanaTrigram> trigrams) {
  for (const KanaTrigram& t : trigrams) {
    trigrams_[t.text] += t.count;
    const std::vector<std::string> c = Characters(t.text);
    if (c.size() == 3) contexts_[c[0] + c[1]] += t.count;
  }
}

double KanaModel::Score(std::string_view kana) const {
  std::vector<std::string> c = Characters(kana);
  c.insert(c.begin(), 2, "^");
  c.emplace_back("$");
  double score = 0;
  for (size_t i = 2; i < c.size(); ++i) {
    const std::string context = c[i - 2] + c[i - 1];
    const auto t = trigrams_.find(context + c[i]);
    const auto x = contexts_.find(context);
    const double hit = t == trigrams_.end() ? 0 : t->second;
    const double total = x == contexts_.end() ? 0 : x->second;
    score += std::log((hit + kAlpha) / (total + kAlpha * kVocabulary));
  }
  return score;
}

int UnreadKeys(const std::vector<Chunk>& chunks) {
  int unread = 0;
  for (size_t i = 0; i < chunks.size(); ++i) {
    if (FinalN(chunks, i)) continue;
    unread += static_cast<int>(
        std::ranges::count_if(chunks[i].conversion + chunks[i].pending, IsLetter));
  }
  return unread;
}

std::optional<std::string> FixTypo(std::string_view raw, const RomajiParser& parse,
                                   const KanaModel& model, double margin, double floor) {
  // Lowercase romaji only: capitals or ASCII-mode keys are typed on purpose.
  if (raw.empty() || raw.size() > kMaxRawLength ||
      !std::ranges::all_of(raw, [](char c) { return (c >= 'a' && c <= 'z') || c == '-'; })) {
    return std::nullopt;
  }
  const std::vector<Chunk> typed = parse(raw);
  if (std::ranges::any_of(typed, [](const Chunk& c) {
        return std::ranges::any_of(c.conversion, IsLetter);
      })) {
    return std::nullopt;
  }
  const size_t first = FirstUnread(typed);
  if (first == std::string::npos) return std::nullopt;

  // Best score per reading, with the typed keys that gave it.
  std::map<std::string, std::pair<double, std::string>> readings;
  const std::string text(raw);
  const auto consider = [&](std::string candidate, double penalty) {
    if (candidate.empty()) return;
    const std::vector<Chunk> chunks = parse(candidate);
    if (UnreadKeys(chunks) != 0) return;
    std::string kana;
    for (size_t i = 0; i < chunks.size(); ++i) {
      kana += FinalN(chunks, i) ? std::string("ん") : chunks[i].conversion + chunks[i].pending;
    }
    const double score = model.Score(kana) - penalty;
    auto [it, added] = readings.try_emplace(kana, score, candidate);
    if (!added && score > it->second.first) it->second = {score, std::move(candidate)};
  };
  // A slip shows up as an unread key at most a few keys later.
  const size_t lo = first >= 3 ? first - 3 : 0;
  const size_t hi = std::min(text.size(), first + 4);
  for (size_t i = lo; i < hi; ++i) {
    for (const char n : Neighbors(text[i])) {
      std::string s = text;
      s[i] = n;
      consider(std::move(s), 0);
    }
    if (i + 1 < text.size() && text[i] != text[i + 1]) {
      std::string s = text;
      std::swap(s[i], s[i + 1]);
      consider(std::move(s), 0);
    }
    {
      std::string s = text;
      s.erase(i, 1);
      consider(std::move(s), 0);
    }
    for (const char v : std::string_view("aiueo")) {
      std::string s = text;
      s.insert(i + 1, 1, v);
      consider(std::move(s), kVowelPenalty);
    }
  }
  auto best = readings.end();
  double runner_up = -INFINITY;
  for (auto it = readings.begin(); it != readings.end(); ++it) {
    if (best == readings.end() || it->second.first > best->second.first) {
      if (best != readings.end()) runner_up = std::max(runner_up, best->second.first);
      best = it;
    } else {
      runner_up = std::max(runner_up, it->second.first);
    }
  }
  if (best == readings.end() || best->second.first - runner_up < margin) return std::nullopt;
  // A lone or clear winner must still look like Japanese ("googke" -> ごおけ).
  const double per_character =
      best->second.first / static_cast<double>(Characters(best->first).size() + 1);
  if (per_character < floor) return std::nullopt;
  return best->second.second;
}

std::vector<TypoEdit> ReadableTypoEdits(std::string_view raw, const RomajiParser& parse,
                                        const TypoPriors& priors) {
  if (raw.size() < 4 || raw.size() > kMaxRawLength ||
      !std::ranges::all_of(raw, [](char c) { return (c >= 'a' && c <= 'z') || c == '\''; })) {
    return {};
  }
  // Kana of fully read keys, or nullopt.
  const auto reading = [&](std::string_view keys) -> std::optional<std::string> {
    const std::vector<Chunk> chunks = parse(keys);
    if (UnreadKeys(chunks) != 0) return std::nullopt;
    std::string kana;
    for (size_t i = 0; i < chunks.size(); ++i) {
      kana += FinalN(chunks, i) ? std::string("ん") : chunks[i].conversion + chunks[i].pending;
    }
    return kana;
  };
  const std::optional<std::string> typed = reading(raw);
  if (!typed || typed->empty()) return {};
  // Small vowels (ふぁ, うぃ) are a foreign word typed as spelled ("fashion",
  // "wifi"), not a slip in Japanese.
  for (const std::string_view small : {"ぁ", "ぃ", "ぅ", "ぇ", "ぉ", "ゎ", "ゔ"}) {
    if (typed->find(small) != std::string::npos) return {};
  }

  // The cheapest kind per distinct reading.
  std::map<std::string, TypoEdit> found;
  const std::string text(raw);
  // x and l type small kana on purpose; no fix brings one in ("nizyuu" is not
  // "nixyuu", にゅう).
  const auto small_keys = [](std::string_view keys) {
    return std::ranges::count_if(keys, [](char c) { return c == 'x' || c == 'l'; });
  };
  const auto typed_small_keys = small_keys(raw);
  const auto add = [&](std::string keys, int prior) {
    if (small_keys(keys) > typed_small_keys) return;
    std::optional<std::string> kana = reading(keys);
    if (!kana || kana->empty() || *kana == *typed) return;
    const auto it = found.find(*kana);
    if (it == found.end() || prior < it->second.prior) {
      found[*kana] = {std::move(keys), *kana, prior};
    }
  };
  // A long vowel left out, also after the first key ("okii" for ookii).
  for (size_t i = 0; i < text.size(); ++i) {
    const char c = text[i];
    if (std::string_view("aiueo").find(c) == std::string_view::npos) continue;
    std::string longer{c};
    if (c == 'o' || c == 'u') longer = c == 'u' ? "u" : "ou";
    if (c == 'e') longer = "ei";
    for (const char v : longer) {
      std::string s = text;
      s.insert(i + 1, 1, v);
      add(std::move(s), priors.long_vowel);
    }
  }
  // The first key is left alone: "ashita" is not "shita" mistyped.
  for (size_t i = 1; i < text.size(); ++i) {
    if (text[i] == text[i - 1]) {  // a key typed twice ("tsuduukete", "hayyaku")
      std::string s = text;
      s.erase(i, 1);
      add(std::move(s), std::string_view("aiueo").find(text[i]) != std::string_view::npos ? priors.doubled_vowel
                                                                   : priors.doubled_consonant);
    }
    // Neighbors swapped ("kareu"); "uo" to ou costs more (see swapped_uo), and
    // ou is never made uo. The ' of n' is no key to swap.
    if (i + 1 < text.size() && text[i] != text[i + 1] && text[i] != '\'' && text[i + 1] != '\'' &&
        text.compare(i, 2, "ou") != 0) {
      std::string s = text;
      std::swap(s[i], s[i + 1]);
      add(std::move(s), text.compare(i, 2, "uo") == 0 ? priors.swapped_uo : priors.swapped);
    }
    // One key too many ("arukite"); not the x/l of a small kana, nor ' or -.
    if (std::string_view("xl'-").find(text[i]) == std::string_view::npos) {
      std::string s = text;
      s.erase(i, 1);
      add(std::move(s), priors.extra_key);
    }
    for (const char n : Neighbors(text[i])) {  // a key next to the right one ("kiagi")
      std::string s = text;
      s[i] = n;
      add(std::move(s), priors.neighbor);
    }
    for (const char v : std::string_view("aiueo")) {  // a dropped vowel ("kyoha")
      std::string s = text;
      s.insert(i + 1, 1, v);
      add(std::move(s), priors.dropped_vowel);
    }
  }
  std::vector<TypoEdit> out;
  for (auto& [kana, edit] : found) out.push_back(std::move(edit));
  return out;
}

}  // namespace jaen
