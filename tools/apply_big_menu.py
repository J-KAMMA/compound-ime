"""右クリックのメニュー（ひらがな・全角カタカナ…）の文字を大きくする（ウィンドウズ版）。

  python tools/apply_big_menu.py <mozc/src>

右クリックのメニューは IME が自分で出す POPUP メニュー（TipLangBarButton::OnClick の TrackPopupMenu）で、
ウィンドウズの決まりの大きさの文字で描かれる。画面の拡大率が 100% だと小さくて読みにくい
（利用者の声 10/27「これが小さすぎる」「ちいさい」）。

項目を自前で描く（MFT_OWNERDRAW）ようにし、メニューの文字の kBigMenuScale/10 倍の大きさで描く:
  - 描く知らせ（WM_MEASUREITEM・WM_DRAWITEM）はメニューの持ち主の窓に届く。メニューを出している間だけ
    持ち主の窓の受け口を差し替えて自分で受け、閉じたら元に戻す（同じスレッドの窓なので安全）
  - 地の色はウィンドウズが塗った色を読み、暗い・明るいに合わせて文字の色を決める（ウィンドウズ 11 の
    メニューに似せる: 選んでいる項目は角の丸い帯、選ばれている種類は小さな点）
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
constexpr int kBigMenuScale = 13;  // 10 分の 1 の単位（1.3 倍。1.8 倍は大きすぎた）

struct BigMenu {
  std::vector<std::wstring> texts;
  std::vector<bool> checked;
  HFONT font = nullptr;
  WNDPROC original = nullptr;
  bool have_background = false;
  COLORREF background = 0;  // ウィンドウズが塗ったメニューの地の色（暗い・明るいはアプリによる）
};
thread_local BigMenu* g_big_menu = nullptr;  // メニューを出している間だけ

COLORREF Shift(COLORREF color, int amount) {
  const auto channel = [&](int value) { return static_cast<BYTE>(std::clamp(value + amount, 0, 255)); };
  return RGB(channel(GetRValue(color)), channel(GetGValue(color)), channel(GetBValue(color)));
}

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
      // ウィンドウズ 11 のメニューと同じく、行の高さは文字のおよそ 2 倍、左に印の場所、右に余白
      item->itemHeight = size.cy * 9 / 5;
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
      RECT rect = item->rcItem;
      const int height = rect.bottom - rect.top;
      // 地の色は、ウィンドウズが項目の外に塗った色を読む（アプリが暗いメニューなら暗い）
      if (!big->have_background) {
        const COLORREF sampled = ::GetPixel(item->hDC, rect.left, rect.top);
        big->background = sampled == CLR_INVALID ? ::GetSysColor(COLOR_MENU) : sampled;
        big->have_background = true;
      }
      const COLORREF background = big->background;
      const bool dark = GetRValue(background) * 299 + GetGValue(background) * 587 + GetBValue(background) * 114 <
                        128 * 1000;
      HBRUSH fill = ::CreateSolidBrush(background);
      ::FillRect(item->hDC, &rect, fill);
      ::DeleteObject(fill);
      if (selected && !grayed) {  // 選んでいる項目は、角の丸い少し違う色の帯
        const int inset = height / 8;
        HBRUSH band = ::CreateSolidBrush(Shift(background, dark ? 20 : -14));
        HGDIOBJ old_brush = ::SelectObject(item->hDC, band);
        HGDIOBJ old_pen = ::SelectObject(item->hDC, ::GetStockObject(NULL_PEN));
        ::RoundRect(item->hDC, rect.left + inset, rect.top + inset / 2, rect.right - inset + 1,
                    rect.bottom - inset / 2 + 1, height / 4, height / 4);
        ::SelectObject(item->hDC, old_pen);
        ::SelectObject(item->hDC, old_brush);
        ::DeleteObject(band);
      }
      const COLORREF text_color = grayed ? (dark ? RGB(0x9d, 0x9d, 0x9d) : RGB(0x6d, 0x6d, 0x6d))
                                         : (dark ? RGB(0xff, 0xff, 0xff) : RGB(0x1a, 0x1a, 0x1a));
      if (big->checked[index]) {  // 選ばれている入力の種類には、小さな点
        const int dot = (std::max)(4, height / 6);
        const int cx = rect.left + height / 2, cy = (rect.top + rect.bottom) / 2;
        HBRUSH brush = ::CreateSolidBrush(text_color);
        HGDIOBJ old_brush = ::SelectObject(item->hDC, brush);
        HGDIOBJ old_pen = ::SelectObject(item->hDC, ::GetStockObject(NULL_PEN));
        ::Ellipse(item->hDC, cx - dot / 2, cy - dot / 2, cx + dot / 2 + 1, cy + dot / 2 + 1);
        ::SelectObject(item->hDC, old_pen);
        ::SelectObject(item->hDC, old_brush);
        ::DeleteObject(brush);
      }
      ::SetBkMode(item->hDC, TRANSPARENT);
      ::SetTextColor(item->hDC, text_color);
      HGDIOBJ old = ::SelectObject(item->hDC, big->font);
      rect.left += height;
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
