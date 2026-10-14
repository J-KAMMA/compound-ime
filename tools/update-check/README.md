# コンパウンドIME 新版のお知らせ

コンパウンドIMEに新しい版が出たとき、デスクトップ通知で知らせる小さな台本です。
自動で入れ替えることはしません。知らせるだけです。

| 環境 | 台本 |
| --- | --- |
| ウィンドウズ（PowerShell 5.1） | `update_check.ps1` |
| Linux（bash、curl、notify-send） | `update_check.sh` |
| マック（bash、curl、osascript） | `update_check_mac.sh` |

## 何をするか

1. 今入っている版を調べます。
2. GitHub の `https://api.github.com/repos/J-KAMMA/compound-ime/releases?per_page=5` から、下書きでない一番新しいリリースの `tag_name`（例 `v3.34.6239.140`）を得ます。試用版（prerelease）も含みます。
3. 4つの数字（3.34.6239.140）として比べ、新しければ「コンパウンドIMEの新しい版（<版>）があります。押すと配布ページを開きます。」と通知します。
4. 押す（または通知の動作を選ぶ）と `https://github.com/J-KAMMA/compound-ime/releases/tag/<tag>` を開きます。

ネットにつながらない、API が失敗した、通知が使えない、今入っている版が分からない、などのときは何も出さずに終わります。タイムアウトは10秒です。

### 環境ごとの違い

- ウィンドウズ: `C:\Program Files (x86)\CompoundIME\mozc_server.exe` のファイルの版（FileVersion）を今の版とします。ファイルがなければ何もしません。トースト通知を使い、押すと配布ページを開きます。トーストが使えなければ何もしません。
- Linux: `/usr/lib/compound-ime/version.txt` を今の版とします（このファイルは配布物に入れる予定です）。ファイルか `notify-send` がなければ何もしません。`notify-send` が `--action` に対応していれば、通知の動作「配布ページを開く」を選ぶと `xdg-open` で開きます。対応していなければ文だけ出します。
- マック: `/Library/Input Methods/CompoundIME.app/Contents/Info.plist` の `CFBundleVersion` を今の版とします。`osascript` の通知は押して開くことが難しいので、文の中に配布ページの URL を入れます。

## どこに何を書くか

最後に確かめた時刻と、知らせた版を、次の場所に書きます。

| 環境 | 場所 |
| --- | --- |
| ウィンドウズ | `%USERPROFILE%\AppData\LocalLow\CompoundIME\update_check.txt` |
| Linux | `~/.config/compound-ime/update_check` |
| マック | `~/Library/Application Support/CompoundIME/update_check` |

中身は次の2行です（時刻は1970年からの秒数）。

```
checked=1760400000
notified=v3.34.6239.140
```

- 問い合わせは1日1回までです。前回から24時間たっていなければ何もしません。問い合わせに失敗した日も、その日は再度試しません。
- 同じ版で知らせるのは1回だけです。

## 動かし方（例）

ログオン時や1日1回の定期実行に登録して使います。登録は利用者が自分で行ってください。

- ウィンドウズ: `powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File update_check.ps1`
- Linux: `bash update_check.sh`
- マック: `bash update_check_mac.sh`

## 止める方法

次のどれかを設定すると、何もしません（通信もしません）。

- ウィンドウズ: レジストリ `HKCU\Software\CompoundIME` の `UpdateCheck`（DWORD）を `0` にします。
  ```
  reg add HKCU\Software\CompoundIME /v UpdateCheck /t REG_DWORD /d 0 /f
  ```
- Linux: `~/.config/compound-ime/settings` に `update_check=0` と1行書きます。
- マック: `~/Library/Application Support/CompoundIME/settings` に `update_check=0` と1行書きます。

台本を登録しない、または消すことでも止まります。

## GitHub に送られるもの

- 上の API への GET の要求だけです。GitHub には、そのときの IP アドレスと、要求の内容（URL と User-Agent `CompoundIME-update-check`）が届きます。
- 打った文字、変換の内容、個人の情報、今入っている版の番号は送りません。
- 外部に送る先は GitHub の API だけです。通知の押下で開く配布ページは、利用者が押したときにブラウザが開くものです。
