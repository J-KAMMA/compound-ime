// Fixes one mistyped key in romaji that the romaji table cannot read, e.g.
// "tokyp" (と + unread "kyp") -> "tokyo" (ときょ). Romaji that reads as kana is
// never touched: "kyouu" or "ka" for "ko" cannot be told from intent.
#ifndef JAEN_TYPO_H_
#define JAEN_TYPO_H_

#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include "jaen_detector.h"

namespace jaen {

struct KanaTrigram {
  const char* text;  // three kana; "^" and "$" mark reading edges
  int count;
};

// How Japanese-like a kana string is, from trigram counts of dictionary readings.
class KanaModel {
 public:
  explicit KanaModel(std::span<const KanaTrigram> trigrams);
  // Log-probability of |kana| (UTF-8 hiragana and ー) as a reading.
  double Score(std::string_view kana) const;

 private:
  std::unordered_map<std::string, int> trigrams_;
  std::unordered_map<std::string, int> contexts_;  // first two characters
};

// Keys the table left unread (ASCII letters in a chunk), apart from a final
// "n" that becomes ん.
int UnreadKeys(const std::vector<Chunk>& chunks);

// The typed keys |raw| with one edit (adjacent-key substitution, swapped
// neighbors, a dropped or doubled key, or a missing vowel) near the first
// unread key, after which every key is read as kana; the reading |model|
// scores highest wins. nullopt when |raw| already reads, is too long, no
// single edit fixes it, the best reading beats the runner-up (a different
// reading) by less than |margin| (natural log), or its average log-probability
// per kana (end mark included) is below |floor|. Only lowercase romaji typed in
// kana mode is considered.
// The one-key edits FixTypo weighs, one per reading (the best-scored keys for
// it), with the kana model's score; empty when FixTypo would not look at |raw|.
struct UnreadTypoEdit {
  std::string keys;
  std::string kana;
  double score = 0;     // |model|'s log-probability, less the vowel penalty
  bool vowel = false;   // a vowel was put in (a missing vowel is a rarer slip)
};
std::vector<UnreadTypoEdit> UnreadTypoEdits(std::string_view raw, const RomajiParser& parse,
                                            const KanaModel& model);
std::optional<std::string> FixTypo(std::string_view raw, const RomajiParser& parse,
                                   const KanaModel& model, double margin = 3.0,
                                   double floor = -4.5);

// A slip in romaji that still reads as kana ("tsuduukete": つづうけて).
// Extra cost (in the converter's cost units) charged for each kind of slip,
// so a likelier slip needs a smaller gain to be taken.
struct TypoPriors {
  // "tsuduukete" for tsudukete. Not 0: "isshoniikokka" (一緒に行こっか) reads
  // 3039 cheaper as いっしょにこっか (一緒に国家); the smallest real such slip
  // in the tests reads 3167 cheaper. 100 puts the 3000 margin between them.
  int doubled_vowel = 100;
  int doubled_consonant = 2000;  // "hayyaku" for hayaku ("nikki" is a word)
  int swapped = 1000;            // "kareu" for kaeru
  int neighbor = 1500;           // "kiagi" for kaigi... a key next to the right one
  int dropped_vowel = 2500;      // "kaig" for kaigi: any vowel left out
  // A long vowel left out (u after o or u, i after e, a vowel doubled:
  // "kyoha" for kyouha, "gakko" for gakkou, "ega" for eiga), the commonest
  // slip and the passport way of writing (chubu, kudo): taken more readily.
  // Measured on 40 such slips and 421 correct sentences (typo150/150b
  // controls and ja400): a 2000 margin fixes 33 and changes none.
  int long_vowel = -1000;
  // "uo" typed for ou ("shiryuo", "bentuo"). Costlier than other swaps: the
  // passport way leaves ou's u out before an o ("chuosen" is 中央線, and
  // ちょうせん reads 5066 cheaper); the 8 such slips read 6858 or more cheaper.
  int swapped_uo = 3000;
  // The i of ai left out ("asatsu" for aisatsu, "shukuda" for shukudai, "rakyaku"
  // for raikyaku): the commonest dropped vowel in typo150b (5 of 6). Measured with
  // the typo tables and ja400: 0 fixes 3 more and changes none of the 950 others;
  // -1000 also breaks one in typo150, 1000 fixes 1. MYIME_TYPO_PRIOR_AI overrides it.
  int dropped_ai = 0;
  // A voiced consonant typed twice ("maddeo" for madeo, "hidda" for hida): Japanese
  // has no small tsu before g, z, j, d or b outside loanwords (バッグ, ベッド). A
  // lower doubled_consonant for every key also breaks mittsu (三つ) into
  // mitsukatta (見つかった). MYIME_TYPO_PRIOR_DV overrides it.
  // Measured: fixes maddeo and hidda, changes none of ja400, the typo controls
  // or the loanwords in group c (beddo, baggu ...).
  int doubled_voiced = 0;
  // kOff leaves a kind of slip out.
  static constexpr int kOff = 1 << 30;
  // A consonant left out before a vowel ("kiou" for kinou, "saeta" for sareta) and
  // any key typed in by mistake ("butsai" for butai): set on the dev typo table
  // (tests/conversion/dev-typo.json). MYIME_TYPO_PRIOR_DC and MYIME_TYPO_PRIOR_EX override them.
  // dropped_consonant was 3000 (6000 cheaper with the 3000 margin): 7 of the 27 such
  // slips in dev-typo were fixed. The runs with a lower margin (the same total for this
  // kind) fix 9 at 1000 (matasaeta, neusugite) and change no ja400 or typo150b sentence
  // to a reading with a consonant put in; most of the rest read as other words (既往, 性悪).
  int dropped_consonant = 1000;
  int extra_key = 2500;
  // A key typed in by mistake that touches neither key around it ("shuogi" read as
  // shugi, not shougi; "tepiku" as teiku): off. MYIME_TYPO_PRIOR_EXF overrides it.
  int extra_key_far = kOff;
};
struct TypoEdit {
  std::string keys;  // the typed keys with the edit
  std::string kana;  // what they read as
  int prior = 0;
};
// The typed keys |raw| with one edit each (never the first key), one per
// distinct reading, with the cheapest kind of slip. The caller compares the
// converter's cost of each reading plus its prior with the typed reading.
std::vector<TypoEdit> ReadableTypoEdits(std::string_view raw, const RomajiParser& parse,
                                        const TypoPriors& priors = {});

// The fixers above look at no more than 64 keys. A longer run of romaji keys
// (a sentence typed without a comma) is cut into parts of at most |max| keys,
// each fixed on its own: after a particle (wo first, then ga ni de ha wa no to
// mo he) followed by a consonant, else after any vowel followed by a consonant
// (never inside a syllable, before ー, ' or a doubled consonant). Parts are at
// least |min| keys where a cut allows. A run of at most |max| keys is one part.
std::vector<std::string_view> SplitLongRomaji(std::string_view run, size_t max = 64, size_t min = 12);

}  // namespace jaen

#endif  // JAEN_TYPO_H_
