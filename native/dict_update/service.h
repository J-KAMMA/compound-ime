// 辞書の更新を、本体の処理（mozc_server など）の中で動かす部分。
//   起動時に、置き場所の辞書を確かめて読む（同期）。
//   そのあと、少し待ってから（起動を遅らせないため）更新を確かめ、以後は6時間ごとに「間隔がたったか」を見る
//   （間隔は既定で1週間。更新の確かめの時刻は置き場所の state.txt に残るので、起動のたびには通信しない）。
// 設定（レジストリ・設定ファイル）で止められる。試験のときだけ、環境変数で置き場所・取る先・公開鍵を替えられる。
#ifndef DICT_UPDATE_SERVICE_H_
#define DICT_UPDATE_SERVICE_H_

#include <memory>
#include <string>

#include "dict_update/updater.h"

namespace dict_update {

// 本体に焼き込む値（apply_dict_update.py が書く）。
struct BakedValues {
  std::string manifest_url;       // 例 https://github.com/J-KAMMA/compound-ime/releases/download/dict-latest/manifest.txt
  std::string url_prefix;         // 目録の中のファイルの URL が始まるべき所
  std::string public_key_hex;     // 署名の公開鍵（16進の64文字）。"UNSET" のときは更新しない
  std::string pos_table_sha256;   // id.def の SHA-256（16進）
  size_t pos_count = 0;           // id.def の行数
};

// MYIME_HERMETIC_TEST=1 の試験のときだけ true（Mozc の試験の決まりと同じ）。
bool IsHermeticTest();

// 設定を読む。試験のときは環境変数 MYIME_DICT_UPDATE（0 で止める）と MYIME_DICT_UPDATE_INTERVAL_HOURS、
// そうでなければ、ウィンドウズはレジストリ HKCU\Software\CompoundIME の DictUpdate・DictUpdateIntervalHours（DWORD）、
// 他は ~/.config/compound-ime/settings の「DictUpdate=0」の行。
Settings ReadSettings();

// 置き場所と取る先を決める。試験のときは環境変数 MYIME_DICT_UPDATE_DIR、MYIME_DICT_UPDATE_BASE（目録のある所）、
// MYIME_DICT_UPDATE_PUBKEY（16進）が全部あるときだけ（file:// と http://127.0.0.1 も許す）。
// 目録の中のファイルの URL が始まるべき所は、MYIME_DICT_UPDATE_URL_PREFIX（なければ取る先の目録のある所）。
// 試験でなければ、焼き込んだ値と標準の置き場所を使う。決められなければ false。
bool MakeConfig(const BakedValues& baked, Config* out);

// 取得の部品。試験のときだけ、環境変数 MYIME_DICT_UPDATE_REWRITE=<元の先頭>=<替える先頭> があれば、その先頭で始まる URL を
// 替えて取る（署名つきの目録の URL は変えずに、手元のファイルから取るため。確かめは元の URL でする）。
std::unique_ptr<Fetcher> MakeFetcher(const Config& config);

// 標準の置き場所（ウィンドウズ %LOCALAPPDATA%\CompoundIME\dict、他は ~/.local/share/compound-ime/dict）。
std::string DefaultRoot();

class Service {
 public:
  Service(Config config, SettingsProvider settings, std::unique_ptr<Fetcher> fetcher, ApplyFn apply);
  ~Service();
  // 辞書を読んで apply に渡す（同期）。読めて apply が受け付ければ true。続けて、背景の確かめを始める
  // （initial_delay_seconds が負なら、読むだけで背景の確かめは始めない）。
  bool Start(int initial_delay_seconds = 120, int confirm_after_seconds = 30);
  void Stop();
  Updater& updater();
  // 今すぐ確かめる（試験用の入口。force なら間隔を見ない）。
  UpdateResult CheckNow(bool force);

 private:
  struct Shared;
  std::shared_ptr<Shared> shared_;
};

}  // namespace dict_update

#endif  // DICT_UPDATE_SERVICE_H_
