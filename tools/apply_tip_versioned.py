"""新しい版を入れたあと、再起動しなくても使えるようにする（ウィンドウズ版）。

  python tools/apply_tip_versioned.py <mozc/src>

文字を打つアプリはどれも、入力の画面側の部品（mozc_tip64.dll、32ビットのアプリは mozc_tip32.dll）を開いたままにする。
同じ名前のファイルは使用中だと上書きできないので、インストーラーは「次の起動時に置き換える」と予約して、
再起動を求めていた（1.155 の記録: 「mozc_tip64.dll は使用中です」、置き換わったのはこの部品だけ）。

部品を版ごとに別の名前（mozc_tip64-3.34.6239.156.dll）で置き、登録をその名前に向け直す:
  - 入れたあとに開いたアプリから新しい版になる。開いていたアプリは、開き直すまで古い版のまま
  - 部品はインストーラーの管理から外し（Permanent）、上書き・削除の予約が起きないようにする
  - 入れ終わったとき（commit）に、使われていない古い版の部品を消す（CleanupOldTip）。使用中のものは
    消せないので残し、次に入れたときに消す
  - 削除するときは全部の版の部品を消し、使用中のものは次の起動時に消す（RemoveAllTip、再起動は求めない）
部品の場所は登録（CLSID の InprocServer32）からフォルダーだけを見る作り（base/system_util.cc）なので、
名前を変えても変換の本体・設定の道具は同じフォルダーを見つける。
"""
import sys
from pathlib import Path

src = Path(sys.argv[1])
W = "win32/installer/installer_oss_64bit.wxs"
C = "win32/custom_action/custom_action.cc"


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


# 消すとき（REMOVE=ALL）は再起動を求める決まり（ScheduleReboot）が、新しい版へ入れ替えるときの古い版の削除でも
# 動き、1.157 では入れ替えだけで「再起動が必要」と出た。入れ替えのときは求めない（効くのは、この決まりを持つ版を
# 次に入れ替えるときから）
edit(W, '<ScheduleReboot After="InstallFinalize" Condition="(REMOVE=&quot;ALL&quot;)" />',
     '<ScheduleReboot After="InstallFinalize" Condition="(REMOVE=&quot;ALL&quot;) AND (NOT UPGRADINGPRODUCTCODE)" />')

# インストーラー: 版つきの名前で置き、インストーラーの管理から外す
for name, bits in (("mozc_tip32", "32"), ("mozc_tip64", "64")):
    edit(W, f'''<Component Id="MozcTIP{bits}" Permanent="no" Bitness="always{bits}">
          <File Id="{name}.dll" Name="{name}.dll"''', f'''<Component Id="MozcTIP{bits}" Permanent="yes" Bitness="always{bits}">
          <File Id="{name}.dll" Name="{name}-$(var.MozcVersion).dll"''')
edit(W, '''    <CustomAction Id="NewerVersionError" Error="4000" />''',
     '''    <CustomAction Id="CleanupOldTip" DllEntry="CleanupOldTip" Execute="commit" Impersonate="no" Return="ignore" BinaryRef="mozc_installer_helper.dll" />
    <CustomAction Id="RemoveAllTip" DllEntry="RemoveAllTip" Execute="deferred" Impersonate="no" Return="ignore" BinaryRef="mozc_installer_helper.dll" />
    <CustomAction Id="NewerVersionError" Error="4000" />''')
edit(W, '''      <Custom Action="UnregisterTIP64" After="UnregisterTIPRollback64" Condition="(REMOVE=&quot;ALL&quot;) AND (NOT UPGRADINGPRODUCTCODE) AND (VersionNT64)" />''',
     '''      <Custom Action="UnregisterTIP64" After="UnregisterTIPRollback64" Condition="(REMOVE=&quot;ALL&quot;) AND (NOT UPGRADINGPRODUCTCODE) AND (VersionNT64)" />
      <Custom Action="RemoveAllTip" After="UnregisterTIP64" Condition="(REMOVE=&quot;ALL&quot;) AND (NOT UPGRADINGPRODUCTCODE)" />''')
edit(W, '''      <Custom Action="EnableTipProfile" Before="InstallFinalize"''',
     '''      <Custom Action="CleanupOldTip" Before="EnableTipProfile" Condition="NOT (REMOVE=&quot;ALL&quot;)" />
      <Custom Action="EnableTipProfile" Before="InstallFinalize"''')

# 登録の処理: 版つきの名前を登録し、古い版の部品を消す
edit("win32/custom_action/custom_action.def", "    RegisterTIP\n", "    RegisterTIP\n    CleanupOldTip\n    RemoveAllTip\n")
edit(C, '''std::wstring GetMozcComponentPath(const absl::string_view filename) {
  return mozc::win32::Utf8ToWide(
      absl::StrCat(mozc::SystemUtil::GetServerDirectory(), "\\\\", filename));
}
''', '''std::wstring GetMozcComponentPath(const absl::string_view filename) {
  return mozc::win32::Utf8ToWide(
      absl::StrCat(mozc::SystemUtil::GetServerDirectory(), "\\\\", filename));
}

// The TIP DLL of this version: mozc_tip64.dll → mozc_tip64-<version>.dll. Each version
// has its own file, so a new one is installed while apps still hold the old one.
std::string VersionedTip(const absl::string_view filename) {
  const absl::string_view stem = filename.substr(0, filename.rfind('.'));
  return absl::StrCat(stem, "-", mozc::Version::GetMozcVersion(), ".dll");
}

// Deletes the TIP DLLs of other versions (all of them with |keep_current| false).
// Ones still loaded by apps cannot be deleted: they are left for the next install, or
// deleted on the next start when the IME is removed.
void DeleteTipFiles(bool keep_current) {
  const std::wstring dir =
      mozc::win32::Utf8ToWide(mozc::SystemUtil::GetServerDirectory());
  const std::wstring keep[] = {
      mozc::win32::Utf8ToWide(VersionedTip(mozc::kMozcTIP32)),
      mozc::win32::Utf8ToWide(VersionedTip(mozc::kMozcTIP64)),
      mozc::win32::Utf8ToWide(VersionedTip(mozc::kMozcTIP64X))};
  WIN32_FIND_DATAW data = {};
  const HANDLE find = ::FindFirstFileW((dir + L"\\\\mozc_tip*.dll").c_str(), &data);
  if (find == INVALID_HANDLE_VALUE) return;
  do {
    const std::wstring name = data.cFileName;
    bool current = false;
    for (const std::wstring& k : keep) current = current || _wcsicmp(name.c_str(), k.c_str()) == 0;
    if (keep_current && current) continue;
    const std::wstring path = dir + L"\\\\" + name;
    if (!::DeleteFileW(path.c_str()) && !keep_current) {
      ::MoveFileExW(path.c_str(), nullptr, MOVEFILE_DELAY_UNTIL_REBOOT);
    }
  } while (::FindNextFileW(find, &data));
  ::FindClose(find);
}
''')
for tip in ("kMozcTIP32", "kMozcTIP64"):
    # ストアのアプリ（AppContainer）にも読ませる許可は、版つきの部品に付ける
    edit(C, f'''  if (!mozc::WinSandbox::EnsureAllApplicationPackagesPermisssion(
          GetMozcComponentPath(mozc::{tip}),''', f'''  if (!mozc::WinSandbox::EnsureAllApplicationPackagesPermisssion(
          GetMozcComponentPath(VersionedTip(mozc::{tip})),''')
edit(C, '''  const std::wstring tip64_path = GetMozcComponentPath(
      is_arm64_machine ? mozc::kMozcTIP64X : mozc::kMozcTIP64);''', '''  const std::wstring tip64_path = GetMozcComponentPath(
      VersionedTip(is_arm64_machine ? mozc::kMozcTIP64X : mozc::kMozcTIP64));''')
edit(C, '''  const std::wstring tip32_path = GetMozcComponentPath(mozc::kMozcTIP32);''',
     '''  const std::wstring tip32_path = GetMozcComponentPath(VersionedTip(mozc::kMozcTIP32));''')
edit(C, '''// [Return='ignore']
UINT __stdcall UnregisterTIPRollback(MSIHANDLE msi_handle) {''', '''// [Return='ignore', Execute='commit']
// After an install or update has succeeded: deletes the TIP DLLs of older versions.
UINT __stdcall CleanupOldTip(MSIHANDLE msi_handle) {
  DEBUG_BREAK_FOR_DEBUGGER();
  DeleteTipFiles(true);
  return ERROR_SUCCESS;
}

// [Return='ignore']
// When the IME is removed: deletes the TIP DLLs of every version.
UINT __stdcall RemoveAllTip(MSIHANDLE msi_handle) {
  DEBUG_BREAK_FOR_DEBUGGER();
  DeleteTipFiles(false);
  return ERROR_SUCCESS;
}

// [Return='ignore']
UINT __stdcall UnregisterTIPRollback(MSIHANDLE msi_handle) {''')
print("tip versioned: ok")
