"""右クリックのメニュー（ひらがな・全角カタカナ…）の文字を大きくする（ウィンドウズ版）。

  python tools/apply_big_menu.py <mozc/src>

右クリックのメニューは IME が自分で出す POPUP メニュー（TipLangBarButton::OnClick の TrackPopupMenu）で、
ウィンドウズの決まりの大きさの文字で描かれる。画面の拡大率が 100% だと小さくて読みにくい
（利用者の声 10/27「これが小さすぎる」「ちいさい」）。

項目を自前で描く（MFT_OWNERDRAW）ようにし、メニューの文字の kBigMenuScale/10 倍の大きさで描く:
  - 描く知らせ（WM_MEASUREITEM・WM_DRAWITEM）はメニューの持ち主の窓に届く。メニューを出している間だけ
    持ち主の窓の受け口を差し替えて自分で受け、閉じたら元に戻す（同じスレッドの窓なので安全）
  - 色は窓の決まりの色（メニューの地・文字・選択中・押せない）を使う。選ばれている項目には ● を付ける
  - 区切り線はウィンドウズが描く
apply_version_display.py（一番上に版の名前を出す）のあとに流す。
"""
import sys
from pathlib import Path

src = Path(sys.argv[1])
M = "win32/tip/tip_lang_bar_menu.cc"


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


edit(M, "#include <algorithm>\n", "#include <algorithm>\n#include <vector>\n")
edit(M, "// メニューの一番上に出す", r"""// 右クリックのメニューを、決まりの文字の kScale 倍で自前で描く（apply_big_menu.py）。
constexpr int kBigMenuScale = 12;  // 10 分の 1 の単位（1.2 倍。1.8 倍は大きすぎた）

struct BigMenu {
  std::vector<std::wstring> texts;
  std::vector<bool> checked;
  HFONT font = nullptr;
  WNDPROC original = nullptr;
};
thread_local BigMenu* g_big_menu = nullptr;  // メニューを出している間だけ

LRESULT CALLBACK BigMenuProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
  BigMenu* big = g_big_menu;
  if (big != nullptr && message == WM_MEASUREITEM) {
    auto* item = reinterpret_cast<MEASUREITEMSTRUCT*>(lparam);
    if (item->CtlType == ODT_MENU && item->itemData > 0 && item->itemData <= big->texts.size()) {
      const std::wstring& text = big->texts[item->itemData - 1];
      HDC dc = ::GetDC(window);
      HGDIOBJ old = ::SelectObject(dc, big->font);
      SIZE size = {};
      ::GetTextExtentPoint32W(dc, text.c_str(), static_cast<int>(text.size()), &size);
      ::SelectObject(dc, old);
      ::ReleaseDC(window, dc);
      item->itemHeight = size.cy * 4 / 3;
      item->itemWidth = size.cx + item->itemHeight * 2;
      return TRUE;
    }
  }
  if (big != nullptr && message == WM_DRAWITEM) {
    auto* item = reinterpret_cast<DRAWITEMSTRUCT*>(lparam);
    if (item->CtlType == ODT_MENU && item->itemData > 0 && item->itemData <= big->texts.size()) {
      const size_t index = item->itemData - 1;
      const bool selected = (item->itemState & ODS_SELECTED) != 0;
      const bool grayed = (item->itemState & (ODS_GRAYED | ODS_DISABLED)) != 0;
      ::FillRect(item->hDC, &item->rcItem,
                 ::GetSysColorBrush(selected && !grayed ? COLOR_HIGHLIGHT : COLOR_MENU));
      ::SetBkMode(item->hDC, TRANSPARENT);
      ::SetTextColor(item->hDC, ::GetSysColor(grayed     ? COLOR_GRAYTEXT
                                              : selected ? COLOR_HIGHLIGHTTEXT
                                                         : COLOR_MENUTEXT));
      HGDIOBJ old = ::SelectObject(item->hDC, big->font);
      RECT rect = item->rcItem;
      const int mark = rect.bottom - rect.top;
      if (big->checked[index]) {
        RECT mark_rect = {rect.left, rect.top, rect.left + mark, rect.bottom};
        ::DrawTextW(item->hDC, L"●", 1, &mark_rect, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
      }
      rect.left += mark;
      const std::wstring& text = big->texts[index];
      ::DrawTextW(item->hDC, text.c_str(), static_cast<int>(text.size()), &rect,
                  DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX);
      ::SelectObject(item->hDC, old);
      return TRUE;
    }
  }
  return ::CallWindowProcW(big != nullptr ? big->original : ::DefWindowProcW, window, message, wparam,
                           lparam);
}

// |menu| の文字の項目を自前で描く印に替え、|owner| の窓の受け口を差し替えてメニューを出す。
// 差し替えられないとき（持ち主の窓がない）は、そのまま出す。
UINT TrackBigPopupMenu(HMENU menu, UINT flags, int x, int y, HWND owner) {
  BigMenu big;
  NONCLIENTMETRICSW metrics = {};
  metrics.cbSize = sizeof(metrics);
  if (owner != nullptr && g_big_menu == nullptr &&
      ::SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof(metrics), &metrics, 0)) {
    metrics.lfMenuFont.lfHeight = metrics.lfMenuFont.lfHeight * kBigMenuScale / 10;
    metrics.lfMenuFont.lfWidth = 0;
    big.font = ::CreateFontIndirectW(&metrics.lfMenuFont);
  }
  if (big.font != nullptr) {
    big.original = reinterpret_cast<WNDPROC>(
        ::SetWindowLongPtrW(owner, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(&BigMenuProc)));
  }
  if (big.original != nullptr) {
    g_big_menu = &big;
    const int count = ::GetMenuItemCount(menu);
    for (int i = 0; i < count; ++i) {
      wchar_t text[256] = {};
      MENUITEMINFOW info = {};
      info.cbSize = sizeof(info);
      info.fMask = MIIM_FTYPE | MIIM_STATE | MIIM_STRING;
      info.dwTypeData = text;
      info.cch = ARRAYSIZE(text);
      if (!::GetMenuItemInfoW(menu, i, TRUE, &info) || (info.fType & MFT_SEPARATOR)) continue;
      big.texts.emplace_back(text);
      big.checked.push_back((info.fState & MFS_CHECKED) != 0);
      MENUITEMINFOW owner_draw = {};
      owner_draw.cbSize = sizeof(owner_draw);
      owner_draw.fMask = MIIM_FTYPE | MIIM_DATA;
      owner_draw.fType = (info.fType & ~MFT_RADIOCHECK) | MFT_OWNERDRAW;
      owner_draw.dwItemData = big.texts.size();
      ::SetMenuItemInfoW(menu, i, TRUE, &owner_draw);
    }
  }
  const UINT result = static_cast<UINT>(::TrackPopupMenu(menu, flags, x, y, 0, owner, nullptr));
  if (g_big_menu == &big) {
    ::SetWindowLongPtrW(owner, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(big.original));
    g_big_menu = nullptr;
  }
  if (big.font != nullptr) ::DeleteObject(big.font);
  return result;
}

// メニューの一番上に出す""")
edit(M, """  const BOOL result = ::TrackPopupMenu(menu.get(), kMenuFlags, point.x, point.y,
                                       0, ::GetFocus(), nullptr);""",
     """  const UINT result = TrackBigPopupMenu(menu.get(), kMenuFlags, point.x, point.y, ::GetFocus());""")
