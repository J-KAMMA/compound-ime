"""判定専用の模型（Jev のような仕組み）の設計のための書き出し（記録だけ。普段の変換は変えない）。

  python tools/apply_jev_dump.py <mozc/src> <myime/src>

tools/apply_jaen_integration.py、tools/apply_selector_stage3.py の後に動かす。次を足す。
  1. MYIME_JEV_DUMP_K=<数>: 候補の書き出し（MYIME_SELECTOR_DUMP）と材料（MYIME_SELECTOR_FEATURES）の
     文節ごとの候補の数を変える（既定は今までどおり 8）。
  2. MYIME_JEV_WHOLE=<ファイル>: 変換の最後に、全文節の読みをつないだ読みで AzooKey の辞書の変換を
     もう1回呼び、返った候補の JSON（文全体の候補を含む）を「読み<TAB>JSON」で1行書き足す。
  3. 試験用の道具（session_handler_main）の命令 JEV_MARK<TAB>印: 上の3つのファイルに「U+0004 印」の行を
     書き足す（どの文の行かを後で分けるため）。
  4. MYIME_JEV_NBEST=<数>: AzooKey の変換で保つ候補の数（N_best、既定 10）を変える（文全体の上位 N を取るため）。
どれも環境変数を決めたときだけ動く。tools/jev_collect.sh が使う。
"""
import sys
from pathlib import Path

mozc = Path(sys.argv[1])
myime = Path(sys.argv[2])


def edit(root, path, old, new):
    p = root / path
    text = p.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected one match for {old[:60]!r}, found {text.count(old)}")
    p.write_text(text.replace(old, new), encoding="utf-8", newline="")


LIMIT = 'static_cast<size_t>(std::getenv("MYIME_JEV_DUMP_K") ? std::atoi(std::getenv("MYIME_JEV_DUMP_K")) : 8)'

# 1. 文節ごとの候補の数
edit(mozc, "engine/engine.cc",
     "      for (size_t c = 0; c < segment.candidates_size() && c < 8; ++c) {\n        line += '\\t';\n        line += segment.candidate(c).value;\n",
     f"      for (size_t c = 0; c < segment.candidates_size() && c < {LIMIT}; ++c) {{\n        line += '\\t';\n        line += segment.candidate(c).value;\n")
edit(mozc, "engine/engine.cc",
     "      for (size_t c = 0; c < segment.candidates_size() && c < 8; ++c) {\n        const auto& cand = segment.candidate(c);\n",
     f"      for (size_t c = 0; c < segment.candidates_size() && c < {LIMIT}; ++c) {{\n        const auto& cand = segment.candidate(c);\n")

# 2. 文全体の候補（AzooKey の辞書の変換の JSON）
A = "converter/azookey_immutable_converter.cc"
edit(mozc, A, "bool ScoreZenzaiSentences(absl::string_view reading, absl::string_view left,\n",
     r'''bool JevWholeCandidates(absl::string_view reading, absl::string_view left,
                        absl::string_view right, std::string* json) {
  if (reading.empty() || json == nullptr || reading.find('\0') != absl::string_view::npos) {
    return false;
  }
  auto& loader = AzooKeyDllLoader::GetInstance();
  const std::lock_guard<std::mutex> operation(loader.operation_mutex());
  if (!loader.IsLoaded() || !loader.ConvertTextWithContext) return false;
  const std::string r(reading), l(left), rt(right);
  const char* result = loader.ConvertTextWithContext(r.c_str(), l.c_str(), rt.c_str(), 0);
  if (result == nullptr) return false;
  json->assign(result);
  loader.FreeString(result);
  return true;
}

bool ScoreZenzaiSentences(absl::string_view reading, absl::string_view left,
''')
edit(mozc, "converter/azookey_immutable_converter.h",
     "[[nodiscard]] bool SelectorTraceForText(absl::string_view text, std::string* trace);\n",
     "[[nodiscard]] bool SelectorTraceForText(absl::string_view text, std::string* trace);\n\n"
     "// 判定専用の模型の設計: 読みの AzooKey の変換の候補の JSON（記録だけ。MYIME_JEV_WHOLE のときだけ使う）。\n"
     "[[nodiscard]] bool JevWholeCandidates(absl::string_view reading, absl::string_view left,\n"
     "                                      absl::string_view right, std::string* json);\n")
edit(mozc, "engine/engine.cc", "    DumpCandidates(*segments);\n",
     "    DumpCandidates(*segments);\n    DumpJevWhole(*segments, left_context, right_context);\n")
edit(mozc, "engine/engine.cc", "  // MYIME_SELECTOR_DUMP=<file>: one line per conversion, segments joined by\n",
     r'''  // MYIME_JEV_WHOLE=<ファイル>: 全文節の読みをつないだ読みの AzooKey の変換の候補の JSON を
  // 「読み<TAB>JSON」で1行書き足す（記録だけ）。
  static void DumpJevWhole(const Segments& segments, std::string_view left, std::string_view right) {
    static const char* path = std::getenv("MYIME_JEV_WHOLE");
    if (!path || !*path) return;
    std::string reading;
    for (const auto& segment : segments.conversion_segments()) reading += segment.key();
    std::string json;
    if (reading.empty() || !JevWholeCandidates(reading, left, right, &json)) json = "[]";
    for (char& ch : json) {
      if (ch == '\n' || ch == '\r' || ch == '\t') ch = ' ';
    }
    std::string line = reading + '\t' + json + '\n';
    static std::mutex jev_mutex;
    std::lock_guard<std::mutex> lock(jev_mutex);
    if (FILE* f = std::fopen(path, "ab")) {
      std::fwrite(line.data(), 1, line.size(), f);
      std::fclose(f);
    }
  }
  // MYIME_SELECTOR_DUMP=<file>: one line per conversion, segments joined by
''')

# 3. 試験用の道具の命令 JEV_MARK
T = "session/session_handler_tool.cc"
edit(mozc, T, '#include "session/session_handler_tool.h"\n',
     '#include "session/session_handler_tool.h"\n\n#include <cstdio>\n#include <cstdlib>\n')
edit(mozc, T, '  } else if (command == "SET_PRECEDING_TEXT") {',
     r'''  } else if (command == "JEV_MARK") {
    const std::string mark = args.size() >= 2 ? std::string(args[1]) : std::string();
    for (const char* name : {"MYIME_SELECTOR_DUMP", "MYIME_SELECTOR_FEATURES", "MYIME_JEV_WHOLE"}) {
      const char* path = std::getenv(name);
      if (path == nullptr || *path == '\0') continue;
      if (FILE* f = std::fopen(path, "ab")) {
        std::fputc(4, f);
        std::fwrite(mark.data(), 1, mark.size(), f);
        std::fputc('\n', f);
        std::fclose(f);
      }
    }
  } else if (command == "SET_PRECEDING_TEXT") {''')

# 4. AzooKey の N_best
edit(myime, "swift-engine/Sources/azookey-engine/AzookeyEngine.swift",
     "    var options = getOptions(allowLearning: allowLearning != 0, leftContext: left, rightContext: right)\n",
     "    var options = getOptions(allowLearning: allowLearning != 0, leftContext: left, rightContext: right)\n"
     "    // 判定専用の模型の設計の書き出し（MYIME_JEV_NBEST を決めたときだけ）: 保つ候補の数\n"
     "    if let raw = ProcessInfo.processInfo.environment[\"MYIME_JEV_NBEST\"], let n = Int(raw), n > 0 {\n"
     "        options.N_best = n\n"
     "    }\n")
print("jev dump applied")
