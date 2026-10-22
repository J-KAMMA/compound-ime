# 辞書の自動更新

2026-10-21 作成。枝 `feat/dict-update`（もとは `feat/combined`）。

2つを組み合わせる。

1. **GitHub で辞書を作り直す**（月1回と手動）: 固有名詞・略語・英語の一覧を作り直し、試験を流して、悪くならなかったときだけ「辞書の配布物」を下書きの配布ページ `dict-YYYYMMDD` に置く。悪くなったら置かずに issue で知らせる。
2. **入っている IME が辞書だけを取りに行く**: 本体が週1回（起動のあとと一定時間ごと）、固定の配布ページの目録を見て、新しい辞書があれば取り、署名とハッシュを確かめ、読み込めることを確かめてから入れ替える。読み直しに失敗したら前の辞書に戻る。設定で止められる。

以下、先に「調べたこと」、次に「設計」、「作ったもの」、「月1回の流れと止める基準」、「こちらでやること」、「確かめたこと・確かめていないこと」、「決めてほしいこと」の順。

---

## 1. 調べたこと

### 1.1 一覧は焼き込みか、実行時に読むファイルか

**全部、組み立て時に焼き込まれている。実行時に読むファイルはない。** 組み立ての手順（`tools/apply_jaen_integration.py` ほか）を読んで確かめた。

| 一覧 | 元 | 焼き込み先 |
|---|---|---|
| 固有名詞 `tools/data/proper-nouns.tsv` | Wikidata（`fetch_wikidata_names.py` → `build_proper_nouns.py`） | ① `build_proper_noun_dictionary.py` が `dictionary14.txt`（読み・左右の品詞番号・費用・表記）にして Mozc の辞書の元データ `data/dictionary_oss/` に入れ、Bazel の `mozc_dataset` が `mozc.data`（と実行ファイルに埋め込む `mozc_data.inc`）にする。② 「打つ形」と表示の形は `converter/brand_casing_data.inc`、英語の言い回し・語は `english_lexicon_data.inc`（C++ の配列）に書かれる |
| 略語 `tools/data/acronyms.tsv` | 手で作った（自作）| 型 b（日本語に読める。あい → AI）の読みは上の `dictionary14.txt` に入る。型 a（api、url …）と手がかりは `build_acronym_table.py` が `native/jaen-detector/jaen_detector.cc`（英語の検出器のコード）の表に書く |
| 英単語の一覧 `jaen-modern-words.tsv`、`jaen-brand-words.txt`、`jaen-domain-words.txt` ほか | 手で作った・分野の文書から作った | `english_lexicon_data.inc` と `brand_casing_data.inc`。起動して最初に使うとき、これらから語の一覧（`jaen::Lexicon`）を組み立てる |

`jaen-modern-words.tsv` と `acronyms.tsv` には作り直す道具がない（手で保つ一覧）。月1回の自動更新が「取り直せる」のは固有名詞だけで、略語と英単語の一覧は、リポジトリの今の中身を配る（下の 3.5）。

### 1.2 Mozc の辞書を実行時に差し替えられるか

- Mozc には、辞書一式（`mozc.data`）を実行時に読み込む仕組みがある（`DataManager::CreateFromFile`、`SEND_ENGINE_RELOAD_REQUEST`、`DataLoader`。読み込みが失敗したら今のエンジンのまま）。C++ だけで書かれていて、ウィンドウズ・Linux・マックで共通。ただし OSS 版の既定は焼き込み（`OssDataManager`）で、この仕組みは使っていない。
- **採らなかった理由**: 差し替えるのは辞書だけでなく接続表・品詞表・各種規則を含む一式で、本体と同じ版で作ったものでなければ読めない。月1回の更新で一式を配ると大きく（接続表の元データだけで36MB。`mozc.data` の大きさは測っていない）、本体の版と一式の版を揃える管理が要る。更新したいのは固有名詞など小さな一覧だけ。
- **利用者辞書の仕組みを使う案も採らなかった**: 利用者の語と混ざり（辞書ツールに出る、利用者が消せる）、品詞を名前で指定する形で、辞書の元データのような品詞番号・費用の指定ができない（読んだ範囲では）。シークレットモードでは引かれない（`DictionaryImpl` が利用者辞書を外す）。
- **採った形**: 焼き込みを「実行時に読む追加の辞書」と「英語の一覧」に分ける。

### 1.3 ウィンドウズの処理の分担

辞書とエンジンを持つのは `mozc_server`（`MozcServer::Run`）の中だけ。入力の画面側（`mozc_tip` の DLL）と描画の処理は、ここと IPC で話すだけで、辞書を持たない。したがって:

- **取りに行く処理**: `mozc_server`。`Run()` の中、`SessionServer` が接続できたあとで `StartDictUpdateService()` を呼ぶ。1つの背景スレッドが動く。
- **読み直させる方法**: 同じ処理の中で表を入れ替えるだけ（`SupplementDictionary::Set`、`SetEnglishExtra`、読みの費用の記憶 `InvalidateReadingMemo` を捨てる）。IPC も再起動も要らない。引いている途中の変換は古い表を最後まで使い、次の引きから新しい表を使う。
- サーバーが何度も起動し直されても、確かめた時刻は置き場所の `state.txt` に残るので、起動のたびに通信しない（週1回）。

---

## 2. 設計

### 2.1 何を更新できて、何ができないか

| 更新できる | 更新できない（次の版の本体を作り直すとき） |
|---|---|
| 固有名詞の読みの候補（ぐーぐる → Google）、日本語に読める略語の読み（あい → AI）。**追加の辞書**に入る | 焼き込み済みの語の削除、費用や品詞の変更（追加の辞書は足すだけ。同じ読み・同じ表記は、費用の小さいほうが効く） |
| 英語の語・名前・言い回しと、小文字で打った語の表示の形。**英語の一覧**に入る | 焼き込み済みの表示の形の変更（焼き込みの表を先に引く） |
| | 略語の手がかり（`acronym-cues.tsv`）と型 b の検出の表（検出器のコードの中） |

### 2.2 配る物（配布ページ）

- `dict-YYYYMMDD`（日付ごとの配布ページ。下書きで作り、こちらが公開する）: `manifest.txt`、`manifest.txt.sig`、`supplement.tsv`（追加の辞書）、`english-extra.tsv`（英語の一覧）、`proper-nouns.tsv`（次の版の本体に焼き込むための元）、`gate-report.md`。
- `dict-latest`（固定の配布ページ）: `manifest.txt` と `manifest.txt.sig` だけ。本体が見に行くのはここ。`https://github.com/J-KAMMA/compound-ime/releases/download/dict-latest/manifest.txt`。
- `dict-` で始まる配布ページは、新版のお知らせの台本（`tools/update-check`）が見る「4つの数字の版」の形ではないので、本体の新版のお知らせと混ざらない。どちらも「最新」の印は付けない。

追加の辞書は `dictionary14.txt` と同じ作り方・同じ形（1行＝読み・左品詞・右品詞・費用・表記）。約24,000行、1.3MB。英語の一覧は約64,000行、1.6MB。どちらも読み込みに30ミリ秒ほど（手元で測った）。

### 2.3 目録と署名（改ざんへの備え）

`manifest.txt`（タブ区切りの文）:

```
compound-ime-dict-manifest	1
version	20261101
created	2026-11-01
pos_table	<id.def の SHA-256>
file	supplement	supplement.tsv	<大きさ>	<SHA-256>	https://github.com/J-KAMMA/compound-ime/releases/download/dict-20261101/supplement.tsv
file	english	english-extra.tsv	<大きさ>	<SHA-256>	https://…/english-extra.tsv
```

- **署名**: 目録の全体に Ed25519 の署名（`manifest.txt.sig`、16進128文字）。秘密鍵は GitHub の secret `DICT_SIGNING_KEY`。**公開鍵は本体に焼き込む**（`tools/dict-update/public-key.txt`）。目録に書かれたハッシュで辞書のファイルを確かめるので、目録の署名が辞書全体の署名になる。
- 本体側の署名の確かめは標準ライブラリだけの自前の実装（`native/dict_update/crypto.cc`、TweetNaCl の組み立て）。python の `cryptography` と照らし合わせて確かめた（乱数で作った300組ほどと RFC 8032 の試験。作り変えた署名も拒む）。
- **巻き戻しの防ぎ**: 版（年月日）は今の版より大きくなければ入れない。古い目録を差し込まれても無視する。
- **品詞の表**: `pos_table` が本体の `id.def` の SHA-256 と違う辞書は受け付けない（品詞番号の意味が違うため）。
- **取る先の制限**: URL は `https://` で、本体に焼いた `https://github.com/J-KAMMA/compound-ime/releases/download/` で始まるものだけ。ファイル名は英数字と `._-` だけ（`..` や `/` は不可）。大きさの上限（目録 64KB、追加の辞書 32MB、英語の一覧 8MB）。
- 読み込みの決まり: 全部の行が決まりに合わなければ、全体を受け付けない（品詞番号が表の外、費用が範囲の外、制御文字、UTF-8 でない、など）。
- **限界**: 公開した辞書を遠隔で取り下げる手段はない（取り下げは、前の辞書に新しい版の番号を付けて出し直す）。署名の鍵が漏れれば辞書を差し込める（鍵を替えるには本体の作り直しが要る）。更新を止められる（新しい辞書を見せない）攻撃は防げない。

### 2.4 置き場所と入れ替え・戻し

置き場所（ウィンドウズ `%LOCALAPPDATA%\CompoundIME\dict\`、Linux・マック `~/.local/share/compound-ime/dict/`）:

```
current/   今の辞書   previous/  1つ前の辞書   staging/  取っている途中（起動のたびに捨てる）   state.txt
```

1. 目録と署名を取る → 署名を確かめる → 版・品詞の表を見る。
2. `staging/` に辞書のファイルを取り、大きさと SHA-256 が目録と合うものだけ書く。
3. **入れ替える前に**、`staging/` を全部読み込めるか確かめる（署名・ハッシュ・全行の形）。読めなければ入れず、その版を「悪い」と覚えて、それ以下の版は取りに行かない。
4. `current/` → `previous/`、`staging/` → `current/` と入れ替える（ディレクトリ単位の名前替え。途中で止まっても、起動時に直る）。
5. 本体に渡して読み直す（表の入れ替え）。**失敗したら** `previous/` を `current/` に戻し、その版を悪いと覚える。
6. 入れた版には「確かめる前」の印を付ける。サーバーが**30秒落ちずに動いたら**印を消す。印が付いたまま**続けて2回起動し直した**（＝入れた辞書で落ちている）ら、`previous/` に戻す。
7. 起動時は `current/` の署名・ハッシュ・中身を毎回確かめてから読む（置き場所の書き換え・壊れに備える）。壊れていれば `previous/`。壊れた版は、サーバーの辞書に問題があるのではないので「悪い」とは覚えず、次の確かめで取り直す。

### 2.5 いつ取りに行くか、止める設定

- 起動して120秒後に最初の確かめ（起動を遅らせない）。以後6時間ごとに「間隔がたったか」を見る。**間隔は既定1週間**（設定で変えられるが24時間より短くはしない）。確かめた時刻は `state.txt` なので、起動のたびには通信しない。取れなかったときは6時間たつまで再び試さない。
- **止める設定**: ウィンドウズはレジストリ `HKCU\Software\CompoundIME` の `DictUpdate`（DWORD）を `0`、Linux・マックは `~/.config/compound-ime/settings` に `DictUpdate=0` と1行。止めると**通信しない**（入っている辞書は使い続ける）。間隔は同じ場所の `DictUpdateIntervalHours`。レジストリ・設定ファイルの置き場所は、既存の `ZenzaiEnabled` などと同じ（`converter/engine_config.cc`）。
- **設定の画面（チェックボックス）は作っていない**。既存の `ZenzaiEnabled` なども設定の画面にはなく、レジストリだけなので合わせた。
- 公開鍵が `UNSET` の間（鍵を作るまで）は、通信しない。**既定の本体は何も変わらない**。
- 送るもの: `https://github.com/…/releases/download/…` への GET と User-Agent（`CompoundIME-dict-update/1`）だけ。打った文字・設定・今の版などは送らない（GitHub には IP アドレスは届く）。

### 2.6 取得の部品（環境ごと）

- ウィンドウズ: WinInet（モデル取得の既存の部品と同じ。`INTERNET_FLAG_SECURE`、証明書の確かめは OS）。
- Linux・マック: `curl` の実行ファイルをシェルを通さずに起動（`--proto =https --proto-redir =https`、大きさの上限つき）。`curl` がなければ取れず、何も変わらない。
- 試験のときだけ（`MYIME_HERMETIC_TEST=1`）、環境変数で置き場所・取る先・公開鍵を替えられる。試験でないときは環境変数は効かない（単体試験で確かめた）。

---

## 3. 作ったもの

### 3.1 本体（`native/dict_update/`、`tools/apply_dict_update.py`）

| ファイル | 中身 |
|---|---|
| `crypto.{h,cc}` | SHA-256、Ed25519 の署名の確かめ |
| `data.{h,cc}` | 追加の辞書・英語の一覧の読み込みと確かめ |
| `manifest.{h,cc}` | 目録の読み取り |
| `updater.{h,cc}` | 確かめ・取得・入れ替え・戻し・起動時の読み込み |
| `fetcher.{h,cc}` | 取得（WinInet、curl） |
| `service.{h,cc}` | 背景の確かめ、設定、置き場所 |
| `mozc/supplement_dictionary.*` | 追加の辞書を Mozc の辞書の1つにする（`DictionaryImpl` が並べる） |
| `mozc/dict_update_glue.*` | 取った辞書を入れて読み直す。試験用の命令 |
| `tools/apply_dict_update.py` | 上を Mozc の作業ツリーに差し込む。`BUILD.bazel`、`dictionary_impl.cc`、`english_lexicon.{h,cc}`、`mozc_server.cc`、`session_handler_main.cc` を書き換える。焼き込む値（品詞の表の SHA-256、公開鍵、取る先）もここで書く |

`linux-test.yml`、`linux-package.yml`、`macos.yml`（2か所）、`windows.yml` の `apply_jaen_integration.py` の次に `apply_dict_update.py` を足した。

### 3.2 作る・確かめる道具

`tools/make_dict_release.py`（鍵を作る、目録を作って署名する、確かめる）、`tools/build_english_extra.py`（英語の一覧を作る）、`tools/dict_quality_gate.py` と `tools/data/dict-gate.json`（止める基準）。

### 3.3 試験

| 試験 | 中身 |
|---|---|
| `tools/run_dict_update_unit_tests.sh` | 暗号の照らし合わせ、本体の部品の単体試験（203件、address と undefined の検査つき）、端から端まで、配布物を作る道具 |
| `tools/dict_update_scenarios.py tool …` | **本物の取得の部品**で 127.0.0.1 の配布ページから取る。取る前は出ない → 取ると読み直しで出る → 再起動しても出る → 同じ版・新しい版・古い目録 → 悪い配布物6種 → 読み直しの失敗 → 確かめる前に続けて落ちる → 止める設定は1回も取りに行かない → つながらない |
| 組 `u`（`tools/run_tests.sh`） | 上の試験を、本体の `session_handler_main` の `DICT_UPDATE` 命令を通して（実際の候補の一覧で）流す |
| `tools/test_make_dict_release.py`、`tools/test_dict_quality_gate.py` | 配布物を作る道具と、止める基準の試験 |
| `native/dict_update/mozc/*_test.cc` | `SupplementDictionary`（本物の `dictionary_interface.h` に合わせて）と `SetEnglishExtra` の試験 |

---

## 4. 月1回の流れと止める基準

`.github/workflows/dict-update.yml`（毎月1日 03:17 UTC と手動）:

| 段 | 内容 |
|---|---|
| data | 署名の鍵の確かめ → 単体試験 → 組み立ての元の木 → Wikidata から取り直し（約1時間）→ `proper-nouns.tsv` → 追加の辞書・英語の一覧 → **止める基準 その1** → 目録と署名 |
| test | `linux-test.yml` を呼び、同じ変換エンジンで「いまの辞書」と「新しい辞書」の両方を流す。新しい辞書は、本体が週1回するのと同じ道（`DICT_UPDATE` 命令。目録と署名の確かめ、ハッシュ、読み込み）で入れてから流す。組は `a1 a2 b e1 e2 g h k m r`（既定。手動で変えられる）。組の数×2 を、**同時に最大16**（`linux-test.yml` の `max-parallel: 16`）で流す |
| gate | **止める基準 その2** |
| publish | 通ったときだけ、下書きの配布ページ `dict-YYYYMMDD` に置く（`--draft --latest=false`） |
| notify | 置かなかったときは issue（ラベル `dict-update`）で知らせる |

公開は `.github/workflows/dict-publish.yml`（手動。`tag` に `dict-YYYYMMDD`）。署名とハッシュをもう一度確かめ、配布ページを公開し、そのあとで `dict-latest` の目録を差し替える（今の版より新しいときだけ）。

### 止める基準（案。値は `tools/data/dict-gate.json`）

**その1（試験の前）**: 取り直した一覧の行数が、いまの一覧との比で 0.85〜1.3 の外、または下限（固有名詞 5,000、追加の辞書 5,000、英語の一覧 10,000）より少ない → 止める。取得の失敗や出典の変更を、1時間の試験を流す前に見つけるため。

**その2（試験の結果）**: 「いまの辞書」と「新しい辞書」の採点（既存の `*-score.txt` の1行目の数）を比べる。正解の数が、許す下がりより多く下がったら止める。許す下がり ＝ `max(最低の件数, 試験の総数 × 割合)` の切り上げ。

| 種類 | 試験（採点の数） | 許す下がり |
|---|---|---|
| 対象（辞書を変えて直したい試験） | 固有名詞の文（名前が合う）、固有名詞の候補（先頭・上位3つ・候補の中）、略語の文（名前が合う）、略語の候補（先頭・候補の中）、開発の道具の候補（先頭）、英単語と重なるローマ字の英語にしたい文（英語で出た） | 0.5%、最低1件 |
| 日本語 | 日本語だけの400文（合計）、英単語と重なるローマ字の日本語だけの文（日本語のまま）、略語と重なる日本語の文、ウィキペディアの文・プログラミング・仮想通貨・開発の道具の名前の文（元の文と同じ、英字が混じった）、話し言葉（厳しい採点） | 0.3%、最低2件 |

- 「英字が混じった」は少ないほうがよい項目（増えたら悪くなった）。
- 新しい辞書の採点がない（試験が流れなかった）、試験の組のどれかが最後まで流れなかった → 止める。基準の側（いまの辞書）に採点がない項目は、比べずに報告に書く。
- 1,298文のうち結果が変わった文の数は報告だけ（基準にしない）。
- 値は案。変換エンジンは人工知能の時間の上限で結果が揺れるので、まず数回流して、いまの辞書どうし（変えずに2回）の揺れを見てから決め直す。

### 3.5 取り直す物・取り直さない物

| 一覧 | 月1回の扱い |
|---|---|
| 固有名詞 | Wikidata から取り直す（`fetch_wikidata_names.py` → `build_proper_nouns.py`）。`dict-sources` に `proper-nouns.tsv` を残すので、次の版の本体に焼き込むときはこれを `tools/data/` に入れる |
| 略語 `acronyms.tsv`、英単語の一覧 `jaen-*.txt/tsv`、`brand-casing.tsv`、`domain-casing.tsv` | **取り直す道具がない**（手で保つ）。リポジトリの今の中身を `english-extra.tsv` に入れて配る。略語の型 b の読みは追加の辞書に入る |

`build_proper_nouns.py` に渡す入力（語の一覧の置き場所、Mozc の辞書にある読みの一覧 `readings.txt`、日本語のローマ字の文）の作り方は、手順書に残っていなかったので、`BUILD.md` とスクリプトの説明から**組み直した**（`dict-update.yml` の中）。原本の手順と同じかは確かめていない。

---

## 5. こちらでやること

1. **鍵を作る**: `python tools/make_dict_release.py keygen`。秘密鍵を GitHub の secret `DICT_SIGNING_KEY` に、公開鍵を `tools/dict-update/public-key.txt`（`UNSET` を置き換える）に書く。**公開鍵を書いたあとに本体を作り直す**（焼き込むため）。鍵が `UNSET` や食い違いのままだと、月1回の流れは最初の段で止まり、issue に出る。
2. まず組 `u` だけで `Linux test` を手動で流し、実機の変換エンジンで仕組みを確かめる（`groups` に `["u"]`）。
3. `Dictionary update` を `refetch` を false にして手動で流し、流れ全体を確かめる（1時間の取得を省ける）。
4. 下書きの `dict-YYYYMMDD` の中身（`gate-report.md` など）を見て、よければ `Dictionary publish` を流す。
5. 止めたい利用者向けに、設定（`DictUpdate=0`）を案内する。

---

## 6. 確かめたこと・確かめていないこと

**この作業場所で確かめた（Linux、g++ とクラウドなし）**

- 暗号の部品を python の `cryptography`・`hashlib` と照らし合わせた（308組）。
- 本体の部品の単体試験 203件（address・undefined の検査つき）。
- 本物の取得の部品（curl）で、127.0.0.1 の配布ページから取る端から端までの試験（上の3.3の流れ全部）。止める設定では取得が0回であること、悪い配布物6種が入らないこと、読み直しの失敗・続けて落ちたときに前の辞書に戻ることを含む。
- `apply_dict_update.py` を、組み立ての途中の木（`mozc-base.patch` と `myime-engine.patch` と `apply_jaen_integration.py` を当てたもの）に当てて、書き換えの場所が1つずつ見つかることを確かめた。
- `SupplementDictionary` を本物の `dictionary_interface.h` で組み立てて動かし（足す・引く・打ち切り・外す）、`SetEnglishExtra`（世代の入れ替え、引きながらの入れ替え）を address の検査つきで動かした。どちらも absl と protobuf の入れ物だけを足した組み立て。
- 実データ（今の `proper-nouns.tsv` と Mozc の辞書の元データ）から作った追加の辞書は、本体に焼き込む `dictionary14.txt` と同じ内容（24,147行）になり、読み込みの決まりに通った。実データで、読みの長さの上限を直した。
- 止める基準の判定と、配布物を作る・確かめる道具。

**確かめていない**

- **Bazel での組み立て**。`BUILD.bazel` の書き方、`dictionary_impl.cc` などの変更のコンパイルは、手元では型の確認（構文）までで、組み立てていない。
- **組 `u` の実機の動き**（`session_handler_main` の `DICT_UPDATE` 命令、読み込んだ追加の辞書の語が実際の候補の一覧に出る順位）。組 `u` の読みは、Mozc の辞書にない並び（ぬぬぬぬぬぬ）で、追加の辞書の1語が一番安い道になるはずだが、動かしていない。
- **ウィンドウズ**（WinInet の取得、レジストリの設定、`%LOCALAPPDATA%` の置き場所、`mozc_server` の中のスレッド）と**マック**。コードは書いたが、組み立ても実行もしていない。
- `dict-update.yml`、`dict-publish.yml` は YAML の構文を確かめただけで、動かしていない（Wikidata の取得、`gh` の使い方、`workflow_call` の権限など）。`actionlint` は使っていない。
- 同じ（読み・表記）が焼き込みと追加の辞書の両方にあるときの二重（run 39695917459 で、中身が同じ辞書の試験が12文変わった原因の1つ）。直した: 追加の辞書は、焼き込みの `dictionary14.txt` と全く同じ行（読み・表記・品詞・費用）を出さない（`supplement_baked.inc` の印で除く）。もう1つの原因は、英語の一覧が分野の語（`jaen-domain-words.txt`）を5文字以上でも厳選にしていたこと（本体の組み立ては4文字以下だけ。inode、kohaku、amazon、basename が日本語の文を英語にした）。直した: `build_english_extra.py` も4文字以下だけ。`refetch=false` の流し方では、一覧が同じことの確かめと、結果の `*.tsv` が1行も違わないことの確かめ（`dict_quality_gate.py scores --identical`）を入れた。
- 同じ利用者の2つのサーバー（遠隔の接続など）が同じ置き場所を使う場合。
- GitHub の配布ページの転送先が `https` 以外になることはないとして `--proto-redir =https` にした。

---

## 7. 決めてほしいこと

1. **公開するか**: いまは下書きまで。公開は `Dictionary publish` を手で流す（自動で公開はしない）。
2. **間隔**: 本体の確かめは1週間（既定）。作り直しは月1回。辞書は月1回しか変わらないので、本体の確かめを2週間などにしても実害は小さい。
3. **止める基準**: 4章の数。まず数回流して揺れを見てから決め直す案。
4. **署名の鍵**: 誰が持つか。鍵を替える手順（本体の作り直し）をどうするか。
5. **設定の画面**に止めるチェックボックスを足すか（いまはレジストリ・設定ファイルだけ）。
6. 取る先を GitHub の配布ページ（`dict-latest`）で良いか。
7. 焼き込み済みの語の削除・費用の変更は、次の版の本体まで待つ（追加の辞書は足すだけ）でよいか。
