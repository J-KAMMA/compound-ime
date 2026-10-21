#include "dict_update/updater.h"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <sstream>

#include "dict_update/crypto.h"

namespace dict_update {
namespace fs = std::filesystem;
namespace {

constexpr size_t kMaxManifestBytes = 65536;
constexpr size_t kMaxSignatureBytes = 512;
constexpr uint64_t kMaxSupplementBytes = 32u << 20;
constexpr uint64_t kMaxEnglishBytes = 8u << 20;

fs::path ToPath(const std::string& utf8) { return fs::path(std::u8string(utf8.begin(), utf8.end())); }

bool ReadFile(const fs::path& path, size_t max_bytes, std::string* out) {
  std::error_code ec;
  const auto size = fs::file_size(path, ec);
  if (ec || size > max_bytes) return false;
  std::ifstream in(path, std::ios::binary);
  if (!in) return false;
  std::ostringstream ss;
  ss << in.rdbuf();
  if (!in && !in.eof()) return false;
  *out = ss.str();
  return out->size() == size;
}

bool WriteFileAtomic(const fs::path& path, const std::string& data) {
  fs::path tmp = path;
  tmp += ".tmp";
  {
    std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
    if (!out) return false;
    out.write(data.data(), static_cast<std::streamsize>(data.size()));
    out.flush();
    if (!out) return false;
  }
  std::error_code ec;
  fs::rename(tmp, path, ec);
  if (ec) {  // Windows では、すでにあるファイルへの rename が失敗することがある
    fs::remove(path, ec);
    ec.clear();
    fs::rename(tmp, path, ec);
  }
  return !ec;
}

bool Exists(const fs::path& p) {
  std::error_code ec;
  return fs::exists(p, ec);
}

void RemoveAll(const fs::path& p) {
  std::error_code ec;
  fs::remove_all(p, ec);
}

bool Rename(const fs::path& from, const fs::path& to) {
  std::error_code ec;
  fs::rename(from, to, ec);
  return !ec;
}

uint64_t SizeLimitFor(const std::string& kind) {
  if (kind == "supplement") return kMaxSupplementBytes;
  if (kind == "english") return kMaxEnglishBytes;
  return 0;  // 知らない種類は取らない
}

bool TransportAllowed(const std::string& url, bool test) {
  if (url.rfind("https://", 0) == 0) return true;
  if (!test) return false;
  return url.rfind("file://", 0) == 0 || url.rfind("http://127.0.0.1", 0) == 0 || url.rfind("http://localhost", 0) == 0;
}

std::string Trim(std::string s) {
  while (!s.empty() && (s.back() == '\n' || s.back() == '\r' || s.back() == ' ')) s.pop_back();
  return s;
}

}  // namespace

const char* StatusName(UpdateResult::Status s) {
  switch (s) {
    case UpdateResult::kDisabled: return "disabled";
    case UpdateResult::kNoKey: return "no-key";
    case UpdateResult::kNotDue: return "not-due";
    case UpdateResult::kUpToDate: return "up-to-date";
    case UpdateResult::kInstalled: return "installed";
    case UpdateResult::kFetchFailed: return "fetch-failed";
    case UpdateResult::kVerifyFailed: return "verify-failed";
    case UpdateResult::kRejected: return "rejected";
    case UpdateResult::kReloadFailed: return "reload-failed";
  }
  return "unknown";
}

Updater::Updater(Config config, SettingsProvider settings, std::unique_ptr<Fetcher> fetcher)
    : config_(std::move(config)), settings_(std::move(settings)), fetcher_(std::move(fetcher)) {}

std::string Updater::Path(const char* name) const {
  const auto u8 = (ToPath(config_.root) / name).u8string();
  return std::string(u8.begin(), u8.end());
}

Updater::State Updater::LoadState() const {
  State s;
  std::string text;
  if (!ReadFile(ToPath(config_.root) / "state.txt", 4096, &text)) return s;
  std::istringstream in(text);
  std::string line;
  while (std::getline(in, line)) {
    const size_t eq = line.find('=');
    if (eq == std::string::npos) continue;
    const std::string key = line.substr(0, eq);
    const std::string value = Trim(line.substr(eq + 1));
    if (value.empty() || value.size() > 18 || value.find_first_not_of("0123456789") != std::string::npos) continue;
    const int64_t n = static_cast<int64_t>(std::stoull(value));
    if (key == "last_check") s.last_check = n;
    else if (key == "last_attempt") s.last_attempt = n;
    else if (key == "installed") s.installed = static_cast<uint64_t>(n);
    else if (key == "trial") s.trial = static_cast<uint64_t>(n);
    else if (key == "boots") s.boots = n;
    else if (key == "bad") s.bad = static_cast<uint64_t>(n);
  }
  return s;
}

bool Updater::SaveState(const State& s) const {
  std::error_code ec;
  fs::create_directories(ToPath(config_.root), ec);
  std::ostringstream out;
  out << "last_check=" << s.last_check << "\nlast_attempt=" << s.last_attempt << "\ninstalled=" << s.installed
      << "\ntrial=" << s.trial << "\nboots=" << s.boots << "\nbad=" << s.bad << "\n";
  return WriteFileAtomic(ToPath(config_.root) / "state.txt", out.str());
}

bool Updater::VerifyDir(const std::string& dir, Snapshot* snap, std::string* error, bool* signature_failed) const {
  auto fail = [&](const std::string& why) {
    if (error) *error = why;
    return false;
  };
  if (signature_failed) *signature_failed = false;
  if (config_.public_key.size() != 32) return fail("no public key");
  const fs::path base = ToPath(dir);
  std::string manifest_text, sig_text;
  if (!ReadFile(base / "manifest.txt", kMaxManifestBytes, &manifest_text) ||
      !ReadFile(base / "manifest.txt.sig", kMaxSignatureBytes, &sig_text)) {
    return fail("manifest or signature missing");
  }
  std::string sig;
  if (!HexDecode(Trim(sig_text), &sig) || !Ed25519Verify(sig, manifest_text, config_.public_key)) {
    if (signature_failed) *signature_failed = true;
    return fail("bad signature");
  }
  Manifest manifest;
  std::string why;
  if (!ParseManifest(manifest_text, config_.url_prefix, &manifest, &why)) return fail(why);
  if (config_.pos_table_sha256.empty() || manifest.pos_table != config_.pos_table_sha256) {
    return fail("pos_table differs from this application's");
  }
  Snapshot result;
  result.version = manifest.version;
  SupplementLimits limits;
  if (config_.pos_count > 0) limits.pos_count = config_.pos_count;
  bool any = false;
  for (const ManifestFile& file : manifest.files) {
    const uint64_t cap = SizeLimitFor(file.kind);
    if (cap == 0) continue;
    if (file.size > cap) return fail(file.name + ": larger than allowed");
    std::string body;
    if (!ReadFile(base / file.name, static_cast<size_t>(cap), &body)) return fail(file.name + ": cannot read");
    if (body.size() != file.size) return fail(file.name + ": size differs");
    if (Sha256Hex(body) != file.sha256) return fail(file.name + ": sha256 differs");
    if (file.kind == "supplement") {
      result.table = SupplementTable::Parse(body, limits, &why);
      if (!result.table) return fail(file.name + ": " + why);
    } else {
      result.english = ParseEnglishExtra(body, EnglishLimits(), &why);
      if (!result.english) return fail(file.name + ": " + why);
    }
    any = true;
  }
  if (!any) return fail("manifest has no known files");
  *snap = std::move(result);
  return true;
}

// current/ を捨てて previous/ を current/ にする。previous/ が使えなければ辞書なしに戻る。
bool Updater::Rollback(State* state, bool mark_bad) {
  if (mark_bad) state->bad = std::max(state->bad, std::max(state->trial, state->installed));
  RemoveAll(ToPath(Path("current")));
  state->installed = 0;
  state->trial = 0;
  state->boots = 0;
  if (Exists(ToPath(Path("previous"))) && Rename(ToPath(Path("previous")), ToPath(Path("current")))) {
    Snapshot snap;
    std::string error;
    if (VerifyDir(Path("current"), &snap, &error)) {
      state->installed = snap.version;
    } else {
      RemoveAll(ToPath(Path("current")));
    }
  }
  SaveState(*state);
  return state->installed != 0;
}

bool Updater::LoadInstalled(Snapshot* out) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (config_.root.empty() || config_.public_key.size() != 32) return false;
  RemoveAll(ToPath(Path("staging")));
  State state = LoadState();
  // 入れ替えの途中で止まった跡: current/ がなく previous/ だけがある
  if (!Exists(ToPath(Path("current"))) && Exists(ToPath(Path("previous")))) {
    Rename(ToPath(Path("previous")), ToPath(Path("current")));
  }
  if (!Exists(ToPath(Path("current")))) return false;
  if (state.trial != 0) {
    ++state.boots;
    SaveState(state);
    if (state.boots >= config_.boot_trial_limit) {
      Rollback(&state, true);  // 入れた版が、確かめる前に続けて落ちた
    }
  }
  Snapshot snap;
  std::string error;
  if (Exists(ToPath(Path("current"))) && VerifyDir(Path("current"), &snap, &error)) {
    if (state.installed != snap.version) {
      state.installed = snap.version;
      SaveState(state);
    }
    *out = std::move(snap);
    return true;
  }
  // current/ が壊れている（書き換えられた、読めない）: previous/ を使う
  if (Exists(ToPath(Path("current")))) {
    Rollback(&state, false);  // ディスクの上で壊れた・書き換えられた。同じ版をまた取ってよい
    if (Exists(ToPath(Path("current"))) && VerifyDir(Path("current"), &snap, &error)) {
      *out = std::move(snap);
      return true;
    }
  }
  return false;
}

void Updater::ConfirmTrial() {
  std::lock_guard<std::mutex> lock(mutex_);
  State state = LoadState();
  if (state.trial != 0 || state.boots != 0) {
    state.trial = 0;
    state.boots = 0;
    SaveState(state);
  }
}

void Updater::ReportApplyFailure() {
  std::lock_guard<std::mutex> lock(mutex_);
  State state = LoadState();
  state.trial = std::max(state.trial, state.installed);
  Rollback(&state, true);
}

uint64_t Updater::InstalledVersion() {
  std::lock_guard<std::mutex> lock(mutex_);
  return LoadState().installed;
}

UpdateResult Updater::CheckAndUpdate(int64_t now, bool force, const ApplyFn& apply) {
  std::lock_guard<std::mutex> lock(mutex_);
  UpdateResult result;
  auto done = [&](UpdateResult::Status status, const std::string& detail) {
    result.status = status;
    result.detail = detail;
    return result;
  };
  const Settings settings = settings_ ? settings_() : Settings();
  if (!settings.enabled) return done(UpdateResult::kDisabled, "stopped by setting");
  if (config_.root.empty() || config_.public_key.size() != 32 || config_.manifest_url.empty()) {
    return done(UpdateResult::kNoKey, "no public key or place");
  }
  State state = LoadState();
  result.version = state.installed;
  const int64_t interval = static_cast<int64_t>(std::max(24, settings.interval_hours)) * 3600;
  if (!force) {
    const bool interval_over = now < state.last_check || now - state.last_check >= interval;
    const bool retry_over = now < state.last_attempt || now - state.last_attempt >= config_.retry_seconds;
    if (!interval_over || !retry_over) return done(UpdateResult::kNotDue, "interval not over");
  }
  state.last_attempt = now;
  SaveState(state);

  if (!TransportAllowed(config_.manifest_url, config_.allow_test_transport)) {
    return done(UpdateResult::kFetchFailed, "manifest url is not https");
  }
  FetchResult manifest_fetch = fetcher_->Get(config_.manifest_url, kMaxManifestBytes);
  if (!manifest_fetch.ok) return done(UpdateResult::kFetchFailed, "manifest: " + manifest_fetch.error);
  FetchResult sig_fetch = fetcher_->Get(config_.manifest_url + ".sig", kMaxSignatureBytes);
  if (!sig_fetch.ok) return done(UpdateResult::kFetchFailed, "signature: " + sig_fetch.error);
  std::string sig;
  if (!HexDecode(Trim(sig_fetch.body), &sig) || !Ed25519Verify(sig, manifest_fetch.body, config_.public_key)) {
    return done(UpdateResult::kVerifyFailed, "manifest signature does not match");
  }
  Manifest manifest;
  std::string why;
  if (!ParseManifest(manifest_fetch.body, config_.url_prefix, &manifest, &why)) {
    return done(UpdateResult::kRejected, why);
  }
  state.last_check = now;  // 署名の合った目録を読めた
  result.version = manifest.version;
  if (manifest.version <= state.installed) {
    SaveState(state);
    result.version = state.installed;
    return done(UpdateResult::kUpToDate, manifest.version < state.installed ? "older manifest ignored" : "same version");
  }
  if (manifest.version <= state.bad) {  // 悪いと分かった版と、それより古い版は取りに行かない
    SaveState(state);
    return done(UpdateResult::kRejected, "this version was rejected before");
  }
  if (manifest.pos_table != config_.pos_table_sha256) {
    state.bad = manifest.version;
    SaveState(state);
    return done(UpdateResult::kRejected, "pos_table differs from this application's");
  }

  // 取る（staging/）。大きさと SHA-256 が目録と合ったものだけを書く。
  const fs::path staging = ToPath(Path("staging"));
  RemoveAll(staging);
  std::error_code ec;
  fs::create_directories(staging, ec);
  if (ec) return done(UpdateResult::kFetchFailed, "cannot create staging");
  bool any = false;
  for (const ManifestFile& file : manifest.files) {
    const uint64_t cap = SizeLimitFor(file.kind);
    if (cap == 0) continue;
    if (file.size > cap) {
      RemoveAll(staging);
      state.bad = manifest.version;
      SaveState(state);
      return done(UpdateResult::kRejected, file.name + ": larger than allowed");
    }
    if (!TransportAllowed(file.url, config_.allow_test_transport)) {
      RemoveAll(staging);
      return done(UpdateResult::kRejected, file.name + ": url is not https");
    }
    FetchResult body = fetcher_->Get(file.url, static_cast<size_t>(file.size));
    if (!body.ok) {
      RemoveAll(staging);
      SaveState(state);
      return done(UpdateResult::kFetchFailed, file.name + ": " + body.error);
    }
    if (body.body.size() != file.size || Sha256Hex(body.body) != file.sha256) {
      RemoveAll(staging);
      state.bad = manifest.version;
      SaveState(state);
      return done(UpdateResult::kVerifyFailed, file.name + ": size or sha256 differs from the manifest");
    }
    if (!WriteFileAtomic(staging / file.name, body.body)) {
      RemoveAll(staging);
      return done(UpdateResult::kFetchFailed, file.name + ": cannot write");
    }
    any = true;
  }
  if (!any || !WriteFileAtomic(staging / "manifest.txt", manifest_fetch.body) ||
      !WriteFileAtomic(staging / "manifest.txt.sig", sig_fetch.body)) {
    RemoveAll(staging);
    return done(UpdateResult::kRejected, "nothing to install");
  }
  // 読み込めることを、入れ替える前に確かめる（読めない辞書は current/ に入れない）
  Snapshot snap;
  if (!VerifyDir(Path("staging"), &snap, &why)) {
    RemoveAll(staging);
    state.bad = manifest.version;
    SaveState(state);
    return done(UpdateResult::kRejected, why);
  }

  // 入れ替える: current/ → previous/、staging/ → current/
  RemoveAll(ToPath(Path("previous")));
  const bool had_current = Exists(ToPath(Path("current")));
  if (had_current && !Rename(ToPath(Path("current")), ToPath(Path("previous")))) {
    RemoveAll(staging);
    return done(UpdateResult::kFetchFailed, "cannot move current aside");
  }
  if (!Rename(staging, ToPath(Path("current")))) {
    if (had_current) Rename(ToPath(Path("previous")), ToPath(Path("current")));
    RemoveAll(staging);
    return done(UpdateResult::kFetchFailed, "cannot move staging into place");
  }
  state.installed = snap.version;
  state.trial = snap.version;
  state.boots = 0;
  SaveState(state);

  // 読み直す。失敗したら前の辞書に戻す。
  if (apply && !apply(snap)) {
    state.trial = snap.version;
    Rollback(&state, true);
    result.version = snap.version;
    return done(UpdateResult::kReloadFailed, "reload failed; back to version " + std::to_string(state.installed));
  }
  return done(UpdateResult::kInstalled, "version " + std::to_string(snap.version));
}

}  // namespace dict_update
