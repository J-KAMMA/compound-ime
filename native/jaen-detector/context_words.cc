#include "context_words.h"

#include <algorithm>
#include <cstdint>
#include <map>
#include <utility>

namespace jaen {
namespace {

// Code points of UTF-8 |text| with the byte offset of each, and the end offset.
void Decode(std::string_view text, std::vector<char32_t>* chars, std::vector<size_t>* offsets) {
  for (size_t i = 0; i < text.size();) {
    const auto b = static_cast<unsigned char>(text[i]);
    const size_t len = b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
    char32_t c = len == 1 ? b : len == 2 ? (b & 0x1F) : len == 3 ? (b & 0x0F) : (b & 0x07);
    for (size_t k = 1; k < len && i + k < text.size(); ++k) {
      c = (c << 6) | (static_cast<unsigned char>(text[i + k]) & 0x3F);
    }
    chars->push_back(c);
    offsets->push_back(i);
    i += len;
  }
  offsets->push_back(text.size());
}

void Append(char32_t c, std::string* out) {
  if (c < 0x80) {
    out->push_back(static_cast<char>(c));
  } else if (c < 0x800) {
    out->push_back(static_cast<char>(0xC0 | (c >> 6)));
    out->push_back(static_cast<char>(0x80 | (c & 0x3F)));
  } else if (c < 0x10000) {
    out->push_back(static_cast<char>(0xE0 | (c >> 12)));
    out->push_back(static_cast<char>(0x80 | ((c >> 6) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | (c & 0x3F)));
  } else {
    out->push_back(static_cast<char>(0xF0 | (c >> 18)));
    out->push_back(static_cast<char>(0x80 | ((c >> 12) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | ((c >> 6) & 0x3F)));
    out->push_back(static_cast<char>(0x80 | (c & 0x3F)));
  }
}

bool IsKanji(char32_t c) {
  return (c >= 0x4E00 && c <= 0x9FFF) || (c >= 0x3400 && c <= 0x4DBF) || (c >= 0xF900 && c <= 0xFAFF) ||
         (c >= 0x20000 && c <= 0x3134F) || c == 0x3005 /* 々 */ || c == 0x3006 /* 〆 */;
}
// ァ..ヺ and ー (not ・).
bool IsKatakana(char32_t c) { return (c >= 0x30A1 && c <= 0x30FA) || c == 0x30FC; }

size_t Chars(std::string_view text) {
  return static_cast<size_t>(std::count_if(text.begin(), text.end(), [](char c) {
    return (static_cast<unsigned char>(c) & 0xC0) != 0x80;
  }));
}

bool AllKanji(std::string_view text) {
  std::vector<char32_t> chars;
  std::vector<size_t> offsets;
  Decode(text, &chars, &offsets);
  return !chars.empty() && std::all_of(chars.begin(), chars.end(), IsKanji);
}

// Kanji runs longer than this are not read one piece at a time.
constexpr size_t kMaxComposedChars = 12;
// Pieces tried for one run at one place in the key.
constexpr size_t kMaxSteps = 20000;

}  // namespace

ContextWords::ContextWords(std::string_view preceding, size_t max_chars) {
  std::vector<char32_t> chars;
  std::vector<size_t> offsets;
  Decode(preceding, &chars, &offsets);
  const size_t start = chars.size() > max_chars ? chars.size() - max_chars : 0;
  for (size_t i = start; i < chars.size();) {
    size_t j = i;
    if (IsKatakana(chars[i])) {
      while (j < chars.size() && IsKatakana(chars[j])) ++j;
      std::string reading;
      bool readable = true, only_long_marks = true;
      for (size_t k = i; k < j; ++k) {
        if (chars[k] == 0x30FC) {
          reading += "ー";
          continue;
        }
        only_long_marks = false;
        if (chars[k] > 0x30F6) readable = false;  // ヷ..ヺ: no hiragana
        Append(chars[k] - 0x60, &reading);
      }
      std::string surface(preceding.substr(offsets[i], offsets[j] - offsets[i]));
      if (j - i >= 2 && readable && !only_long_marks && Chars(reading) >= kMinKatakanaReading &&
          std::none_of(katakana_.begin(), katakana_.end(),
                       [&](const Katakana& k) { return k.surface == surface; })) {
        katakana_.push_back({std::move(surface), std::move(reading)});
      }
    } else if (IsKanji(chars[i])) {
      while (j < chars.size() && IsKanji(chars[j])) ++j;
      std::string surface(preceding.substr(offsets[i], offsets[j] - offsets[i]));
      if (j - i >= 2 && std::find(kanji_.begin(), kanji_.end(), surface) == kanji_.end()) {
        kanji_.push_back(std::move(surface));
      }
    } else {
      j = i + 1;
    }
    i = j;
  }
}

std::vector<ContextMatch> ContextWords::MatchAt(std::string_view key, size_t begin,
                                                const PrefixLookup* lookup) const {
  std::vector<ContextMatch> out;
  if (begin >= key.size()) return out;
  for (const Katakana& word : katakana_) {
    if (key.substr(begin, word.reading.size()) == word.reading) {
      out.push_back({word.surface, word.reading.size(), true, false});
    }
  }
  if (lookup != nullptr && *lookup && !kanji_.empty()) {
    // The dictionary words at each place of the key, looked up once.
    std::map<size_t, std::vector<DictionaryWord>> at;
    const auto words_at = [&](size_t p) -> const std::vector<DictionaryWord>& {
      auto it = at.find(p);
      if (it == at.end()) it = at.emplace(p, (*lookup)(key.substr(p))).first;
      return it->second;
    };
    // A dictionary word of 2+ kanji written inside a run.
    for (const DictionaryWord& word : words_at(begin)) {
      if (Chars(word.value) < 2 || Chars(word.reading) < kMinKanjiReading || !AllKanji(word.value) ||
          key.substr(begin, word.reading.size()) != word.reading) {
        continue;
      }
      if (std::any_of(kanji_.begin(), kanji_.end(),
                      [&](const std::string& run) { return run.find(word.value) != std::string::npos; })) {
        out.push_back({word.value, word.reading.size(), false, false});
      }
    }
    // A whole run read piece by piece.
    for (const std::string& run : kanji_) {
      if (Chars(run) > kMaxComposedChars) continue;
      size_t steps = 0;
      const std::function<void(size_t, size_t, bool, bool)> walk = [&](size_t done, size_t p, bool single,
                                                                       bool pieces) {
        if (++steps > kMaxSteps) return;
        if (done == run.size()) {
          if (pieces && Chars(key.substr(begin, p - begin)) >= kMinKanjiReading) {
            out.push_back({run, p - begin, false, single});
          }
          return;
        }
        if (p >= key.size()) return;
        for (const DictionaryWord& word : words_at(p)) {
          if (word.value.empty() || word.reading.empty() ||
              run.compare(done, word.value.size(), word.value) != 0 ||
              key.compare(p, word.reading.size(), word.reading) != 0) {
            continue;
          }
          const bool whole = done == 0 && word.value.size() == run.size();
          walk(done + word.value.size(), p + word.reading.size(), single || Chars(word.value) == 1,
               pieces || !whole);
        }
      };
      walk(0, begin, false, false);
    }
  }
  // Longest first; a dictionary word before a composed reading; one of each.
  std::stable_sort(out.begin(), out.end(), [](const ContextMatch& a, const ContextMatch& b) {
    if (a.bytes != b.bytes) return a.bytes > b.bytes;
    return !a.composed && b.composed;
  });
  std::vector<ContextMatch> unique;
  for (ContextMatch& m : out) {
    if (std::none_of(unique.begin(), unique.end(), [&](const ContextMatch& u) {
          return u.surface == m.surface && u.bytes == m.bytes;
        })) {
      unique.push_back(std::move(m));
    }
  }
  return unique;
}

bool ContextWords::HasKatakanaReading(std::string_view kana) const {
  return std::any_of(katakana_.begin(), katakana_.end(),
                     [&](const Katakana& word) { return word.reading == kana; });
}

}  // namespace jaen
