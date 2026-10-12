// Local record of conversions the user corrected (another candidate, F6-F10,
// resized segments), to find what to improve next. Kept only on this PC.
#ifndef JAEN_CORRECTION_LOG_H_
#define JAEN_CORRECTION_LOG_H_

#include <cstdint>
#include <filesystem>
#include <mutex>
#include <string_view>

namespace jaen {

class CorrectionLog {
 public:
  // At about this size the older half is dropped.
  static constexpr std::uintmax_t kMaxBytes = 1 << 20;

  explicit CorrectionLog(std::filesystem::path file) : file_(std::move(file)) {}

  // Appends "time<TAB>kind<TAB>key<TAB>first<TAB>chosen". Tabs and line breaks
  // in the fields become spaces.
  void Record(std::string_view kind, std::string_view key, std::string_view first,
              std::string_view chosen);
  // Removes the file.
  void Clear();

 private:
  const std::filesystem::path file_;
  std::mutex mutex_;
};

}  // namespace jaen

#endif  // JAEN_CORRECTION_LOG_H_
