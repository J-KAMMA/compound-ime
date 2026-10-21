// Detects English words typed as raw romaji inside a Japanese composition,
// e.g. "kyouhagoogledekensaku" -> 今日は|google|で検索.
// Idea after Meltype (GPL-3.0); this is an independent implementation, no code
// or data copied.
#ifndef JAEN_DETECTOR_H_
#define JAEN_DETECTOR_H_

#include <cstddef>
#include <cstdint>
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
  // A hand-listed name (opencode, geminicli, llamacpp) of 6+ letters: like AddSignalOnly, but a
  // longer English word running over its first or last edge does not stop it (hage over
  // ha|geminicli, hall over ha|llamacpp).
  void AddNamed(std::string_view word);
  bool IsNamed(std::string_view word) const;
  // Common English words (SCOWL level 20 or less): only these are kept as
  // English when their kana reads only as a rare Japanese entry (hero: へろ),
  // not rarer ones (omen: お面, redo).
  void AddCommon(std::string_view word);
  bool IsCommon(std::string_view word) const;
  bool IsSignalOnly(std::string_view word) const;

 private:
  std::unordered_map<std::string, bool> words_;
  std::unordered_map<std::string, Place> places_;
  std::unordered_set<std::string> joined_;
  std::unordered_set<std::string> signal_only_;
  std::unordered_set<std::string> named_;
  std::unordered_set<std::string> common_;
  std::unordered_map<std::string, std::vector<size_t>> phrases_;
};

// Lowercase form of a valid lexicon word ([a-z'], starting with a letter, up
// to 32 letters), or an empty string.
std::string NormalizeWord(std::string_view word);

// What the user chose before (keys are NormalizeWord forms). ChoiceStore
// derives this from its decaying scores (see jaen_choices.h).
struct Choices {
  // Words committed as typed ASCII instead of the kana they were read as,
  // with a count (the positive score, rounded down). Taken like lexicon words
  // after kEnglishChoiceCount (one F10 over "snsno" must not make it English
  // for good); a word that is plain romaji (no foreign chunk) is taken like a
  // curated word after kPlainChoiceCount.
  std::unordered_map<std::string, int> english;
  // Words the user turned back into Japanese often enough (score -2, or -3
  // for strongly English words such as brands); never taken as English.
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
// |reads_naturally| (optional), for a common word (Lexicon::IsCommon), also
// takes it as English when its own kana does not read naturally:
// whether it reads as natural Japanese (a cheap way through the dictionary),
// not merely as some rare entry (へろ, さふぇ, いであ are in the dictionary but
// read only as rare words: hero, safe, idea stay English).
// Returns an empty vector when no English piece is chosen.
inline constexpr size_t kMinPlainWordLength = 5;
inline constexpr size_t kMinUnreadWordLength = 4;
// 厳選した語（略語・製品名・分野の用語。api、dao）は、かなが辞書にないか、辞書にあっても
// 自然な日本語として読めない（あぴ、だお）なら、3文字から英語にする。
inline constexpr size_t kMinCuratedUnreadWordLength = 3;
using ReadingCheck = std::function<bool(std::string_view kana)>;

// 日本語の辞書と接続の費用（Mozc のもの。手元の試しでは jaen_trial の写し）。文脈で決める段
// （下の |japanese_model|）が、かなの並びを日本語の語で読む一番安い読み方の費用を出すのに使う。
struct JapaneseWord {
  size_t bytes = 0;  // 読みのバイト数（かなの先頭から）
  uint16_t lid = 0;  // 左の品詞番号
  uint16_t rid = 0;  // 右の品詞番号
  int cost = 0;      // 語の費用
};
struct JapaneseModel {
  // |kana| の先頭を読む辞書の語すべて（日本語として読める語だけ。英語の別名や、かなと違う
  // カタカナの語は入れない）。
  std::function<void(std::string_view kana, std::vector<JapaneseWord>* words)> prefix_words;
  // 右の品詞番号 rid の語の次に左の品詞番号 lid の語が来る費用。0 は文の頭と終わり。
  std::function<int(uint16_t rid, uint16_t lid)> transition;
  uint16_t noun = 1851;       // 英単語を置く品詞（名詞,一般）。知らないかなもこれ
  int unknown_cost = 8000;    // どの語も読まないかな1文字の費用
};

// 「打った英字の並びが英単語として読めるなら英語にする」段。ローマ字のまま日本語に読める英単語
// （made: まで、take: たけ、same: さめ、one: おね）は、ほかの規則では日本語のままになる。文脈で
// 決めるため、英語にしていない日本語の部分ごとに、(a) 全部を日本語の語で読む一番安い費用と、
// (b) 英単語を一覧の語として入れてよい分け方での一番安い費用を、辞書と接続の費用で比べ、(b) が
// kContextMargin 以上安いときだけ英語にする。助詞・活用が続いて日本語として自然に読める
// なら (a) が安く、読みが不自然（英語の文、英単語の連なり、定義済みの英語の隣）なら (b) が安い。
// |japanese_model| が空なら、この段は働かない。
struct ContextCosts {
  int word_base = 0;      // 英単語1語の費用（辞書の語の費用と同じ尺度）
  int per_letter = 0;     // 1文字ごとの上乗せ
  int rare_extra = 0;     // 一覧にない珍しい語（SCOWL の大きい段）の上乗せ
  int common_bonus = 0;   // よく使う語・厳選した語の割引
  int run_start = 0;      // 日本語から英語に変わる費用（英語が続く間、文の頭からの英語は払わない）
  int run_end = 0;        // 英語から日本語に戻る費用（文の終わりで終わる英語は払わない）
  int short_extra = 0;    // 1〜2文字の語の上乗せ
  int particle_extra = 0; // 助詞の綴りの語（to、no、he、ha、ya）の上乗せ。日本語の助詞のほうを取らせる
  int one_letter_extra = 0;  // 1文字の語（a、i）の上乗せ（short_extra に足す）
  int margin = 0;         // 英語にするために安くなければならない差（2語以上のつながり、英語の隣）
  int alone_margin = 0;   // 同じ差を、英単語1語だけで英語の隣でもないときは、これにする（日本語としても読める）
  // 直前に確定した文字が英字の語で終わるとき（|previous_english|）、入力の最初から始まる走りに使う値。
  // 英語の文を1語ずつ確定しながら打つ人の make・take・same は、前が英語なので英語の隣として扱う。
  // 日本語から英語に変わる費用（run_start）は払わず、差は follow_margin（1語だけでも alone_margin にしない）。
  // 0 以下の値は「この寄せを使わない」。入力の途中から始まる走りには働かない。
  int follow_margin = 0;
};
const ContextCosts& DefaultContextCosts();

// 直前に確定した文字（空白は読み飛ばす）が英字の語で終わっているか。「make 」「I want to」「今日は Slack 」は真、
// 「今日は」「Hello, 」「2024 」は偽。
bool EndsWithEnglishWord(std::string_view text);

std::vector<Piece> SplitEnglish(const std::vector<Chunk>& chunks,
                                const Lexicon& lexicon,
                                const RomajiParser& parse,
                                const Choices* choices = nullptr,
                                const ReadingCheck* is_reading = nullptr,
                                const ReadingCheck* reads_naturally = nullptr,
                                const JapaneseModel* japanese_model = nullptr,
                                const ContextCosts* context_costs = nullptr,
                                bool previous_english = false);

}  // namespace jaen

#endif  // JAEN_DETECTOR_H_
