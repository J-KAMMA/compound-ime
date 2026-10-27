"""画面の文字を変換に使う（試験用。既定では今までどおり）。

  python tools/apply_screen_words.py <mozc/src>

ほかの差し込みのあと、最後に流す（engine.cc の変換の入口の形は差し込みごとに変わるので、変わらない入口の
宣言だけを目印にする）。

カーソルより前の文字（入力欄の前の文。いずれ画面の文字も）は長くなりうる。試験（tests/conversion/context-long.tsv、
組 o）では、記事の頭から渡すと前の1文だけのときより正解が減った（669 → 652/1000）。一方、間違えた 331 文の
うち 79 文は、正しい漢字・カタカナの語が記事の前の部分にそのまま出ていた（前の1文にあったのは 19 文）。そこで:
  - MYIME_CTX_NEAR=<字数>: 人工知能（と選び手）に渡す前の文を、終わりのその字数までにする（0・なしは全部）
  - MYIME_SCREEN_WORDS=1: 変換の後、先頭の候補が前の文字に出ていない文節で、同じ読みの候補（30 番目まで）の中に、
    前の文字に出ている語（2字以上で漢字かカタカナを含む、付属語を除いた部分）があれば、それを先頭にする
"""
import sys
from pathlib import Path

src = Path(sys.argv[1])
E = "engine/engine.cc"


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


edit(E, """  bool ConvertWithContext(const ConversionOptions& options, Segments* segments,
                          std::string_view left_context,
                          std::string_view right_context) const override {
""", """  bool ConvertWithContext(const ConversionOptions& options, Segments* segments,
                          std::string_view left_context,
                          std::string_view right_context) const override {
    const bool converted = ConvertWithNearContext(options, segments, NearContext(left_context), right_context);
    if (converted) PreferScreenWords(left_context, segments);
    return converted;
  }

  // MYIME_CTX_NEAR: the most characters of the left context the neural model reads (the
  // end of it); unset or 0 passes all of it.
  static std::string_view NearContext(std::string_view left) {
    static const size_t limit = [] {
      const char* value = std::getenv("MYIME_CTX_NEAR");
      return value != nullptr ? static_cast<size_t>(std::strtol(value, nullptr, 10)) : size_t{0};
    }();
    if (limit == 0 || Util::CharsLen(left) <= limit) return left;
    return Util::Utf8SubString(left, Util::CharsLen(left) - limit);
  }

  // MYIME_SCREEN_WORDS=1: a segment whose first candidate is not in the text before the
  // cursor, but another candidate of the same reading is (a word of two or more
  // characters with kanji or katakana, among the first 30), takes that one first.
  static void PreferScreenWords(std::string_view screen, Segments* segments) {
    static const bool enabled = [] {
      const char* value = std::getenv("MYIME_SCREEN_WORDS");
      return value != nullptr && std::string_view(value) == "1";
    }();
    if (!enabled || screen.empty() || segments == nullptr) return;
    // MYIME_SCREEN_MIN: the fewest characters of such a word; MYIME_SCREEN_COUNT: how many
    // times it must be in the text.
    static const size_t min_chars = [] {
      const char* value = std::getenv("MYIME_SCREEN_MIN");
      return value != nullptr ? static_cast<size_t>(std::strtol(value, nullptr, 10)) : size_t{2};
    }();
    static const size_t min_count = [] {
      const char* value = std::getenv("MYIME_SCREEN_COUNT");
      return value != nullptr ? static_cast<size_t>(std::strtol(value, nullptr, 10)) : size_t{1};
    }();
    const auto on_screen = [&](const converter::Candidate& candidate) {
      const std::string& word = candidate.content_value;
      if (Util::CharsLen(word) < min_chars ||
          !(Util::ContainsScriptType(word, Util::KANJI) || Util::ContainsScriptType(word, Util::KATAKANA)))
        return false;
      size_t found = 0;
      for (size_t at = screen.find(word); at != std::string_view::npos && found < min_count;
           at = screen.find(word, at + word.size()))
        ++found;
      return found >= min_count;
    };
    for (size_t i = 0; i < segments->conversion_segments_size(); ++i) {
      auto* segment = segments->mutable_conversion_segment(i);
      if (segment->candidates_size() < 2 || segment->segment_type() == Segment::FIXED_VALUE ||
          segment->segment_type() == Segment::SUBMITTED || on_screen(segment->candidate(0)))
        continue;
      const size_t count = std::min<size_t>(segment->candidates_size(), 30);
      for (size_t j = 1; j < count; ++j) {
        if (segment->candidate(j).key == segment->candidate(0).key && on_screen(segment->candidate(j))) {
          segment->move_candidate(static_cast<int>(j), 0);
          break;
        }
      }
    }
  }

  bool ConvertWithNearContext(const ConversionOptions& options, Segments* segments,
                              std::string_view left_context,
                              std::string_view right_context) const {
""")
print("screen words ok")
