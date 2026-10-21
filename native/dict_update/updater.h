// 辞書の更新の本体（Mozc に依存しない）。配布ページの目録を見て、新しい辞書があれば取ってきて、
// 署名と SHA-256 を確かめ、読み込めることを確かめてから入れ替える。入れ替えのあとで読み直しに失敗したり、
// 確かめる前に続けて落ちたりしたら、前の辞書に戻す。
//
// 置き場所（root）の中:
//   current/   今の辞書（manifest.txt、manifest.txt.sig、辞書のファイル）
//   previous/  1つ前の辞書（戻す先）
//   staging/   取っている途中（起動のたびに捨てる）
//   state.txt  last_check、last_attempt、installed、trial、boots、bad
// 取ってきたものは、署名と SHA-256 が合い、中身を全部読めたものだけが current/ に入る。
#ifndef DICT_UPDATE_UPDATER_H_
#define DICT_UPDATE_UPDATER_H_

#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>

#include "dict_update/data.h"
#include "dict_update/manifest.h"

namespace dict_update {

struct FetchResult {
  bool ok = false;
  std::string body;
  std::string error;
};

class Fetcher {
 public:
  virtual ~Fetcher() = default;
  // url の中身を最大 max_bytes まで取る。超えたら失敗。
  virtual FetchResult Get(const std::string& url, size_t max_bytes) = 0;
};

struct Settings {
  bool enabled = true;          // 止める設定（DictUpdate=0）のとき false
  int interval_hours = 24 * 7;  // 確かめる間隔。24時間より短くはしない
};
using SettingsProvider = std::function<Settings()>;

struct Config {
  std::string root;               // 置き場所（UTF-8）
  std::string manifest_url;       // 目録の URL（.sig は同じ名前に .sig を付けたもの）
  std::string url_prefix;         // 目録の中のファイルの URL が始まるべき所
  std::string public_key;         // 署名の公開鍵（32バイトの生の値）。空なら更新しない
  std::string pos_table_sha256;   // 本体に焼いた品詞の表の SHA-256（16進）
  size_t pos_count = 0;           // 品詞番号の数
  bool allow_test_transport = false;  // file:// と http://127.0.0.1 を許す（試験専用）
  int64_t retry_seconds = 6 * 3600;   // 取れなかったあと、次に試すまで
  int64_t boot_trial_limit = 2;       // 確かめる前に、これだけ続けて起動したら戻す
};

struct Snapshot {
  uint64_t version = 0;
  std::shared_ptr<const SupplementTable> table;
  std::shared_ptr<const EnglishExtra> english;
};

// 入れ替えたあとの「読み直し」。false を返すと、前の辞書に戻す。
using ApplyFn = std::function<bool(const Snapshot&)>;

struct UpdateResult {
  enum Status {
    kDisabled,      // 設定で止めてある（通信しない）
    kNoKey,         // 署名の公開鍵が入っていない（通信しない）
    kNotDue,        // まだ間隔がたっていない（通信しない）
    kUpToDate,      // 新しい辞書はない
    kInstalled,     // 入れ替えた
    kFetchFailed,   // 取れなかった（ネットワーク、大きさの超過など）
    kVerifyFailed,  // 署名やハッシュが合わない
    kRejected,      // 署名は合うが、中身を受け付けられない（品詞の表の違い、読めない行）
    kReloadFailed,  // 入れ替えたが読み直しに失敗したので、前に戻した
  };
  Status status = kNotDue;
  uint64_t version = 0;  // 見つけた版（kUpToDate では今の版）
  std::string detail;
};
const char* StatusName(UpdateResult::Status s);

class Updater {
 public:
  Updater(Config config, SettingsProvider settings, std::unique_ptr<Fetcher> fetcher);

  // 起動時: 置き場所の辞書を確かめて読む。current/ が壊れていれば previous/ を使う。
  // 確かめる前に続けて落ちた版は、previous/ に戻す。読めた辞書があれば true。
  bool LoadInstalled(Snapshot* out);

  // 週1回ほどの確かめ（force なら間隔を見ない）。now は1970年からの秒。
  UpdateResult CheckAndUpdate(int64_t now, bool force, const ApplyFn& apply);

  // 入れ替えてしばらく無事に動いたとき、「確かめる前」の印を消す。
  void ConfirmTrial();

  // 起動時に読んだ辞書を本体が使えなかったとき（読み直しの失敗）: previous/ に戻して、その版を悪いものとして覚える。
  void ReportApplyFailure();

  // 今の版（なければ 0）
  uint64_t InstalledVersion();

 private:
  struct State {
    int64_t last_check = 0;
    int64_t last_attempt = 0;
    uint64_t installed = 0;
    uint64_t trial = 0;
    int64_t boots = 0;
    uint64_t bad = 0;
  };
  State LoadState() const;
  bool SaveState(const State& s) const;
  std::string Path(const char* name) const;
  // dir の辞書を全部確かめて読む。署名、品詞の表、ファイルの大きさと SHA-256、中身。
  bool VerifyDir(const std::string& dir, Snapshot* snap, std::string* error, bool* signature_failed = nullptr) const;
  bool Rollback(State* state, bool mark_bad);

  Config config_;
  SettingsProvider settings_;
  std::unique_ptr<Fetcher> fetcher_;
  std::mutex mutex_;
};

}  // namespace dict_update

#endif  // DICT_UPDATE_UPDATER_H_
