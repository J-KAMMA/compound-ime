# 複合IME（CompoundIME）


2026年10月に、見える名前を「コンパウンドIME」から「複合IME」に替えました。入れる場所（CompoundIME）や設定・学習の引き継ぎは前と同じで、前の版から上書きで入れられます。
**英語まじりの日本語を、そのまま打てる日本語入力。**
ローマ字で打った英単語は英語のまま残り、日本語の部分だけが漢字かなになります。変換はすべてパソコンの中で動き、打った文字を外へ送りません。

```
ashitanomeetinghagozenchuudesu   →  明日のmeetingは午前中です
githubnipushshiteokimasu         →  GitHubにpushしておきます
kyohaatsui（打ち間違い）           →  今日は暑い
denwabangouhazerokyuuzero        →  電話番号は090
```

[![最新の版](https://img.shields.io/github/v/release/J-KAMMA/compound-ime?include_prereleases&label=%E6%9C%80%E6%96%B0%E3%81%AE%E7%89%88)](https://github.com/J-KAMMA/compound-ime/releases)
[![ライセンス](https://img.shields.io/badge/%E3%83%A9%E3%82%A4%E3%82%BB%E3%83%B3%E3%82%B9-MIT-blue)](LICENSE)
![対応](https://img.shields.io/badge/%E5%AF%BE%E5%BF%9C-Windows%20%7C%20Mac%20%7C%20Linux-informational)

> **試用版です。** 問題があれば[課題欄](https://github.com/J-KAMMA/compound-ime/issues)で教えてください。
> [Mozc](https://github.com/google/mozc) をもとにしていますが、Google とは関係がなく、Google が推奨するものでもありません。

---

## ダウンロード

[**配布ページ（最新の版）**](https://github.com/J-KAMMA/compound-ime/releases) から、使うパソコンに合うファイルを取ってください。

| パソコン | ファイル | 確かめている環境 |
|---|---|---|
| ウィンドウズ | `CompoundIME-1.xxx-windows-x64.msi` | Windows 11（64ビット） |
| マック | `CompoundIME-1.xxx-mac-arm64.pkg` | Apple シリコン、macOS 13 以降（試用） |
| Linux | `compound-ime-1.xxx-linux-x64.tar.gz` | Ubuntu 24.04、ibus（試用） |

版の名前は「1.141」のように、1 と通し番号です。インストーラーには署名がないので、配布ページの `SHA256SUMS.txt` でファイルが同じことを確かめてから使ってください。

---

## できること

### 英語と日本語をまぜて打てる
- `meeting`、`excel`、`remote` のような英単語は、かなに化けずにそのまま残ります。
- 小文字で打っても、`iPhone`、`YouTube`、`GitHub`、`JPYC` のような正しい書き方を1番目に、打ったままの形を2番目に出します。
- 続けて打った英単語の間には空白を入れます（`weeklyreport` → `weekly report`）。
- `made`（まで）、`take`（たけ）、`same`（さめ）のようにローマ字として日本語にも読める英単語は、前後の読みで決めます。`make sure`、`same time`、英語の隣は英語に、助詞・活用が続いて日本語として自然に読める文は日本語のままです（[決め方の表](docs/all-english.md)）。
- カタカナ語は英単語も候補に出します（コンピューター → 2番目に computer）。
- `ulo`（ウォ）や `fula`（ファ）のように l や x で打った小さいかなを、英単語と取り違えません。

### 打ち間違いを直す
- 伸ばす音の抜け：`kyoha` → 今日は、`gakko` → 学校、`ega` → 映画
- 母音の重なり：`tsuduukete` → 続けて
- 入れ替わり：`shiryuo` → 資料、`kareu` → 帰る
- 1文字の打ち損じで読めなくなったローマ字

### 数と日付
- `nijuuyokka` → 24日、`shichigatsuhatsuka` → 7月20日、`gozenkuji` → 午前9時
- 番号を1けたずつ読んだもの：`zerokyuuzero` → 090
- 変換した文の数字は半角にそろえます。

### 文全体を見て変換
- パソコンの中で動く小さな人工知能（[azooKey](https://github.com/azooKey/AzooKeyKanaKanjiConverter) の Zenzai）が、前後の文章を見て同じ読みの言葉を選びます。
- 人工知能の答えが遅いときは、0.7秒でふつうの変換に切り替えるので、入力が止まりません。

### 使い心地
- 候補の窓と入力の種類の表示が、明るい／暗い配色に合わせて切り替わります。
- 新しい版が出ると、1日1回までお知らせします（入れ替えは自動ではしません）。

---

## 打ち方のこつ

| したいこと | 打ち方 |
|---|---|
| 英字のまま入れる | 最初の文字を **Shift** を押しながら打つ（`Zenzai`） |
| 打ったものを英字にする | 打ったあと **F10**（押すたびに小文字・大文字・先頭だけ大文字） |
| 全角の英字にする | **F9** |
| カタカナにする | **F7** |
| 候補を1つ戻る | **↑**（一番上で押すと「そのほかの文字種」に回ります） |

---

## インストール

### ウィンドウズ
1. 配布ページから `.msi` を取って実行します。初めてのときは「発行元不明」の警告が出ます。
2. インストール中に、変換用の人工知能（約74MB）を公式の配布元から取得します。
3. **Windows キー＋スペース**で「複合IME」を選びます。

公式の Mozc と並べて入れられるよう、名前や置き場所をすべて分けています。

### マック（試用）
1. `.pkg` を**右クリック →「開く」**で開きます（署名がないため、ダブルクリックでは開けません）。
2. 「システム設定」→「キーボード」→「入力ソース」の「編集」→「＋」→「日本語」から「複合IME」を追加します。
3. 外すときは「アプリケーション」→「CompoundIME」→「UninstallCompoundIME」。

### Linux（ibus、試用）
```bash
tar xzf compound-ime-1.xxx-linux-x64.tar.gz
cd compound-ime-*/ && sudo ./install.sh && ibus restart
```
入力方式の設定で「複合IME」を追加します。外すときは `sudo ./uninstall.sh`。

---

## プライバシー

- 変換はすべてパソコンの中で行います。打った文字を外へ送ることはありません。
- インターネットにつなぐのは、次の2つだけです。
  - インストールのときに、変換用の人工知能を公式の配布元から取得するとき
  - 新しい版があるかを、1日1回まで GitHub の配布ページに問い合わせるとき（止め方は [tools/update-check/README.md](tools/update-check/README.md)）
- 打った読みと選んだ候補の記録は、**既定では残しません**。

---

## どうやって品質を確かめているか

変更のたびに、GitHub の計算機で次の試験を流し、悪くなった文がないことを確かめてから版を作ります。

| 試験 | 中身 |
|---|---|
| 日本語400文 | 同じ読みの言葉、活用、敬語、数、固有名、カタカナ語、話し言葉、長い文、助詞、慣用句 |
| 英語まじり 470文 | 実装を見ずに作った正解つきの文 |
| 打ち間違い 300文 | 打ち間違いの文と、直してはいけない正しい文 |
| 打ち方の揺れ 約5,000行 | 同じ文を訓令式、l／x の小さいかな、`ltu`、`xn`、`n'` で打っても結果が同じか |
| ウィキペディア 3,000文 | ローマ字で打ち込み、日本語を英単語と取り違えないか |
| 英単語と重なるローマ字 約1,400文 | 英単語と同じ綴りのローマ字をはさんだ文（英語にしたい）と、同じ綴りの日本語の語だけの文（英語にしてはいけない） |
| 1,298文 | 版ごとの変化を全部見比べる |
| 利用者が見つけた失敗 | 報告された失敗が二度と起きないか |

試験の文は人工知能の学習には使いません（学習の材料から自動で除いています）。

---

## これからの予定

- 変換用の人工知能を、このIME向けに追加で学習させる（同じ読みの言葉、話し言葉、英語まじり）
- 候補の中から正しいものを選ぶ専用の、小さく速い人工知能
- 予測変換の改善

---

## ソースから作る

このリポジトリには、上流（[MyIME](https://github.com/unok/myime)、Mozc）への改造と、その生成器だけがあります。`tools/apply_jaen_integration.py` が改造をすべて当てます。手順は [BUILD.md](BUILD.md) にあります。ウィンドウズ版・マック版・Linux 版は GitHub Actions で組み立てられます（`.github/workflows/`）。

以前の開発版（Mozc の名前のもの）から学習データと設定を写すには `tools/migrate-to-compound-ime.ps1` を使います（引数なしで確認だけ、`-Apply` で実行）。

---

## ライセンス

- このリポジトリで新たに書いたコードとデータは [MIT ライセンス](LICENSE) です。
- Mozc は BSD-3-Clause、MyIME と AzooKeyKanaKanjiConverter は MIT、Qt は LGPLv3 です。同梱する第三者のソフトとデータの表示は、インストール先の `credits_en.html`（設定ツールの「このソフトについて」）にあります。
- Qt のソースは、各版の配布ページに同じ版のものを添えています。
- 試験に使うウィキペディアの文（`tests/conversion/wiki-typing.tsv`）は CC BY-SA 4.0 です。
