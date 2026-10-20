"""判定の門を IME の変換の流れに組み込む（既定は無効。今の動きは変えない）。

  python tools/apply_jev_gate.py <mozc/src> <MyIME の src> <このリポジトリ>

tools/apply_batch_score.py と tools/apply_latency_profile.py の後に、1回だけ動かす（最後）。
判定の門 = 「この変換で全文の人工知能の生成が要るか」を当てる小さな模型（tools/jev-gate/、docs/jev-gate.md）。
空白キーの変換で、全文の生成（engine.cc の PreferWholePhrase の問い合わせ。all_zenzai）の直前に門を通し、
「要らない」と当てた変換は生成を飛ばして、生成なしの候補を zenz で採点（既にある一括採点 ScoreZenzaiSuffixes）して
最大のものを返す。環境変数（tools/jev-gate/engine_gate_config.inc の頭に一覧）で切り替える:
  MYIME_JEV_GATE=<しきい値> と MYIME_JEV_GATE_MODEL=<jevgate.bin> がそろったときだけ動く。どちらかがなければ今までと同じ。

足すもの:
  1. 変換エンジン（Swift）: 人工知能を使わない単発の変換 ConvertTextNoAI（辞書だけの文全体の候補を作る）。
  2. C++ の読み込み側（azookey_immutable_converter）: ConvertTextNoAI を呼ぶ ScopedAzooKeyNoAI（同じスレッドの間だけ有効）。
  3. engine/jev_gate.cc、jev_gate.h、jevgate_core.h（tools/jev-gate/ から写す）と、engine/BUILD.bazel の jev_gate（AVX2 の部品）。
  4. engine.cc: 設定（engine_gate_config.inc）、門と選び方（engine_gate.inc）、PreferWholePhrase の入り口の呼び出し。
     門が有効なときは、打っている間の先回りの生成（prefetch_typing_）を止める（要らない生成を走らせないため）。
Windows の組み立てには使わない（AVX2 の指定と Swift 側の書き出しは Linux の試験用）。
"""
import shutil
import sys
from pathlib import Path

mozc = Path(sys.argv[1])  # Mozc の src
src = Path(sys.argv[2])  # MyIME の src
repo = Path(sys.argv[3])  # このリポジトリ
gate = repo / "tools" / "jev-gate"
engine_swift = src / "swift-engine/Sources/azookey-engine/AzookeyEngine.swift"


def edit(path, old, new, count=1):
    # 改行の記号（LF か CRLF）は、ファイルによって違う。LF で探し、見つからなければ CRLF で探す
    text = path.read_bytes().decode("utf-8")
    for newline in ("\n", "\r\n"):
        o, n = old.replace("\n", newline), new.replace("\n", newline)
        if text.count(o) == count:
            path.write_bytes(text.replace(o, n).encode("utf-8"))
            return
    raise SystemExit(f"{path}: expected {count} match(es) for {old[:70]!r}, found {text.count(old)}")


# ---- 1. Swift: 人工知能を使わない単発の変換 ----
edit(engine_swift, '''@_cdecl("ConvertTextWithContext")
public func convertTextWithContext(
    _ key: UnsafePointer<CChar>?,
    _ leftContext: UnsafePointer<CChar>?,
    _ rightContext: UnsafePointer<CChar>?,
    _ allowLearning: Int32
) -> UnsafePointer<CChar>? {
    guard let key = key else { return nil }
''', '''@_cdecl("ConvertTextWithContext")
public func convertTextWithContext(
    _ key: UnsafePointer<CChar>?,
    _ leftContext: UnsafePointer<CChar>?,
    _ rightContext: UnsafePointer<CChar>?,
    _ allowLearning: Int32
) -> UnsafePointer<CChar>? {
    convertTextWithContextImpl(key, leftContext, rightContext, allowLearning, noAI: false)
}

/// 判定の門（tools/apply_jev_gate.py）: ConvertTextWithContext と同じ形で、人工知能を使わず辞書だけで変換する
/// （模型が読み込まれていても生成しない）。文全体の候補（辞書の変換の上位）を作るために使う。
@_cdecl("ConvertTextNoAI")
public func convertTextNoAI(
    _ key: UnsafePointer<CChar>?,
    _ leftContext: UnsafePointer<CChar>?,
    _ rightContext: UnsafePointer<CChar>?,
    _ allowLearning: Int32
) -> UnsafePointer<CChar>? {
    convertTextWithContextImpl(key, leftContext, rightContext, allowLearning, noAI: true)
}

func convertTextWithContextImpl(
    _ key: UnsafePointer<CChar>?,
    _ leftContext: UnsafePointer<CChar>?,
    _ rightContext: UnsafePointer<CChar>?,
    _ allowLearning: Int32,
    noAI: Bool
) -> UnsafePointer<CChar>? {
    guard let key = key else { return nil }
''')
edit(engine_swift, "    if keyString.unicodeScalars.count > 128 {\n        options.zenzaiMode = .off\n    }\n",
     "    if noAI || keyString.unicodeScalars.count > 128 {\n        options.zenzaiMode = .off\n    }\n")

# ---- 2. C++ の読み込み側 ----
A = mozc / "converter/azookey_immutable_converter.cc"
H = mozc / "converter/azookey_immutable_converter.h"
edit(A, "  using ConvertTextWithContextFunc = const char* (*)(const char*, const char*, const char*, int);\n",
     "  using ConvertTextWithContextFunc = const char* (*)(const char*, const char*, const char*, int);\n"
     "  using ConvertTextNoAIFunc = const char* (*)(const char*, const char*, const char*, int);\n")
edit(A, "  ConvertTextWithContextFunc ConvertTextWithContext = nullptr;\n",
     "  ConvertTextWithContextFunc ConvertTextWithContext = nullptr;\n  ConvertTextNoAIFunc ConvertTextNoAI = nullptr;\n")
edit(A, """    ConvertTextWithContext = reinterpret_cast<ConvertTextWithContextFunc>(
        GetProcAddress(dll_handle_, "ConvertTextWithContext"));
""", """    ConvertTextWithContext = reinterpret_cast<ConvertTextWithContextFunc>(
        GetProcAddress(dll_handle_, "ConvertTextWithContext"));
    ConvertTextNoAI = reinterpret_cast<ConvertTextNoAIFunc>(
        GetProcAddress(dll_handle_, "ConvertTextNoAI"));
""")
edit(A, "    MYIME_LOAD(ConvertTextWithContext);\n", "    MYIME_LOAD(ConvertTextWithContext);\n    MYIME_LOAD(ConvertTextNoAI);\n")
edit(A, "    ConvertTextWithContext = nullptr;\n", "    ConvertTextWithContext = nullptr;\n    ConvertTextNoAI = nullptr;\n")
# 人工知能を使わない呼び出しの印（同じスレッドの間だけ）
edit(A, "// Dynamic DLL loader for AzooKey engine\n", '''// 判定の門（tools/apply_jev_gate.py）: このスレッドの AzooKey の変換を、人工知能なし（辞書だけ）にする印。
thread_local bool g_azookey_no_ai = false;
// 人工知能なしの呼び出しでも打ち間違いの補正の探索を残すか（MYIME_JEV_GATE_NOAI_TYPO=1）。既定は止める（探索は変換1回で約55ミリ秒かかる）。
static bool JevGateNoAiKeepsTypo() {
  static const bool keep = [] {
    const char* value = std::getenv("MYIME_JEV_GATE_NOAI_TYPO");
    return value != nullptr && value[0] == '1';
  }();
  return keep;
}

// Dynamic DLL loader for AzooKey engine
''')
edit(A, "        loader.SetTypoCorrectionEnabled(typo_correction_enabled);\n",
     "        loader.SetTypoCorrectionEnabled(typo_correction_enabled && !(g_azookey_no_ai && !JevGateNoAiKeepsTypo()));\n")
edit(A, "        loader.SetTypoCorrectionUseAi(typo_correction_use_ai);\n",
     "        loader.SetTypoCorrectionUseAi(typo_correction_use_ai && !g_azookey_no_ai);\n")
edit(A, """      const char* candidates_json = loader.ConvertTextWithContext
          ? loader.ConvertTextWithContext(key.c_str(), left.c_str(), right.c_str(), allow_learning)
          : loader.ConvertText(key.c_str(), allow_learning);
""", """      const char* candidates_json = g_azookey_no_ai
          ? (loader.ConvertTextNoAI
                 ? loader.ConvertTextNoAI(key.c_str(), left.c_str(), right.c_str(), allow_learning)
                 : nullptr)
          : (loader.ConvertTextWithContext
                 ? loader.ConvertTextWithContext(key.c_str(), left.c_str(), right.c_str(), allow_learning)
                 : loader.ConvertText(key.c_str(), allow_learning));
""")
edit(A, "bool HasLoadedZenzaiModelForReading(absl::string_view reading) {\n", '''ScopedAzooKeyNoAI::ScopedAzooKeyNoAI() : previous_(g_azookey_no_ai) { g_azookey_no_ai = true; }
ScopedAzooKeyNoAI::~ScopedAzooKeyNoAI() { g_azookey_no_ai = previous_; }

bool HasLoadedZenzaiModelForReading(absl::string_view reading) {
''')
edit(H, "}  // namespace mozc\n\n#endif  // MOZC_CONVERTER_AZOOKEY_IMMUTABLE_CONVERTER_H_", '''// 判定の門（tools/apply_jev_gate.py）: この物がある間、同じスレッドの AzooKey の変換は人工知能を使わない（辞書だけ）。
class ScopedAzooKeyNoAI {
 public:
  ScopedAzooKeyNoAI();
  ~ScopedAzooKeyNoAI();
  ScopedAzooKeyNoAI(const ScopedAzooKeyNoAI&) = delete;
  ScopedAzooKeyNoAI& operator=(const ScopedAzooKeyNoAI&) = delete;

 private:
  bool previous_;
};

}  // namespace mozc

#endif  // MOZC_CONVERTER_AZOOKEY_IMMUTABLE_CONVERTER_H_''')

# ---- 3. engine/ に部品を写し、BUILD に足す ----
E = mozc / "engine"
for name in ("jev_gate.cc", "jev_gate.h", "jevgate_core.h"):
    shutil.copyfile(gate / name, E / name)
BUILD = E / "BUILD.bazel"
edit(BUILD, '''mozc_cc_library(
    name = "engine",
    srcs = [
        "engine.cc",
        "whole_surface_path_v2.h",
    ],
''', '''# 判定の門の推論（tools/apply_jev_gate.py）。AVX2 の命令を使うので、この部品だけに指定する（実行時に AVX2 がなければ読み込まない）。
mozc_cc_library(
    name = "jev_gate",
    srcs = [
        "jev_gate.cc",
        "jevgate_core.h",
    ],
    hdrs = ["jev_gate.h"],
    copts = select({
        "//:compiler_msvc_like": ["/arch:AVX2"],
        "//conditions:default": [
            "-mavx2",
            "-mfma",
            "-O3",
        ],
    }),
)

mozc_cc_library(
    name = "engine",
    srcs = [
        "engine.cc",
        "whole_surface_path_v2.h",
    ],
''')
edit(BUILD, '''    deps = [
        "//converter:azookey_async_converter",
        ":data_loader",
        ":engine_converter",
''', '''    deps = [
        "//converter:azookey_async_converter",
        ":data_loader",
        ":engine_converter",
        ":jev_gate",
''')

# ---- 4. engine.cc ----
EC = E / "engine.cc"
edit(EC, '#include "whole_surface_path_v2.h"\n', '#include "whole_surface_path_v2.h"\n#include "jev_gate.h"\n')
edit(EC, "#include <utility>\n", "#include <utility>\n#include <functional>\n#include <map>\n#include <queue>\n#include <set>\n")
config_text = (gate / "engine_gate_config.inc").read_text(encoding="utf-8")
edit(EC, "// Runs the whole-sentence AI query for the reading being typed in a\n",
     config_text + "// Runs the whole-sentence AI query for the reading being typed in a\n")
edit(EC, "      prefetch_typing_ = delay > 0;\n", "      prefetch_typing_ = delay > 0 && !JevGateEnabled();\n")
gate_text = (gate / "engine_gate.inc").read_text(encoding="utf-8")
edit(EC, """  static void PreferWholePhrase(const ConversionOptions& options,
                                const ImmutableConverterInterface& mozc,
""", gate_text + """  static void PreferWholePhrase(const ConversionOptions& options,
                                const ImmutableConverterInterface& mozc,
""")
edit(EC, """    // Loaded status only qualifies this optional query; it does not prove request NN execution.
    Segments full(*segments); full.InitForConvert(key);
""", """    // 判定の門: 生成が要らないと当てたら、生成なしの候補から zenz の採点で選んで終わる（既定は無効）。
    if (JevGateSkipGeneration(options, azoo, pos, segments, key, left, right, original)) return;
    // Loaded status only qualifies this optional query; it does not prove request NN execution.
    Segments full(*segments); full.InitForConvert(key);
""")
print("jev gate ok")
