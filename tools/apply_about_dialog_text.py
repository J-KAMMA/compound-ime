"""「このソフトについて」の画面の英語の文を日本語にし、人工知能の状態の出し方を直す。

  python tools/apply_about_dialog_text.py <mozc/src>
apply_version_display.py の最後から呼ばれる（製品名・版の表示の直後）。

直すところ:
  変換エンジンの行（「Engine: AzooKey (Zenzai: ...)」）を日本語にする。
  著作権の行の「Based on Mozc.」を日本語にする（Copyright の一文は法的な表記なので英語のまま）。
  リンクの「issues」を「不具合の報告」にする。

人工知能の状態は、確かめられる事実だけを出す。
  ウィンドウズでは、変換エンジン（mozc_server.exe 内）が自分の状態をレジストリに書き、
  設定の画面（mozc_tool.exe）がそれを読む。ところが mozc_server.exe は権限を絞った
  プロセスで、レジストリの書き込みが「アクセス拒否（5）」で失敗する（記録に
  「RegCreateKeyExW failed: 5」が残る）。そのため状態の記録が無いのが普通で、
  以前は「engine status unverified」と出ていた。変換そのものには影響しない。
  今は、記録があって現在の模型と一致するときだけ「動作を確認済み」または「読み込みに
  失敗」と出し、記録が無いときは「人工知能のファイルあり（版 …）」と事実だけを出す。
"""
import re
import sys
from pathlib import Path

src = Path(sys.argv[1])


def edit(path, old, new, count=1):
    p = src / path
    t = p.read_text(encoding="utf-8")
    assert t.count(old) == count, (path, old[:70], t.count(old))
    p.write_text(t.replace(old, new), encoding="utf-8", newline="")


CC = "gui/about_dialog/about_dialog.cc"
UI = "gui/about_dialog/about_dialog.ui"

# --- リンクの名前 ------------------------------------------------------------
edit(CC, 'Replace(replaced, "[ForumName]", QObject::tr("issues"));',
     'Replace(replaced, "[ForumName]", QString::fromUtf8("不具合の報告"));')

# --- 著作権の行 --------------------------------------------------------------
edit(UI, "<string>Copyright 2026 CompoundIME contributors. Based on Mozc.</string>",
     "<string>Copyright 2026 CompoundIME contributors. Mozc をもとにしています。</string>")

# --- 変換エンジンの行 --------------------------------------------------------
NEW_BLOCK = '''  // 確かめられる事実だけを出す。ウィンドウズでは変換エンジン側からの状態の記録
  // （レジストリ）が権限の都合で書けないことがあり、記録が無くても変換は動いている。
  // 記録が無いことを「未確認」と出すと利用者に誤解を与えるので、ファイルの有無と版だけを出す。
  std::string engine_info = "変換エンジン: AzooKey";
#ifdef _WIN32
  const auto engine_state =
      internal::ReadHkcuMozcDword(L"AzooKeyEngineState");
  if (engine_state == 1) {
    engine_info += "（部品を読み込めません: " +
                   internal::WideToUtf8(
                       internal::ReadHkcuMozcString(L"AzooKeyEngineError")) +
                   "）";
  } else if (engine_state == 2) {
    engine_info += "（初期化に失敗しました: " +
                   internal::WideToUtf8(
                       internal::ReadHkcuMozcString(L"AzooKeyEngineError")) +
                   "）";
  } else {
#endif  // _WIN32
    if (!IsZenzaiUserEnabled()) {
      engine_info += "（Zenzai: 使わない設定）";
    } else if (!ZenzaiModelExists()) {
      engine_info += "（Zenzai: 人工知能のファイルが見つかりません）";
    } else {
      const std::string model_file =
          "人工知能のファイルあり、版 " + GetZenzaiModelVersionString();
#ifdef _WIN32
      const std::wstring model_state =
          internal::ReadHkcuMozcString(L"ZenzaiModelState");
      const auto active = internal::ReadHkcuMozcDword(L"ZenzaiActive");
      const std::string model_path = GetZenzaiWeightPath();
      const bool matching_model =
          !model_path.empty() &&
          internal::WideToUtf8(
              internal::ReadHkcuMozcString(L"ZenzaiWeightPath")) ==
          model_path;
      if (matching_model && model_state == L"loaded" && active == 1) {
        engine_info += "（Zenzai: " + model_file + "、動作を確認済み）";
      } else if (matching_model && active == 0 && model_state == L"failed") {
        engine_info += "（Zenzai: " + model_file + "、読み込みに失敗した記録があります）";
      } else {
        engine_info += "（Zenzai: " + model_file + "）";
      }
#else
      engine_info += "（Zenzai: " + model_file + "）";
#endif  // _WIN32
    }
#ifdef _WIN32
    if (engine_state == 0 &&
        internal::ReadHkcuMozcDword(L"AzooKeyLearningActive") == 0) {
      engine_info += " ／ 学習: 無効";
    }
  }
#endif  // _WIN32
'''
p = src / CC
t = p.read_text(encoding="utf-8")
start = t.index("  // Runtime reports are snapshots; file presence alone does not prove loading.\n")
end = t.index("  engine_label->setText(")
old_block = t[start:end]
# 想定した元の形かを確かめる（形が違えば、黙って壊さず止める）
for anchor in ('"Engine: AzooKey"', "engine status unverified", "Learning: disabled",
               "DLL load failed", "Initialize failed", "Zenzai: Disabled", "Zenzai: Model not found"):
    assert anchor in old_block, anchor
t = t[:start] + NEW_BLOCK + t[end:]
p.write_text(t, encoding="utf-8", newline="")
print("about dialog text applied")
