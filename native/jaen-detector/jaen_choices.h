// Learns, from what the user commits, which romaji words they want as typed
// ASCII and which as Japanese, and keeps them in a small text file.
//
// Every word has a score and the time (unix seconds) it was last changed.
// English commits add, Japanese commits subtract; the effective score decays
// toward 0 with a half-life of kHalfLifeDays, so old choices fade. A choice the
// user made deliberately (picked a non-first candidate, F6-F10) weighs 1, a
// weak one (the first candidate, Enter without converting) weighs 0.5.
// Choosing English for a word with a negative score first resets it to 0, so
// one deliberate English pick undoes a Japanese mark. A word is Japanese
// ("never English") at score <= -kJapaneseScore, or <= -kJapaneseStrongScore
// when the strong predicate says it is surely English (lexicon, brands).
//
// File (jaen_choices.txt), UTF-8, LF, written atomically:
//   # v2
//   w<TAB>word<TAB>score<TAB>unix_time
// Older files are read too: "e<TAB>word<TAB>count" is score +count,
// "j<TAB>word<TAB>2" score -2, "j<TAB>word<TAB>1" and "j<TAB>word" score -1;
// their time is the file's modification time (or now when unknown).
// tools/learned-words.ps1 lists and edits this file.
#ifndef JAEN_CHOICES_H_
#define JAEN_CHOICES_H_

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <unordered_map>

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
  // entry with the smallest effective score magnitude.
  static constexpr size_t kMaxWords = 2000;
  static constexpr double kMaxScore = 10.0;
  static constexpr double kHalfLifeDays = 60.0;
  static constexpr double kDeliberateWeight = 1.0;
  static constexpr double kWeakWeight = 0.5;
  static constexpr double kJapaneseScore = 2.0;
  static constexpr double kJapaneseStrongScore = 3.0;
  // Entries whose effective score fell below this are dropped.
  static constexpr double kForgetBelow = 0.05;

  using Clock = std::function<int64_t()>;  // unix seconds
  using StrongPredicate = std::function<bool(std::string_view word)>;

  explicit ChoiceStore(std::filesystem::path file, size_t max_words = kMaxWords,
                       Clock clock = nullptr)
      : file_(std::move(file)), max_words_(max_words), clock_(std::move(clock)) {}

  // Words for which |strong| is true need kJapaneseStrongScore to be Japanese.
  void SetStrongPredicate(StrongPredicate strong);

  // Current choices; loaded from the file on first use (retried while the
  // file exists but cannot be read; nothing is saved meanwhile). Never null.
  std::shared_ptr<const Choices> Get() { return Get(Now()); }
  std::shared_ptr<const Choices> Get(int64_t now);
  // Records one choice and saves the file.
  void Record(Choice choice, std::string_view word, bool deliberate = true) {
    Record(choice, word, deliberate, Now());
  }
  void Record(Choice choice, std::string_view word, bool deliberate, int64_t now);
  // Effective score of a word at |now| (0 when unknown).
  double Score(std::string_view word, int64_t now);
  // Forgets everything and removes the file.
  void Clear();

 private:
  struct Entry {
    double score = 0;
    int64_t time = 0;
  };

  int64_t Now() const;
  void LoadLocked(int64_t now);
  void SaveLocked();
  std::shared_ptr<const Choices> DeriveLocked(int64_t now) const;

  const std::filesystem::path file_;
  const size_t max_words_;
  const Clock clock_;
  std::mutex mutex_;
  bool loaded_ = false;
  StrongPredicate strong_;
  std::unordered_map<std::string, Entry> entries_;
  std::shared_ptr<const Choices> choices_ = std::make_shared<Choices>();
  int64_t derived_at_ = 0;
  bool dirty_ = true;
  // The file's time as we last read or wrote it, to notice outside edits.
  static constexpr int64_t kRecheckSeconds = 10;
  std::filesystem::file_time_type seen_write_{};
  bool seen_valid_ = false;
  int64_t checked_at_ = 0;
};

}  // namespace jaen

#endif  // JAEN_CHOICES_H_
