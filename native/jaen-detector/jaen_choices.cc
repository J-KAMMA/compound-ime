#include "jaen_choices.h"

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <locale>
#include <sstream>
#include <system_error>
#include <utility>

namespace jaen {
namespace {

std::string Lower(std::string_view text) {
  std::string out(text);
  for (char& c : out) {
    if (c >= 'A' && c <= 'Z') c = static_cast<char>(c | 0x20);
  }
  return out;
}

bool IsAscii(std::string_view text) {
  return std::ranges::all_of(text, [](char c) { return static_cast<unsigned char>(c) < 0x80; });
}

// Kana or kanji: the user chose Japanese (full-width ASCII does not count).
bool HasJapanese(std::string_view text) {
  for (size_t i = 0; i < text.size();) {
    const auto b = static_cast<unsigned char>(text[i]);
    size_t len = b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
    if (i + len > text.size()) return false;
    uint32_t cp = len == 1 ? b : len == 2 ? (b & 0x1F) : len == 3 ? (b & 0x0F) : (b & 0x07);
    for (size_t k = 1; k < len; ++k) cp = (cp << 6) | (static_cast<unsigned char>(text[i + k]) & 0x3F);
    if ((cp >= 0x3040 && cp <= 0x30FF) || (cp >= 0x3400 && cp <= 0x9FFF) ||
        (cp >= 0xFF66 && cp <= 0xFF9F)) {
      return true;
    }
    i += len;
  }
  return false;
}

// A little decay is forgiven at the thresholds: two picks a day apart still
// count as two (one point loses 1.2% a day).
constexpr double kSlack = 0.05;

int64_t SystemNow() {
  return std::chrono::duration_cast<std::chrono::seconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

// |score| after |seconds| have passed: halves every ChoiceStore::kHalfLifeDays.
double Decayed(double score, int64_t seconds) {
  if (seconds <= 0) return score;
  return score * std::exp2(-static_cast<double>(seconds) / (ChoiceStore::kHalfLifeDays * 86400.0));
}

// 小数の from_chars/to_chars は macOS 13.3 より前の libc++ にないので、
// 地域の設定に左右されない classic の流れで読み書きする。
bool ParseNumber(const std::string& text, double* out) {
  if (text.empty()) return false;
  std::istringstream in(text);
  in.imbue(std::locale::classic());
  in >> *out;
  return in && in.peek() == std::char_traits<char>::eof() && std::isfinite(*out);
}

bool ParseTime(const std::string& text, int64_t* out) {
  const char* end = text.data() + text.size();
  const auto [ptr, ec] = std::from_chars(text.data(), end, *out);
  return ec == std::errc() && ptr == end;
}

}  // namespace

Choice ClassifyCommit(std::string_view raw, std::string_view key, std::string_view value,
                      std::string* word) {
  const std::string lower_raw = Lower(raw);
  const auto typed = [&](std::string_view text) {
    const std::string w = NormalizeWord(text);
    return !w.empty() && lower_raw.find(w) != std::string::npos ? w : std::string();
  };
  if (IsAscii(value)) {
    std::string w = typed(value);
    if (w.size() >= 2 && Lower(key) != w) {
      *word = std::move(w);
      return Choice::kEnglish;
    }
    return Choice::kNone;
  }
  if (IsAscii(key) && HasJapanese(value)) {
    std::string w = typed(key);
    if (w.size() >= 2 && w.size() == key.size()) {
      *word = std::move(w);
      return Choice::kJapanese;
    }
  }
  return Choice::kNone;
}

int64_t ChoiceStore::Now() const { return clock_ ? clock_() : SystemNow(); }

void ChoiceStore::SetStrongPredicate(StrongPredicate strong) {
  std::lock_guard lock(mutex_);
  strong_ = std::move(strong);
  dirty_ = true;
}

std::shared_ptr<const Choices> ChoiceStore::Get(int64_t now) {
  std::lock_guard lock(mutex_);
  LoadLocked(now);
  // Decay moves slowly: derive again at most hourly unless something changed.
  if (dirty_ || now < derived_at_ || now - derived_at_ >= 3600) {
    choices_ = DeriveLocked(now);
    derived_at_ = now;
    dirty_ = false;
  }
  return choices_;
}

double ChoiceStore::Score(std::string_view word, int64_t now) {
  const std::string w = NormalizeWord(word);
  std::lock_guard lock(mutex_);
  LoadLocked(now);
  const auto it = entries_.find(w);
  return it == entries_.end() ? 0.0 : Decayed(it->second.score, now - it->second.time);
}

std::shared_ptr<const Choices> ChoiceStore::DeriveLocked(int64_t now) const {
  auto out = std::make_shared<Choices>();
  for (const auto& [word, entry] : entries_) {
    const double score = Decayed(entry.score, now - entry.time);
    if (score >= 1.0 - kSlack) {
      out->english[word] = static_cast<int>(std::floor(score + kSlack));
    } else if (score < 0) {
      const double need = strong_ && strong_(word) ? kJapaneseStrongScore : kJapaneseScore;
      if (score <= -need + kSlack) out->japanese.insert(word);
    }
  }
  return out;
}

void ChoiceStore::Record(Choice choice, std::string_view word, bool deliberate, int64_t now) {
  const std::string w = NormalizeWord(word);
  if (choice == Choice::kNone || w.empty()) return;
  std::lock_guard lock(mutex_);
  LoadLocked(now);
  if (!loaded_) return;  // never overwrite a file that could not be read
  const double weight = deliberate ? kDeliberateWeight : kWeakWeight;
  auto it = entries_.find(w);
  if (it == entries_.end()) {
    if (entries_.size() >= max_words_) {
      // Full: forget the entry whose effective score is closest to 0 (the
      // oldest among equals).
      auto least = entries_.end();
      double least_magnitude = 0;
      for (auto e = entries_.begin(); e != entries_.end(); ++e) {
        const double magnitude = std::abs(Decayed(e->second.score, now - e->second.time));
        if (least == entries_.end() || magnitude < least_magnitude ||
            (magnitude == least_magnitude && e->second.time < least->second.time)) {
          least = e;
          least_magnitude = magnitude;
        }
      }
      if (least == entries_.end()) return;
      entries_.erase(least);
    }
    it = entries_.emplace(w, Entry{}).first;
  }
  double score = Decayed(it->second.score, now - it->second.time);
  if (choice == Choice::kEnglish) {
    if (score < 0) score = 0;  // one English pick undoes the Japanese marks
    score = std::min(score + weight, kMaxScore);
  } else {
    score = std::max(score - weight, -kMaxScore);
  }
  it->second = Entry{score, now};
  dirty_ = true;
  SaveLocked();
}

void ChoiceStore::Clear() {
  std::lock_guard lock(mutex_);
  loaded_ = true;
  entries_.clear();
  choices_ = std::make_shared<Choices>();
  dirty_ = false;
  seen_valid_ = false;
  derived_at_ = Now();
  std::filesystem::path temp = file_;
  temp += ".tmp";
  for (const std::filesystem::path& path : {file_, temp}) {
    std::error_code error;
    if (!std::filesystem::remove(path, error) && std::filesystem::exists(path, error)) {
      std::ofstream(path, std::ios::binary | std::ios::trunc);  // at least empty it
    }
  }
}

void ChoiceStore::LoadLocked(int64_t now) {
  if (loaded_) {
    // The file may be edited behind our back (tools/learned-words.ps1 removes
    // a word): look at its time now and then, and read it again if it changed.
    if (now >= checked_at_ && now - checked_at_ < kRecheckSeconds) return;
    checked_at_ = now;
    std::error_code stat_error;
    const auto stamp = std::filesystem::last_write_time(file_, stat_error);
    if (stat_error) {
      if (stat_error == std::errc::no_such_file_or_directory && seen_valid_) {
        entries_.clear();  // deleted: everything is forgotten
        seen_valid_ = false;
        dirty_ = true;
      }
      return;
    }
    if (seen_valid_ && stamp == seen_write_) return;
    loaded_ = false;
  }
  std::error_code error;
  const bool exists = std::filesystem::exists(file_, error);
  if (error) return;  // unknown: try again later, and do not save meanwhile
  checked_at_ = now;
  if (!exists) {
    loaded_ = true;
    return;
  }
  std::ifstream in(file_, std::ios::binary);
  if (!in) return;  // e.g. a sharing violation: try again later
  loaded_ = true;
  dirty_ = true;
  // Time of old-format lines: when the file was last written.
  int64_t file_time = now;
  if (const auto written = std::filesystem::last_write_time(file_, error); !error) {
    seen_write_ = written;
    seen_valid_ = true;
    const auto age = std::filesystem::file_time_type::clock::now() - written;
    file_time = now - std::chrono::duration_cast<std::chrono::seconds>(age).count();
  }
  entries_.clear();
  std::string line;
  while (std::getline(in, line) && entries_.size() < max_words_) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.empty() || line[0] == '#') continue;
    std::istringstream fields(line);
    std::string kind, word, number, stamp;
    if (!std::getline(fields, kind, '\t') || !std::getline(fields, word, '\t')) continue;
    word = NormalizeWord(word);
    if (word.empty()) continue;
    std::getline(fields, number, '\t');
    Entry entry{0, file_time};
    if (kind == "w") {
      if (!ParseNumber(number, &entry.score)) continue;
      std::getline(fields, stamp, '\t');
      if (!ParseTime(stamp, &entry.time)) entry.time = file_time;
      entry.time = std::min(entry.time, now);
    } else if (kind == "e") {
      double count = 1;
      if (!number.empty() && ParseNumber(number, &count)) count = std::max(count, 1.0);
      entry.score = count;
    } else if (kind == "j") {
      double count = 1;
      if (!number.empty() && ParseNumber(number, &count)) count = std::max(count, 1.0);
      entry.score = -std::min(count, kJapaneseScore);
    } else {
      continue;
    }
    entry.score = std::clamp(entry.score, -kMaxScore, kMaxScore);
    if (std::abs(Decayed(entry.score, now - entry.time)) < kForgetBelow) continue;
    entries_[word] = entry;
  }
}

void ChoiceStore::SaveLocked() {
  std::error_code ignored;
  std::filesystem::path temp = file_;
  temp += ".tmp";
  const int64_t now = Now();
  {
    std::ofstream out(temp, std::ios::binary | std::ios::trunc);
    if (!out) return;
    out << "# v2\n";
    for (const auto& [word, entry] : entries_) {
      if (std::abs(Decayed(entry.score, now - entry.time)) < kForgetBelow) continue;
      std::ostringstream number;
      number.imbue(std::locale::classic());
      number << std::fixed << std::setprecision(4) << entry.score;
      out << "w\t" << word << '\t' << number.str() << '\t' << entry.time << '\n';
    }
    if (!out.flush()) {
      out.close();
      std::filesystem::remove(temp, ignored);
      return;
    }
  }
  std::filesystem::rename(temp, file_, ignored);
  if (ignored) {
    std::filesystem::remove(temp, ignored);
    return;
  }
  seen_write_ = std::filesystem::last_write_time(file_, ignored);
  seen_valid_ = !ignored;
}

}  // namespace jaen
