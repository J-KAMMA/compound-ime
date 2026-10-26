"""新しい絵文字（Unicode 12.1 以降）を、OS が表示できるなら候補に出す。

  python tools/apply_emoji_renderable.py <mozc/src>

Mozc は、アプリ側（client）が「表示できる文字の組」（Request.additional_renderable_character_groups）を
伝えないと、絵文字 12.1 以降を候補から全部外す（rewriter/environmental_filter_rewriter.cc）。
いまの Mozc（unok/mozc 2d993fd）のアプリ側には、それを伝える処理（本家の client/character_renderability.cc）が
まだないので、どの OS でも 1918 個のうち 199 個が出なかった。

変換をする側（同じ計算機で動く）で OS の版を見て、本家と同じ基準で組を足す。
  ウィンドウズ: 22000 以上で 12.1〜13.1、22621 で 14.0、22631 で 15.0、26100 で 15.1、26200 で 16.0・17.0
  Mac: 12.1〜13.1 は常に、12.3 で 14.0、13.3 で 15.0、14.4 で 15.1、15.4 で 16.0、26.4 で 17.0
  Linux: 12.1〜14.0（本家と同じ。字体は入っている Noto Color Emoji 次第）
アプリが伝えた組はそのまま使い、足りない組だけを足す。
"""
import sys
from pathlib import Path

src = Path(sys.argv[1])
F = "rewriter/environmental_filter_rewriter.cc"


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


edit(F, '#include "rewriter/environmental_filter_rewriter.h"\n',
     '''#include "rewriter/environmental_filter_rewriter.h"

#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif  // WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif  // NOMINMAX
#include <windows.h>
#elif defined(__APPLE__)
#include <sys/sysctl.h>
#endif  // _WIN32, __APPLE__
''')

edit(F, '''bool EnvironmentalFilterRewriter::Rewrite(const ConversionRequest& request,
                                          Segments* segments) const {
  DCHECK(segments);
  const std::vector<AdditionalRenderableCharacterGroup> nonrenderable_groups =
      GetNonrenderableGroups(
          request.request().additional_renderable_character_groups());
''', '''namespace {

// この OS が表示できる新しい絵文字の組（tools/apply_emoji_renderable.py）。
std::vector<AdditionalRenderableCharacterGroup> OsEmojiGroups() {
  std::vector<AdditionalRenderableCharacterGroup> groups;
#if defined(_WIN32)
  // GetVersionEx は互換の版を返すので、ntdll の RtlGetVersion で本当の版（ビルド番号）を見る
  struct OsVersion {
    ULONG size, major, minor, build, platform;
    WCHAR service_pack[128];
  } version = {sizeof(OsVersion)};
  using RtlGetVersionFn = LONG(WINAPI*)(OsVersion*);
  const HMODULE ntdll = ::GetModuleHandleW(L"ntdll.dll");
  const auto rtl_get_version =
      ntdll == nullptr ? nullptr
                       : reinterpret_cast<RtlGetVersionFn>(
                             ::GetProcAddress(ntdll, "RtlGetVersion"));
  const int build =
      rtl_get_version != nullptr && rtl_get_version(&version) == 0
          ? static_cast<int>(version.build)
          : 0;
  if (build >= 22000) {
    groups.push_back(commands::Request::EMOJI_12_1);
    groups.push_back(commands::Request::EMOJI_13_0);
    groups.push_back(commands::Request::EMOJI_13_1);
  }
  if (build >= 22621) groups.push_back(commands::Request::EMOJI_14_0);
  if (build >= 22631) groups.push_back(commands::Request::EMOJI_15_0);
  if (build >= 26100) groups.push_back(commands::Request::EMOJI_15_1);
  if (build >= 26200) {
    groups.push_back(commands::Request::EMOJI_16_0);
    groups.push_back(commands::Request::EMOJI_17_0);
  }
#elif defined(__APPLE__)
  char text[32] = {};
  size_t size = sizeof(text) - 1;
  int major = 0, minor = 0;
  if (::sysctlbyname("kern.osproductversion", text, &size, nullptr, 0) == 0) {
    const char* p = text;
    for (; *p >= '0' && *p <= '9'; ++p) major = major * 10 + (*p - '0');
    if (*p == '.') {
      for (++p; *p >= '0' && *p <= '9'; ++p) minor = minor * 10 + (*p - '0');
    }
  }
  const int v = major * 10000 + minor;
  groups.push_back(commands::Request::EMOJI_12_1);
  groups.push_back(commands::Request::EMOJI_13_0);
  groups.push_back(commands::Request::EMOJI_13_1);
  if (v >= 120003) groups.push_back(commands::Request::EMOJI_14_0);
  if (v >= 130003) groups.push_back(commands::Request::EMOJI_15_0);
  if (v >= 140004) groups.push_back(commands::Request::EMOJI_15_1);
  if (v >= 150004) groups.push_back(commands::Request::EMOJI_16_0);
  if (v >= 260004) groups.push_back(commands::Request::EMOJI_17_0);
#elif defined(__linux__)
  groups.push_back(commands::Request::EMOJI_12_1);
  groups.push_back(commands::Request::EMOJI_13_0);
  groups.push_back(commands::Request::EMOJI_13_1);
  groups.push_back(commands::Request::EMOJI_14_0);
#endif  // _WIN32, __APPLE__, __linux__
  return groups;
}

}  // namespace

bool EnvironmentalFilterRewriter::Rewrite(const ConversionRequest& request,
                                          Segments* segments) const {
  DCHECK(segments);
  // アプリが伝えた組に、この OS が表示できる絵文字の組を足す（OS の版は変換の間に変わらないので1回だけ見る）
  static const std::vector<AdditionalRenderableCharacterGroup>* os_groups =
      new std::vector<AdditionalRenderableCharacterGroup>(OsEmojiGroups());
  ::mozc::protobuf::RepeatedField<int> renderable =
      request.request().additional_renderable_character_groups();
  for (const AdditionalRenderableCharacterGroup group : *os_groups) {
    if (absl::c_find(renderable, static_cast<int>(group)) == renderable.end()) {
      renderable.Add(group);
    }
  }
  const std::vector<AdditionalRenderableCharacterGroup> nonrenderable_groups =
      GetNonrenderableGroups(renderable);
''')
print("emoji renderable: OS emoji groups added")
