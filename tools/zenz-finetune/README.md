# zenz の追加学習（試作）

コンパウンドIME が変換に使う小さな人工知能 **zenz-v3.2-small** に、文の意味を見て選ぶ練習を
追加でさせ、試験用の新しい模型（GGUF ファイル）を作るための道具です。Google Colab で動かします。

ねらいは、今の変換で残っている次のような間違いです。

- 同音異義語（解答用紙／回答用紙、意志／医師、仮定／過程、信仰心が厚い／熱い、仕事に就いた）
- 話し言葉（〜しよっか、ネットの書き方、方言まじりの言い方）
- 英単語まじりの文（英単語は打ったまま残り、前後の日本語だけを変換する文）

**できた模型はまだ公開しないでください。** 今の模型と試験で比べ、悪くなっていないと確かめてから
使うかどうかを決めます（下の「今の模型との比べ方」）。

## 入っているもの

| ファイル | 役目 |
|---|---|
| `finetune.ipynb` | Colab で上から順に押していく手順書（日本語）。①〜⑬のセル |
| `build_dataset.py` | 練習問題を作る。試験の文を除き、出どころと利用条件の目録（manifest.json）も作る |
| `zenz_tune.py` | 手順書から呼ぶ部品（GGUF を学習できる形に戻す、学習、途中からの再開、成績、GGUF の確認、時間とドライブの容量の見積り） |
| `domain_text.py`、`fetch_domain_sources.py`、`domain_sources.json` | プログラミング・仮想通貨の文書から文を取り出す（下の「分野の練習問題と試験」） |
| `persona_text.py` | RealPersonaChat（雑談）の発話から文を取り出す（下の「出典ごとの割合で作る」） |
| `check_dataset.py` | 練習問題が試験の文を含まないこと、目録に出典・版・利用条件・件数があることを確かめる。試験の文をわざと混ぜる確かめも |
| `measure_dataset.py` | 練習問題を数字にして、1問の字数・ファイルの大きさ・速さを測る（見積りの根拠） |
| `../../.github/workflows/mix-data.yml` | 出典ごとの割合で、小さな規模と本番の規模（300万問）を GitHub で試しに作る（手動） |

## やること（クリックする所）

1. ファイル（`build_dataset.py`、`zenz_tune.py`、`domain_sources.json`、`persona_text.py` など）が、①の `REPO_REF`
   の枝（v4-mix は `exp/finetune-mix`）に入っていることを確かめます（まだなら、Google ドライブに
   `zenz-finetune/kit` というフォルダを作り、`tools/zenz-finetune` の中身を入れておきます）。
2. `finetune.ipynb` を Colab で開きます（GitHub の画面から「Open in Colab」、または Colab の
   「ファイル」→「ノートブックを開く」→「GitHub」で `J-KAMMA/compound-ime` の枝を選ぶ）。
3. メニューの「ランタイム」→「ランタイムのタイプを変更」で **T4 GPU**（または L4）を選び、「保存」を押します。
   練習問題作りだけを先に GPU なしで済ませるなら、①の `ONLY_DATA = True` にして CPU のランタイムで⑦まで押します。
4. セルの左の ▶ を、①から順に1つずつ押します。②で Google ドライブへの接続の許可を求められたら、
   自分のアカウントを選んで許可します。③で時間・ユニット・ドライブの容量の見積りが出ます。
5. ⑨（学習）がいちばん長くかかります。**タブは閉じずに開いたままにしてください**（バックグラウンド実行は
   Ultra の契約だけの機能のため、タブを閉じると止まります）。
6. 途中で接続が切れたら、①から順に押し直します。終わった所は飛ばし、練習問題は足りない部品だけ作り直し、
   学習は最後のチェックポイント（20分ごとにドライブへ保存）から続きます。数百万問は何回かに分かれます。
   1回の学習時間を決めたいときは、①の `RUN_MINUTES`（分）に入れます。
7. ⑩で学習の前と後の成績が表で出ます。ふつうの文（wiki_whole など）の成績が下がっていれば注意が出ます。
8. ⑬が終われば完成です。

## どの GPU を選ぶか

おすすめは **L4** です（速さと費用の釣り合いがよい）。手順書は、つながった GPU を見て設定を自動で変えます。

| GPU | 計算の精度 | 一度に流す問題 | 学習の見積り | 全体の見積り | ユニットの見積り |
|---|---|---|---|---|---|
| L4（おすすめ） | bf16 | 64問×2回 | 約20分 | 約1時間10分 | 約5 |
| T4（無料枠） | fp16 | 16問×8回 | 約85分（実測） | 約2時間 | 約3 |
| A100 | bf16 | 128問 | 約10分 | 約55分 | 約11 |

上の表は **40万問・2回くり返し・1問平均78字**（v1〜v3）の場合です。**300万問（v4-mix）では T4 で学習が約 9.6 時間**
（下の「数百万問で学習するとき」）。

- 1時間あたりのユニット: T4 約1.76、L4 約4.82、A100 約11.77（2026-10 時点の目安。Colab の表示が正）。
- T4 は実測（約12,300字/秒）です。L4 と A100 は仮の値で、まだ測っていません。⑨が始まると実際の速さで残り時間と
  残りのユニットを出し直します。
- 全体の見積りには、準備・問題作り（GPU を使わず CPU で10〜20分）・成績の比較・GGUF 化を含みます。
- どの GPU でも1歩あたりの問題数（128問）は同じにしてあるので、学習の結果は GPU によらずほぼ同じです。

## 結果の置き場所

Google ドライブの `マイドライブ/zenz-finetune/v1/`（`v1` は①の `RUN_NAME`）。

| 場所 | 中身 |
|---|---|
| `result/zenz-v3.2-small-ft-v1-Q5_K_M.gguf` | **学習した模型**（約74MB、今の模型と同じ形式・同じ量子化） |
| `result/zenz-v3.2-small-roundtrip-Q5_K_M.gguf` | 対照：学習せず、同じ手順で作り直しただけの模型 |
| `result/SHA256SUMS.txt` | 上の2つの SHA256（試験で使う） |
| `result/MODEL_CARD.md` | 出典と利用条件の表示（配るときに必ず付ける） |
| `result/manifest.json` | 練習問題の出どころ・件数・除いた試験の文の数 |
| `result/eval.json` | 学習の前と後の成績 |
| `data/` | 練習問題（v4-mix は部品 train-text・train-wiki…of….jsonl.gz と valid.jsonl、昔は train.jsonl）と目録 manifest.json |
| `train-<終わりの記号の番号>.npz`、`valid-….npz` | 数字にした練習問題（圧縮）。作り直しを避けるための控え |
| `checkpoints/` | 学習の途中の結果（既定は最新の1つ。保存の最中だけ2つ分。終われば消してかまいません、約1.1GB ずつ） |
| `base/`、`final/` | 学習できる形の元の模型と、学習後の模型 |

## しくみ

### zenz への問いの形

コンパウンドIME（中で使う AzooKeyKanaKanjiConverter）は、zenz-v3.2 に次の形で問い合わせます。
練習問題も同じ形で作ります。

```
[U+EE02 左の文脈][U+EE07 右の文脈] U+EE00 読み（カタカナ） U+EE01 → 変換結果 → 文の終わりの記号
```

- U+EE00 は読みの始まり、U+EE01 は答えの始まり、U+EE02 は左の文脈、U+EE07 は右の文脈（v3.2 から）。
  U+EE03〜EE06 はプロフィール・話題・文体・好み（v3 から。コンパウンドIME は使っていない）。
  根拠: AzooKeyKanaKanjiConverter の `Docs/zenzai.md` と
  `Sources/KanaKanjiConverterModule/ConversionAlgorithms/Zenzai/Zenz/ZenzPromptBuilder.swift`
  （MyIME a8486ec に同梱の版も同じ）。
- 文脈は、改行で切った1行の、左は末尾40文字・右は先頭40文字（MyIME の `conversionContext` と
  `ZenzPromptBuilder` の既定）。半角の空白は全角の空白に置き換え、改行は消す（`ZenzContext.preprocessText`）。
- 問いの前に始まりの記号は付けません（GGUF の `add_bos_token` が False）。
- 英単語まじりの文: 英単語は確定済みの文節になり、人工知能には渡りません。英単語で区切られた日本語の
  部分ごとに、英単語とほかの部分を左右の文脈として問い合わせます
  （`tools/apply_jaen_integration.py` の `PreferWholePhraseRuns`）。たとえば「明日のmeetingは午前中です」なら、
  「左: 明日のmeeting」「読み: ハゴゼンチュウデス」→「は午前中です」。練習問題も同じ形にします。
- 文の終わりの記号: GGUF の設定では番号2（`<s>`）、分かち方の部品の設定では `</s>`（番号3）と食い違って
  います。⑧で、元の模型が答えの後にどちらを出すかを数えて、多い方に合わせます。

### 元の模型

zenz-v3.2-small は GGUF（量子化済み）でしか配られていません（Hugging Face の Miwa-Keita のページに
学習できる形の v3.2 はなく、あるのは v3.1 まで）。そこで⑥で、配布されている GGUF の量子化をほどいて
学習できる形に戻します。分かち方の部品（語彙）は zenz-v3.1-small のものを使います。v3.2 の GGUF と
語彙・つなぎ方・特別な記号の番号がすべて同じであることを確かめてあります（⑥でも毎回確かめます）。

量子化をほどいて学習し、もう一度量子化するので、学習しなくても少し変わります。その分を見分けるため、
⑪で学習しない対照の模型も同じ手順で作ります。

### GGUF にする道具

コンパウンドIME が動かすときと同じ llama.cpp（fkunn1326/llama.cpp、`10131b23ee0dbd9d03dfc618cec9fe3402919277`）の
`convert_hf_to_gguf.py` で GGUF にし、`llama-quantize` で Q5_K_M にします。この版の変換スクリプトは
zenz の分かち方（`gpt2-small-japanese-char`）を知っていて、手元の小さな模型で、元の v3.2 と同じ語彙の
設定ができること、GGUF から戻した重みが元と完全に同じになることを確かめました。⑫で、元の GGUF との
設定・重みの形・量子化の種類の違い、分かち方、llama.cpp で動かした答えを確かめます。

## 練習問題（約40万問）

| 種類 | 割合 | 中身 | 出どころ |
|---|---|---|---|
| wiki_whole | 32% | 文全体を、文脈なしで変換 | ウィキペディア |
| wiki_context | 14% | 文全体を、前の文を左の文脈にして変換 | ウィキペディア |
| wiki_span | 12% | 文の一部（文節1〜3つ）を、左右の文脈つきで変換 | ウィキペディア |
| homophone | 12% | 同音異義語の候補を含む文（`homophone-cues.tsv` の語で選ぶ） | ウィキペディア |
| mixed_english | 16% | カタカナ語を英単語にした文（`katakana-english-common.tsv`）。英単語は文脈側 | ウィキペディア＋自作の一覧 |
| casual | 8% | 話し言葉（`colloquial.tsv` の語を短い型に入れる） | 自作の一覧 |
| modern_words | 4% | 略語・サービス名を文脈に含む文（`jaen-modern-words.tsv`） | 自作の一覧 |
| english_phrases | 2% | 英語の決まった言い回しを文脈に含む文（`english-phrases.txt`） | 自作の一覧 |

- 自作の一覧からの問題は種類が限られるため、同じ問題をくり返さず、足りない分はウィキペディアの文で埋めます。
- ウィキペディアの文は、ひらがなを含み、漢字・かな・句読点・かぎかっこだけでできた8〜60字の文だけを使います
  （数字・英字・括弧書きの読みがなを含む文は、打つときの読みと合わないので使いません）。
- 読みは SudachiPy（Apache-2.0）と SudachiDict core（Apache-2.0）で付けます。辞書が改まった読みを選びやすい語
  （明日→アス、日本→ニッポン など）は、打つときの読み（アシタ、ニホン）に直します（`READING_OVERRIDE`）。
- 確かめ用（学習に使わない）は、記事・見出し語の単位で分けます。同じ記事の文が両方に入ることはありません。
- 同じ seed と同じ材料なら、まったく同じ問題が同じ順でできます。

### 試験の文は学習に入れない

`build_dataset.py` の `TestExclusion` が、`tests/conversion/` の全部のファイル（ja400.json、jaen270.json、
jaen200b.json、typo150.json、typo150b.json、reported.json、inputs.txt、variants.tsv、expected-windows-139.tsv、
今後足される .txt・.tsv も）の文と、**表記または読みが同じか、それを含む文**を、問題にする前に捨てます。

- 表記: 正解と別解（と、念のため今の変換結果）。NFKC・小文字にそろえ、空白・句読点・括弧を除いて比べます。
- 読み: 各文のローマ字を Mozc のローマ字表でかなにしたもの。英単語まじりの文は英単語を打ったまま残した形と、
  英単語をカタカナ語に戻した形（明日のmeeting… と 明日のミーティング…）の両方。
- 「含む」の検査は、表記4文字以上・読み6文字以上の試験の文で行います（それより短いと、ふつうの文が大量に
  消えるため。短いものは「同じ」だけを調べます）。
- 文脈に使う前後の文も、同じ検査を通ったものだけです。除いた件数は manifest.json、除いた文の例は excluded.txt。
- 型の文（話し言葉の「そろそろ」「めっちゃ」など）は、試験の文を見ずに一般的な言い回しから書きました
  （試験のファイルは形を確かめるために先頭と末尾の1件を見ただけです。手元の試運転で、除いた文の記録に
  試験の語がいくつか出ましたが、それに合わせて型を変えてはいません）。

## 分野の練習問題と試験（プログラミング・仮想通貨）

プログラミングと仮想通貨の文は、ウィキペディアにあまり出てこない言葉（git、npm、Python、DeFi、NFT、
ブロックチェーン、デプロイ…）が多いため、その分野の文書から文を取り出して、練習問題と試験を作ります。
学習はこの道具ではしません。

| ファイル | 役目 |
|---|---|
| `domain_sources.json` | 出どころの一覧（リポジトリ・コミット・取り出す場所・利用条件・試験に回す文書の割合） |
| `fetch_domain_sources.py` | 出どころを、コミットを固定して git の sparse checkout で取り出す（リポジトリには材料を入れない） |
| `domain_text.py` | 文書から日本語の文を取り出す（下記）。`sentences.jsonl` と出典ごとの件数 `counts.json` を作る |
| `../domain_typing_test.py` | 試験用の文書の文から、打ち込み試験 `tests/conversion/domain-prog.tsv`、`domain-crypto.tsv` を作る |
| `build_dataset.py --domain-text …` | 練習用の文書の文を、ウィキペディアなどと混ぜて train/valid にする |

**出どころ（版は固定）**

| 名前 | 分野 | 版（コミット） | 利用条件 |
|---|---|---|---|
| mdn: MDN Web Docs 日本語版（mdn/translated-content の files/ja） | プログラミング | `a213f11c…` | CC BY-SA 2.5 |
| python: Python 文書の日本語訳（python/python-docs-ja。po の訳文 msgstr だけ、未訳・fuzzy は除く） | プログラミング | `d2a3519d…` | PSF |
| kubernetes: Kubernetes 日本語版（kubernetes/website の content/ja） | プログラミング | `2f85f280…` | CC BY 4.0 |
| react: ja.react.dev（reactjs/ja.react.dev の src/content） | プログラミング（補助） | `356741e6…` | CC BY 4.0 |
| rust: プログラミング言語Rust（rust-lang-ja/book-ja の src） | プログラミング（補助） | `5092e539…` | MIT または Apache-2.0 |
| ethereum: ethereum.org 日本語版（ethereum/ethereum-org-website の translations/ja。文章のみ） | 仮想通貨 | `1b3d51c0…` | CC BY 4.0 |

**文の取り出し（`domain_text.py`）**: md の前置き（front matter）・コードの囲み・表・HTML・見出し・リンクの書式、
マクロ（MDN の `{{ }}`、Kubernetes の `{{< >}}`、mdbook の `{{#include}}`）を除き、句点（。！？）で文に分けます。
`git` のような短いコードの書式は英字の言葉として文に残し、複雑なコードや使えないマクロを含む文は捨てます。
日本語の割合が 6 割に満たない文、10 字未満・80 字超の文、使えない記号（括弧書きなど）を含む文、重複した文も捨てます。
英字だけの括弧書き（`分散型金融 (DeFi)` の `(DeFi)`）は取り除いて文を残します。日本語の隣の空白は消します
（ローマ字で打つときに空白は入らないため）。

**試験用と練習用は文書の単位で分けます**（同じ文書の文が両方に入りません）。分け方は文書の名前と種（20261015）で
決まるので、同じ版の材料なら毎回同じです。試験用の文書にある文は、ほかの文書に同じ文があっても練習用に入れません。
試験の tsv にした文は、さらに `TestExclusion` で練習問題から除かれます（`--extra-test` で、まだリポジトリに入れていない
試験の tsv も指定できます）。

**打ち込み試験（`domain-prog.tsv` 300 文、`domain-crypto.tsv` 200 文ほど）**: 10〜45 字で句点で終わり、漢字・かな・
英字の言葉（最大 3 語、数字や記号なし）だけでできた文を、出典ごとの枠（`domain_sources.json` の `test_quota`）で選びます。
英字の言葉を含む文を 4 割ねらい、1 つの文書から 4 文まで。ローマ字は日本語の部分だけ SudachiPy の読みから作り、
英字の言葉は小文字で打ったままにします。期待する答えは元の文どおり（`git`、`npm`、`Python`、`DeFi`、`NFT`）です。
先頭の `#` の行に出典・コミット・利用条件を書き、各行の 3 列目に出典名を入れます。採点は
`tools/score_wiki_typing.py`（出典別・英字入りの文別の内訳つき）。

**話し言葉（Tatoeba）**: `tools/colloquial_text.py`（手動の流れ `.github/workflows/colloquial-data.yml`）が、Tatoeba の
日本語の文（CC BY 2.0 FR、`jpn_sentences.tsv.bz2` を SHA-256 で固定）から、(1) 打ち込み試験 `tests/conversion/colloquial.tsv`
（300 文。終助詞・縮約・くだけた言い方・疑問・感嘆。文の番号の SHA-256 で取り分けた 10% の枠から選ぶ）と、(2) 練習の材料の候補
`colloquial-train.jsonl`（枠の外の、話し言葉のしるしがある文。`domain_text.py` の `sentences.jsonl` と同じ形で、
`source` は `tatoeba`）を作ります。練習問題に混ぜるときは `cat out/sentences.jsonl colloquial-train.jsonl > all.jsonl` として
`--domain-text all.jsonl` に渡します（出典は `domain_sources.json` の `tatoeba`。`kind: external` なので取り出しの道具は
読み飛ばします）。試験の採点は `tools/score_colloquial.py`（厳しい・記号ゆれ込み・緩いの 3 つと間違いの型）。

**練習問題への混ぜ方**: `--domain-text out/sentences.jsonl`（`--domain-share` が分野の割合。既定 0.5 で、
`--size` のうち半分が分野、残りがウィキペディアなど）。分野の問題は 4 種類です。

| 種類 | 割合（分野の中） | 中身 |
|---|---|---|
| domain_whole | 30% | 英字の言葉のない文を、文脈なしで変換 |
| domain_context | 15% | 同じ段落の前の文を左の文脈にして変換 |
| domain_span | 20% | 文の一部（文節1〜3つ）を、左右の文脈つきで変換 |
| domain_english | 35% | 英字の言葉を含む文の日本語の部分。英字の言葉は左右の文脈側（実行時と同じ形） |

1 周で足りない種類は、同じ文の別の形の問題で最大 3 周（`--domain-passes`）まで足します。それでも足りない分は
予定より少ないまま、終わりの表示と `manifest.json` に出ます。確かめ用は分野の文書の 5%（`--domain-valid-fraction`）。
`manifest.json` の `domain` に、出典ごとの名前・コミット・利用条件・取り出した文の数・練習用/確かめ用の問題の数を記録します。
英字だけの試験の語（`github`、`python` など）は「同じ」だけを調べ、「含む」は調べません（調べると、その語を含む
分野の文が大量に消えるため。日本語を含む試験の文は今までどおり「含む」も調べます）。

**GitHub での作り方**: `.github/workflows/domain-data.yml`（手動）。材料の取り出し → 文の取り出し → 試験の文 → 練習問題
の順に流し、成果物 `domain-data` に `sentences.jsonl`・`counts.json`・`tests/domain-*.tsv`・`dataset/`
（`train.jsonl`、`valid.jsonl`、`manifest.json`、`excluded.txt`）を置きます。試験の tsv は中身を確かめてから
`tests/conversion/` に入れます。入れたあとは `linux-test.yml` の組 `g` が、今の人工知能の点数を出します。

**Colab の手順の変更点（v3-domain のとき）**: ① の設定に `USE_DOMAIN`・`DOMAIN_SHARE` が増え、⑦ が分野の材料を取り出して
文にしました。**v4-mix 以降は、これらを `MIX`（出典ごとの割合）に置き換えました**（次の節）。`--domain-share` は
`--mix` を付けないときの古い指定として残してあります。

## 出典ごとの割合で作る（数百万問、v4-mix）

v3-domain は分野が 50% で、ふつうの文が下がりました（ウィキペディアの打ち込み 1800→1775、前後の文つき 639/622→634/614、
ja400 379→375）。v4-mix は、分野を 10% に抑え、雑談・話し言葉を足して、全体を 300万問にします。

### 出典と割合（既定）

| 出典（`--mix` の名前） | 割合 | 問題数（300万問） | 中身 | 材料 | 利用条件 |
|---|---|---|---|---|---|
| `wiki` | 64.5%（実際 66.4%） | 193.5万（実際 199.3万） | 文全体・前の文つき・文の一部・同音異義語・英単語まじり | ウィキペディア日本語版の 5 分割（00007、00004、00005、00006、00008。**00003 と 00011 は試験・選び手の材料なので除く**。SHA256 固定） | CC BY-SA |
| `persona` | 22%（実際 22.0%） | 66万 | 雑談の文（前の発話を左の文脈にする） | RealPersonaChat（GitHub の v1.0.0＝コミット 28d0b6b3…。Hugging Face の nu-dialogue/real-persona-chat は読み込みの台本だけで a5be0f51…） | CC BY-SA 4.0（下の注意） |
| `domain` | 10%（実際 8.8%） | 30万（実際 26.3万） | プログラミング・仮想通貨の文書の文 | MDN、Python、Kubernetes、React、Rust、ethereum.org（コミット固定） | 出典ごと（下の表） |
| `tatoeba` | 2.7%（実際 2.4%） | 8.1万（実際 7.1万） | 話し言葉の短い文 | Tatoeba 日本語（話し言葉のしるしがある文。試験の枠 10% は除く） | CC BY 2.0 FR |
| `synthetic` | 0.8%（実際 0.5%） | 2.4万（実際 1.4万） | 話し言葉の語・略語・英語の言い回し（自作の一覧） | `tools/data/` | MIT |

- 雑談・話し言葉（persona + tatoeba + synthetic の話し言葉）で 約 25%。
- **材料の数に上限があります。** 試運転（2026-10-17、300万問の割合、3周まで）で作れた数は、domain 26.3万、tatoeba 7.1万、
  synthetic 1.4万、persona は予定の 66万を全部（41.7万文を最大 3 つの形で）でした。足りない分（5.8万）は、既定で
  ウィキペディアの問題で埋めます（`--no-fill-wiki` で止める）。予定と実際は `manifest.json` の `mix_result` と、⑦ の最後の表に出ます。
- 1問の平均は 71.5字（ウィキペディアだけなら 78字）です。

### 指定のしかた（`build_dataset.py`）

```
--mix wiki=0.645,persona=0.22,tatoeba=0.027,domain=0.10,synthetic=0.008   出典ごとの割合（自動で合計 1 にそろえる）
--max-passes wiki=2,persona=3,tatoeba=3,domain=3,synthetic=1              出典ごとの「同じ文から作る問題の形の数」の上限
--size 3000000                                                            学習用の問題の合計
```

- `--max-passes`: 材料が足りないときだけ、同じ文を別の形（文全体・前の文つき・文の一部）で使い回す回数の上限です。
  文全体と前の文つきは同じ文から 1 つずつ、文の一部は毎回違う所を選びます。上限まで使っても足りない分は埋め草になります。
- 昔の `--mix`（種類ごとの割合の上書き）は `--kind-weights` に改めました。`--mix` を付けないと、昔の指定（`--domain-share`）です。
- 文の一覧（domain・tatoeba・persona）は `--domain-text` に 1 つのファイルにまとめて渡します
  （`cat sentences.jsonl colloquial-train.jsonl persona-train.jsonl > all.jsonl`）。どの出典がどの割合の名前かは、
  `domain_sources.json` の `mix` の欄で決まります（省略は `domain`）。

**部品に分けて作る**（数百万問のため。切れても足りない部品だけ作り直せ、メモリも抑えられます）:

```
build_dataset.py … --only-source synthetic domain tatoeba persona --part text      # 文の一覧からの出典（1工程）
build_dataset.py … --only-source wiki --slice 0/2 --part wiki0of2 --english-only-exact --wiki <5つ>   # 2工程を並べて
build_dataset.py … --only-source wiki --slice 1/2 --part wiki1of2 --english-only-exact --wiki <5つ>
build_dataset.py --out data --merge-parts                                          # valid.jsonl と manifest.json
```

部品は `train-<名前>.jsonl.gz`、`valid-<名前>.jsonl`、目録 `part-<名前>.json` です（目録は最後に書くので、あれば作り終わっています）。
ウィキペディアの部品は、`text` の足りなかった分を読んで、その分だけ多く作ります（だから `text` を先に）。
`--english-only-exact` は、文の一覧を渡さない部品でも、英字だけの試験の語を「同じ」だけ調べる規則（`--domain-text` を付けたときと同じ）にします。

### 試験の文との重なりの除外（全部の出典）

`TestExclusion` は、`tests/conversion/` の**全ファイル**を読みます（既知の形のもの＋`.txt`・`.tsv`・`.csv`・`.jsonl` で形が分からないものは
全部の列を見て、ローマ字の形の列は読みとして、日本語を含む列は表記として数えます。`context.tsv` の元の文と前の文もこれで入ります）。

- 全部の出典（ウィキペディア・自作の一覧・分野・Tatoeba・RealPersonaChat）の文に、同じ検査をします。
- 句点で複数の文になる試験（「A。B」）は、1文ずつも試験の文に数えます（片方だけ使うと、試験の文の半分を覚えさせるため）。
- 前の文とつなげると試験の文になる場合は、その前の文を文脈から外します（試運転の確かめで、これで 2 問が見つかり、直しました）。
- 読めなかったファイルは `manifest.json` の `test_exclusion.keys.files_unhandled` に出ます。
- 確かめ: `check_dataset.py probe` が、試験の文（13 ファイル・712 文）をわざと各出典の材料に混ぜた入れ物を作り、`check_dataset.py verify` が
  練習問題の左の文脈＋正解＋右の文脈をつなぎ直して、試験の文と重ならないこと（文全体を問う種類は 0 件）と、混ぜた文が 1 つも
  残らないことを確かめます。試運転（小さな規模）では、混ぜた 712 文が全部除かれ、残りは 0 でした。

### RealPersonaChat を使うときの守ること

- 作者の注意（個人を特定しようとしない／なりすましに使わない／話者の属性・性格の推定に使わない）に従い、**使うのは発話の文字だけ**です。
  話者ID・ペルソナ・性格特性・属性・時刻は読まず、練習問題にも残しません（`persona_text.py`）。
- 発話は句点で文に分け、重複は 1 つにし、絵文字・顔文字・「w」だけの笑いなどを含む文は捨てます。
  対話の 5% は「試験の枠」として練習に使いません（将来の雑談の試験用）。
- **利用条件の食い違い**: GitHub の LICENSE・README と Hugging Face のカードは CC BY-SA 4.0 ですが、Hugging Face の読み込み台本
  `real-persona-chat.py` の `_LICENSE` だけ CC BY-ND 4.0 と書かれています。データ本体の GitHub の表示（CC BY-SA 4.0）に従いますが、
  模型を配る前に作者に確かめると安心です。
- 表示: Yamashita et al. 2023, RealPersonaChat（https://github.com/nu-dialogue/real-persona-chat）。`MODEL_CARD.md` に自動で入ります。
- Tatoeba は毎週書き出しを入れ替え、古い版を消します（2026-10-10 の版は 2026-10-17 には取れませんでした）。そのため版は固定できず、
  取った版の SHA-256 と日付を `manifest.json` に記録し、Colab ではドライブの `cache/` に控えて以後それを使います。
  試験の枠は文の番号で決まるので、版が違っても試験とは重なりません。

### 数百万問で学習するとき（時間と容量の見積り）

実測（2026-10-17、GitHub の実行機で 300万問を作って測定）と、T4 の実測（12,300字/秒）から:

| 項目 | 見積り | 根拠 |
|---|---|---|
| 学習用の問題 | 300万問（確かめ用 約 8千問） | 試運転で 3,000,000 問を作れた |
| 1問の平均 | 71.5字 | 試運転の実測（71.49） |
| 学習（T4、2周） | **約 9.7 時間**（3,000,000×2×71.5 ÷ 12,300字/秒） | T4 の実測 12,300字/秒。1回の接続で約170分学習できるとして **約 4 回**に分かれる |
| 学習（L4 / A100） | 約 2.6 時間 / 約 1.1 時間 | 仮の速さ（45,000 / 110,000 字/秒）。未測定 |
| 練習問題作り（CPU） | Colab で 約 25 分 | GitHub の実行機の実測: text 1分41秒、wiki 2工程を並べて各 約4分、集める 数秒。Colab はその 3 倍ほどと見込む（git での文書取り出しなど別に数分） |
| 数字にする（⑧） | 約 5〜10 分 | 実測 3.1分（16,110問/秒）。Colab はその 2 倍ほどと見込む |
| 確かめた除外 | 300万問すべてで 0 件 | `check_dataset.py verify`（文全体を問う種類で試験の文と重なる問題 0） |

**Google ドライブに置くもの**（`keep=1`＝途中の結果は最新の 1 つ。`zenz_tune.drive_plan` が③で同じ表を出します）:

| 置くもの | 大きさ（GB） |
|---|---|
| 材料の控え（元の GGUF・分かち方・ローマ字表・Tatoeba の書き出し） | 0.12 |
| `base/`（学習できる形の元の模型） | 0.37 |
| `final/`（学習後の模型） | 0.37 |
| `result/`（GGUF 2 つ・説明書き） | 0.16 |
| 練習問題の部品（`data/` の train-*.jsonl.gz。実測 227MB） | 0.23 |
| 数字にした練習問題（npz、圧縮。実測 210MB） | 0.21 |
| 途中の結果（`checkpoints/`、1 個） | 1.10 |
| **合計** | **約 2.6**（保存の最中は新旧の 2 個分で **約 3.7**） |

- 上限は 4GB（`DRIVE_BUDGET_GB`）。③が見積りを出し、超えるなら練習問題と npz を Colab の手元（`/content/work`）に置く設定に
  自動で切り替えます（ドライブには結果と最小限だけ。そのとき接続が切れたら⑦⑧をやり直します）。
- 保存の途中で切れて残った書きかけ（`checkpoints/tmp-*`、約1.1GB）は、次の⑨の始めに自動で消します。
- さらに空けたいときは、①の `CLEAN_CHECKPOINTS = True`（学習が終わったら途中の結果を消す）で 1.1GB、
  GGUF 化のあとに `base/` を消して 0.37GB。

**何回かに分けて学習できること**（切れても続きから）: 手元の小さな模型（CPU、fp32）で、`stop_after_seconds` で 26 回に分けて
止めては続けた学習が、切れずに学習した結果と**重みが完全に同じ**（最大の差 0.0、歩数・字数も一致）になることを確かめました。
このとき `keep=1` で、途中の結果が常に最新の 1 つだけで、書きかけも残らないことも確認しました。
T4（fp16）では完全な一致までは確かめていません（ほぼ同じになるはず）。

## 利用条件と、守ること

| もの | 利用条件 | 守ること |
|---|---|---|
| MDN Web Docs 日本語版（mdn/translated-content） | CC BY-SA 2.5 | 表示・同じ条件（同じ条件で配る） |
| Python 文書の日本語訳（python/python-docs-ja） | PSF | 表示（訳文 msgstr だけを使う） |
| Kubernetes 日本語版、ja.react.dev、ethereum.org 日本語版（文章のみ） | CC BY 4.0 | 表示（出典・変更したこと） |
| プログラミング言語Rust 日本語版（rust-lang-ja/book-ja） | MIT または Apache-2.0 | 著作権表示 |
| zenz-v3.2-small（元の模型） | 配布ページの表示は Apache-2.0。ただし元になった ku-nlp/gpt2-small-japanese-char と zenz の以前の版（v1〜v3.1）は CC BY-SA 4.0 | 下の理由で CC BY-SA 4.0 として扱う |
| ku-nlp/gpt2-small-japanese-char | CC BY-SA 4.0 | 表示・同じ条件 |
| ウィキペディア日本語版の本文 | CC BY-SA（データセット wikimedia/wikipedia は CC BY-SA 3.0 と GFDL と表示） | 表示・同じ条件 |
| RealPersonaChat（nu-dialogue/real-persona-chat） | CC BY-SA 4.0（GitHub の LICENSE・README と HF のカード。HF の読み込み台本だけ CC BY-ND 4.0 と書き、食い違う） | 表示・同じ条件。作者の注意（個人を特定しようとしない・なりすましに使わない・属性や性格の推定に使わない）を守る。配る前に作者に確かめる |
| Tatoeba の日本語の文 | CC BY 2.0 FR（一部 CC0） | 表示（投稿者。文の番号 https://tatoeba.org/sentences/show/<番号>）。版は固定できないので、取った版の SHA-256 と日付を記録 |
| SudachiPy、SudachiDict | Apache-2.0 | 読みを付けるのに使うだけ（配る物には入らない） |
| Mozc のローマ字表 | BSD-3-Clause | 試験の文の読みを作るのに使うだけ |
| tools/data/ の一覧 | このリポジトリの MIT | — |

**できた模型を配るとき（公開するとき）は CC BY-SA 4.0 として配ります。** v3.2 の GGUF のページは
Apache-2.0 と表示していますが、GGUF の中の名前が `Gpt2 Small Japanese Char`（ku-nlp）で、元になった模型が
CC BY-SA 4.0 なので、表示が食い違っています。安全な側に倒して、次を守ります。

1. 出典を示す: zenz（Miwa Keita さん）、ku-nlp/gpt2-small-japanese-char、ウィキペディア日本語版。
   ⑬が作る `MODEL_CARD.md` に書いてあるので、模型と一緒に置きます。
2. 変更したことを示す（追加学習したこと。MODEL_CARD.md に書いてあります）。
3. 同じ CC BY-SA 4.0 で配り、それ以上の制限を付けない。
4. コンパウンドIME の `credits_en.html`（第三者の表示）にもこの模型の表示を足す。

なお、Apache-2.0 の表示が正しい（作者が意図した）のかを、作者に確かめておくと安心です。

## 今の模型との比べ方（公開せずに）

GitHub の試験（`.github/workflows/linux-test.yml`）は、模型を決まった URL から取って SHA256 を確かめています。
候補の模型を公開せずに同じ試験を流すには、次のどちらかが使えます（ワークフローの変更はまだしていません）。

**案A: 下書きのリリースに置く（おすすめ）**
1. GitHub の「Releases」で新しいリリースを**下書き（Draft）のまま**作り、学習した GGUF と対照の GGUF を添付します。
   下書きのリリースは、リポジトリに書き込める人にしか見えません。
2. ワークフローの手動実行（`workflow_dispatch`）に、入力欄 `model_tag`（下書きのタグ名）と `model_sha256` を足します。
   入力があるときだけ、`gh release download <タグ> --pattern '*.gguf'` で取り、`sha256sum -c` で確かめてから、
   今の `$W/model.gguf` の代わりに使います。入力がないときは今までどおり。下書きのリリースを読むには、
   ワークフローの権限を `contents: write` にする必要があるかもしれません（まだ確かめていません）。

**案B: Hugging Face の非公開の置き場所**
1. Hugging Face に非公開（Private）のリポジトリを作って GGUF を上げます。
2. 読み取り専用のトークンを GitHub の「Secrets」に `HF_TOKEN` として登録し、ワークフローの手動実行の入力に
   `model_url` と `model_sha256` を足して、`curl -H "Authorization: Bearer $HF_TOKEN"` で取ります。

どちらも、模型の中身は公開されません（公開リポジトリでは試験の記録と結果は誰でも見られますが、模型は見られません）。

**比べる組み合わせ**: ①今の模型、②対照（学習せず作り直しただけ）、③学習した模型、の3つを同じ試験で流します。
③と②の差が学習の効き目、②と①の差が作り直しによる変化です。

**見る試験**: 全部の組（a1・a2・b・c・d1・d2）。特に、
- **1,298文（inputs）と日本語だけの400文（ja400）**: ふつうの変換が悪くなっていないか。ここが下がる模型は使いません。
- 英単語まじりの267文・200文、利用者が見つけた失敗（reported）、打ち間違いの150文2組、打ち方の揺れ。
- 速さ（100文の時間）。模型の大きさと形は同じなので、変わらないはずです。

これまでの改良と同じく「悪化なし」（下がった文がない、または理由が分かって許せる）を採用の条件にすることを
おすすめします。

## 危うい点

- **ふつうの変換が悪くなるおそれ**（学び直しで以前の力が崩れること）。学習率を小さく（3e-5）、くり返しを
  2回にし、問題の6割弱をふつうの文にしています。⑩で下がっていれば注意が出ます。最後は試験で判断します。
  v4-mix は、v3-domain の反省から分野を 10% に抑え、ウィキペディアを 64.5% にしましたが、雑談（RealPersonaChat 22%）は
  ですます調の短い発話が多く、ウィキペディア・試験の文と文体が違います。300万問・2周は v1 の 7.5 倍の学習量なので、
  過学習（同じ文の別の形を最大 3 回、さらに 2 周）にも注意してください（確かめ用の損失が上がり始めたら止める）。
- **作った割合のずれ**。材料が足りない出典の分はウィキペディアで埋まるので、実際の割合は予定と違います（⑦の最後の表と
  `manifest.json` の `mix_result`）。
- **量子化のほどき・かけ直しによる変化**。対照の模型で大きさを測れます。
- **読みの誤り**。Sudachi が付けた読みが打つときの読みと違う文が混ざります（例: 方言・固有名詞）。
  間違った読みを覚えると、その語の変換が崩れることがあります。
- **ウィキペディアは書き言葉**。話し言葉の材料は自作の一覧の型だけなので、話し言葉の効き目は小さいかもしれません。
- **実行時の使われ方との違い**。実行時は、辞書が出した候補を模型が採点する形で使います（模型に自由に書かせる
  わけではありません）。練習問題は正解の書き方を覚えさせるので採点にも効くはずですが、⑩の正解率（模型に
  自由に書かせた答え）がそのまま試験の結果になるわけではありません。
- **Colab の部品の版**。Colab の torch・numpy は Colab 側の版を使います（固定していません）。動かなくなったら、
  ④の表示（版）を添えて知らせてください。

## 手元で問題作りだけ試す

```
python -m venv venv && venv/Scripts/python -m pip install sudachipy==0.6.11 sudachidict-small==20260428
venv/Scripts/python tools/zenz-finetune/build_dataset.py --out out --romaji-table romanji-hiragana.tsv \
    --wiki 文章ファイル.txt --size 2000 --sudachi-dict small --show 2
```

文章ファイルは、空行で記事を区切り、各記事の1行目を題名とする形です。`romanji-hiragana.tsv` は Mozc の
`src/data/preedit/romanji-hiragana.tsv` です。出典ごとの割合を試すなら、`--mix wiki=0.7,persona=0.3 --domain-text 文の一覧.jsonl`
のように付けます（`check_dataset.py verify --data out --romaji-table …` で除外と目録を確かめられます）。
