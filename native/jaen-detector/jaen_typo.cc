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

std::vector<UnreadTypoEdit> UnreadTypoEdits(std::string_view raw, const RomajiParser& parse,
                                            const KanaModel& model) {
  // Lowercase romaji only: capitals or ASCII-mode keys are typed on purpose.
  if (raw.empty() || raw.size() > kMaxRawLength ||
      !std::ranges::all_of(raw, [](char c) { return (c >= 'a' && c <= 'z') || c == '-'; })) {
    return {};
  }
  const std::vector<Chunk> typed = parse(raw);
  if (std::ranges::any_of(typed, [](const Chunk& c) {
        return std::ranges::any_of(c.conversion, IsLetter);
      })) {
    return {};
  }
  const size_t first = FirstUnread(typed);
  if (first == std::string::npos) return {};

  // Best score per reading, with the typed keys that gave it.
  std::map<std::string, UnreadTypoEdit> readings;
  const std::string text(raw);
  const auto consider = [&](std::string candidate, bool vowel) {
    if (candidate.empty()) return;
    const std::vector<Chunk> chunks = parse(candidate);
    if (UnreadKeys(chunks) != 0) return;
    std::string kana;
    for (size_t i = 0; i < chunks.size(); ++i) {
      kana += FinalN(chunks, i) ? std::string("ん") : chunks[i].conversion + chunks[i].pending;
    }
    const double score = model.Score(kana) - (vowel ? kVowelPenalty : 0);
    auto [it, added] = readings.try_emplace(kana, UnreadTypoEdit{candidate, kana, score, vowel});
    if (!added && score > it->second.score) it->second = {std::move(candidate), kana, score, vowel};
  };
  // A slip shows up as an unread key at most a few keys later.
  const size_t lo = first >= 3 ? first - 3 : 0;
  const size_t hi = std::min(text.size(), first + 4);
  for (size_t i = lo; i < hi; ++i) {
    for (const char n : Neighbors(text[i])) {
      std::string s = text;
      s[i] = n;
      consider(std::move(s), false);
    }
    if (i + 1 < text.size() && text[i] != text[i + 1]) {
      std::string s = text;
      std::swap(s[i], s[i + 1]);
      consider(std::move(s), false);
    }
    {
      std::string s = text;
      s.erase(i, 1);
      consider(std::move(s), false);
    }
    for (const char v : std::string_view("aiueo")) {
      std::string s = text;
      s.insert(i + 1, 1, v);
      consider(std::move(s), true);
    }
  }
  std::vector<UnreadTypoEdit> out;
  out.reserve(readings.size());
  for (auto& [kana, edit] : readings) out.push_back(std::move(edit));
  return out;
}

std::optional<std::string> FixTypo(std::string_view raw, const RomajiParser& parse,
                                   const KanaModel& model, double margin, double floor) {
  const std::vector<UnreadTypoEdit> edits = UnreadTypoEdits(raw, parse, model);
  const UnreadTypoEdit* best = nullptr;
  double runner_up = -INFINITY;
  for (const UnreadTypoEdit& edit : edits) {
    if (best == nullptr || edit.score > best->score) {
      if (best != nullptr) runner_up = std::max(runner_up, best->score);
      best = &edit;
    } else {
      runner_up = std::max(runner_up, edit.score);
    }
  }
  if (best == nullptr || best->score - runner_up < margin) return std::nullopt;
  // A lone or clear winner must still look like Japanese ("googke" -> ごおけ).
  const double per_character = best->score / static_cast<double>(Characters(best->kana).size() + 1);
  if (per_character < floor) return std::nullopt;
  return best->keys;
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
  // A long vowel left out, also after the first key ("okii" for ookii). Not after an e
  // before another vowel: "dakeatokara" is だけあとから, not だけえあとから ("gakkoe" for
  // gakkoue stays).
  for (size_t i = 0; i < text.size(); ++i) {
    const char c = text[i];
    if (std::string_view("aiueo").find(c) == std::string_view::npos) continue;
    if (c == 'e' && i + 1 < text.size() && std::string_view("aiueo").find(text[i + 1]) != std::string_view::npos) continue;
    std::string longer{c};
    if (c == 'o' || c == 'u') longer = c == 'u' ? "u" : "ou";
    if (c == 'e') longer = "ei";
    for (const char v : longer) {
      std::string s = text;
      s.insert(i + 1, 1, v);
      add(std::move(s), priors.long_vowel);
    }
    if (c == 'a') {  // the i of ai left out
      std::string s = text;
      s.insert(i + 1, 1, 'i');
      add(std::move(s), priors.dropped_ai);
    }
  }
  // The first key is left alone: "ashita" is not "shita" mistyped.
  for (size_t i = 1; i < text.size(); ++i) {
    if (text[i] == text[i - 1]) {  // a key typed twice ("tsuduukete", "hayyaku")
      std::string s = text;
      s.erase(i, 1);
      add(std::move(s), std::string_view("aiueo").find(text[i]) != std::string_view::npos ? priors.doubled_vowel
                        : std::string_view("gzjdb").find(text[i]) != std::string_view::npos ? priors.doubled_voiced
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
    if (priors.dropped_consonant != TypoPriors::kOff &&
        std::string_view("aiueo").find(text[i]) != std::string_view::npos) {
      for (const char c : std::string_view("kstnhmyrwgzdbpj")) {  // a dropped consonant ("kiou")
        std::string s = text;
        s.insert(i, 1, c);
        add(std::move(s), priors.dropped_consonant);
      }
    }
    if (text[i] != text[i - 1] && text[i] != '\'') {
      // A key typed in by mistake ("butsai"): next to a key around it, or any key at extra_key_far.
      const auto touches = [&](size_t j) {
        return j < text.size() && Neighbors(text[j]).find(text[i]) != std::string_view::npos;
      };
      const int prior = touches(i - 1) || touches(i + 1) ? priors.extra_key : priors.extra_key_far;
      // A lone c, q or v after a mora and before a particle is the letter itself ("cwomotto": cをもっと),
      // not a key typed in by mistake: these keys start no kana before w, g, h, n, d, t or m.
      const bool lone_letter = std::string_view("cqv").find(text[i]) != std::string_view::npos &&
                               std::string_view("aiueon").find(text[i - 1]) != std::string_view::npos &&
                               StartsWithParticleSpelling(std::string_view(text).substr(i + 1));
      if (prior != TypoPriors::kOff && !lone_letter) {
        std::string s = text;
        s.erase(i, 1);
        add(std::move(s), prior);
      }
    }
  }
  std::vector<TypoEdit> out;
  for (auto& [kana, edit] : found) out.push_back(std::move(edit));
  return out;
}

bool StartsWithParticleSpelling(std::string_view keys) {
  constexpr std::string_view kParticles[] = {"no", "ni", "de", "wo", "ga", "wa", "ha", "to", "mo", "he", "ya"};
  return std::ranges::any_of(kParticles, [&](std::string_view p) { return keys.starts_with(p); });
}

std::optional<std::pair<size_t, size_t>> EnglishRunBetweenJapanese(std::string_view raw,
                                                                   const std::vector<Piece>& pieces) {
  size_t first = pieces.size(), last = pieces.size();
  for (size_t i = 0; i < pieces.size(); ++i) {
    if (!pieces[i].english) continue;
    if (first == pieces.size()) {
      first = i;
    } else if (last + 1 != i) {
      return std::nullopt;  // two English runs: not one slip
    }
    last = i;
  }
  if (first == pieces.size() || first == 0 || last + 1 >= pieces.size()) return std::nullopt;
  const size_t begin = pieces[first].begin, end = pieces[last].end;
  if (end >= raw.size() || StartsWithParticleSpelling(raw.substr(end))) return std::nullopt;
  return std::pair{begin, end};
}

bool EditNear(std::string_view raw, std::string_view fixed, size_t begin, size_t end) {
  if (raw == fixed) return false;
  size_t head = 0;
  while (head < raw.size() && head < fixed.size() && raw[head] == fixed[head]) ++head;
  size_t tail = 0;
  while (tail < raw.size() - head && tail < fixed.size() - head &&
         raw[raw.size() - 1 - tail] == fixed[fixed.size() - 1 - tail]) {
    ++tail;
  }
  // The keys of |raw| the edit changed (empty for a key put in): [head, raw.size() - tail).
  return head + 1 >= begin && raw.size() - tail <= end + 1;
}

std::vector<std::string_view> SplitLongRomaji(std::string_view run, size_t max, size_t min) {
  std::vector<std::string_view> parts;
  if (max == 0) return {run};
  const auto vowel = [](char c) { return std::string_view("aiueo").find(c) != std::string_view::npos; };
  // How good a cut before run[p] is: 2 after "wo", 1 after another particle, 0
  // after any other vowel, -1 where no cut may go (inside a syllable, before ー,
  // ', a vowel or y, or before a doubled consonant (っ: kitte)).
  const auto rank = [&](std::string_view text, size_t p) {
    if (p < 2 || p >= text.size() || !vowel(text[p - 1])) return -1;
    const char next = text[p];
    if (next < 'a' || next > 'z' || vowel(next) || next == 'y') return -1;
    if (p + 1 < text.size() && text[p + 1] == next) return -1;
    const std::string_view before = text.substr(p - 2, 2);
    if (before == "wo") return 2;
    for (const std::string_view particle : {"ga", "ni", "de", "ha", "wa", "no", "to", "mo", "he"}) {
      if (before == particle) return 1;
    }
    return 0;
  };
  // The best cut in [low, high]: the highest rank, then the longest part.
  const auto find = [&](std::string_view text, size_t low, size_t high, int* best_rank) {
    size_t best = 0;
    *best_rank = -1;
    for (size_t p = high; p >= low && p >= 2; --p) {
      if (text.size() - p < min) continue;  // the part after it would be too short
      const int r = rank(text, p);
      if (r > *best_rank) {
        *best_rank = r;
        best = p;
      }
    }
    return best;
  };
  std::string_view rest = run;
  while (rest.size() > max) {
    const size_t high = std::min(max, rest.size() - 1);
    // A cut in the second half of the part first, so that parts stay long.
    int best_rank = -1;
    size_t best = find(rest, std::max(min, high / 2), high, &best_rank);
    if (best_rank < 0) best = find(rest, std::max<size_t>(min, 2), high, &best_rank);
    if (best_rank < 0) {
      // No cut after a vowel: leave the rest whole (the fixers skip it, as before).
      break;
    }
    parts.push_back(rest.substr(0, best));
    rest.remove_prefix(best);
  }
  parts.push_back(rest);
  return parts;
}

}  // namespace jaen
