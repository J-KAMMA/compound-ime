#include "dict_update/fetcher.h"

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <vector>

#ifdef _WIN32
// clang-format off
#include <windows.h>
#include <wininet.h>
// clang-format on
#pragma comment(lib, "wininet.lib")
#else
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
extern char** environ;
#endif

namespace dict_update {
namespace fs = std::filesystem;
namespace {

FetchResult Fail(const std::string& why) {
  FetchResult r;
  r.error = why;
  return r;
}

// file:///path の中身（試験専用）
FetchResult GetFile(const std::string& url, size_t max_bytes) {
  const std::string path = url.substr(7);
  std::error_code ec;
  const fs::path p(std::u8string(path.begin(), path.end()));
  const auto size = fs::file_size(p, ec);
  if (ec) return Fail("file not found");
  if (size > max_bytes) return Fail("larger than allowed");
  std::ifstream in(p, std::ios::binary);
  std::ostringstream ss;
  ss << in.rdbuf();
  FetchResult r;
  r.ok = true;
  r.body = ss.str();
  return r;
}

#ifdef _WIN32

std::wstring Widen(const std::string& s) {
  const int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, nullptr, 0);
  std::wstring w(n > 0 ? n - 1 : 0, L'\0');
  if (n > 0) MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, w.data(), n);
  return w;
}

class WinInetFetcher : public Fetcher {
 public:
  explicit WinInetFetcher(bool test) : test_(test) {}
  FetchResult Get(const std::string& url, size_t max_bytes) override {
    if (url.rfind("file://", 0) == 0) return test_ ? GetFile(url, max_bytes) : Fail("file:// not allowed");
    HINTERNET internet = InternetOpenW(L"CompoundIME-dict-update/1", INTERNET_OPEN_TYPE_PRECONFIG, nullptr, nullptr, 0);
    if (!internet) return Fail("InternetOpen failed");
    DWORD timeout = 30000;
    InternetSetOptionW(internet, INTERNET_OPTION_CONNECT_TIMEOUT, &timeout, sizeof(timeout));
    InternetSetOptionW(internet, INTERNET_OPTION_RECEIVE_TIMEOUT, &timeout, sizeof(timeout));
    DWORD flags = INTERNET_FLAG_RELOAD | INTERNET_FLAG_NO_CACHE_WRITE | INTERNET_FLAG_NO_COOKIES;
    if (url.rfind("https://", 0) == 0) flags |= INTERNET_FLAG_SECURE;  // 証明書の確かめを外す旗は付けない
    HINTERNET h = InternetOpenUrlW(internet, Widen(url).c_str(), nullptr, 0, flags, 0);
    if (!h) {
      InternetCloseHandle(internet);
      return Fail("cannot connect");
    }
    DWORD status = 0, size = sizeof(status);
    if (!HttpQueryInfoW(h, HTTP_QUERY_STATUS_CODE | HTTP_QUERY_FLAG_NUMBER, &status, &size, nullptr) || status != 200) {
      InternetCloseHandle(h);
      InternetCloseHandle(internet);
      return Fail("http status " + std::to_string(status));
    }
    FetchResult r;
    char buffer[16384];
    while (true) {
      DWORD got = 0;
      if (!InternetReadFile(h, buffer, sizeof(buffer), &got)) {
        InternetCloseHandle(h);
        InternetCloseHandle(internet);
        return Fail("read failed");
      }
      if (got == 0) break;
      r.body.append(buffer, got);
      if (r.body.size() > max_bytes) {
        InternetCloseHandle(h);
        InternetCloseHandle(internet);
        return Fail("larger than allowed");
      }
    }
    InternetCloseHandle(h);
    InternetCloseHandle(internet);
    r.ok = true;
    return r;
  }

 private:
  bool test_;
};

#else  // Linux、マック

class CurlFetcher : public Fetcher {
 public:
  explicit CurlFetcher(bool test) : test_(test) {}
  FetchResult Get(const std::string& url, size_t max_bytes) override {
    if (url.rfind("file://", 0) == 0) return test_ ? GetFile(url, max_bytes) : Fail("file:// not allowed");
    // 出力は一時ファイルに書かせ、終わってから大きさの上限つきで読む
    char tmpl[] = "/tmp/compound-dict-XXXXXX";
    const int fd = mkstemp(tmpl);
    if (fd < 0) return Fail("cannot create temp file");
    close(fd);
    const std::string out_path = tmpl;
    const std::string limit = std::to_string(max_bytes + 1);
    // -f: HTTP エラーで失敗、-L: 配布ページの転送に従う、--proto: https だけ（試験では http も）、
    // --proto-redir: 転送先も https だけ
    std::vector<std::string> args = {"curl", "-fsSL", "--proto", test_ ? "=http,https" : "=https", "--proto-redir", "=https",
                                     "--max-time", "120", "--connect-timeout", "20", "--max-filesize", limit,
                                     "-A", kUserAgent, "-o", out_path, "--", url};
    std::vector<char*> argv;
    for (std::string& a : args) argv.push_back(a.data());
    argv.push_back(nullptr);
    pid_t pid = 0;
    if (posix_spawnp(&pid, "curl", nullptr, nullptr, argv.data(), environ) != 0) {
      unlink(out_path.c_str());
      return Fail("curl cannot be started");
    }
    int status = 0;
    if (waitpid(pid, &status, 0) < 0 || !WIFEXITED(status) || WEXITSTATUS(status) != 0) {
      unlink(out_path.c_str());
      return Fail("curl failed");
    }
    FetchResult r = GetFile("file://" + out_path, max_bytes);
    unlink(out_path.c_str());
    return r;
  }

 private:
  bool test_;
};

#endif

}  // namespace

std::unique_ptr<Fetcher> MakeDefaultFetcher(bool allow_test_transport) {
#ifdef _WIN32
  return std::make_unique<WinInetFetcher>(allow_test_transport);
#else
  return std::make_unique<CurlFetcher>(allow_test_transport);
#endif
}

}  // namespace dict_update
