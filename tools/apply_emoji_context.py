"""「えもじ」の変換で、直前の文に合う絵文字を先に並べる（猫が寝てる→💤😪🐈…、ありがとう→🙏…）。

  python tools/apply_emoji_context.py <mozc/src>

tools/apply_jaen_integration.py の後に、1回だけ動かす（その script が commands::Context に足す
recent_committed_text を使うため）。

今の Mozc は「えもじ」で全部の絵文字を、文字の番号の順に6番目から並べる。これを次のようにする。
  - 並べる場所を2番目からにする（1番目は「絵文字」などの語のまま）。
  - 並べる順を、直前の文に合う絵文字（最大10個）、よく使う絵文字（kDefault）、残り（今までの順）にする。
直前の文は、アプリが教える入力欄の前の文、なければ IME が覚えている直前の確定（recent_committed_text）に、
Mozc の確定の履歴（history_segments）をつないだもの。合わせ方の本体は native/jaen-detector/emoji_context.h。
言葉の表は data/emoji/emoji_data.tsv の「言葉」の列（6列目）から、組み立てのたびに作る
（rewriter/emoji_context_table.inc）。
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
src = Path(sys.argv[1])

# 言葉が指す絵文字がこれより多いとき（顔、動物、記号など）は、手がかりにならないので使わない。
MAX_EMOJI_PER_KEYWORD = 25
# 直前の文に合うものがないときにも先に出す、よく使う絵文字（辞書にある形に合わせて使う）。
DEFAULT = ["😊", "👍", "🙏", "😂", "✨", "🎉", "😭", "🙇", "💦", "❤"]
# 辞書の言葉の列にない、あいさつや気持ちの言い方（辞書の言葉より先に並べる）。
MANUAL = {
    "お疲れ様": "🙇 🍵 ✨", "お疲れさま": "🙇 🍵 ✨", "おつかれ": "🙇 🍵 ✨",
    "すみません": "🙇 🙏 💦", "ごめん": "🙏 🙇 💦", "申し訳": "🙇 🙏 💦",
    "よろしく": "🙇 🙏 😊", "ありがと": "🙏 😊 ✨", "感謝": "🙏 ✨",
    "楽し": "😊 🎶 ✨", "嬉し": "😊 ☺️ ✨", "うれし": "😊 ☺️ ✨", "面白": "😂 🤣", "おもしろ": "😂 🤣",
    "悲し": "😢 😭", "かなし": "😢 😭", "残念": "😢 💦", "やった": "🎉 🙌 ✨",
    "おはよう": "☀️ 😊", "こんにちは": "😊 👋", "こんばんは": "🌙 😊", "おやすみ": "💤 🌙",
    "会議": "💼 📅", "仕事": "💼 💻", "頑張": "💪 🔥", "がんば": "💪 🔥", "了解": "👍 🙆", "OK": "👍 🙆",
    "いいね": "👍 ✨", "大好き": "❤️ 😍", "好き": "❤️ 😊", "笑": "😂 🤣",
}


def edit(path, old, new, count=1):
    # 改行の記号（LF か CRLF）は、ファイルによって違う。LF で探し、見つからなければ CRLF で探す
    p = src / path
    text = p.read_bytes().decode("utf-8")
    for newline in ("\n", "\r\n"):
        o, n = old.replace("\n", newline), new.replace("\n", newline)
        if text.count(o) == count:
            p.write_bytes(text.replace(o, n).encode("utf-8"))
            return
    raise SystemExit(f"{path}: expected {count} match(es) for {old[:70]!r}, found {text.count(old)}")


def is_hiragana(ch):
    return "ぁ" <= ch <= "ゟ"


def is_kana(ch):
    return is_hiragana(ch) or "゠" <= ch <= "ヿ"


def has_kanji(text):
    return any("一" <= ch <= "鿿" or ch == "々" for ch in text)


def usable(word):
    if not word or word.isascii() or any(ch in word for ch in "（）()"):
        return False
    if all(is_hiragana(ch) for ch in word):
        return len(word) >= 3  # 短いひらがなは文のどこにでもある
    if all(is_kana(ch) or ch == "ー" for ch in word):
        return len(word) >= 2
    return True


def build_table(tsv):
    words = {}  # 言葉 -> 絵文字（辞書の順）
    stems = set()  # 語幹として足した言葉（文の中で後ろにひらがなが続くときだけ合う）
    emojis = []
    for line in tsv.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 6 or not cols[1]:
            continue
        emoji = cols[1]
        emojis.append(emoji)
        found = set()
        # 言葉の列（6列目）に、読みの列（3列目、ひらがな）も足す: 一度に打った「あかちょうちんえもじ」は読みで合わせる
        for word in cols[5].split() + cols[2].split():
            if usable(word):
                found.add(word)
            # 寝る→寝、疲れた→疲れ、眠い→眠: 言葉の終わりのひらがなを外した形でも探す（寝てる、疲れて、眠くて）
            stem = word.rstrip("".join(chr(c) for c in range(0x3041, 0x30a0)))
            if stem != word and has_kanji(stem) and all(not is_kana(ch) for ch in stem[-1:]):
                found.add(stem)
                if not usable(stem) or stem not in cols[5].split():
                    stems.add(stem)
        for word in sorted(found):
            words.setdefault(word, [])
            if emoji not in words[word]:
                words[word].append(emoji)
    known = set(emojis)
    rows = []
    for word, listed in MANUAL.items():
        for emoji in listed.split():
            # 辞書には異体の印（U+FE0F）付きの形があるので、辞書にある形を使う
            form = emoji if emoji in known else emoji + "️" if emoji + "️" in known else emoji.rstrip("️")
            if form in known:
                rows.append((word, form, 1, False))
    for word, listed in sorted(words.items()):
        if len(listed) > MAX_EMOJI_PER_KEYWORD or word in MANUAL:
            continue
        for emoji in listed:
            rows.append((word, emoji, len(listed), word in stems))
    defaults = []
    for want in DEFAULT:
        # 辞書には異体の印（U+FE0F）付きの形があるので、その形を使う
        form = next((e for e in emojis if e == want), None) or next((e for e in emojis if e == want + "️"), None)
        if form:
            defaults.append(form)
    return rows, defaults


def c_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


rows, defaults = build_table(src / "data/emoji/emoji_data.tsv")
if len(rows) < 1000 or len(defaults) < 5:
    raise SystemExit(f"emoji table too small: {len(rows)} rows, {len(defaults)} defaults")
table = ["// tools/apply_emoji_context.py が data/emoji/emoji_data.tsv から作る。手で直さない。",
         "constexpr jaen::EmojiKeyword kEmojiContextTable[] = {"]
table += [f"    {{{c_string(w)}, {c_string(e)}, {n}{', true' if s else ''}}}," for w, e, n, s in rows]
table += ["};", "constexpr std::string_view kEmojiDefault[] = {"]
table += [f"    {c_string(e)}," for e in defaults]
table += ["};", ""]
(src / "rewriter/emoji_context_table.inc").write_bytes("\n".join(table).encode("utf-8"))
(src / "rewriter/emoji_context.h").write_bytes((REPO / "native/jaen-detector/emoji_context.h").read_bytes())
print(f"emoji context: {len(rows)} rows, {len({r[0] for r in rows})} keywords, {len(defaults)} defaults")

edit("rewriter/BUILD.bazel", """    srcs = ["emoji_rewriter.cc"],
""", """    srcs = [
        "emoji_context.h",
        "emoji_context_table.inc",
        "emoji_rewriter.cc",
    ],
""")

edit("rewriter/emoji_rewriter.h", "  bool RewriteCandidates(Segments* segments) const;",
     "  // |context| は直前の文。「えもじ」の変換で、合う絵文字を先に並べる。\n"
     "  bool RewriteCandidates(Segments* segments, absl::string_view context = \"\") const;")

R = "rewriter/emoji_rewriter.cc"
edit(R, '#include "rewriter/rewriter_util.h"\n',
     '#include "rewriter/rewriter_util.h"\n#include "rewriter/emoji_context.h"\n')
edit(R, "constexpr size_t kDefaultInsertPos = 6;\n",
     "constexpr size_t kDefaultInsertPos = 6;\n"
     "// 「えもじ」の絵文字を並べる場所（1番目は「絵文字」などの語のまま）。\n"
     "constexpr size_t kEmojiKeyInsertPos = 1;\n\n"
     '#include "rewriter/emoji_context_table.inc"\n')
edit(R, """  DCHECK(segments);
  return RewriteCandidates(segments);""", """  DCHECK(segments);
  // 直前の文: アプリが教える入力欄の前の文、なければ IME が覚えている直前の確定、に確定の履歴をつなぐ
  std::string context = request.context().preceding_text().empty()
                            ? request.context().recent_committed_text()
                            : request.context().preceding_text();
  for (const Segment& segment : segments->history_segments()) {
    if (segment.candidates_size() > 0) context += segment.candidate(0).value;
  }
  return RewriteCandidates(segments, context);""")
edit(R, "bool EmojiRewriter::RewriteCandidates(Segments* segments) const {",
     "bool EmojiRewriter::RewriteCandidates(Segments* segments,\n"
     "                                      absl::string_view context) const {")
edit(R, """  for (Segment& segment : segments->conversion_segments()) {
    reading = japanese_util::FullWidthAsciiToHalfWidthAscii(segment.key());""",
     """  // 同じ変換の中で前にある文節も直前の文に足す（「たんじょうびおめでとうえもじ」を一度に変換したとき）
  // 前の文節の読みも、改行で区切って最後に足す（「あかちょうちん」が赤提灯にならなくても読みで合う）
  std::string sentence(context);
  std::string keys;
  const Segment* previous = nullptr;
  for (Segment& segment : segments->conversion_segments()) {
    if (previous != nullptr && previous->candidates_size() > 0) {
      sentence += previous->candidate(0).value;
      keys += previous->key();
    }
    previous = &segment;
    const std::string with_keys = keys.empty() ? sentence : sentence + "\\n" + keys;
    reading = japanese_util::FullWidthAsciiToHalfWidthAscii(segment.key());""")
edit(R, """      const EmojiEntryList utf8_emoji_list =
          GatherAllEmojiData(tokens, string_array_);
      if (utf8_emoji_list.empty()) {
        continue;
      }
""", """      EmojiEntryList utf8_emoji_list =
          GatherAllEmojiData(tokens, string_array_);
      if (utf8_emoji_list.empty()) {
        continue;
      }
      // 直前の文に合う絵文字、よく使う絵文字、残り（今までの順）の順にする
      std::vector<absl::string_view> first;
      for (const std::string_view emoji :
           jaen::ContextEmoji(with_keys, kEmojiContextTable)) {
        first.push_back(emoji);
      }
      for (const std::string_view emoji : kEmojiDefault) {
        first.push_back(emoji);
      }
      auto rank = [&first](absl::string_view emoji) {
        return absl::c_find(first, emoji) - first.begin();
      };
      absl::c_stable_sort(utf8_emoji_list, [&rank](const auto& a, const auto& b) {
        return rank(a.first) < rank(b.first);
      });
""")
edit(R, """          CreateAllEmojiData(reading, cost, utf8_emoji_list);
      modified |= insert_candidates(std::move(candidates), &segment);
      continue;""", """          CreateAllEmojiData(reading, cost, utf8_emoji_list);
      segment.insert_candidates(
          RewriterUtil::CalculateInsertPosition(segment, kEmojiKeyInsertPos),
          std::move(candidates));
      modified = true;
      continue;""")
