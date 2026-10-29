# 「今の変換は違う」をその場で記録する（Ctrl+Shift+F12）

変換がおかしいと思ったときに **Ctrl+Shift+F12** を押すと、その文をパソコンの中のファイルに1行残します。
あとで `tools/misconversions_to_tests.py` で試験の表の下書きにし、直す材料にします。

## 押すとき

| いつ押すか | 記録するもの | キーはどうなるか |
|---|---|---|
| 変換中（候補を選んでいる途中） | 打ったキー・読み・今の表示の全体・選んでいる文節 | IME が受け取る（表示は変わらない） |
| 入力中（変換の前） | 打ったキー・読み・今の表示 | IME が受け取る |
| 何も打っていないとき | 直前に確定した文（**2分以内**・同じ入力欄・まだ記録していないもの） | 記録するものがあれば IME が受け取る。なければアプリへそのまま渡す |

- 同じ確定は1回だけ記録します。2回目に押すと、キーはアプリへ渡ります。
- 入力欄が変わると（アプリが入力欄の印を教える場合）、直前の確定は忘れます。
- 押しても画面には何も出ません（Mozc に軽く知らせる表示の仕組みがないため）。記録できたかはファイルを開いて確かめてください。

### キーを Ctrl+Shift+F12 にした理由

- Mozc の4つのキー割り当て（MS-IME・ATOK・ことえり・ChromeOS）のどれにも使われていない。F12 を使うのは ATOK 風の **Ctrl+F12**（設定画面）だけで、Shift を足せばぶつからない。
- 打つ途中の指の動きで偶然押すことがない。
- アプリ側では Word の印刷（Ctrl+Shift+F12）などに使われている。そのため、**何も打っていないときは、記録するもの（2分以内の未記録の確定）があるときだけ**受け取り、ほかはアプリへ渡す。確定の直後に Word で Ctrl+Shift+F12 を押すと、1回目は記録になり、印刷は2回目で始まる。

## 記録の中身

ファイルはタブ区切りで、1行目は見出しです。

```
# 時刻	種類	ローマ字	読み	出た変換	選んでいた文節	直前の文
2026-10-29T10:15:02	commit	kisyanokisyagakisyadekisyasita	きしゃのきしゃがきしゃできしゃした	記者の記者が汽車で帰社した		今日のニュースです。
2026-10-29T10:16:40	convert	kousei	こうせい	構成	構成	文の
```

- 種類: `commit`（確定のあと）、`convert`（変換中）、`compose`（入力中）。
- ローマ字: 打ったキーそのもの（かな入力ならかな）。
- 直前の文: アプリが教える入力欄の前の文、なければ IME が覚えている直前の確定。**最後の 40 字まで**。
- 1つの欄は 256 バイトまで。ファイルが 1MB を超えたら古い半分を捨てます。

## プライバシー

- **外へは送りません。** 書くのはこの PC のファイルだけで、通信はしません。
- **自分でキーを押したときだけ**書きます。押さなければファイルはできません。
- 次のときは何も覚えず、キーも横取りしません:
  - パスワードの欄（アプリが入力の種類を IME に教える場合。教えないアプリでは見分けられません）
  - シークレットモード（設定、またはアプリが教えるもの）
  - 環境変数 `MYIME_MISS_REPORT=0`（この機能を止める。設定したあとサインインし直すと確実に効く）
- 打った文がそのまま入ります。人に渡す・公開の試験の表に入れる前に、中身を確かめてください。

### ファイルの場所

| OS | 場所 |
|---|---|
| ウィンドウズ | `%USERPROFILE%\AppData\LocalLow\CompoundIME\misconversions.tsv` |
| マック | `~/Library/Application Support/CompoundIME/misconversions.tsv` |
| Linux | `~/.config/compound-ime/misconversions.tsv` |

### 消し方

- ファイルをそのまま消してかまいません（次に押したとき、新しく作ります）。
- 設定の「入力履歴の消去」（学習の履歴を消す）でも一緒に消えます。

ウィンドウズの PowerShell:

```powershell
Remove-Item "$env:USERPROFILE\AppData\LocalLow\CompoundIME\misconversions.tsv"
```

マック・Linux:

```sh
rm ~/Library/Application\ Support/CompoundIME/misconversions.tsv   # マック
rm ~/.config/compound-ime/misconversions.tsv                       # Linux
```

## 試験の表の下書きにする

```sh
python tools/misconversions_to_tests.py                 # この PC の既定の場所を読んで画面に出す
python tools/misconversions_to_tests.py misconversions.tsv -o draft.tsv --context
```

出る列は `ローマ字<TAB>期待<TAB>出た変換`（`--context` で4列目に直前の文）。期待の欄は空なので、正しい変換を書き込み、書いた行だけを試験に使います。同じローマ字・同じ出た変換は1行にまとめます。

## 作り（開発者向け）

- 本体: `native/jaen-detector/miss_report.h`（標準の C++ だけ。単体試験 `miss_report_test.cc` は g++ で動く。`linux-test.yml` の単体試験の段で流す）。
- Mozc への差し込み: `tools/apply_miss_report.py`（`apply_jaen_integration.py` の後。4つの組み立て手順に足した）。
  - `Session` が直前の確定を1つ持つ（`jaen::LastCommit`）。各呼び出しの前に組み立て中のキーと読みを写し（確定すると消えるため）、後で確定の結果（`Output.result` の値と読み）と合わせて覚える。ファイルに書くのはキーを押したときだけ。
  - `SendKey` の始め（`HandleIndirectImeOnOff` の直後）でキーを見る。ウィンドウズは先に `TestSendKey` で受け取るかを聞くので、何も打っていないときは同じ条件（記録するものがあるか）で答える。
  - 学習の履歴を消すと、`converter::ClearMissReport()` がファイルを消す。
- 既存の `correction_log.tsv`（別の候補・F6〜F10・文節の区切り直しを自動で残す記録。既定は無効）とは別のファイル。こちらは利用者が「違う」と言った文だけを残す。
- 確かめていないこと: Mozc 本体としての組み立て（差し込みの位置は、上流の `session.cc`・`session.h`・`session/BUILD.bazel` に `mozc-base.patch` と `apply_jaen_integration.py` の session の部分を当てた木で、1か所ずつ当たることを確かめた）、各 OS で Ctrl+Shift+F12 が IME まで届くか。
