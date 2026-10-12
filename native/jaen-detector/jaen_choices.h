// Learns, from what the user commits, which romaji words they want as typed
// ASCII and which as Japanese, and keeps them in a small text file.
#ifndef JAEN_CHOICES_H_
#define JAEN_CHOICES_H_

#include <cstddef>
#include <filesystem>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>

#include "jaen_detector.h"

namespace jaen {

enum class Choice { kNone, kEnglish, kJapanese };

// Reads one committed segment of a composition whose typed keys are |raw|.
// kEnglish: the value is an ASCII word typed as such (found in |raw|) while
//   the key is not that word, i.e. the user asked for ASCII (F10 and the like)
//   instead of the kana it was read as.
// kJapanese: the key is an ASCII word found in |raw| (a detected English
//   piece) but the user committed kana or kanji for it.
// The word is returned in |word| (NormalizeWord form).
Choice ClassifyCommit(std::string_view raw, std::string_view key, std::string_view value,
                      std::string* word);

class ChoiceStore {
 public:
  // At most this many words are kept; when full, a new word replaces the
  // least used English word.
  static constexpr size_t kMaxWords = 2000;
  static constexpr int kMaxCount = 1000;

  explicit ChoiceStore(std::filesystem::path file) : file_(std::move(file)) {}

  // Current choices; loaded from the file on first use (retried while the
  // file exists but cannot be read; nothing is saved meanwhile). Never null.
  std::shared_ptr<const Choices> Get();
  // Records one choice and saves the file. The latest choice of a word wins.
  void Record(Choice choice, std::string_view word);
  // Forgets everything and removes the file.
  void Clear();

 private:
  void LoadLocked();
  void SaveLocked() const;

  const std::filesystem::path file_;
  std::mutex mutex_;
  bool loaded_ = false;
  std::shared_ptr<const Choices> choices_ = std::make_shared<Choices>();
};

}  // namespace jaen

#endif  // JAEN_CHOICES_H_
