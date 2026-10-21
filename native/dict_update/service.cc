#include "dict_update/service.h"

#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <fstream>
#include <mutex>
#include <thread>

#include "dict_update/crypto.h"
#include "dict_update/fetcher.h"

#ifdef _WIN32
#include <windows.h>
#pragma comment(lib, "advapi32.lib")
#endif

namespace dict_update {
namespace {

// 環境変数（無ければ空）。ウィンドウズでは getenv の警告を避けて Win32 で読む。
std::string EnvOr(const char* name) {
#ifdef _WIN32
  char buf[1024];
  const DWORD n = GetEnvironmentVariableA(name, buf, sizeof(buf));
  return n > 0 && n < sizeof(buf) ? std::string(buf, n) : std::string();
#else
  const char* v = std::getenv(name);
  return v ? v : "";
#endif
}

bool EnvIs(const char* name, const char* value) { return EnvOr(name) == value; }

bool ParseSmallInt(const std::string& s, int* out) {
  if (s.empty() || s.size() > 6 || s.find_first_not_of("0123456789") != std::string::npos) return false;
  *out = std::stoi(s);
  return true;
}

}  // namespace

bool IsHermeticTest() { return EnvIs("MYIME_HERMETIC_TEST", "1"); }

Settings ReadSettings() {
  Settings s;
  if (IsHermeticTest()) {
    if (EnvIs("MYIME_DICT_UPDATE", "0")) s.enabled = false;
    int hours = 0;
    if (ParseSmallInt(EnvOr("MYIME_DICT_UPDATE_INTERVAL_HOURS"), &hours)) s.interval_hours = hours;
    return s;
  }
#ifdef _WIN32
  DWORD v = 0, size = sizeof(v);
  if (RegGetValueW(HKEY_CURRENT_USER, L"Software\\CompoundIME", L"DictUpdate", RRF_RT_REG_DWORD, nullptr, &v, &size) ==
      ERROR_SUCCESS) {
    s.enabled = v != 0;
  }
  size = sizeof(v);
  if (RegGetValueW(HKEY_CURRENT_USER, L"Software\\CompoundIME", L"DictUpdateIntervalHours", RRF_RT_REG_DWORD, nullptr,
                   &v, &size) == ERROR_SUCCESS) {
    s.interval_hours = static_cast<int>(v);
  }
#else
  const std::string config = EnvOr("XDG_CONFIG_HOME");
  const std::string home = EnvOr("HOME");
  const std::string path = !config.empty() ? config + "/compound-ime/settings"
                           : !home.empty() ? home + "/.config/compound-ime/settings" : "";
  if (!path.empty()) {
    std::ifstream file(path);
    std::string line;
    while (std::getline(file, line)) {
      const size_t eq = line.find('=');
      if (eq == std::string::npos) continue;
      std::string key = line.substr(0, eq), value = line.substr(eq + 1);
      while (!value.empty() && (value.back() == '\r' || value.back() == ' ')) value.pop_back();
      int n = 0;
      if (!ParseSmallInt(value, &n)) continue;
      if (key == "DictUpdate") s.enabled = n != 0;
      if (key == "DictUpdateIntervalHours") s.interval_hours = n;
    }
  }
#endif
  return s;
}

std::string DefaultRoot() {
#ifdef _WIN32
  wchar_t buf[MAX_PATH];
  const DWORD n = GetEnvironmentVariableW(L"LOCALAPPDATA", buf, MAX_PATH);
  if (n == 0 || n >= MAX_PATH) return "";
  const int len = WideCharToMultiByte(CP_UTF8, 0, buf, static_cast<int>(n), nullptr, 0, nullptr, nullptr);
  std::string utf8(len > 0 ? len : 0, '\0');
  if (len > 0) WideCharToMultiByte(CP_UTF8, 0, buf, static_cast<int>(n), utf8.data(), len, nullptr, nullptr);
  return utf8 + "\\CompoundIME\\dict";
#else
  const std::string data = EnvOr("XDG_DATA_HOME");
  const std::string home = EnvOr("HOME");
  if (!data.empty()) return data + "/compound-ime/dict";
  if (!home.empty()) return home + "/.local/share/compound-ime/dict";
  return "";
#endif
}

bool MakeConfig(const BakedValues& baked, Config* out) {
  Config c;
  c.pos_table_sha256 = baked.pos_table_sha256;
  c.pos_count = baked.pos_count;
  if (IsHermeticTest()) {
    const std::string root = EnvOr("MYIME_DICT_UPDATE_DIR"), base = EnvOr("MYIME_DICT_UPDATE_BASE"),
                      key = EnvOr("MYIME_DICT_UPDATE_PUBKEY");
    if (root.empty() || base.empty() || key.empty()) return false;
    if (!HexDecode(key, &c.public_key) || c.public_key.size() != 32) return false;
    c.root = root;
    c.manifest_url = base + "/manifest.txt";
    const std::string prefix = EnvOr("MYIME_DICT_UPDATE_URL_PREFIX");
    c.url_prefix = prefix.empty() ? base + "/" : prefix;
    c.allow_test_transport = true;
    *out = std::move(c);
    return true;
  }
  c.root = DefaultRoot();
  if (c.root.empty()) return false;
  c.manifest_url = baked.manifest_url;
  c.url_prefix = baked.url_prefix;
  std::string key;
  if (baked.public_key_hex != "UNSET" && HexDecode(baked.public_key_hex, &key) && key.size() == 32) {
    c.public_key = key;  // 入っていなければ空のまま（更新しない）
  }
  *out = std::move(c);
  return true;
}

namespace {
class RewriteFetcher : public Fetcher {
 public:
  RewriteFetcher(std::unique_ptr<Fetcher> inner, std::string from, std::string to)
      : inner_(std::move(inner)), from_(std::move(from)), to_(std::move(to)) {}
  FetchResult Get(const std::string& url, size_t max_bytes) override {
    if (url.compare(0, from_.size(), from_) == 0) return inner_->Get(to_ + url.substr(from_.size()), max_bytes);
    return inner_->Get(url, max_bytes);
  }

 private:
  std::unique_ptr<Fetcher> inner_;
  std::string from_, to_;
};
}  // namespace

std::unique_ptr<Fetcher> MakeFetcher(const Config& config) {
  std::unique_ptr<Fetcher> fetcher = MakeDefaultFetcher(config.allow_test_transport);
  if (config.allow_test_transport && IsHermeticTest()) {
    const std::string rule = EnvOr("MYIME_DICT_UPDATE_REWRITE");
    const size_t eq = rule.find('=', rule.find("://") == std::string::npos ? 0 : rule.find("://") + 3);
    if (!rule.empty() && eq != std::string::npos && eq > 0) {
      fetcher = std::make_unique<RewriteFetcher>(std::move(fetcher), rule.substr(0, eq), rule.substr(eq + 1));
    }
  }
  return fetcher;
}

struct Service::Shared {
  Shared(Config c, SettingsProvider s, std::unique_ptr<Fetcher> f, ApplyFn a)
      : updater(std::move(c), std::move(s), std::move(f)), apply(std::move(a)) {}
  Updater updater;
  ApplyFn apply;
  std::mutex mutex;
  std::condition_variable cv;
  bool stop = false;
};

Service::Service(Config config, SettingsProvider settings, std::unique_ptr<Fetcher> fetcher, ApplyFn apply)
    : shared_(std::make_shared<Shared>(std::move(config), std::move(settings), std::move(fetcher), std::move(apply))) {}

Service::~Service() { Stop(); }

Updater& Service::updater() { return shared_->updater; }

UpdateResult Service::CheckNow(bool force) {
  const int64_t now = std::chrono::duration_cast<std::chrono::seconds>(std::chrono::system_clock::now().time_since_epoch()).count();
  return shared_->updater.CheckAndUpdate(now, force, shared_->apply);
}

bool Service::Start(int initial_delay_seconds, int confirm_after_seconds) {
  bool applied = false;
  Snapshot snap;
  if (shared_->updater.LoadInstalled(&snap)) {
    if (shared_->apply(snap)) {
      applied = true;
    } else {
      shared_->updater.ReportApplyFailure();
    }
  }
  if (initial_delay_seconds < 0) return applied;  // 読むだけ（試験用。背景の確かめは始めない）
  std::shared_ptr<Shared> shared = shared_;
  std::thread([shared, initial_delay_seconds, confirm_after_seconds] {
    using Clock = std::chrono::steady_clock;
    const Clock::time_point start = Clock::now();
    Clock::time_point next_check = start + std::chrono::seconds(initial_delay_seconds);
    Clock::time_point confirm_at = start + std::chrono::seconds(confirm_after_seconds);
    bool confirmed = false;
    std::unique_lock<std::mutex> lock(shared->mutex);
    while (!shared->stop) {
      Clock::time_point wake = next_check;
      if (!confirmed && confirm_at < wake) wake = confirm_at;
      if (shared->cv.wait_until(lock, wake, [&] { return shared->stop; })) break;
      const Clock::time_point now = Clock::now();
      lock.unlock();
      if (!confirmed && now >= confirm_at) {
        shared->updater.ConfirmTrial();  // 入れて30秒、落ちずに動いた
        confirmed = true;
      }
      if (now >= next_check) {
        const int64_t epoch = std::chrono::duration_cast<std::chrono::seconds>(std::chrono::system_clock::now().time_since_epoch()).count();
        const UpdateResult result = shared->updater.CheckAndUpdate(epoch, false, shared->apply);
        next_check = Clock::now() + std::chrono::hours(6);
        if (result.status == UpdateResult::kInstalled) {  // 入れた版も、30秒落ちずに動いたら「確かめた」印を付ける
          confirmed = false;
          confirm_at = Clock::now() + std::chrono::seconds(confirm_after_seconds);
        }
      }
      lock.lock();
    }
  }).detach();  // 終了を待たない（通信の途中でも本体の終了を遅らせない）。状態は shared が持つ
  return applied;
}

void Service::Stop() {
  if (!shared_) return;
  std::lock_guard<std::mutex> lock(shared_->mutex);
  shared_->stop = true;
  shared_->cv.notify_all();
}

}  // namespace dict_update
