#include "correction_log.h"

#include <chrono>
#include <ctime>
#include <fstream>
#include <string>
#include <system_error>
#include <vector>

namespace jaen {
namespace {

std::string Clean(std::string_view text) {
  std::string out(text.substr(0, 256));
  if (text.size() > 256) {  // do not keep half a character
    while (!out.empty() && (static_cast<unsigned char>(out.back()) & 0xC0) == 0x80) out.pop_back();
    if (!out.empty() && static_cast<unsigned char>(out.back()) >= 0xC0) out.pop_back();
  }
  for (char& c : out) {
    if (c == '\t' || c == '\n' || c == '\r') c = ' ';
  }
  return out;
}

}  // namespace

void CorrectionLog::Record(std::string_view kind, std::string_view key, std::string_view first,
                           std::string_view chosen) {
  const std::time_t now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
  std::tm local{};
  localtime_s(&local, &now);
  char stamp[32];
  std::strftime(stamp, sizeof(stamp), "%Y-%m-%dT%H:%M", &local);
  const std::string line = std::string(stamp) + "\t" + Clean(kind) + "\t" + Clean(key) + "\t" +
                           Clean(first) + "\t" + Clean(chosen) + "\n";
  std::lock_guard lock(mutex_);
  std::error_code error;
  if (std::filesystem::file_size(file_, error) > kMaxBytes && !error) {
    std::vector<std::string> lines;
    {
      std::ifstream in(file_, std::ios::binary);
      for (std::string l; std::getline(in, l);) lines.push_back(l);
    }
    std::ofstream out(file_, std::ios::binary | std::ios::trunc);
    for (size_t i = lines.size() / 2; i < lines.size(); ++i) out << lines[i] << '\n';
  }
  std::ofstream(file_, std::ios::binary | std::ios::app) << line;
}

void CorrectionLog::Clear() {
  std::lock_guard lock(mutex_);
  std::error_code error;
  std::filesystem::remove(file_, error);
}

}  // namespace jaen
