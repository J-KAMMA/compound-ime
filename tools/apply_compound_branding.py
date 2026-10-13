"""Publishes the build as CompoundIME (コンパウンドIME), side by side with official Mozc.

  python tools/apply_compound_branding.py <mozc/src>
Run by apply_jaen_integration.py as its last step.


New TSF/COM GUIDs, MSI UpgradeCode, product/profile/program folder names,
event/mutex/pipe/window-class/service names, HKCU settings key, and every
user-visible "Mozc" or "Google LLC" (as maker) in the Mozc branding branch.
Upstream copyright notices and the credits page are kept (BSD clauses 1-2).
"""
import re
import sys
from pathlib import Path

src = Path(sys.argv[1])
ASCII, JA = "CompoundIME", "コンパウンドIME"
COMPANY = "CompoundIME Project"
URL = "https://github.com/J-KAMMA/compound-ime"


def edit(path, old, new, count=1):
    p = src / path
    t = p.read_text(encoding="utf-8")
    assert t.count(old) == count, (path, old[:70], t.count(old))
    p.write_text(t.replace(old, new), encoding="utf-8", newline="")


def guid_init(guid):
    a, b, c, d, e = guid.split("-")
    tail = [d[0:2], d[2:4]] + [e[i:i + 2] for i in range(0, 12, 2)]
    return (f"0x{a.lower()},\n    0x{b.lower()},\n    0x{c.lower()},\n    {{" +
            ", ".join(f"0x{x.lower()}" for x in tail) + "}")


def replace_guid(path, old, new):
    """Replaces '// {OLD}' and the GUID initializer that follows it."""
    p = src / path
    t = p.read_text(encoding="utf-8")
    pattern = re.compile(r"// \{" + re.escape(old) + r"\}\n((?:static const|constexpr) GUID \w+ = \{)[^;]*?\}\};", re.S)
    matches = pattern.findall(t)
    assert len(matches) == 1, (path, old, len(matches))
    t = pattern.sub(lambda m: f"// {{{new}}}\n{m.group(1)}\n    {guid_init(new)}}};", t)
    p.write_text(t, encoding="utf-8", newline="")


GUIDS = [
    ("win32/base/tsf_profile.cc", "10A67BC8-22FA-4A59-90DC-2546652C56BF", "9D4DB88F-641D-4DEE-9F14-FA3185A93477"),
    ("win32/base/tsf_profile.cc", "186F700C-71CF-43FE-A00E-AACB1D9E6D3D", "E48BFBC2-BD7D-415B-B66C-2261FB7E7F45"),
    ("win32/tip/tip_display_attributes.cc", "84CA1E7E-3020-4D1C-8968-DDA372D1E067", "5CA27846-E94C-45DB-BDFF-67EC0059819E"),
    ("win32/tip/tip_display_attributes.cc", "8A4028E5-2DCD-4365-A5DC-71F67E797437", "91B64419-D9AB-448B-AD17-77DA8C853862"),
    ("win32/tip/tip_lang_bar.cc", "FC8E2486-F5BA-4863-91C3-8D166B454604", "129522A7-7A4B-46E5-B364-6483AADFB2B2"),
    ("win32/tip/tip_lang_bar.cc", "1BA637CA-7521-4F21-B51E-6516271A9FE3", "B6BFE272-7BF9-4DEC-B3C0-65ADF4CB046E"),
    ("win32/tip/tip_lang_bar.cc", "F78AD6B1-49D3-400E-8218-896F22A70011", "3047CDEE-FD70-4496-9945-170A580212D0"),
    ("win32/tip/tip_text_service.cc", "F16B7D92-84B0-4AC6-A35B-06EA77180A18", "DB67C531-B55D-4E47-B932-EFEAB7EAB93F"),
    ("win32/tip/tip_text_service.cc", "80DAD291-1981-46FA-998D-B84D6C1BA02C", "D01971FD-F422-4BE9-87C4-7DDBD45B485B"),
    ("win32/tip/tip_text_service.cc", "95571C08-B05A-4ABA-B038-F3DEAE532F91", "7A1F7F4E-00DC-458C-B946-9C3A1ED23276"),
    ("win32/tip/tip_text_service.cc", "ECFB2528-E7D2-4CA0-BBE4-32FE08C148F4", "EA87F22A-C872-45E6-80E5-540465BA257F"),
    ("win32/tip/tip_ui_element_delegate.cc", "AD2489FB-D4C4-4632-85A9-7F9F917AB0FD", "328B0A7E-4394-4879-8755-22AF8768CF51"),
    ("win32/tip/tip_ui_element_delegate.cc", "0E2D447F-9B4A-490C-9C4D-61A6A707BE26", "FA25A1D2-9DA4-415D-8987-1A5D377C130A"),
    ("win32/tip/tip_ui_element_delegate.cc", "ED70ECDE-C8AA-4170-96CC-0090DEA8AEC2", "0983746C-D945-427D-90B3-6E89F235A40A"),
    ("win32/tip/tip_ui_element_delegate.cc", "0090BF80-5F33-41B1-843C-E3EC79ED25F9", "41480E75-3765-4EBD-878A-5C455976CC0C"),
]
for path, old, new in GUIDS:
    replace_guid(path, old, new)
edit("base/system_util.cc", 'L"{10A67BC8-22FA-4A59-90DC-2546652C56BF}"', 'L"{9D4DB88F-641D-4DEE-9F14-FA3185A93477}"')
edit("win32/tip/tip_lang_bar_menu.h", '#define IIDSTR_IMozcLangBarItem "75B2153A-504B-48C9-9257-BA8D60E523E6"',
     '#define IIDSTR_IMozcLangBarItem "E80E30F8-BCDA-4606-BBA5-28CAD1656504"')
edit("win32/tip/tip_lang_bar_menu.h", '#define IIDSTR_IMozcLangBarToggleItem "9ABF0C3B-4AC6-4DED-9EF6-97E728852CF3"',
     '#define IIDSTR_IMozcLangBarToggleItem "3D7247EF-EE35-418D-A01C-0DB90444D4A4"')
edit("win32/installer/build_installer.py", "    upgrade_code = 'DD94B570-B5E2-4100-9D42-61930C611D8A'",
     "    upgrade_code = '5C585624-F0D2-4899-B999-11B493EC6247'  # CompoundIME")

# Names in base/const.h (Mozc branch only).
C = "base/const.h"
edit(C, 'inline constexpr char kProductNameInEnglish[] = "Mozc";\n#define kProductPrefix "Mozc"',
     f'inline constexpr char kProductNameInEnglish[] = "{ASCII}";\n#define kProductPrefix "{ASCII}"')
for old, new in [
    ('inline constexpr char kCompanyNameInEnglish[] = "Mozc Project";', f'inline constexpr char kCompanyNameInEnglish[] = "{COMPANY}";'),
    ('inline constexpr char kEventPathPrefix[] = "Local\\\\Mozc.event.";', f'inline constexpr char kEventPathPrefix[] = "Local\\\\{ASCII}.event.";'),
    ('inline constexpr char kMutexPathPrefix[] = "Local\\\\Mozc.mutex.";', f'inline constexpr char kMutexPathPrefix[] = "Local\\\\{ASCII}.mutex.";'),
    ('inline constexpr wchar_t kMozcCacheServiceName[] = L"MozcCacheService";', f'inline constexpr wchar_t kMozcCacheServiceName[] = L"{ASCII}CacheService";'),
    ('    L"mozc.renderer.message";', f'    L"{ASCII.lower()}.renderer.message";'),
    ('inline constexpr wchar_t kMessageReceiverClassName[] = L"mozc.renderer.window";', f'inline constexpr wchar_t kMessageReceiverClassName[] = L"{ASCII.lower()}.renderer.window";'),
    ('inline constexpr wchar_t kCandidateWindowClassName[] = L"MozcCandidateWindow";', f'inline constexpr wchar_t kCandidateWindowClassName[] = L"{ASCII}CandidateWindow";'),
    ('    L"MozcCompositionWindow";', f'    L"{ASCII}CompositionWindow";'),
    ('inline constexpr wchar_t kIndicatorWindowClassName[] = L"MozcIndicatorWindow";', f'inline constexpr wchar_t kIndicatorWindowClassName[] = L"{ASCII}IndicatorWindow";'),
    ('inline constexpr wchar_t kInfolistWindowClassName[] = L"MozcInfolistWindow";', f'inline constexpr wchar_t kInfolistWindowClassName[] = L"{ASCII}InfolistWindow";'),
    ('inline constexpr wchar_t kIMEUIWndClassName[] = L"MozcUIWindow";', 'inline constexpr wchar_t kIMEUIWndClassName[] = L"CompoundUIWnd";'),
    ('inline constexpr char kIPCPrefix[] = "\\\\\\\\.\\\\pipe\\\\mozc.";', f'inline constexpr char kIPCPrefix[] = "\\\\\\\\.\\\\pipe\\\\{ASCII.lower()}.";'),
    ('inline constexpr wchar_t kCandidateUIDescription[] = L"MozcCandidateUI";', f'inline constexpr wchar_t kCandidateUIDescription[] = L"{ASCII}CandidateUI";'),
    ('inline constexpr wchar_t kConfigurationDisplayname[] = L"Mozc Configuration";', f'inline constexpr wchar_t kConfigurationDisplayname[] = L"{ASCII} Configuration";'),
    ('inline constexpr wchar_t kMozcRegKey[] = L"Software\\\\Mozc Project\\\\Mozc";', f'inline constexpr wchar_t kMozcRegKey[] = L"Software\\\\{ASCII}";'),
    ('    L"Software\\\\Policies\\\\Mozc Project\\\\Mozc\\\\Preferences";', f'    L"Software\\\\Policies\\\\{ASCII}\\\\Preferences";'),
]:
    edit(C, old, new)
assert len("CompoundUIWnd") < 16  # kIMEUIWndClassName limit incl. NUL

# MyIME settings key, model and learning folders.
for path, n in [("converter/engine_config.cc", 2), ("converter/azookey_immutable_converter.cc", 2),
                ("gui/config_dialog/config_dialog.cc", 6)]:
    edit(path, 'L"Software\\\\Mozc"', f'L"Software\\\\{ASCII}"', n)
edit("gui/config_dialog/config_dialog.cc", "RegCreateKeyExW(Software\\\\Mozc) failed", f"RegCreateKeyExW(Software\\\\{ASCII}) failed", 6)
edit("converter/engine_config.cc", 'return base + "\\\\Mozc\\\\models\\\\";', f'return base + "\\\\{ASCII}\\\\models\\\\";', 2)
edit("converter/engine_config.cc", 'L"\\\\Mozc\\\\azookey_memory"', f'L"\\\\{ASCII}\\\\azookey_memory"')

# Version resources: maker, copyright, product, file descriptions.
R = "build_tools/mozc_win32_resource_template.rc"
edit(R, '''  #elif defined(MOZC_BUILD)
    #define MOZC_RES_COMPANY_NAME "Google LLC"''', f'''  #elif defined(MOZC_BUILD)
    #define MOZC_RES_COMPANY_NAME "{COMPANY}"''')
edit(R, '''  #define MOZC_RES_LEGAL_COPYRIGHT "Copyright 2026 Google LLC. All Rights Reserved."''',
     '''  #if defined(MOZC_BUILD)
    #define MOZC_RES_LEGAL_COPYRIGHT "Copyright 2026 CompoundIME contributors. Based on Mozc (Copyright Google LLC, BSD-3-Clause)."
  #else
    #define MOZC_RES_LEGAL_COPYRIGHT "Copyright 2026 Google LLC. All Rights Reserved."
  #endif''')
edit(R, '''  #elif defined(MOZC_BUILD)
    #define MOZC_RES_PRODUCT_NAME "Mozc"''', f'''  #elif defined(MOZC_BUILD)
    #define MOZC_RES_PRODUCT_NAME "{JA}"''')
for path, old in [("gui/tool/mozc_tool.rc", "Mozc Tool"), ("renderer/win32/mozc_renderer.rc", "Mozc Renderer"),
                  ("server/mozc_server.rc", "Mozc Converter"), ("win32/broker/mozc_broker.rc", "Mozc Broker"),
                  ("win32/cache_service/mozc_cache_service.rc", "Mozc Cache Service"),
                  ("win32/custom_action/custom_action.rc", "Mozc Installer Helper"),
                  ("win32/tip/tip_resource.rc", "Mozc TIP Module")]:
    edit(path, f'#define MOZC_RES_FILE_DESCRIPTION "{old}"', f'#define MOZC_RES_FILE_DESCRIPTION "{old.replace("Mozc", ASCII)}"')

# Input switcher names and other TIP strings (ja then en blocks).
T = "win32/tip/tip_resource.rc"
edit(T, 'IDS_IME_DISPLAYNAME     "Mozc"', f'IDS_IME_DISPLAYNAME     "{JA}"', 2)
edit(T, 'IDS_TEXTSERVICE_DISPLAYNAME_SYNONYM  "Mozc"', f'IDS_TEXTSERVICE_DISPLAYNAME_SYNONYM  "{JA}"', 2)
edit(T, 'IDS_ABOUT               "Mozc について"', f'IDS_ABOUT               "{JA} について"')
edit(T, 'IDS_ABOUT               "About Mozc"', f'IDS_ABOUT               "About {ASCII}"')
for ja in ("サジェストウィンドウ", "サジェスト候補ウィンドウ", "候補ウィンドウ", "インジケータ ウィンドウ"):
    edit(T, f'"Mozc {ja}"', f'"{JA} {ja}"')
for en in ("Suggestion Window", "Suggestion Candidate Window", "Candidate Window"):
    edit(T, f'"Mozc {en}"', f'"{ASCII} {en}"')
t = (src / T).read_text(encoding="utf-8")
t = re.sub(r'"Mozc (Indicator Window)"', rf'"{ASCII} \1"', t)
(src / T).write_text(t, encoding="utf-8", newline="")

edit("win32/tip/tip_text_service.cc", 'L"Mozc Immersive Task Message Window"', f'L"{ASCII} Immersive Task Message Window"')
edit("win32/tip/tip_text_service.cc", '"https://github.com/google/mozc"', f'"{URL}"')

# Cache service names shown in services.msc.
S = "win32/cache_service/mozc_cache_service.rc"
s = (src / S).read_text(encoding="utf-8")
s = s.replace('"Mozc Cache Service"', f'"{ASCII} Cache Service"').replace("Mozc の", f"{JA} の").replace("of Mozc", f"of {ASCII}")
(src / S).write_text(s, encoding="utf-8", newline="")

# Server message boxes, installer helper texts.
edit("server/mozc_server_main.cc", 'L"Mozc - Zenzai Model"', f'L"{JA} - Zenzai Model"')
edit("server/mozc_server_main.cc", 'L"Mozc - Error"', f'L"{JA} - エラー"')
edit("win32/custom_action/custom_action.cc", "later from the Mozc settings.", f"later from the {ASCII} settings.")
edit("win32/custom_action/custom_action.rc", '"Mozc インストーラー (バージョン %1!s!)"', f'"{JA} インストーラー (バージョン %1!s!)"')
edit("win32/custom_action/custom_action.rc", '"Mozc Installer (Ver. %1!s!)"', f'"{ASCII} Installer (Ver. %1!s!)"')

# Installer: name, maker, folder, cabinet, service, run value, messages.
W = "win32/installer/installer_oss_64bit.wxs"
edit(W, '<Package Name="Mozc" Language="1041" Codepage="932" Version="$(var.MozcVersion)" Manufacturer="Google LLC"',
     f'<Package Name="{JA}" Language="1041" Codepage="932" Version="$(var.MozcVersion)" Manufacturer="{COMPANY}"')
edit(W, 'Description="Mozc インストーラー" Manufacturer="Google LLC"', f'Description="{JA} インストーラー" Manufacturer="{COMPANY}"')
edit(W, 'Message="Mozc をインストールするには', f'Message="{JA} をインストールするには', 2)
edit(W, 'Cabinet="Mozc.cab"', f'Cabinet="{ASCII}.cab"')
edit(W, '新しいバージョンの Mozc が', f'新しいバージョンの {JA} が')
edit(W, '<Feature Id="MozcInstall" Title="Mozc"', f'<Feature Id="MozcInstall" Title="{JA}"')
edit(W, '<Directory Id="MozcDir" Name="Mozc">', f'<Directory Id="MozcDir" Name="{ASCII}">')
edit(W, 'Name="MozcCacheService"', f'Name="{ASCII}CacheService"', 2)
edit(W, 'Name="Mozc Prelauncher"', f'Name="{ASCII} Prelauncher"')

# Settings tool: product name in every window title, About dialog.
edit("gui/base/util.cc", '''  const QString name = QObject::tr("Mozc");
#endif''', f'''  const QString name = QLocale::system().language() == QLocale::Japanese
                            ? QString::fromUtf8("{JA}")
                            : QStringLiteral("{ASCII}");
#endif''')
edit("gui/about_dialog/about_dialog.cc", 'Replace(replaced, "[ProductUrl]", "https://github.com/google/mozc");',
     f'Replace(replaced, "[ProductUrl]", "{URL}");')
edit("gui/about_dialog/about_dialog.cc", 'Replace(replaced, "[ForumUrl]", "https://github.com/google/mozc/issues");',
     f'Replace(replaced, "[ForumUrl]", "{URL}/issues");')
edit("gui/about_dialog/about_dialog.ui", "<string>Copyright 2026 Google LLC. All rights reserved.</string>",
     "<string>Copyright 2026 CompoundIME contributors. Based on Mozc.</string>")

# Downloader identities.
edit("win32/custom_action/custom_action.cc", 'L"MozcInstaller/1.0"', f'L"{ASCII}Installer/1.0"')
edit("gui/zenzai_download/zenzai_download_dialog.cc", 'L"MozcZenzaiDownloader/1.0"', f'L"{ASCII}ZenzaiDownloader/1.0"')
# Linux 版の名前: 節: Linux 版の名前と置き場所を公式の Mozc と分ける。
#
# /usr/lib/mozc → /usr/lib/compound-ime、~/.config/mozc → ~/.config/compound-ime、
# ibus の部品名 com.google.IBus.Mozc → org.compoundime.IBus.CompoundIME、
# エンジン名 mozc-jp → compound-ime-jp など。ウィンドウズ版には影響しない。


def edit(path, old, new, count=1):
    p = src / path
    t = p.read_text(encoding="utf-8")
    assert t.count(old) == count, (path, old[:70], t.count(old))
    p.write_text(t.replace(old, new), encoding="utf-8", newline="")


edit("config.bzl", '''LINUX_MOZC_ICONS_DIR = "/usr/share/icons/mozc"
LINUX_MOZC_SERVER_DIR = "/usr/lib/mozc"''', '''LINUX_MOZC_ICONS_DIR = "/usr/share/icons/compound-ime"
LINUX_MOZC_SERVER_DIR = "/usr/lib/compound-ime"''')
edit("config.bzl", '''IBUS_MOZC_INSTALL_DIR = "/usr/share/ibus-mozc"''', '''IBUS_MOZC_INSTALL_DIR = "/usr/share/ibus-compound-ime"''')
edit("config.bzl", '''IBUS_MOZC_PATH = "/usr/lib/ibus-mozc/ibus-engine-mozc"''',
     '''IBUS_MOZC_PATH = "/usr/lib/ibus-compound-ime/ibus-engine-compound-ime"''')
edit("config.bzl", '''EMACS_MOZC_CLIENT_DIR = "/usr/share/emacs/site-lisp/emacs-mozc"''',
     '''EMACS_MOZC_CLIENT_DIR = "/usr/share/emacs/site-lisp/emacs-compound-ime"''')

S = "base/system_util.cc"
edit(S, 'constexpr absl::string_view kMozcServerDir = "/usr/lib/mozc";',
     'constexpr absl::string_view kMozcServerDir = "/usr/lib/compound-ime";')
edit(S, 'constexpr absl::string_view kMozcDocumentDir = "/usr/lib/mozc/documents";',
     'constexpr absl::string_view kMozcDocumentDir = "/usr/lib/compound-ime/documents";')
edit(S, '      return FileUtil::JoinPath(pw.pw_dir, ".mozc");', '      return FileUtil::JoinPath(pw.pw_dir, ".compound-ime");')
edit(S, '    std::string old_dir = FileUtil::JoinPath(home, ".mozc");', '    std::string old_dir = FileUtil::JoinPath(home, ".compound-ime");')
edit(S, '      return FileUtil::JoinPath(xdg_config_home, "mozc");', '      return FileUtil::JoinPath(xdg_config_home, "compound-ime");')
edit(S, '    return FileUtil::JoinPath(home, ".config/mozc");', '    return FileUtil::JoinPath(home, ".config/compound-ime");')

edit("unix/ibus/path_util.cc", '#define MOZC_IBUS_INSTALL_DIR "/usr/share/ibus-mozc"',
     '#define MOZC_IBUS_INSTALL_DIR "/usr/share/ibus-compound-ime"')
G = "unix/ibus/gen_mozc_xml.py"
edit(G, "      'name': 'com.google.IBus.Mozc',", "      'name': 'org.compoundime.IBus.CompoundIME',")
edit(G, "      'author': 'Google LLC',", "      'author': 'CompoundIME contributors',")
edit(G, "      'homepage': 'https://github.com/google/mozc',", f"      'homepage': '{URL}',")
edit(G, "      'textdomain': 'ibus-mozc',", "      'textdomain': 'ibus-compound-ime',")
edit(G, "  product_name = PRODUCT_NAMES[options.branding]", f"  product_name = '{JA}'")

C = "unix/ibus/ibus_config.textproto"
edit(C, '''  name : "mozc-jp"
  longname : "Mozc"''', f'''  name : "compound-ime-jp"
  longname : "{JA}"''')
edit(C, '''  name : "mozc-on"
  longname : "Mozc:あ"''', f'''  name : "compound-ime-on"
  longname : "{JA}:あ"''')
edit(C, '''  name : "mozc-off"
  longname : "Mozc:A_"''', f'''  name : "compound-ime-off"
  longname : "{JA}:A_"''')
edit("unix/build_package.py", "        'mozc.xml': os.path.join(args.ibus_component_dir, 'mozc.xml'),",
     "        'mozc.xml': os.path.join(args.ibus_component_dir, 'compound-ime.xml'),")
edit(G, "<!-- * $XDG_CONFIG_HOME/mozc/ibus_config.textproto -->", "<!-- * $XDG_CONFIG_HOME/compound-ime/ibus_config.textproto -->")
edit(G, "<!-- * $HOME/.config/mozc/ibus_config.textproto -->", "<!-- * $HOME/.config/compound-ime/ibus_config.textproto -->")
edit(G, "<!-- * $HOME/.mozc/ibus_config.textproto -->", "<!-- * $HOME/.compound-ime/ibus_config.textproto -->")

# Mac 版の名前: 節: Mac 版の名前と置き場所を公式の Mozc と分ける。
#
# /Library/Input Methods/Mozc.app → CompoundIME.app（中の MozcConverter.app なども
# CompoundIMEConverter.app などに）、識別子 org.mozc.inputmethod.Japanese →
# org.compoundime.inputmethod.Japanese、学習データ ~/Library/Application Support/Mozc
# → .../CompoundIME、入力メニューの名前を「コンパウンドIME」に。ウィンドウズ版と
# Linux 版には影響しない。


def edit(path, old, new, count=1):
    p = src / path
    t = p.read_text(encoding="utf-8")
    assert t.count(old) == count, (path, old[:70], t.count(old))
    p.write_text(t.replace(old, new), encoding="utf-8", newline="")


edit("config.bzl", 'MACOS_BUNDLE_ID_PREFIX = "org.mozc.inputmethod.Japanese"',
     'MACOS_BUNDLE_ID_PREFIX = "org.compoundime.inputmethod.Japanese"')
edit("mac/BUILD.bazel", "    bundle_name = BRANDING,\n", '    bundle_name = "CompoundIME",\n')
edit("server/BUILD.bazel", '    bundle_name = BRANDING + "Converter",', '    bundle_name = "CompoundIMEConverter",')
edit("renderer/BUILD.bazel", '    bundle_name = BRANDING + "Renderer",', '    bundle_name = "CompoundIMERenderer",')
edit("gui/tool/BUILD.bazel", '    bundle_name = BRANDING + "Prelauncher",', '    bundle_name = "CompoundIMEPrelauncher",')

# Info.plist の差し込み値（実行ファイル名・識別子・表示名）
T = "build_tools/tweak_info_plist.py"
edit(T, """    domain_prefix = 'org.mozc'
    product_name = 'Mozc'""", """    domain_prefix = 'org.compoundime'
    product_name = 'CompoundIME'""")
edit(T, """      'BRANDING':
          options.branding,""", """      'BRANDING':
          'CompoundIME' if options.branding == 'Mozc' else options.branding,""")
edit(T, "  copyright_message = u'© %d Google Inc.' % _COPYRIGHT_YEAR",
     "  copyright_message = u'© %d CompoundIME contributors' % _COPYRIGHT_YEAR")
S = "build_tools/tweak_info_plist_strings.py"
edit(S, """        'CF_BUNDLE_NAME_EN': 'Mozc',
        'CF_BUNDLE_NAME_JA': 'Mozc',""", f"""        'CF_BUNDLE_NAME_EN': 'CompoundIME',
        'CF_BUNDLE_NAME_JA': '{JA}',""")
edit(S, "        'INPUT_MODE_ANNOTATION': 'Mozc',", f"        'INPUT_MODE_ANNOTATION': '{JA}',")

edit("base/mac/mac_util.mm", 'const char kProjectPrefix[] = "org.mozc.inputmethod.Japanese.";',
     'const char kProjectPrefix[] = "org.compoundime.inputmethod.Japanese.";')
edit("base/system_util.cc", '    return FileUtil::JoinPath(dir, "Mozc");', '    return FileUtil::JoinPath(dir, "CompoundIME");')

A = "mac/ActivatePane/ActivatePane.mm"
edit(A, 'static const unsigned char kInstalledLocation[] = "/Library/Input Methods/Mozc.app";',
     'static const unsigned char kInstalledLocation[] = "/Library/Input Methods/CompoundIME.app";')
edit(A, '    @"/Library/LaunchAgents/org.mozc.inputmethod.Japanese.Converter.plist",',
     '    @"/Library/LaunchAgents/org.compoundime.inputmethod.Japanese.Converter.plist",')
edit(A, '    @"/Library/LaunchAgents/org.mozc.inputmethod.Japanese.Renderer.plist", nil};',
     '    @"/Library/LaunchAgents/org.compoundime.inputmethod.Japanese.Renderer.plist", nil};')
edit(A, 'static NSString *const kSourceID = @"org.mozc.inputmethod.Japanese";',
     'static NSString *const kSourceID = @"org.compoundime.inputmethod.Japanese";')
U = "mac/Uninstaller/Uninstaller.mm"
edit(U, '      "/Library/Input Methods/Mozc.app",', '      "/Library/Input Methods/CompoundIME.app",')
edit(U, '      "/Library/LaunchAgents/org.mozc.inputmethod.Japanese.Converter.plist",',
     '      "/Library/LaunchAgents/org.compoundime.inputmethod.Japanese.Converter.plist",')
edit(U, '      "/Library/LaunchAgents/org.mozc.inputmethod.Japanese.Renderer.plist", "/Applications/Mozc",',
     '      "/Library/LaunchAgents/org.compoundime.inputmethod.Japanese.Renderer.plist", "/Applications/CompoundIME",')

# 起動用の設定（LaunchAgents）: 名前と中身
L = src / "mac/installer/LaunchAgents"
for part in ("Converter", "Renderer"):
    old = L / f"org.mozc.inputmethod.Japanese.{part}.plist"
    text = old.read_text(encoding="utf-8")
    text = text.replace("/Library/Input Methods/Mozc.app/Contents/Resources/Mozc" + part + ".app/Contents/MacOS/Mozc" + part,
                        "/Library/Input Methods/CompoundIME.app/Contents/Resources/CompoundIME" + part +
                        ".app/Contents/MacOS/CompoundIME" + part)
    text = text.replace("org.mozc.inputmethod.Japanese.", "org.compoundime.inputmethod.Japanese.")
    assert "mozc" not in text.lower(), text
    (L / f"org.compoundime.inputmethod.Japanese.{part}.plist").write_text(text, encoding="utf-8", newline="")
    old.unlink()
edit("mac/installer/BUILD.bazel", """        "LaunchAgents/org.mozc.inputmethod.Japanese.Converter.plist",
        "LaunchAgents/org.mozc.inputmethod.Japanese.Renderer.plist",""",
     """        "LaunchAgents/org.compoundime.inputmethod.Japanese.Converter.plist",
        "LaunchAgents/org.compoundime.inputmethod.Japanese.Renderer.plist",""")
edit("mac/installer/distribution.xml", "org.mozc.pkg.JapaneseInput", "org.compoundime.pkg.JapaneseInput", 5)
edit("mac/installer/distribution.xml", "    <title>Mozc</title>", f"    <title>{JA}</title>")
edit("mac/build_package.py", "    identifier = 'org.mozc.pkg.JapaneseInput'", "    identifier = 'org.compoundime.pkg.JapaneseInput'")
P = "mac/installer/postflight_template.sh"
edit(P, "/usr/bin/killall MozcConverter", "/usr/bin/killall CompoundIMEConverter")
edit(P, "/usr/bin/killall MozcRenderer", "/usr/bin/killall CompoundIMERenderer")
edit(P, "/usr/bin/killall Mozc > /dev/null", "/usr/bin/killall CompoundIME > /dev/null")
W = "mac/tweak_installer_files.py"
edit(W, "  name = 'Mozc' if oss else 'GoogleJapaneseInput'", "  name = 'CompoundIME' if oss else 'GoogleJapaneseInput'")
edit(W, """    name = 'Mozc'
    folder = 'Mozc'""", """    name = 'CompoundIME'
    folder = 'CompoundIME'""")

# 消去用アプリの名前（UninstallCompoundIME.app）
edit("mac/BUILD.bazel", """                      oss = "Mozc",
                      prod = "GoogleJapaneseInput",
                  ),
    infoplists = ["Uninstaller/Info.plist"],""", """                      oss = "CompoundIME",
                      prod = "GoogleJapaneseInput",
                  ),
    infoplists = ["Uninstaller/Info.plist"],""")

# Product icon (input switcher, settings tool, Apps list).
import subprocess  # noqa: E402
icons = src / "data/images/win"
subprocess.run([sys.executable, str(Path(__file__).with_name("make_compound_icon.py")), str(icons)], check=True)
(icons / "product_icon.ico").write_bytes((icons / "compound_ime.ico").read_bytes())
(icons / "product_icon_langbar.ico").write_bytes((icons / "compound_ime_langbar.ico").read_bytes())
for name in ("compound_ime.ico", "compound_ime_langbar.ico", "compound_ime-256.png",
             "compound_ime.svg", "compound_ime_langbar-64.png"):
    (icons / name).unlink()
print("branding applied")
