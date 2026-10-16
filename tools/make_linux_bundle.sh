#!/bin/bash
# make_linux_bundle.sh <版> <作業フォルダ> <このリポジトリ> : コンパウンドIME の Linux 版配布物（tar.gz）を作る。
# <作業フォルダ> には myime/（MyIME と Mozc の木）、llama.cpp/、swift/ がある（BUILD.md の Linux 版の節）。
# 中身: Mozc の Linux 一式（ibus 用）、変換エンジン、llama.cpp、Swift の実行部品、
#       辞書などの資源、利用条件の表示、install.sh / uninstall.sh
set -e
V=$1
W=$(cd "$2" && pwd)
REPO=$(cd "$3" && pwd)
OUT=$W/dist/compound-ime-$V-linux-x64
rm -rf $OUT; mkdir -p $OUT/files $OUT/lib
cd $OUT/files
unzip -q $W/myime/mozc/src/bazel-bin/unix/mozc.zip
# Emacs 用の補助は /usr/bin で公式の Mozc と名前がぶつかるので入れない
rm -rf usr/bin/mozc_emacs_helper usr/share/emacs tmp
# Mozc の絵を弓の絵に差し替える（tools/make_compound_icon.py の出力）
# 絵: COMPOUND_ICON_DIR に make_compound_icon.py の出力があればそれを使い、なければここで作る（python3-pil が要る）
IC=${COMPOUND_ICON_DIR:-$W/dist/icons}
[ -n "$COMPOUND_ICON_DIR" ] || { rm -rf $IC; python3 "$REPO/tools/make_compound_icon.py" $IC >/dev/null; }
cp $IC/compound_ime_langbar-64.png usr/share/ibus-compound-ime/product_icon.png
cp $IC/compound_ime-256.png usr/share/icons/compound-ime/mozc.png
cp $IC/compound_ime.svg usr/share/icons/compound-ime/mozc.svg
# 変換エンジンと推論部品、Swift の実行部品は /usr/lib/compound-ime に置く
L=$OUT/lib
cp $W/myime/src/swift-engine/.build/release/libazookey-engine.so $L/
cp $W/llama.cpp/build/bin/libllama.so $W/llama.cpp/build/bin/libggml.so $W/llama.cpp/build/bin/libggml-base.so $W/llama.cpp/build/bin/libggml-cpu.so $L/
# Swift の実行部品: 見つからない部品を、なくなるまで Swift の道具一式から写す
SW=$W/swift/usr/lib/swift/linux
for i in 1 2 3 4 5; do
  missing=$(for f in $L/*.so; do LD_LIBRARY_PATH=$L ldd $f; done | awk '/not found/ {print $1}' | sort -u)
  [ -z "$missing" ] && break
  for so in $missing; do [ -f $SW/$so ] && cp $SW/$so $L/ || { echo "見つからない部品: $so"; exit 1; }; done
done
for d in $W/myime/src/swift-engine/.build/release/*.resources; do
  cp -r $d $L/
done
rm -rf $L/AzooKeyKanaKanjiConverter_KanaKanjiConverterModuleWithDefaultDictionary.resources/EmojiDictionary
cp "$REPO/docs/credits_en.html" $OUT/credits_en.html
cp "$REPO/LICENSE" $OUT/LICENSE
# 新しい版のお知らせ: 版の番号、台本、ログイン時の自動起動（止め方は tools/update-check/README.md）
echo "$V" > $L/version.txt
cp "$REPO/tools/update-check/update_check.sh" $L/update_check.sh
chmod +x $L/update_check.sh
mkdir -p $OUT/files/etc/xdg/autostart
cat > $OUT/files/etc/xdg/autostart/compound-ime-update-check.desktop <<'EOD'
[Desktop Entry]
Type=Application
Name=CompoundIME update check
Name[ja]=コンパウンドIME 新しい版のお知らせ
Exec=/usr/lib/compound-ime/update_check.sh
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOD

cat > $OUT/install.sh <<'EOS'
#!/bin/bash
# コンパウンドIME（Linux 版）を入れる。sudo で実行する。
set -e
[ "$(id -u)" = 0 ] || { echo "sudo ./install.sh で実行してください"; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
cp -a "$HERE/files/." /
mkdir -p /usr/lib/compound-ime
cp -a "$HERE/lib/." /usr/lib/compound-ime/
mkdir -p /usr/share/doc/compound-ime
cp "$HERE/credits_en.html" "$HERE/LICENSE" /usr/share/doc/compound-ime/
# 変換モデル（zenz-v3.2-small を追加学習した ft-v1）を配布ページから取得し、SHA-256 を照合する
M=/usr/share/compound-ime/models; mkdir -p $M
F=zenz-v3.2-small-ft-v1-Q5_K_M.gguf
URL=https://github.com/J-KAMMA/compound-ime/releases/download/model-zenz-ft-v1/$F
SUM=8e957561ce050f69fe89b68d106078b60ee9728a4b9a8260915944429f7a204f
if ! echo "$SUM  $M/$F" | sha256sum -c --status 2>/dev/null; then
  echo "変換モデル（約74MB）を取得しています..."
  curl -fL -o $M/$F.part "$URL"
  echo "$SUM  $M/$F.part" | sha256sum -c --status || { echo "モデルの照合に失敗しました"; rm -f $M/*.part; exit 1; }
  mv $M/$F.part $M/$F
fi
echo "入れました。ibus を再起動してください: ibus restart"
echo "そのあと、設定の「キーボード」または ibus-setup で「コンパウンドIME」を追加します。"
EOS
cat > $OUT/uninstall.sh <<'EOS'
#!/bin/bash
# コンパウンドIME（Linux 版）を外す。学習データ（~/.config/compound-ime など）は消さない。
set -e
[ "$(id -u)" = 0 ] || { echo "sudo ./uninstall.sh で実行してください"; exit 1; }
rm -rf /usr/lib/compound-ime /usr/lib/ibus-compound-ime /usr/share/ibus-compound-ime \
       /usr/share/icons/compound-ime /usr/share/compound-ime /usr/share/doc/compound-ime
rm -f /usr/share/ibus/component/compound-ime.xml /etc/xdg/autostart/compound-ime-update-check.desktop
echo "外しました。ibus を再起動してください: ibus restart"
EOS
chmod +x $OUT/install.sh $OUT/uninstall.sh
cd $W/dist; tar -czf compound-ime-$V-linux-x64.tar.gz compound-ime-$V-linux-x64
sha256sum compound-ime-$V-linux-x64.tar.gz
ls -la compound-ime-$V-linux-x64.tar.gz
find $OUT/files -type f | sort
