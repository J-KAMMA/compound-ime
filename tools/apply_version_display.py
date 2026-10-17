"""利用者に見せる版の名前（コンパウンドIME 1.<通し番号>）を IME の中に出す。

  python tools/apply_version_display.py <mozc/src>
apply_compound_branding.py の最後から呼ばれる。

見せる名前は、中の番号（3.34.6239.N）の4つ目 N から作る。N は組み立てのたびに
version.bzl から入るので、版ごとに手で書き換える所はない。N が 0（試しの組み立て）
のときは「1.0（試し）」と出す。

出す場所:
  ウィンドウズ版の IME のメニュー（「あ」の右クリックと左クリックのメニュー）の一番上、押せない項目
  設定の画面と各画面の題名（製品名の直後に版の名前）
  「このソフトについて」の画面の版の行（中の番号も併記）
"""
import sys
from pathlib import Path

src = Path(sys.argv[1])
JA = "コンパウンドIME"


def edit(path, old, new, count=1):
    p = src / path
    t = p.read_text(encoding="utf-8")
    assert t.count(old) == count, (path, old[:70], t.count(old))
    p.write_text(t.replace(old, new), encoding="utf-8", newline="")


# --- 版の名前を作る関数（全部の土台で共通） ---------------------------------
edit("base/version.h", "  static int GetMozcVersionMajor();",
     """  // 利用者に見せる版の名前。中の番号の4つ目 N から「1.N」を作る。
  // N が 0（試しの組み立て）のときは「1.0（試し）」。
  static std::string GetCompoundVersionName();
#ifdef _WIN32
  static std::wstring GetCompoundVersionNameW();
#endif  // _WIN32

  static int GetMozcVersionMajor();""")
edit("base/version.cc", "std::string Version::GetMozcVersion() { return version::kMozcVersion; }",
     """std::string Version::GetMozcVersion() { return version::kMozcVersion; }

std::string Version::GetCompoundVersionName() {
  const int revision = version::kMozcVersionRevision;
  if (revision == 0) {
    // 「1.0（試し）」（UTF-8。文字コードの設定に左右されないよう数値で書く）
    return std::string("1.0") + "\\xEF\\xBC\\x88" + "\\xE8\\xA9\\xA6" +
           "\\xE3\\x81\\x97" + "\\xEF\\xBC\\x89";
  }
  return "1." + std::to_string(revision);
}""")
edit("base/version.cc", """std::wstring Version::GetMozcVersionW() {
  return win32::Utf8ToWide(version::kMozcVersion);
}""", """std::wstring Version::GetMozcVersionW() {
  return win32::Utf8ToWide(version::kMozcVersion);
}

std::wstring Version::GetCompoundVersionNameW() {
  return win32::Utf8ToWide(GetCompoundVersionName());
}""")

# --- ウィンドウズ版の IME のメニュー ---------------------------------------
M = "win32/tip/tip_lang_bar_menu.cc"
edit(M, '#include "base/win32/com.h"\n',
     '#include "base/version.h"\n#include "base/win32/com.h"\n')
edit(M, '#include "base/win32/com_implements.h"\n',
     '#include "base/win32/com_implements.h"\n#include "base/win32/wide_char.h"\n')
edit(M, 'constexpr char kTextIconFont[] = "ＭＳ ゴシック";\n', f'''constexpr char kTextIconFont[] = "ＭＳ ゴシック";

// メニューの一番上に出す「{JA} 1.N」。押せない項目にする。
// 中の番号から作るので、版ごとに書き換えなくてよい。
constexpr UINT kVersionMenuId = 0xFFFF;

const std::wstring& VersionMenuText() {{
  static const std::wstring* const text = new std::wstring(
      win32::Utf8ToWide(std::string("{JA} ") +
                        Version::GetCompoundVersionName()));
  return *text;
}}

// ITfMenu の先頭に、版の名前（押せない）と区切り線を足す。
HRESULT AddVersionMenuItems(ITfMenu* menu) {{
  const std::wstring& text = VersionMenuText();
  HRESULT result = menu->AddMenuItem(kVersionMenuId, TF_LBMENUF_GRAYED, nullptr,
                                     nullptr, text.c_str(),
                                     static_cast<ULONG>(text.size()), nullptr);
  if (result != S_OK) {{
    return result;
  }}
  return menu->AddMenuItem(kVersionMenuId, TF_LBMENUF_SEPARATOR, nullptr,
                           nullptr, L"", 0, nullptr);
}}
''')
# 右クリックのメニュー（自前の POPUP メニュー）
edit(M, """  wil::unique_hmenu menu(::CreatePopupMenu());
  for (size_t i = 0; i < menu_data_size(); ++i) {""", """  wil::unique_hmenu menu(::CreatePopupMenu());
  // 一番上に版の名前（押せない）と区切り線を出す。
  constexpr int kVersionMenuItems = 2;
  {
    MENUITEMINFO version_info = {};
    version_info.cbSize = CCSIZEOF_STRUCT(MENUITEMINFO, hbmpItem);
    version_info.fMask = MIIM_ID | MIIM_FTYPE | MIIM_STRING | MIIM_STATE;
    version_info.fType = MFT_STRING;
    version_info.fState = MFS_GRAYED;
    version_info.wID = kVersionMenuId;
    version_info.dwTypeData = const_cast<wchar_t*>(VersionMenuText().c_str());
    ::InsertMenuItem(menu.get(), 0, TRUE, &version_info);
    MENUITEMINFO separator_info = {};
    separator_info.cbSize = CCSIZEOF_STRUCT(MENUITEMINFO, hbmpItem);
    separator_info.fMask = MIIM_FTYPE;
    separator_info.fType = MFT_SEPARATOR;
    ::InsertMenuItem(menu.get(), 1, TRUE, &separator_info);
  }
  for (size_t i = 0; i < menu_data_size(); ++i) {""")
edit(M, "    ::InsertMenuItem(menu.get(), i, TRUE, &info);",
     "    ::InsertMenuItem(menu.get(), i + kVersionMenuItems, TRUE, &info);")
# 左クリックのメニュー（ITfMenu）: ボタン型とトグル型
edit(M, """  // Add the menu items of this object to the given ITfMenu object.
  for (size_t i = 0; i < menu_data_size(); ++i) {
    const TipLangBarMenuData* data = menu_data(i);

    const UINT icon_id_for_theme""", """  // Add the menu items of this object to the given ITfMenu object.
  result = AddVersionMenuItems(menu);
  if (result != S_OK) {
    return result;
  }
  for (size_t i = 0; i < menu_data_size(); ++i) {
    const TipLangBarMenuData* data = menu_data(i);

    const UINT icon_id_for_theme""")
edit(M, """  // Add the menu items of this object to the given ITfMenu object.
  for (size_t i = 0; i < menu_data_size(); ++i) {
    const TipLangBarMenuData* data = menu_data(i);
    result = menu->AddMenuItem(i, data->flags_, nullptr, nullptr, data->text_,""", """  // Add the menu items of this object to the given ITfMenu object.
  result = AddVersionMenuItems(menu);
  if (result != S_OK) {
    return result;
  }
  for (size_t i = 0; i < menu_data_size(); ++i) {
    const TipLangBarMenuData* data = menu_data(i);
    result = menu->AddMenuItem(i, data->flags_, nullptr, nullptr, data->text_,""")
edit("win32/tip/BUILD.bazel", """        ":tip_resource",
        "//base/win32:com",
        "//base/win32:com_implements",
        "//bazel/win32:user32",
        "//win32/base:text_icon",""", """        ":tip_resource",
        "//base:version",
        "//base/win32:com",
        "//base/win32:com_implements",
        "//base/win32:wide_char",
        "//bazel/win32:user32",
        "//win32/base:text_icon",""")

# --- 設定の画面・各画面の題名、「このソフトについて」の画面 -----------------
edit("gui/base/util.cc", "#include <utility>\n", "#include <utility>\n\n#include \"base/version.h\"\n")
edit("gui/base/util.cc", """void GuiUtil::ReplaceTitle(QWidget *widget) {
  widget->setWindowTitle(GuiUtil::ReplaceString(widget->windowTitle()));
}""", """void GuiUtil::ReplaceTitle(QWidget *widget) {
  QString title = GuiUtil::ReplaceString(widget->windowTitle());
  // 題名に出る製品名の直後に版の名前（1.N）を足す。
  const QString name = GuiUtil::ProductName();
  const std::string version_name = Version::GetCompoundVersionName();
  const QString name_with_version =
      name + QLatin1Char(' ') +
      QString::fromUtf8(version_name.data(), static_cast<int>(version_name.size()));
  const int position = title.indexOf(name);
  if (position >= 0 && !title.contains(name_with_version)) {
    title.replace(position, name.size(), name_with_version);
  }
  widget->setWindowTitle(title);
}""")
edit("gui/about_dialog/about_dialog.cc", """  std::string version_info = "(" + Version::GetMozcVersion() + ")";
  version_label->setText(QLatin1String(version_info.c_str()));""", """  // 利用者に見せる版の名前（1.N）と、中の番号を小さく併記する。
  const std::string compound_version = Version::GetCompoundVersionName();
  const std::string version_info =
      compound_version + " (" + Version::GetMozcVersion() + ")";
  version_label->setText(GuiUtil::ProductName() + QLatin1Char(' ') +
                         QString::fromUtf8(version_info.c_str()));""")
print("version display applied")
