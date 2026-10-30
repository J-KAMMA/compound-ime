"""辞書にない外来語の読みを、細切れの漢字ではなくカタカナ1語にする（えんまーたーる → エンマータール）。

  python tools/apply_loanword_katakana.py <mozc/src>

tools/apply_jaen_integration.py から呼ばれる（converter/immutable_converter.cc はほかの script が
触らない）。

原因: Mozc の辞書に無い外来語（トクソドン、エンマータール、ヘーメルシェンブルク）は、最良の道が
読みを短い語に切る（閻魔|ー|タール、へ|ー|め|ルシェン|ブル|苦情）。Mozc には辞書に無い読みを
カタカナ1語にする節が無い。人工知能（zenz）が文全体でカタカナを出しても、engine.cc の見張り
（人工知能が Mozc に無いカタカナを持ち込まない）がそれを断る。

直し方: 変換（RequestType::CONVERSION）の Viterbi のあと、最良の道に「切られた外来語の音」
（前のかなと切り離されて節の頭に来た ー、または前のかなと母音の違う小さい母音 しぇ・つぃ・ふぁ）
があれば、その前の節から後ろ3節までのカタカナの語を一般名詞として格子に足し、Viterbi をやり直す。
足す条件と見積もりは native/jaen-detector/loanword_katakana.inc（単体試験は
native/jaen-detector/loanword_katakana_test.cc、Mozc を組み立てずに g++ で動く）。
MYIME_LOANWORD_KATAKANA=0 で止まる。
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
src = Path(sys.argv[1])


def edit(path, old, new, count=1):
    # 改行の記号（LF か CRLF）は、ファイルによって違う。LF で探し、見つからなければ CRLF で探す
    p = src / path
    text = p.read_bytes().decode("utf-8")
    for newline in ("\n", "\r\n"):
        o, n = old.replace("\n", newline), new.replace("\n", newline)
        if text.count(o) == count:
            p.write_bytes(text.replace(o, n).encode("utf-8"))
            return
    raise SystemExit(f"{path}: expected {count} match(es) of {old[:60]!r}")


C = "converter/immutable_converter.cc"
edit(C, "#include <utility>\n#include <vector>\n",
     "#include <cstdlib>\n#include <string_view>\n#include <utility>\n#include <vector>\n")

INC = (REPO / "native/jaen-detector/loanword_katakana.inc").read_text(encoding="utf-8")
edit(C, "namespace mozc {\nnamespace {\n", "namespace mozc {\nnamespace {\n\n" + INC + r'''
// MYIME_LOANWORD_KATAKANA=0 turns the loanword katakana nodes off.
bool LoanwordKatakanaEnabled() {
  static const bool enabled = [] {
    const char* value = std::getenv("MYIME_LOANWORD_KATAKANA");
    return value == nullptr || std::string_view(value) != "0";
  }();
  return enabled;
}

// Adds the katakana nodes of loanword_katakana::FindSpans for the best path of
// `lattice` (right after Viterbi) as general nouns. Returns true when a node
// was added, so that Viterbi has to run again.
bool AddLoanwordKatakanaNodes(const dictionary::PosMatcher& pos_matcher,
                              size_t conversion_begin, Lattice* lattice) {
  std::vector<loanword_katakana::PathNode> path;
  const Node* eos = lattice->eos_node();
  for (const Node* node = lattice->bos_node()->next; node != nullptr && node != eos;
       node = node->next) {
    if (path.size() >= 512) return false;
    loanword_katakana::PathNode item;
    item.begin = node->begin_pos;
    item.end = node->end_pos;
    item.value = node->value;
    item.conjugating = pos_matcher.IsContentWordWithConjugation(node->lid);
    item.functional =
        pos_matcher.IsFunctional(node->lid) || pos_matcher.IsSuffixWord(node->lid);
    path.push_back(std::move(item));
  }
  const absl::string_view key = lattice->key();
  const std::vector<loanword_katakana::Span> spans = loanword_katakana::FindSpans(
      std::string_view(key.data(), key.size()), conversion_begin, path);
  if (spans.empty()) return false;
  const uint16_t noun = pos_matcher.GetGeneralNounId();
  for (const loanword_katakana::Span& span : spans) {
    Node* node = lattice->NewNode();
    node->key.assign(key.substr(span.begin, span.end - span.begin));
    node->value = span.value;
    node->lid = noun;
    node->rid = noun;
    node->wcost = span.cost;
    node->node_type = Node::NOR_NODE;
    lattice->Insert(span.begin, node);
  }
  return true;
}
''')

edit(C, """    if (!Viterbi(options, *segments, lattice)) {
      LOG(WARNING) << "viterbi failed";
      return false;
    }
  }
""", """    if (!Viterbi(options, *segments, lattice)) {
      LOG(WARNING) << "viterbi failed";
      return false;
    }
    // A loanword cut into short words (閻魔|ー|タール): add its katakana and
    // run Viterbi again (native/jaen-detector/loanword_katakana.inc).
    if (options.request_type == RequestType::CONVERSION && LoanwordKatakanaEnabled()) {
      size_t conversion_size = 0;
      for (const Segment& segment : segments->conversion_segments()) {
        conversion_size += segment.key().size();
      }
      const size_t key_size = lattice->key().size();
      const size_t conversion_begin =
          conversion_size <= key_size ? key_size - conversion_size : key_size;
      if (AddLoanwordKatakanaNodes(pos_matcher_, conversion_begin, lattice) &&
          !Viterbi(options, *segments, lattice)) {
        LOG(WARNING) << "viterbi failed after loanword katakana";
        return false;
      }
    }
  }
""")
print("loanword katakana applied")
