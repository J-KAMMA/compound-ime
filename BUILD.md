# ビルド手順

コンパウンドIMEは、上流の MyIME のソースツリーに、このリポジトリのスクリプトとソースを重ねて作ります。ここには改造部分とその生成器だけがあり、上流のソースは含みません。`<...>` は各自の環境に合わせて置き換えてください。Windows 10/11 x64、Visual Studio（MSVC、C++ と Windows SDK）、Git for Windows、Python 3.13、LLVM（clang-cl）、.NET SDK（WiX 用）が必要です。

## 1. 上流の入力（固定版）

| 入力 | 版 | 入手先 |
|---|---|---|
| MyIME | コミット `a8486eca5312556ff88fed7f1850a28843b67977` | https://github.com/unok/myime |
| Mozc（MyIME の submodule `mozc/`） | コミット `2d993fd532c0df849ff3a5f6c7851b3757471ed6` | https://github.com/unok/mozc |
| llama.cpp（fork） | コミット `10131b23ee0dbd9d03dfc618cec9fe3402919277`（タグ b4846） | https://github.com/fkunn1326/llama.cpp |
| Zenzai モデル | `zenz-v3.2-small-ft-v5-mix-Q5_K_M.gguf`、SHA-256 `2f9d9d9679dbd3b38ebd48f402369cc1c66f709bfcf83d70d87ca3353e541fff`（zenz-v3.2-small を追加学習、CC BY-SA 4.0） | https://github.com/J-KAMMA/compound-ime/releases/download/model-zenz-ft-v5/zenz-v3.2-small-ft-v5-mix-Q5_K_M.gguf |
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

大文字を含む英字の固有名詞（`tools/data/proper-nouns.tsv`、Wikidata の CC0 データ）の作り直し: `fetch_wikidata_names.py --out <dir>`（Wikidata の問い合わせサービスと Wikimedia の API から取得。約1時間）、続けて `build_proper_nouns.py`（`--wikidata <dir>` ほか。詳しくは冒頭の説明。英語の検出器の試し用 `native/jaen-detector/jaen_trial.cc` が要る）。日本語だけの文のローマ字と英単語まじりの文は `make_japanese_romaji_corpus.py` で作る。

英語の切り分けだけを手元で動かす（Mozc なし）: `g++ -std=c++20 -O2 -I native/jaen-detector native/jaen-detector/jaen_trial.cc native/jaen-detector/jaen_detector.cc -o jaen_trial`、続けて `JAEN_DICT=<mozc>/src/data/dictionary_oss CONTEXT=1 ./jaen_trial <romaji.tsv と readings.txt の場所> <一覧の場所> < ローマ字の行`（`CONTEXT=1` で、ローマ字として日本語に読める英単語を文脈で決める段まで動く。詳しくは [docs/all-english.md](docs/all-english.md)）。英単語と重なるローマ字の試験の文は `tools/make_allenglish_tests.py` で作り、組 `m` で流す。

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

このスクリプトは、変換エンジン（Swift）の `<work>/myime/src` にも `tools/apply_zenzai_deadline.py` で改造を足します（手順 2 のパッチを当ててあること）。変換 1 回あたりの人工知能の時間の上限（既定 1000 ミリ秒。環境変数 `MYIME_ZENZAI_TIME_LIMIT_MS`、または設定 `ZenzaiTimeLimitMs`。0 で上限なし）と、人工知能の重みのメモリ固定（既定は有効。`MYIME_ZENZAI_MLOCK=0`、または設定 `ZenzaiMemoryLock=0` でやめる）です。足したあとに変換エンジンを組み立て直してください。

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

## 10. Linux 版（ibus、試用版）

Ubuntu 24.04（x64）で確かめています。ウィンドウズ版と同じ手順 2〜5 で作業ツリーを用意したあと、次のようにします。

1. 道具と部品を入れる:
   ```
   sudo apt install -y clang cmake ninja-build libibus-1.0-dev ibus qt6-base-dev libgtk-3-dev \
     gnupg2 libcurl4-openssl-dev libncurses-dev libncurses6 libxml2-dev libz3-dev python3-pil
   ```
   Swift 6.3.3（Ubuntu 24.04 用、https://download.swift.org/swift-6.3.3-release/ubuntu2404/swift-6.3.3-RELEASE/swift-6.3.3-RELEASE-ubuntu24.04.tar.gz 、署名は https://www.swift.org/keys/all-keys.asc で確認）を `<work>/swift` に展開し、bazelisk を用意します。Mozc の Linux 版の組み立ては `ld.lld` という名前のリンカーを探すので、`ld.lld-18` へのリンクを作った道具フォルダーを渡します。
2. llama.cpp（手順 1 の版に `patches/llama-utf8.patch` を当てたもの）を共有ライブラリーとして組み立てる:
   ```
   cmake -S <work>/llama.cpp -B <work>/llama.cpp/build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON \
     -DGGML_NATIVE=OFF -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON -DLLAMA_CURL=OFF \
     -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=OFF
   cmake --build <work>/llama.cpp/build
   ```
3. 変換エンジンを Linux 用に直して組み立てる:
   ```
   python3 tools/apply_linux_engine_port.py <work>/myime/src
   cd <work>/myime/src/swift-engine
   swift build -c release -Xlinker -L<work>/llama.cpp/build/bin -Xlinker -lllama -Xlinker -lggml -Xlinker -lggml-base \
     -Xlinker -rpath -Xlinker '$ORIGIN' -Xswiftc -no-toolchain-stdlib-rpath
   ```
4. Mozc の Linux 版を組み立てる（`apply_jaen_integration.py` が Linux 用の書き換えと名前の変更も済ませています）:
   ```
   cd <src>
   bazelisk build --config oss_linux -c opt --nocheck_visibility \
     --action_env=PATH=<tools>:/usr/bin:/bin --host_action_env=PATH=<tools>:/usr/bin:/bin \
     --linkopt=-B<tools> --host_linkopt=-B<tools> //unix:package
   ```
5. 配布物を作る: `bash tools/make_linux_bundle.sh <版> <work> <このリポジトリ>`。`<work>/dist/compound-ime-<版>-linux-x64.tar.gz` ができます。中の `install.sh` を sudo で実行すると `/usr/lib/compound-ime` などに入り、変換モデルを公式から取得します。公式の Mozc（`/usr/lib/mozc`、ibus の `mozc-jp`）とは名前も置き場所も別です。

試験: `session_handler_main`（`//session:session_handler_main`）で手順 9 と同じ一括試験ができます。開発者の環境では 1,298 入力のうち 1,279 がウィンドウズ版と同じ結果で、残りは人工知能の計算のわずかな差による同点付近の入れ替わりでした。

## 11. Mac 版（試用版）

`.github/workflows/macos.yml` が GitHub の Mac（macos-15、Xcode 16.4、Swift 6.1）で、手順 2〜5 と同じ準備をしたうえで次を行います。手元の Mac でも同じ順に実行できます。

1. Qt 6.9.1 を `build_tools/build_qt.py --release --confirm_license --macos_cpus=arm64` で組み立てる（ソースは手順 1 と同じ tarball）。
2. 変換エンジン: `python3 tools/apply_linux_engine_port.py <work>/myime/src` のあと `swift build -c release`。llama.cpp は上流の azooKey が配る署名済みの xcframework（b4846）を Swift が自動で取得します。
3. `tools/make_compound_icon.py` の絵から `data/images/mac/product_icon.icns` を作る（`sips` と `iconutil`）。
4. `bazelisk build --config oss_macos -c opt --nocheck_visibility //mac:package_files` で作った zip を展開し、`CompoundIMEConverter.app` に `libazookey-engine.dylib`（`Contents/MacOS`）、`llama.framework`（`Contents/Frameworks`）、`*.bundle`（アプリの直下と `Contents/Resources`、絵文字辞書は除く）を入れ、`codesign --force --deep -s -` で簡易署名し直してから、`mac/build_package.py --oss` で `.pkg` にします。
5. 導入時の処理（postflight）が、変換モデルを公式の配布元から `/Library/Application Support/CompoundIME/models` に取得し、SHA-256 を照合します。

名前と置き場所は公式の Mozc と分けてあります（`/Library/Input Methods/CompoundIME.app`、識別子 `org.compoundime.inputmethod.Japanese`、学習データ `~/Library/Application Support/CompoundIME`）。試験の手順（`tools/batch_convert.sh`）では、1,298 文のうち 1,278 がウィンドウズ版と同じ結果でした。
