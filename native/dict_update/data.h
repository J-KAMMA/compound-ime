// 配布される辞書の中身（追加の辞書と英語の一覧）を読み込んで確かめる部分。Mozc に依存しない。
//
// 追加の辞書（supplement.tsv）: Mozc の辞書の元データ（dictionary*.txt）と同じ形の行
//   読み<TAB>左の品詞番号<TAB>右の品詞番号<TAB>費用<TAB>表記
// 英語の一覧（english-extra.tsv）: 行ごとに「種類<TAB>語[<TAB>表示の形]」
//   curated  厳選の英単語（Lexicon::Add(word, true)）
//   named    手で挙げた名前（AddNamed）
//   signal   強い印のときだけ英語に取る語（AddSignalOnly）
//   phrase   2語以上の決まった言い回し（AddPhrase。語は空白で区切る）
//   casing   小文字で打った語の表示の形（brand-casing 相当。<打った形><TAB><表示の形>）
//   casing2  普通の英単語でもある名前の表示の形（打った形を先、これを2番目に出す）
// どちらも「#」で始まる行と空行は読み飛ばす。1行でも決まりに合わなければ、全体を受け付けない
// （中途半端な辞書は入れない）。
#ifndef DICT_UPDATE_DATA_H_
#define DICT_UPDATE_DATA_H_

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace dict_update {

struct SupplementEntry {
  std::string key;    // 読み（UTF-8）
  std::string value;  // 表記（UTF-8）
  uint16_t lid = 0;
  uint16_t rid = 0;
  int cost = 0;
};

struct SupplementLimits {
  size_t pos_count = 65536;      // 品詞番号はこれ未満（Mozc の id.def の行数）
  size_t max_entries = 400000;   // 行数の上限
  size_t max_key_bytes = 192;
  size_t max_value_bytes = 256;
  int max_cost = 32767;
};

// 読みの順に並べた、変えられない表。作ったあとは複数の処理から同時に引いてよい。
class SupplementTable {
 public:
  // text を読む。決まりに合わない行があれば nullptr を返し、*error に行番号と理由を入れる。
  static std::shared_ptr<const SupplementTable> Parse(std::string_view text, const SupplementLimits& limits,
                                                      std::string* error);
  size_t size() const { return entries_.size(); }
  const SupplementEntry& at(size_t i) const { return entries_[i]; }
  // key と読みが同じ行の範囲 [first, second)
  std::pair<size_t, size_t> ExactRange(std::string_view key) const;
  // key で始まる読みの行の範囲（key が空なら全部）
  std::pair<size_t, size_t> PredictiveRange(std::string_view key) const;
  bool HasKey(std::string_view key) const;
  bool HasValue(std::string_view value) const;

 private:
  std::vector<SupplementEntry> entries_;  // (key, value) の順。同じ組は1つだけ（費用の小さいほう）
  std::vector<std::string> values_sorted_;
};

struct EnglishExtra {
  std::vector<std::string> curated, named, signal, phrases;
  std::vector<std::pair<std::string, std::string>> casing, casing2;  // 打った形 → 表示の形（打った形の順）
  size_t size() const { return curated.size() + named.size() + signal.size() + phrases.size() + casing.size() + casing2.size(); }
};

struct EnglishLimits {
  size_t max_rows = 300000;
};

std::shared_ptr<const EnglishExtra> ParseEnglishExtra(std::string_view text, const EnglishLimits& limits,
                                                      std::string* error);

// UTF-8 として正しく、制御文字（タブ・改行を含む）がない。
bool IsCleanUtf8(std::string_view s);

}  // namespace dict_update

#endif  // DICT_UPDATE_DATA_H_
