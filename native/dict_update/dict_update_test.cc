// 辞書の更新の単体試験（Mozc なし）。
//   python3 tools/dict_update_fixtures.py /tmp/fx
//   g++ -std=c++20 -I native native/dict_update/{crypto,data,manifest,updater,fetcher,service,dict_update_test}.cc -o dict_update_test
//   ./dict_update_test /tmp/fx
// 通信はしない（取得は FunctionFetcher が配布物の置き場所のファイルを返す）。
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <unistd.h>

#include "dict_update/crypto.h"
#include "dict_update/data.h"
#include "dict_update/fetcher.h"
#include "dict_update/manifest.h"
#include "dict_update/service.h"
#include "dict_update/updater.h"

namespace fs = std::filesystem;
using namespace dict_update;

static int g_failed = 0, g_checked = 0;
#define CHECK(cond)                                                              \
  do {                                                                           \
    ++g_checked;                                                                 \
    if (!(cond)) {                                                               \
      ++g_failed;                                                                \
      std::cerr << __FILE__ << ":" << __LINE__ << ": CHECK failed: " #cond "\n"; \
    }                                                                            \
  } while (0)
#define CHECK_EQ(a, b)                                                                              \
  do {                                                                                              \
    ++g_checked;                                                                                    \
    if (!((a) == (b))) {                                                                            \
      ++g_failed;                                                                                   \
      std::cerr << __FILE__ << ":" << __LINE__ << ": CHECK_EQ failed: " #a " == " #b "  (" << (a) << " vs " << (b) << ")\n"; \
    }                                                                                               \
  } while (0)

static std::string ReadAll(const fs::path& p) {
  std::ifstream in(p, std::ios::binary);
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

static std::string Trim(std::string s) {
  while (!s.empty() && (s.back() == '\n' || s.back() == ' ')) s.pop_back();
  return s;
}

static void TestCrypto() {
  CHECK_EQ(Sha256Hex(""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  CHECK_EQ(Sha256Hex("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  // RFC 8032 の試験 1（空の文）
  std::string pub, sig;
  HexDecode("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", &pub);
  HexDecode("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b", &sig);
  CHECK(Ed25519Verify(sig, "", pub));
  CHECK(!Ed25519Verify(sig, "x", pub));
  sig[10] ^= 1;
  CHECK(!Ed25519Verify(sig, "", pub));
  std::string bytes;
  CHECK(!HexDecode("abc", &bytes));
  CHECK(!HexDecode("zz", &bytes));
}

static void TestData() {
  SupplementLimits limits;
  limits.pos_count = 100;
  std::string error;
  auto table = SupplementTable::Parse("# 注釈\nあいう\t10\t11\t5000\tAIU\nあいう\t10\t11\t4000\tAIU\nあいえ\t10\t11\t5000\tAIE\n\nか\t1\t2\t3\tK\n", limits, &error);
  CHECK(table != nullptr);
  CHECK_EQ(table->size(), size_t{3});  // 同じ (読み, 表記) は1つ
  auto exact = table->ExactRange("あいう");
  CHECK_EQ(exact.second - exact.first, size_t{1});
  CHECK_EQ(table->at(exact.first).cost, 4000);  // 費用の小さいほうが残る
  auto predictive = table->PredictiveRange("あい");
  CHECK_EQ(predictive.second - predictive.first, size_t{2});
  CHECK(table->HasKey("か"));
  CHECK(!table->HasKey("き"));
  CHECK(table->HasValue("AIE"));
  CHECK(!table->HasValue("nothing"));
  // 受け付けない行（1行でもあれば全体を受け付けない）
  for (const char* bad : {"あ\t10\t11\t5000\n", "あ\t100\t11\t5000\tX\n", "あ\t10\t11\t99999\tX\n", "あ\t10\t11\t-1\tX\n",
                          "あ\t10\t11\t5000\tX\tY\n", "\t10\t11\t5000\tX\n", "あ\t10\t11\t5000\t\n", "あ\t10\t11\t5000\tA\x01\n",
                          "あ\t10\t11\t5000\t\xff\xfe\n", "あ\t1x\t11\t5000\tX\n"}) {
    error.clear();
    CHECK(SupplementTable::Parse(bad, limits, &error) == nullptr);
    CHECK(!error.empty());
  }
  CHECK(IsCleanUtf8("固有名詞 Google"));
  CHECK(!IsCleanUtf8("a\tb"));
  CHECK(!IsCleanUtf8("\xed\xa0\x80"));  // サロゲート

  auto english = ParseEnglishExtra("named\tfoo\nsignal\tbar\ncurated\tbaz\nphrase\tsee you\ncasing\tgithub\tGitHub\ncasing\tgithub\tGithub\ncasing2\tchina\tChina\n", EnglishLimits(), &error);
  CHECK(english != nullptr);
  CHECK_EQ(english->named.size(), size_t{1});
  CHECK_EQ(english->casing.size(), size_t{1});
  CHECK_EQ(english->casing[0].second, "GitHub");  // 同じ打った形は最初の行
  CHECK_EQ(english->casing2.size(), size_t{1});
  CHECK(ParseEnglishExtra("casing\tnew york\tNew York\ncasing\thermes\tHermès\n", EnglishLimits(), &error) != nullptr);  // 空白も、語の外の字も
  CHECK(ParseEnglishExtra("casing\t new york\tNew York\n", EnglishLimits(), &error) == nullptr);
  CHECK(ParseEnglishExtra("casing\tnew  york\tNew York\n", EnglishLimits(), &error) == nullptr);
  for (const char* bad : {"named\tFoo\n", "named\n", "phrase\tone\n", "phrase\tsee  you\n", "casing\tfoo\n", "unknown\tx\n", "casing\tfoo\tA\"B\n"}) {
    CHECK(ParseEnglishExtra(bad, EnglishLimits(), &error) == nullptr);
  }
}

static void TestManifest() {
  const std::string sha(64, 'a');
  const std::string good = "compound-ime-dict-manifest\t1\nversion\t20261101\ncreated\t2026-11-01\npos_table\t" + sha +
                           "\nfile\tsupplement\tsupplement.tsv\t10\t" + sha + "\thttps://example.test/x/supplement.tsv\nfuture\tx\n";
  Manifest m;
  std::string error;
  CHECK(ParseManifest(good, "https://example.test/", &m, &error));
  CHECK_EQ(m.version, uint64_t{20261101});
  CHECK(m.Find("supplement") != nullptr);
  CHECK(!ParseManifest(good, "https://other.test/", &m, &error));  // 許した場所の外
  auto replace = [&](const std::string& a, const std::string& b) {
    std::string s = good;
    s.replace(s.find(a), a.size(), b);
    return s;
  };
  CHECK(!ParseManifest(replace("version\t20261101", "version\t2026110"), "", &m, &error));
  CHECK(!ParseManifest(replace("compound-ime-dict-manifest\t1", "compound-ime-dict-manifest\t2"), "", &m, &error));
  CHECK(!ParseManifest(replace("supplement.tsv\t10", "../x\t10"), "", &m, &error));
  CHECK(!ParseManifest(replace("\t10\t", "\t-1\t"), "", &m, &error));
  CHECK(!ParseManifest(replace(sha.substr(0, 4), "ZZZZ"), "", &m, &error));
  CHECK(!ParseManifest("compound-ime-dict-manifest\t1\nversion\t20261101\n", "", &m, &error));
}

struct Env {
  fs::path fx, work;
  std::string pub, other_pub, pos_sha;
  size_t pos_count = 0;
  std::map<std::string, int> fetches;  // URL ごとの回数
  std::string serving = "v1";          // いま配布ページが見せている版（フィクスチャの名前）
  bool network_down = false;
  std::unique_ptr<Fetcher> MakeFetcher() {
    return std::make_unique<FunctionFetcher>([this](const std::string& url, size_t max) {
      ++fetches[url];
      FetchResult r;
      if (network_down) {
        r.error = "network down";
        return r;
      }
      const std::string prefix = "https://example.test/";
      if (url.rfind(prefix, 0) != 0) {
        r.error = "unknown host";
        return r;
      }
      std::string rest = url.substr(prefix.size());
      std::string file = rest;
      if (rest.rfind("latest/", 0) == 0) file = serving + "/" + rest.substr(7);  // dict-latest の目録
      const fs::path path = fx / file;
      if (!fs::exists(path)) {
        r.error = "404";
        return r;
      }
      r.body = ReadAll(path);
      if (r.body.size() > max) {
        r.body.clear();
        r.error = "larger than allowed";
        return r;
      }
      r.ok = true;
      return r;
    });
  }
  int FetchCount() const {
    int n = 0;
    for (const auto& [_, c] : fetches) n += c;
    return n;
  }
  Config MakeConfig(const std::string& name) {
    Config c;
    c.root = (work / name).string();
    c.manifest_url = "https://example.test/latest/manifest.txt";
    c.url_prefix = "https://example.test/";
    HexDecode(pub, &c.public_key);
    c.pos_table_sha256 = pos_sha;
    c.pos_count = pos_count;
    return c;
  }
};

static Updater MakeUpdater(Env& env, const Config& c, Settings settings = Settings()) {
  return Updater(c, [settings] { return settings; }, env.MakeFetcher());
}

static const int64_t kDay = 86400;

static void TestUpdater(Env& env) {
  const ApplyFn accept = [](const Snapshot&) { return true; };
  int applied = 0;
  const ApplyFn counting = [&applied](const Snapshot&) {
    ++applied;
    return true;
  };

  // --- 入れる、間隔、最新のとき ---
  Config c = env.MakeConfig("a");
  Updater u = MakeUpdater(env, c);
  Snapshot snap;
  CHECK(!u.LoadInstalled(&snap));  // 何も入っていない
  env.serving = "v1";
  int64_t t0 = 1'800'000'000;
  UpdateResult r = u.CheckAndUpdate(t0, false, counting);
  CHECK_EQ(std::string(StatusName(r.status)), "installed");
  CHECK_EQ(applied, 1);
  CHECK_EQ(u.InstalledVersion(), uint64_t{20261101});
  CHECK(fs::exists(env.work / "a/current/manifest.txt"));
  CHECK(!fs::exists(env.work / "a/staging"));
  const int fetched = env.FetchCount();
  CHECK_EQ(fetched, 4);  // 目録、署名、辞書、英語の一覧
  r = u.CheckAndUpdate(t0 + 3 * kDay, false, counting);  // 間隔の前: 通信しない
  CHECK_EQ(std::string(StatusName(r.status)), "not-due");
  CHECK_EQ(env.FetchCount(), fetched);
  r = u.CheckAndUpdate(t0 + 8 * kDay, false, counting);  // 間隔のあと、同じ版
  CHECK_EQ(std::string(StatusName(r.status)), "up-to-date");
  CHECK_EQ(env.FetchCount(), fetched + 2);  // 目録と署名だけ
  CHECK_EQ(applied, 1);

  // --- 起動時の読み込み（新しい Updater） ---
  {
    Updater again = MakeUpdater(env, c);
    Snapshot s;
    CHECK(again.LoadInstalled(&s));
    CHECK_EQ(s.version, uint64_t{20261101});
    CHECK(s.table != nullptr && s.english != nullptr);
    auto range = s.table->ExactRange("ずずずぷろーぶ");
    CHECK_EQ(range.second - range.first, size_t{1});
    CHECK_EQ(s.english->named.size(), size_t{1});
  }

  // --- 新しい版へ。前の版は previous/ に残る ---
  env.serving = "v2";
  int64_t t1 = t0 + 16 * kDay;
  r = u.CheckAndUpdate(t1, false, counting);
  CHECK_EQ(std::string(StatusName(r.status)), "installed");
  CHECK_EQ(u.InstalledVersion(), uint64_t{20261201});
  CHECK(fs::exists(env.work / "a/previous/manifest.txt"));
  CHECK_EQ(applied, 2);
  u.ConfirmTrial();  // 動いたあと（サービスが30秒後にすること）

  // --- 古い目録（巻き戻し）は無視する ---
  env.serving = "older";
  r = u.CheckAndUpdate(t1 + 8 * kDay, false, counting);
  CHECK_EQ(std::string(StatusName(r.status)), "up-to-date");
  CHECK_EQ(u.InstalledVersion(), uint64_t{20261201});

  // --- 悪い配布物: 今の辞書は変わらない ---
  int64_t t = t1 + 20 * kDay;
  struct Bad { const char* name; const char* status; };
  for (const Bad& bad : {Bad{"bad-sig", "verify-failed"}, Bad{"bad-hash", "verify-failed"}, Bad{"bad-content", "rejected"},
                         Bad{"wrong-pos", "rejected"}, Bad{"bad-url", "rejected"}, Bad{"huge", "rejected"}}) {
    env.serving = bad.name;
    t += 8 * kDay;
    r = u.CheckAndUpdate(t, false, accept);
    if (std::string(StatusName(r.status)) != bad.status) std::cerr << bad.name << ": " << r.detail << "\n";
    CHECK_EQ(std::string(StatusName(r.status)), std::string(bad.status));
    CHECK_EQ(u.InstalledVersion(), uint64_t{20261201});
    Updater probe = MakeUpdater(env, c);
    Snapshot s;
    CHECK(probe.LoadInstalled(&s));
    CHECK_EQ(s.version, uint64_t{20261201});
    probe.ConfirmTrial();
    CHECK(!fs::exists(env.work / "a/staging"));
  }
  // 悪いと分かった版は、もう取りに行かない（目録だけ見て終わる）
  env.serving = "bad-content";
  const int before = env.FetchCount();
  r = u.CheckAndUpdate(t + 8 * kDay, false, accept);
  CHECK_EQ(std::string(StatusName(r.status)), "rejected");
  CHECK_EQ(env.FetchCount(), before + 2);

  // --- 読み直しに失敗したら前の辞書に戻す ---
  Config c2 = env.MakeConfig("b");
  Updater u2 = MakeUpdater(env, c2);
  env.serving = "v1";
  CHECK_EQ(std::string(StatusName(u2.CheckAndUpdate(t0, false, accept).status)), "installed");
  env.serving = "v2";
  r = u2.CheckAndUpdate(t0 + 8 * kDay, false, [](const Snapshot&) { return false; });
  CHECK_EQ(std::string(StatusName(r.status)), "reload-failed");
  CHECK_EQ(u2.InstalledVersion(), uint64_t{20261101});  // v1 に戻った
  {
    Updater probe = MakeUpdater(env, c2);
    Snapshot s;
    CHECK(probe.LoadInstalled(&s));
    CHECK_EQ(s.version, uint64_t{20261101});
    CHECK_EQ(s.table->size(), size_t{1});
  }
  r = u2.CheckAndUpdate(t0 + 16 * kDay, false, accept);  // 失敗した版は、また試さない
  CHECK_EQ(std::string(StatusName(r.status)), "rejected");
  // 最初の1回で失敗したときは、辞書なしに戻る
  Config c3 = env.MakeConfig("c");
  Updater u3 = MakeUpdater(env, c3);
  env.serving = "v1";
  CHECK_EQ(std::string(StatusName(u3.CheckAndUpdate(t0, false, [](const Snapshot&) { return false; }).status)), "reload-failed");
  CHECK_EQ(u3.InstalledVersion(), uint64_t{0});
  CHECK(!fs::exists(env.work / "c/current"));

  // --- 止める設定: 通信しない ---
  Config c4 = env.MakeConfig("d");
  Settings off;
  off.enabled = false;
  Updater u4 = MakeUpdater(env, c4, off);
  const int calls = env.FetchCount();
  r = u4.CheckAndUpdate(t0, true, accept);  // force でも止まったまま
  CHECK_EQ(std::string(StatusName(r.status)), "disabled");
  CHECK_EQ(env.FetchCount(), calls);
  // 公開鍵がなければ通信しない
  Config c5 = env.MakeConfig("e");
  c5.public_key.clear();
  Updater u5 = MakeUpdater(env, c5);
  r = u5.CheckAndUpdate(t0, true, accept);
  CHECK_EQ(std::string(StatusName(r.status)), "no-key");
  CHECK_EQ(env.FetchCount(), calls);
  // 別の鍵（署名の確かめに使う鍵が違う）では、正しい配布物も受け付けない
  Config c6 = env.MakeConfig("f");
  HexDecode(env.other_pub, &c6.public_key);
  Updater u6 = MakeUpdater(env, c6);
  env.serving = "v1";
  CHECK_EQ(std::string(StatusName(u6.CheckAndUpdate(t0, true, accept).status)), "verify-failed");
  // 試験用でない設定は https だけ
  Config c7 = env.MakeConfig("g");
  c7.manifest_url = "http://example.test/latest/manifest.txt";
  Updater u7 = MakeUpdater(env, c7);
  CHECK_EQ(std::string(StatusName(u7.CheckAndUpdate(t0, true, accept).status)), "fetch-failed");
  c7.manifest_url = "file:///etc/passwd";
  Updater u8 = MakeUpdater(env, c7);
  CHECK_EQ(std::string(StatusName(u8.CheckAndUpdate(t0, true, accept).status)), "fetch-failed");

  // --- 取れなかったとき: 6時間は再び試さず、そのあとは試す ---
  Config c9 = env.MakeConfig("h");
  Updater u9 = MakeUpdater(env, c9);
  env.network_down = true;
  CHECK_EQ(std::string(StatusName(u9.CheckAndUpdate(t0, false, accept).status)), "fetch-failed");
  CHECK_EQ(std::string(StatusName(u9.CheckAndUpdate(t0 + 3600, false, accept).status)), "not-due");
  CHECK_EQ(std::string(StatusName(u9.CheckAndUpdate(t0 + 7 * 3600, false, accept).status)), "fetch-failed");
  env.network_down = false;
  env.serving = "v1";
  CHECK_EQ(std::string(StatusName(u9.CheckAndUpdate(t0 + 14 * 3600, false, accept).status)), "installed");

  // --- 間隔は24時間より短くしない ---
  Config c10 = env.MakeConfig("i");
  Settings fast;
  fast.interval_hours = 1;
  Updater u10 = MakeUpdater(env, c10, fast);
  CHECK_EQ(std::string(StatusName(u10.CheckAndUpdate(t0, false, accept).status)), "installed");
  CHECK_EQ(std::string(StatusName(u10.CheckAndUpdate(t0 + 7 * 3600, false, accept).status)), "not-due");
  CHECK_EQ(std::string(StatusName(u10.CheckAndUpdate(t0 + 25 * 3600, false, accept).status)), "up-to-date");
}

static void TestLoadRecovery(Env& env) {
  const ApplyFn accept = [](const Snapshot&) { return true; };
  int64_t t0 = 1'800'000'000;
  // --- 入れた辞書のファイルが書き換えられていたら、previous/ を使う ---
  {
    Config c = env.MakeConfig("tamper");
    Updater u = MakeUpdater(env, c);
    env.serving = "v1";
    u.CheckAndUpdate(t0, false, accept);
    env.serving = "v2";
    u.CheckAndUpdate(t0 + 8 * kDay, false, accept);
    u.ConfirmTrial();
    std::ofstream(env.work / "tamper/current/supplement.tsv", std::ios::app) << "ぱ\t1\t1\t1\tInjected\n";
    Updater fresh = MakeUpdater(env, c);
    Snapshot s;
    CHECK(fresh.LoadInstalled(&s));
    CHECK_EQ(s.version, uint64_t{20261101});
    CHECK(!s.table->HasValue("Injected"));
    // 署名のファイルが消されたときも同じ
    fs::remove(env.work / "tamper/current/manifest.txt.sig");
    Updater fresh2 = MakeUpdater(env, c);
    Snapshot s2;
    CHECK(!fresh2.LoadInstalled(&s2));  // v1 は previous に移って current になったあとなので、current/ は欠けている
  }
  // --- 入れた版が確かめられる前に続けて落ちたら、前の版に戻す ---
  {
    Config c = env.MakeConfig("trial");
    Updater u = MakeUpdater(env, c);
    env.serving = "v1";
    u.CheckAndUpdate(t0, false, accept);
    u.ConfirmTrial();
    env.serving = "v2";
    u.CheckAndUpdate(t0 + 8 * kDay, false, accept);  // v2 を入れた（確かめる前）
    Snapshot s;
    Updater boot1 = MakeUpdater(env, c);
    CHECK(boot1.LoadInstalled(&s));  // 1回目の起動: まだ v2
    CHECK_EQ(s.version, uint64_t{20261201});
    Updater boot2 = MakeUpdater(env, c);  // 確かめる前にもう1回起動（前の起動で落ちた）
    CHECK(boot2.LoadInstalled(&s));
    CHECK_EQ(s.version, uint64_t{20261101});  // v1 に戻った
    // 戻した版（v2）は、もう取らない
    env.serving = "v2";
    UpdateResult r = boot2.CheckAndUpdate(t0 + 30 * kDay, false, accept);
    CHECK_EQ(std::string(StatusName(r.status)), "rejected");
  }
  // --- 確かめたあとなら、何度起動しても戻さない ---
  {
    Config c = env.MakeConfig("confirmed");
    Updater u = MakeUpdater(env, c);
    env.serving = "v1";
    u.CheckAndUpdate(t0, false, accept);
    u.ConfirmTrial();
    for (int i = 0; i < 4; ++i) {
      Updater boot = MakeUpdater(env, c);
      Snapshot s;
      CHECK(boot.LoadInstalled(&s));
      CHECK_EQ(s.version, uint64_t{20261101});
    }
  }
  // --- 入れ替えの途中で止まった（current/ がなく previous/ だけ） ---
  {
    Config c = env.MakeConfig("halfway");
    Updater u = MakeUpdater(env, c);
    env.serving = "v1";
    u.CheckAndUpdate(t0, false, accept);
    u.ConfirmTrial();
    fs::rename(env.work / "halfway/current", env.work / "halfway/previous");
    Updater boot = MakeUpdater(env, c);
    Snapshot s;
    CHECK(boot.LoadInstalled(&s));
    CHECK_EQ(s.version, uint64_t{20261101});
  }
  // --- 起動時に使えなかったとき（本体の読み直しの失敗）は previous/ に戻す ---
  {
    Config c = env.MakeConfig("startfail");
    Updater u = MakeUpdater(env, c);
    env.serving = "v1";
    u.CheckAndUpdate(t0, false, accept);
    u.ConfirmTrial();
    env.serving = "v2";
    u.CheckAndUpdate(t0 + 8 * kDay, false, accept);
    u.ConfirmTrial();
    Updater boot = MakeUpdater(env, c);
    Snapshot s;
    CHECK(boot.LoadInstalled(&s));
    CHECK_EQ(s.version, uint64_t{20261201});
    boot.ReportApplyFailure();
    CHECK_EQ(boot.InstalledVersion(), uint64_t{20261101});
  }
}

// 背景の確かめ（Service）: 起動時に入っている辞書を読み、少し待って確かめ、入れた版に「確かめた」印を付ける
static void TestService(Env& env) {
  std::atomic<int> applied{0};
  std::atomic<uint64_t> last_version{0};
  Config c = env.MakeConfig("service");
  env.serving = "v1";
  {
    Service service(c, [] { return Settings(); }, env.MakeFetcher(), [&](const Snapshot& s) {
      ++applied;
      last_version = s.version;
      return true;
    });
    CHECK(!service.Start(0, 0));  // 何も入っていないので、起動時には読めない。0秒後に確かめて入れる
    for (int i = 0; i < 300 && applied.load() == 0; ++i) usleep(10000);
    CHECK_EQ(applied.load(), 1);
    CHECK_EQ(last_version.load(), uint64_t{20261101});
    service.Stop();
  }
  usleep(100000);
  // 確かめる前の印（trial）は、入れて0秒後に消える。次の起動では、起動の回数を数えずに v1 を読む
  for (int i = 0; i < 3; ++i) {
    Updater boot = MakeUpdater(env, c);
    Snapshot s;
    CHECK(boot.LoadInstalled(&s));
    CHECK_EQ(s.version, uint64_t{20261101});
  }
  // 読むだけ（initial_delay が負）: 通信しない
  const int calls = env.FetchCount();
  {
    int loaded = 0;
    Service service(c, [] { return Settings(); }, env.MakeFetcher(), [&](const Snapshot&) {
      ++loaded;
      return true;
    });
    CHECK(service.Start(-1, 0));
    CHECK_EQ(loaded, 1);
  }
  usleep(50000);
  CHECK_EQ(env.FetchCount(), calls);
  // 起動時に読んだ辞書を本体が使えなかったら、前に戻す（previous がなければ辞書なし）
  {
    Service service(c, [] { return Settings(); }, env.MakeFetcher(), [](const Snapshot&) { return false; });
    CHECK(!service.Start(-1, 0));
    CHECK_EQ(service.updater().InstalledVersion(), uint64_t{0});
  }
}

static void TestSettingsAndConfig(const fs::path& fx) {
  // 試験でなければ、環境変数では何も変えられない（取る先・公開鍵・止める設定の上書き）
  setenv("MYIME_HERMETIC_TEST", "0", 1);
  setenv("MYIME_DICT_UPDATE", "0", 1);
  setenv("MYIME_DICT_UPDATE_BASE", "http://127.0.0.1:1", 1);
  setenv("MYIME_DICT_UPDATE_DIR", "/tmp/should-not-be-used", 1);
  setenv("MYIME_DICT_UPDATE_PUBKEY", std::string(64, 'a').c_str(), 1);
  setenv("XDG_CONFIG_HOME", "/nonexistent", 1);
  setenv("XDG_DATA_HOME", "/tmp/xdg-data-for-test", 1);
  CHECK(ReadSettings().enabled);
  BakedValues baked;
  baked.manifest_url = "https://github.com/J-KAMMA/compound-ime/releases/download/dict-latest/manifest.txt";
  baked.url_prefix = "https://github.com/J-KAMMA/compound-ime/releases/download/";
  baked.public_key_hex = "UNSET";
  baked.pos_table_sha256 = std::string(64, 'b');
  Config c;
  CHECK(MakeConfig(baked, &c));
  CHECK_EQ(c.manifest_url, baked.manifest_url);
  CHECK_EQ(c.root, std::string("/tmp/xdg-data-for-test/compound-ime/dict"));
  CHECK(c.public_key.empty());  // 公開鍵が入っていなければ更新しない
  CHECK(!c.allow_test_transport);
  baked.public_key_hex = std::string(64, 'c');
  CHECK(MakeConfig(baked, &c));
  CHECK_EQ(c.public_key.size(), size_t{32});
  // 設定ファイル（Linux・マック）で止める
  fs::create_directories("/tmp/dict-update-settings-test/compound-ime");
  setenv("XDG_CONFIG_HOME", "/tmp/dict-update-settings-test", 1);
  {
    std::ofstream("/tmp/dict-update-settings-test/compound-ime/settings") << "ZenzaiEnabled=1\nDictUpdate=0\nDictUpdateIntervalHours=48\n";
  }
#ifndef _WIN32
  CHECK(!ReadSettings().enabled);
  CHECK_EQ(ReadSettings().interval_hours, 48);
  {
    std::ofstream("/tmp/dict-update-settings-test/compound-ime/settings") << "DictUpdate=1\n";
  }
  CHECK(ReadSettings().enabled);
#endif
  // 試験の中では環境変数が使える
  setenv("MYIME_HERMETIC_TEST", "1", 1);
  CHECK(!ReadSettings().enabled);  // MYIME_DICT_UPDATE=0
  setenv("MYIME_DICT_UPDATE", "1", 1);
  CHECK(ReadSettings().enabled);
  unsetenv("MYIME_DICT_UPDATE_DIR");
  CHECK(!MakeConfig(baked, &c));  // 試験では、置き場所・取る先・公開鍵が全部そろったときだけ
  setenv("MYIME_DICT_UPDATE_DIR", "/tmp/dict-update-env-root", 1);
  setenv("MYIME_DICT_UPDATE_BASE", "http://127.0.0.1:18080/rel", 1);
  CHECK(MakeConfig(baked, &c));
  CHECK_EQ(c.manifest_url, std::string("http://127.0.0.1:18080/rel/manifest.txt"));
  CHECK(c.allow_test_transport);
  CHECK_EQ(c.url_prefix, std::string("http://127.0.0.1:18080/rel/"));
  setenv("MYIME_DICT_UPDATE_URL_PREFIX", "https://example.test/dict-1/", 1);
  CHECK(MakeConfig(baked, &c));
  CHECK_EQ(c.url_prefix, std::string("https://example.test/dict-1/"));
  // URL の先頭を替えて、手元のファイルから取る（署名つきの目録の URL は変えない）
  setenv("MYIME_DICT_UPDATE_REWRITE", ("https://example.test/dict-1/=file://" + (fx / "v1").string() + "/").c_str(), 1);
  auto fetcher = MakeFetcher(c);
  FetchResult got = fetcher->Get("https://example.test/dict-1/manifest.txt", 65536);
  CHECK(got.ok);
  CHECK(got.body.rfind("compound-ime-dict-manifest", 0) == 0);
  CHECK(!fetcher->Get("https://example.test/dict-1/no-such-file", 65536).ok);
  // 試験でなければ、書き換えの指定は効かない
  setenv("MYIME_HERMETIC_TEST", "0", 1);
  Config production;
  production.allow_test_transport = false;
  CHECK(!MakeFetcher(production)->Get("file://" + (fx / "v1/manifest.txt").string(), 65536).ok);  // file:// は試験専用
  setenv("MYIME_HERMETIC_TEST", "1", 1);
  unsetenv("MYIME_DICT_UPDATE_URL_PREFIX");
  unsetenv("MYIME_DICT_UPDATE_REWRITE");
  unsetenv("MYIME_HERMETIC_TEST");
}

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "usage: dict_update_test <fixtures>\n";
    return 2;
  }
  Env env;
  env.fx = argv[1];
  env.pub = Trim(ReadAll(env.fx / "key.hex"));
  env.other_pub = Trim(ReadAll(env.fx / "other-key.hex"));
  {
    std::istringstream in(ReadAll(env.fx / "pos.txt"));
    in >> env.pos_sha >> env.pos_count;
  }
  env.work = fs::temp_directory_path() / ("dict-update-test-" + std::to_string(::getpid()));
  fs::remove_all(env.work);
  fs::create_directories(env.work);
  TestCrypto();
  TestData();
  TestManifest();
  TestUpdater(env);
  TestLoadRecovery(env);
  TestService(env);
  TestSettingsAndConfig(env.fx);
  fs::remove_all(env.work);
  std::cout << "checks " << g_checked << ", failed " << g_failed << "\n";
  return g_failed == 0 ? 0 : 1;
}
