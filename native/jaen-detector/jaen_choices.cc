#include "jaen_choices.h"

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <fstream>
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

std::shared_ptr<const Choices> ChoiceStore::Get() {
  std::lock_guard lock(mutex_);
  LoadLocked();
  return choices_;
}

void ChoiceStore::Record(Choice choice, std::string_view word) {
  const std::string w = NormalizeWord(word);
  if (choice == Choice::kNone || w.empty()) return;
  std::lock_guard lock(mutex_);
  LoadLocked();
  if (!loaded_) return;  // never overwrite a file that could not be read
  if (choice == Choice::kEnglish ? choices_->english.contains(w) &&
                                       choices_->english.at(w) >= kMaxCount
                                 : choices_->japanese.contains(w)) {
    return;  // nothing changes
  }
  auto next = std::make_shared<Choices>(*choices_);
  const bool known = next->english.contains(w) || next->japanese.contains(w);
  if (!known && next->english.size() + next->japanese.size() >= kMaxWords) {
    // Full: forget the least used English word (Japanese choices fix mistakes).
    const auto least = std::ranges::min_element(
        next->english, {}, [](const auto& entry) { return entry.second; });
    if (least == next->english.end()) return;
    next->english.erase(least);
  }
  if (choice == Choice::kEnglish) {
    next->japanese.erase(w);
    int& count = next->english[w];
    count = std::min(count + 1, kMaxCount);
  } else {
    next->english.erase(w);
    next->japanese.insert(w);
  }
  choices_ = std::move(next);
  SaveLocked();
}

void ChoiceStore::Clear() {
  std::lock_guard lock(mutex_);
  loaded_ = true;
  choices_ = std::make_shared<Choices>();
  std::filesystem::path temp = file_;
  temp += ".tmp";
  for (const std::filesystem::path& path : {file_, temp}) {
    std::error_code error;
    if (!std::filesystem::remove(path, error) && std::filesystem::exists(path, error)) {
      std::ofstream(path, std::ios::binary | std::ios::trunc);  // at least empty it
    }
  }
}

// Format: one word per line, "e<TAB>word<TAB>count" or "j<TAB>word".
void ChoiceStore::LoadLocked() {
  if (loaded_) return;
  std::error_code error;
  const bool exists = std::filesystem::exists(file_, error);
  if (error) return;  // unknown: try again later, and do not save meanwhile
  if (!exists) {
    loaded_ = true;
    return;
  }
  std::ifstream in(file_, std::ios::binary);
  if (!in) return;  // e.g. a sharing violation: try again later
  loaded_ = true;
  auto loaded = std::make_shared<Choices>();
  std::string line;
  while (std::getline(in, line) && loaded->english.size() + loaded->japanese.size() < kMaxWords) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    std::istringstream fields(line);
    std::string kind, word;
    int count = 1;
    if (!std::getline(fields, kind, '\t') || !std::getline(fields, word, '\t')) continue;
    word = NormalizeWord(word);
    if (word.empty()) continue;
    if (kind == "e") {
      if (std::string number; std::getline(fields, number, '\t')) {
        count = std::clamp(std::atoi(number.c_str()), 1, kMaxCount);
      }
      loaded->english[word] = count;
    } else if (kind == "j") {
      loaded->japanese.insert(word);
    }
  }
  choices_ = std::move(loaded);
}

void ChoiceStore::SaveLocked() const {
  std::error_code ignored;
  std::filesystem::path temp = file_;
  temp += ".tmp";
  {
    std::ofstream out(temp, std::ios::binary | std::ios::trunc);
    if (!out) return;
    for (const auto& [word, count] : choices_->english) out << "e\t" << word << '\t' << count << '\n';
    for (const std::string& word : choices_->japanese) out << "j\t" << word << '\n';
    if (!out.flush()) {
      out.close();
      std::filesystem::remove(temp, ignored);
      return;
    }
  }
  std::filesystem::rename(temp, file_, ignored);
  if (ignored) std::filesystem::remove(temp, ignored);
}

}  // namespace jaen
