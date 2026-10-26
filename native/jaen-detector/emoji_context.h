// 「えもじ」の変換で、直前の文に合う絵文字を先に並べる（tools/apply_emoji_context.py）。
//
// 表は Mozc の絵文字の辞書（data/emoji/emoji_data.tsv）の「言葉」の列から作る（猫→🐱、寝る→💤 など）。
// 直前の文の最後の kContextChars 字に、表の言葉が入っているかを見て、後ろで見つかった言葉ほど、
// 長い言葉ほど、その言葉を持つ絵文字が少ないほど先にする。標準だけで書いてあり、単体試験は emoji_context_test.cc。
#ifndef JAEN_EMOJI_CONTEXT_H_
#define JAEN_EMOJI_CONTEXT_H_

#include <algorithm>
#include <cstddef>
#include <string>
#include <string_view>
#include <tuple>
#include <unordered_map>
#include <vector>

namespace jaen {

struct EmojiKeyword {
  std::string_view keyword;  // 文の中で探す言葉
  std::string_view emoji;
  int count;  // この言葉を持つ絵文字の数（少ないほど言葉がその絵文字に特有）
  bool kana_after = false;  // 語幹（寝る→寝）: 文の中ですぐ後ろにひらがなが続くときだけ合う（寝てる○、明日×）
};

// |text| の |pos| からひらがなが始まるか（UTF-8 で U+3041〜U+309F）。
inline bool HiraganaAt(std::string_view text, size_t pos) {
  if (pos + 3 > text.size()) return false;
  const auto b0 = static_cast<unsigned char>(text[pos]), b1 = static_cast<unsigned char>(text[pos + 1]),
             b2 = static_cast<unsigned char>(text[pos + 2]);
  return b0 == 0xE3 && ((b1 == 0x81 && b2 >= 0x81) || (b1 == 0x82 && b2 <= 0x9F));
}

// |keyword| が |context| で最後に合う位置の終わり。合わなければ npos。
inline size_t LastMatchEnd(std::string_view context, const EmojiKeyword& k) {
  size_t from = std::string_view::npos;
  while (true) {
    const size_t found = context.rfind(k.keyword, from);
    if (found == std::string_view::npos) return found;
    const size_t end = found + k.keyword.size();
    if (!k.kana_after || HiraganaAt(context, end)) return end;
    if (found == 0) return std::string_view::npos;
    from = found - 1;
  }
}

inline constexpr size_t kContextChars = 40;
inline constexpr size_t kMaxContextEmoji = 10;

// |text| の最後の |chars| 字（UTF-8 の文字の切れ目にそろえる）。
inline std::string_view LastChars(std::string_view text, size_t chars) {
  size_t pos = text.size();
  for (size_t n = 0; n < chars && pos > 0; ++n) {
    --pos;
    while (pos > 0 && (static_cast<unsigned char>(text[pos]) & 0xC0) == 0x80) --pos;
  }
  return text.substr(pos);
}

// 直前の文に合う絵文字を、合う順に最大 kMaxContextEmoji 個返す。合うものがなければ空。
template <typename Table>
std::vector<std::string_view> ContextEmoji(std::string_view context, const Table& table) {
  context = LastChars(context, kContextChars);
  if (context.empty()) return {};
  // 絵文字ごとの一番よい合い方: 見つかった言葉の終わりの位置（後ろほどよい）、言葉の長さ、言葉の特有さ、表の順
  using Score = std::tuple<size_t, size_t, int, size_t>;
  std::unordered_map<std::string_view, Score> best;
  for (size_t i = 0; i < std::size(table); ++i) {
    const EmojiKeyword& k = table[i];
    const size_t end = LastMatchEnd(context, k);
    if (end == std::string_view::npos) continue;
    const Score s{end, k.keyword.size(), -k.count, std::size(table) - i};
    auto [it, inserted] = best.emplace(k.emoji, s);
    if (!inserted && it->second < s) it->second = s;
  }
  std::vector<std::pair<Score, std::string_view>> ranked;
  ranked.reserve(best.size());
  for (const auto& [emoji, score] : best) ranked.emplace_back(score, emoji);
  std::sort(ranked.begin(), ranked.end(), [](const auto& a, const auto& b) { return a.first > b.first; });
  std::vector<std::string_view> out;
  for (size_t i = 0; i < ranked.size() && i < kMaxContextEmoji; ++i) out.push_back(ranked[i].second);
  return out;
}

}  // namespace jaen

#endif  // JAEN_EMOJI_CONTEXT_H_
