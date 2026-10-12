# ビルド手順

コンパウンドIMEは、上流の MyIME のソースツリーに、このリポジトリのスクリプトとソースを重ねて作ります。ここには改造部分とその生成器だけがあり、上流のソースは含みません。`<...>` は各自の環境に合わせて置き換えてください。Windows 10/11 x64、Visual Studio（MSVC、C++ と Windows SDK）、Git for Windows、Python 3.13、LLVM（clang-cl）、.NET SDK（WiX 用）が必要です。

## 1. 上流の入力（固定版）

| 入力 | 版 | 入手先 |
|---|---|---|
| MyIME | コミット `a8486eca5312556ff88fed7f1850a28843b67977` | https://github.com/unok/myime |
| Mozc（MyIME の submodule `mozc/`） | コミット `2d993fd532c0df849ff3a5f6c7851b3757471ed6` | https://github.com/unok/mozc |
| llama.cpp（fork） | コミット `10131b23ee0dbd9d03dfc618cec9fe3402919277`（タグ b4846） | https://github.com/fkunn1326/llama.cpp |
| Zenzai モデル | `ggml-model-Q5_K_M.gguf`、SHA-256 `29c223d4c23327b80fd13ebb5ab2555057a46317997d5da391584ffbef0db673` | https://huggingface.co/Miwa-Keita/zenz-v3.2-small-gguf/resolve/c67e03e07d215c869f591b274c1631170d3e11fe/ggml-model-Q5_K_M.gguf |
| Swift | 6.3.3 | https://download.swift.org/swift-6.3.3-release/windows10/swift-6.3.3-RELEASE/swift-6.3.3-RELEASE-windows10.exe |
| Bazel | 9.0.2（Bazelisk 経由、`USE_BAZEL_VERSION`） | |
| Qt | 6.9.1 | 下の 4 |
| WiX | 5.0.2 | |

固定版の一覧は `versions.json`、Swift 依存の固定は `tools/swift-Package.resolved` にあります。モデルはリポジトリにも MSI にも含めません。インストール時に公式の配布元から取得します。

外部データ（生成器が取得します。このリポジトリは取得しません）:

- SCOWL 2020.12.07: https://downloads.sourceforge.net/project/wordlist/SCOWL/2020.12.07/scowl-2020.12.07.tar.gz 、SHA-256 `5587667caa20c4891390c2d42dbb4d5c4c3f41bee77af1457ece3ba23fb859cc`（`tools/build_english_lexicon.py` が自動で取得して照合。`--archive` で手元のファイルも指定可）
- SudachiDict 由来の `mozcdic-ut-sudachidict.txt.bz2`（Apache-2.0）: https://github.com/utuhiro78/mozcdic-ut-sudachidict の配布物。SHA-256 `d2cb4b2b16d513e257d26d1c33673ebda254a1d5aa0c3c0c9bc94f932619fbdc`（`tools/build_ut_dictionary.py` に記録した採用版。展開した `mozcdic-ut-sudachidict.txt` を置いたフォルダーを `--ut` に渡す）
- CMU Pronouncing Dictionary（`cmudict.dict`、BSD、https://github.com/cmusphinx/cmudict）: `tools/data/loanwords.tsv` を作り直すときだけ必要

`tools/data/*` は生成済みの語彙・対応表です。通常は作り直さずそのまま使えます。第三者の著作権表示は `docs/credits_en.html` にあります。

## 2. 作業ツリーを用意する

```
git clone https://github.com/unok/myime.git <work>/myime
git -C <work>/myime checkout a8486eca5312556ff88fed7f1850a28843b67977
git -C <work>/myime submodule update --init --recursive   # mozc は 2d993fd5
```

続けて、このリポジトリの `patches/` にある土台の改修（文脈処理・非同期変換・学習まわり）を当てます。

```
git -C <work>/myime/mozc apply --whitespace=nowarn <this-repo>/patches/mozc-base.patch
git -C <work>/myime apply --whitespace=nowarn <this-repo>/patches/myime-engine.patch
```

`mozc-base.patch` は Mozc 2d993fd5 に、`myime-engine.patch` は MyIME a8486eca の Swift 側（`src/`）に当たります。当てた結果が開発に使った土台と一致することは、ファイル単位で確認済みです（改行コードの違いを除く）。

以降、`<src>` は `<work>/myime/mozc/src` です。`apply_jaen_integration.py` は 1 つの作業ツリーに 1 回だけ実行します。やり直すときは新しく用意し直してください。

## 3. 生成器（適用の前に実行）

```
python tools/build_english_lexicon.py --out <lex>                       # english-lexicon.txt, curated-words.txt, SCOWL-Copyright.txt
python tools/build_ut_dictionary.py --mozc <src> --ut <ut-dir> --sources sudachidict --out <tmp>/dictionary10.txt --install
```

`build_ut_dictionary.py --install` は `<src>/data/dictionary_oss/dictionary10.txt` を置き、その BUILD.bazel に追加します。ローマ字別名辞書（dictionary11）と仮名の3文字連接モデルは、次の適用スクリプトが `tools/build_romaji_alias_dictionary.py` と `tools/build_kana_model.py` を呼んで作ります。

任意（`tools/data` の作り直し）: `build_brand_casing.py`（`--ut` に上記 txt）、`build_hepburn_names.py`、`build_loanword_pairs.py`（`--cmudict`、`--lexicon`）。

## 4. precision117 エンジンを重ねる

```
copy native/precision117/engine.cc                   <src>/engine/engine.cc
copy native/precision117/whole_surface_path_v2.h     <src>/engine/whole_surface_path_v2.h
```

## 5. 改造を適用する

```
python tools/apply_jaen_integration.py <src> <lex>
```

日英判定（`native/jaen-detector`）、辞書、変換、製品名の変更（最後に `tools/apply_compound_branding.py`、アイコンは `tools/make_compound_icon.py`、Pillow が必要）をすべて適用します。成功すると `applied` と表示します。

## 6. azooKey 変換エンジン DLL

llama.cpp（上記の fork、b4846）には、日本語などを含むパスから推論用 DLL を読めるようにする `patches/llama-utf8.patch` を当ててからビルドします。

Swift 6.3.3 のツールチェーンを `<work>/swift` に置き、`tools/build-engine.ps1 -BuildRoot <work> -SwiftSdk <Windows SDK for Swift> -VisualStudioDirectory <VS>` で `azookey-engine.dll` を作ります（MyIME の `src/swift-engine` を `swift build -c release`。Package.resolved が `tools/swift-Package.resolved` と一致することを確認します）。出力は `<work>/myime/build/x64/release/` に置かれます。

## 7. Qt 6.9.1

Mozc の `build_tools/build_qt.py` で作ります。手順とソースの入手先は `docs/QT-SOURCE.md`。

```
python build_tools/build_qt.py --release --confirm_license
```

`<src>/third_party/qt/` に出力されます。

## 8. Bazel ビルド

```
set BAZEL_SH=<Git>\usr\bin\bash.exe
set BAZEL_VC=<VS>\VC
set USE_BAZEL_VERSION=9.0.2
set BAZEL_LLVM=<llvm>
set DOTNET_CLI_HOME=<work>\dotnet-home          (.NET SDK を PATH に)
set PYTHONUTF8=1
cd <src>
bazelisk --batch --output_user_root=<bazel-root> build --config=oss_windows --spawn_strategy=local --jobs=8 ^
  --generate_json_trace_profile=no --nocheck_visibility ^
  "--copt=/clang:-resource-dir=<llvm>/lib/clang/<clang の版>" "--host_copt=/clang:-resource-dir=<llvm>/lib/clang/<clang の版>" ^
  --action_env=MOZC_VERSION=<版番号> ^
  //server:mozc_server_win //renderer/win32:win32_renderer_main //win32/broker:mozc_broker_main ^
  //win32/cache_service:mozc_cache_service //win32/tip:mozc_tip32 //win32/tip:mozc_tip64 ^
  //win32/custom_action //gui/tool:mozc_tool_win //session:session_handler_main
```

`<版番号>` は `3.34.6239.<ビルド番号>` の形です。

## 9. インストーラー（MSI）

Bazel で作った各部品と、手順 6 の DLL・`*.resources`、`docs/credits_en.html`、Qt の DLL を集め、`<src>/win32/installer/build_installer.py` を `<src>` から `python -m win32.installer.build_installer` で呼びます。主な引数:

`--output <msi>` `--branding Mozc` `--arch x64` `--vs_install_dir <VS>\VC` `--azookey_dll_dir <engine フォルダー>` `--version_file <mozc_version.txt>` `--mozc_server` `--mozc_tool` `--mozc_tip64` `--mozc_tip32` `--mozc_renderer` `--mozc_broker` `--mozc_cache_service` `--custom_action <mozc_installer_helper.dll>` `--icon_path <src>/data/images/win/product_icon.ico` `--credit_file docs/credits_en.html` `--qt_core_dll <src>/third_party/qt/bin/Qt6Core.dll` `--wxs_path <src>/win32/installer/installer_oss_64bit.wxs` `--wix_path <wix.cmd>`

azooKey の絵文字辞書（`EmojiDictionary`）は上流に許諾の記載がないため、`AzooKeyKanaKanjiConverter_*.resources` から除いて同梱します。絵文字は Mozc のデータから出ます。
