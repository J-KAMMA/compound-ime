// Detects English words typed as raw romaji inside a Japanese composition,
// e.g. "kyouhagoogledekensaku" -> 今日は|google|で検索.
// Idea after Meltype (GPL-3.0); this is an independent implementation, no code
// or data copied.
#ifndef JAEN_DETECTOR_H_
#define JAEN_DETECTOR_H_

#include <cstddef>
#include <functional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace jaen {

// One romaji-table chunk: typed keys, the kana the table produced and keys
// still pending (e.g. "g" of "gl", which has no table entry).
struct Chunk {
  std::string raw;         // e.g. "kyo", "g", "le"
  std::string conversion;  // e.g. "きょ", "", "ぇ"
  std::string pending;     // e.g. "", "g", ""
};

// Parses typed keys from scratch with the romaji table (Mozc's in the IME).
using RomajiParser = std::function<std::vector<Chunk>(std::string_view raw)>;

// Half-open range [begin, end) of typed keys; English pieces stay as typed.
struct Piece {
  size_t begin = 0;
  size_t end = 0;
  bool english = false;
  // Raw positions inside an English piece where two merged words meet and
  // their concatenation is no lexicon word ("birthday|present"): shown with a
  // space there.
  std::vector<size_t> spaces;
  friend bool operator==(const Piece&, const Piece&) = default;
};

class Lexicon {
 public:
  // Words are matched case-insensitively; only [a-z'] words are kept.
  // Curated words (brands, developer terms) may be taken without a foreign chunk.
  void Add(std::string_view word, bool curated = false);
  bool Contains(std::string_view word) const;
  bool IsCurated(std::string_view word) const;
  size_t size() const { return words_.size(); }

  // A place name typed in English-style Hepburn without long vowels ("tokyo"),
  // its kanji ("東京") and how its reading is normally typed ("toukyou").
  // Taken as English only on chunk edges, before a particle or at the end,
  // and not inside its normal spelling (user decision 2026-10-11).
  struct Place {
    std::string surface;
    std::vector<std::string> standards;
  };
  void AddPlace(std::string_view spelling, std::string_view surface, std::string_view standard);
  const Place* FindPlace(std::string_view spelling) const;

  // Words made of two shorter words (download, backup): two such typed words
  // are shown without a space between them.
  void AddJoined(std::string_view word);
  bool IsJoined(std::string_view word) const;

  // Set phrases of two or more words ("see you", "made in japan"): typed
  // together on chunk edges they are one English piece, shown with spaces.
  void AddPhrase(std::string_view phrase);
  // Where the spaces go in |typed| (offsets after each word but the last), or
  // nullptr when it is no phrase.
  const std::vector<size_t>* FindPhrase(std::string_view typed) const;

  // Rarer words and names (london, ukulele, pilates) taken only when what was
  // typed is no plain Japanese romaji (lo: ぉ, a pending c), on chunk edges.
  void AddSignalOnly(std::string_view word);
  bool IsSignalOnly(std::string_view word) const;

 private:
  std::unordered_map<std::string, bool> words_;
  std::unordered_map<std::string, Place> places_;
  std::unordered_set<std::string> joined_;
  std::unordered_set<std::string> signal_only_;
  std::unordered_map<std::string, std::vector<size_t>> phrases_;
};

// Lowercase form of a valid lexicon word ([a-z'], starting with a letter, up
// to 32 letters), or an empty string.
std::string NormalizeWord(std::string_view word);

// What the user chose before (keys are NormalizeWord forms).
struct Choices {
  // Words committed as typed ASCII instead of the kana they were read as,
  // with how often. Taken like lexicon words after kEnglishChoiceCount
  // commits (one F10 over "snsno" must not make it English for good); a word
  // that is plain romaji (no foreign chunk) is taken like a curated word after
  // kPlainChoiceCount commits.
  std::unordered_map<std::string, int> english;
  // Words turned back into Japanese; never taken as English.
  std::unordered_set<std::string> japanese;
};
inline constexpr int kEnglishChoiceCount = 2;
inline constexpr int kPlainChoiceCount = 3;

// Evidence that a chunk is not Japanese romaji. Strong: keys the table left as
// ASCII (a trailing "n" still becomes ん) or a consonant+w+vowel chunk such as
// "gwo". Weak (one English word may outweigh it, several may not): a lone small
// kana typed as l?/x?, or kana typed with v?, q?, c? other than ch?.
bool IsForeignChunk(const Chunk& chunk);

// Splits |raw| (the typed keys of one composition, whose own chunks are
// |chunks|) into Japanese and English pieces. An English piece is a lexicon
// word that is not plain romaji (its own parse has a foreign chunk), or a
// curated word of at least kMinPlainWordLength letters; Japanese pieces are
// re-parsed on their own. Pieces that would cut through one of |chunks| are
// slightly penalized, and never cut a small kana typed as x?/l? (っ as xtu;
// "xn" for ん may be cut).
// Adjacent English words are merged into one piece. |choices| (optional)
// adds and removes words as described there.
// |is_reading| (optional) tells whether kana is a reading in the Japanese
// dictionary. A lexicon word of at least kMinUnreadWordLength letters on the
// typed chunk edges whose kana is no Japanese reading (remote: れもて, safe:
// さふぇ) is English too, unless a Japanese reading of 3+ kana crosses one of
// its edges (the て of "kono|te|gami" belongs to 手紙).
// Returns an empty vector when no English piece is chosen.
inline constexpr size_t kMinPlainWordLength = 5;
inline constexpr size_t kMinUnreadWordLength = 4;
using ReadingCheck = std::function<bool(std::string_view kana)>;
std::vector<Piece> SplitEnglish(const std::vector<Chunk>& chunks,
                                const Lexicon& lexicon,
                                const RomajiParser& parse,
                                const Choices* choices = nullptr,
                                const ReadingCheck* is_reading = nullptr);

}  // namespace jaen

#endif  // JAEN_DETECTOR_H_
