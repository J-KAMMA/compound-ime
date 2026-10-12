# Qt source code offer (LGPL v3)

CompoundIME (コンパウンドIME) uses the Qt toolkit, version 6.9.1, as dynamic libraries:

- `Qt6Core.dll`, `Qt6Gui.dll`, `Qt6Widgets.dll`
- `platforms\qwindows.dll`

Qt is licensed under the GNU Lesser General Public License version 3 (LGPLv3), which incorporates the GNU General Public License version 3. Both license texts are included in `credits_en.html` ("documents\credits_en.html" in the installed program).

## Corresponding source

The Qt libraries were built, unmodified, from:

| | |
|---|---|
| Archive | `qtbase-everywhere-src-6.9.1.tar.xz` (Qt Base 6.9.1, from the Qt Project, https://download.qt.io/archive/qt/6.9/6.9.1/submodules/) |
| SHA-256 | `40caedbf83cc9a1959610830563565889878bc95f115868bbf545d1914acf28e` |
| Build script | `src/build_tools/build_qt.py` of Mozc (the version in the CompoundIME source, see below) |
| Compiler | Microsoft Visual C++ (MSVC 19.51.36257.0), target x64, Windows |

**The same source archive is published next to each release of CompoundIME** (same download page as the installer), so that anyone who has received the installer can get the matching source from the same place. This offer is valid for at least three years after the release of each version, and applies to anyone who has received the binaries.

No patches were applied to the Qt source. (Mozc's `build_qt.py` unpacks the archive and runs `configure`; it does not patch it.)

## Build command

```
python build_tools/build_qt.py --release --confirm_license
```

(run from `src/` of the Mozc tree, with the archive placed at `src/third_party_cache/qtbase-everywhere-src-6.9.1.tar.xz`.)

`build_qt.py` first builds the Qt host tools (static, release, `-no-gui -no-widgets`; they are not shipped), then builds Qt for the target. The configure options used for the shipped libraries (recorded in `config.opt` of the build tree and in the build log) are:

```
-opensource -c++std c++20 -silent
-no-cups -no-dbus
-no-feature-androiddeployqt -no-feature-animation -no-feature-calendarwidget -no-feature-completer
-no-feature-concatenatetablesproxymodel -no-feature-concurrent -no-feature-dial -no-feature-effects
-no-feature-fontcombobox -no-feature-fontdialog -no-feature-identityproxymodel
-no-feature-image_heuristic_mask -no-feature-imageformatplugin -no-feature-islamiccivilcalendar
-no-feature-itemmodeltester -no-feature-jalalicalendar -no-feature-macdeployqt -no-feature-mdiarea
-no-feature-mimetype -no-feature-movie -no-feature-network -no-feature-poll-exit-on-error
-no-feature-qmake -no-feature-sha3-fast -no-feature-sharedmemory -no-feature-socks5
-no-feature-splashscreen -no-feature-sql -no-feature-sqlmodel -no-feature-sspi
-no-feature-stringlistmodel -no-feature-tabletevent -no-feature-testlib -no-feature-textbrowser
-no-feature-textmarkdownreader -no-feature-textmarkdownwriter -no-feature-textodfwriter
-no-feature-timezone -no-feature-topleveldomain -no-feature-undoview -no-feature-whatsthis
-no-feature-windeployqt -no-feature-wizard -no-feature-xml
-no-icu -no-opengl
-no-sql-db2 -no-sql-ibase -no-sql-mysql -no-sql-oci -no-sql-odbc -no-sql-psql -no-sql-sqlite
-nomake examples -nomake tests
-force-debug-info -ltcg -no-freetype -no-harfbuzz
-platform win32-msvc -intelcet
-confirm-license -release -optimize-size
-prefix <install directory>
```

The CMake invocation generated from these options (from the build log) used `-G Ninja`, `-DCMAKE_BUILD_TYPE=RelWithDebInfo`, `-DCMAKE_INTERPROCEDURAL_OPTIMIZATION_RELWITHDEBINFO=ON`, `-DFEATURE_cxx20=ON`, `-DINPUT_freetype=no`, `-DINPUT_harfbuzz=no`, `-DFEATURE_intelcet=ON`, `-DFEATURE_optimize_size=ON`, and `-DQT_QMAKE_TARGET_MKSPEC=win32-msvc`.

Note: although `-no-freetype -no-harfbuzz` is given (as in Mozc), the resulting Qt 6.9.1 binaries on Windows still contain Qt's bundled FreeType 2.13.3 and HarfBuzz 11.2.1 (the configure summary reports both as enabled). They are therefore attributed in the third-party notices of `credits_en.html`, together with the other bundled libraries (libpng 1.6.48, zlib 1.3.1, PCRE2 10.45 and others).

## Replacing the Qt libraries

The Qt libraries are used as DLLs. You may build Qt 6.9.1 yourself from the source above (or take a compatible Qt 6.9.x build) and replace the files listed at the top in the installation folder (`Qt6*.dll` and `platforms\qwindows.dll`). CompoundIME's terms do not forbid this, nor reverse engineering for debugging such replacements.

## Source of the rest of CompoundIME

CompoundIME is based on Mozc (https://github.com/google/mozc, BSD-3-Clause) and MyIME (https://github.com/unok/myime, MIT). Their licenses do not require the publication of source code; sources are available from those projects.

## Contact

For a copy of the Qt source on physical media or for any question about this offer: please open an issue at https://github.com/J-KAMMA/compound-ime/issues.

Qt is a trademark of The Qt Company Ltd. CompoundIME is not affiliated with or endorsed by The Qt Company.
