// 「今の変換は違う」をその場で記録する（docs/miss-report.md、tools/apply_miss_report.py）。
//
// Ctrl+Shift+F12 を押すと、
//   - 変換中・入力中なら、その文（打ったローマ字・読み・今の表示・選んでいる文節）を、
//   - 何も打っていないときは、直前に確定した文（2分以内・まだ記録していないもの）を、
// 利用者のプロファイルのフォルダの misconversions.tsv に1行足す。パソコンの外へは送らない。
// パスワードの欄・シークレットモード・環境変数 MYIME_MISS_REPORT=0 のときは何も覚えず、キーもアプリへそのまま渡す。
//
// 標準だけで書いてあり、単体試験は miss_report_test.cc（g++ で動く）。時刻は呼ぶ側が渡す。
#ifndef JAEN_MISS_REPORT_H_
#define JAEN_MISS_REPORT_H_

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>
#include <vector>

namespace jaen {

// 書く先のファイル名（プロファイルのフォルダの中）。学習の履歴を消すと一緒に消える（english_lexicon.cc にも同じ名前）。
inline constexpr char kMissReportFileName[] = "misconversions.tsv";
// これを超えたら古い半分を捨てる。
inline constexpr std::uintmax_t kMissReportMaxBytes = 1 << 20;
// ファイルの1行目（見出し）。tools/misconversions_to_tests.py は # の行を読み飛ばす。
inline constexpr std::string_view kMissReportHeader =
    "# 時刻\t種類\tローマ字\t読み\t出た変換\t選んでいた文節\t直前の文\n";

// commands::KeyEvent（protocol/commands.proto）の値。session.cc に同じ番号の static_assert がある。
inline constexpr int kMissKeyF12 = 30;
inline constexpr uint32_t kMissModCtrl = 1 | 32 | 256;     // CTRL, LEFT_CTRL, RIGHT_CTRL
inline constexpr uint32_t kMissModAlt = 2 | 64 | 512;      // ALT, LEFT_ALT, RIGHT_ALT
inline constexpr uint32_t kMissModShift = 4 | 128 | 1024;  // SHIFT, LEFT_SHIFT, RIGHT_SHIFT
inline constexpr uint32_t kMissModKeyUp = 16;

// Ctrl+Shift+F12（Alt なし、押したとき）。
inline bool IsMissReportKey(int special_key, uint32_t modifiers) {
  return special_key == kMissKeyF12 && (modifiers & kMissModCtrl) != 0 &&
         (modifiers & kMissModShift) != 0 && (modifiers & kMissModAlt) == 0 &&
         (modifiers & kMissModKeyUp) == 0;
}

// MYIME_MISS_REPORT=0 で止まる（既定は有効）。
inline bool MissReportEnabled() {
  static const bool enabled = [] {
    const char* value = std::getenv("MYIME_MISS_REPORT");
    return !(value != nullptr && std::string_view(value) == "0");
  }();
  return enabled;
}

struct MissEntry {
  std::string kind;      // commit（確定のあと）、convert（変換中）、compose（入力中）
  std::string romaji;    // 打ったキー（かな入力ならかな）
  std::string reading;   // 読み
  std::string shown;     // 出た変換（変換中は今の表示の全体）
  std::string selected;  // 変換中に選んでいた文節（ほかは空）
  std::string context;   // 直前の文（入力欄の前の文、なければ IME が覚えている直前の確定。最後の 40 字）
};

namespace miss_internal {
inline bool IsContinuation(char c) { return (static_cast<unsigned char>(c) & 0xC0) == 0x80; }
}  // namespace miss_internal

// 1つの欄: タブ・改行・制御文字を空白にし、max_bytes を超えたら文字の途中で切らずに縮める。
inline std::string MissField(std::string_view text, size_t max_bytes = 256) {
  std::string out(text.substr(0, max_bytes));
  if (text.size() > max_bytes) {
    // 切った位置が文字の途中なら、その文字ごと落とす
    size_t end = out.size();
    while (end > 0 && miss_internal::IsContinuation(text[end])) --end;
    out.resize(end);
  }
  for (char& c : out) {
    if (static_cast<unsigned char>(c) < 0x20 || c == 0x7f) c = ' ';
  }
  return out;
}

// 最後の max_chars 字（UTF-8）。
inline std::string MissTail(std::string_view text, size_t max_chars) {
  size_t chars = 0, pos = text.size();
  while (pos > 0) {
    size_t start = pos - 1;
    while (start > 0 && miss_internal::IsContinuation(text[start])) --start;
    if (chars == max_chars) break;
    ++chars;
    pos = start;
  }
  return std::string(text.substr(pos));
}

inline std::string FormatMissLine(std::string_view stamp, const MissEntry& e) {
  std::string line = MissField(stamp, 32);
  for (const std::string* field : {&e.kind, &e.romaji, &e.reading, &e.shown, &e.selected, &e.context}) {
    line += '\t';
    line += MissField(*field);
  }
  line += '\n';
  return line;
}

// 今の時刻（その PC の時刻、秒まで）。
inline std::string MissStamp() {
  const std::time_t now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
  std::tm local{};
#ifdef _WIN32
  localtime_s(&local, &now);
#else
  localtime_r(&now, &local);
#endif
  char stamp[32];
  std::strftime(stamp, sizeof(stamp), "%Y-%m-%dT%H:%M:%S", &local);
  return stamp;
}

// 1行足す。ファイルがなければ見出しから書く。max_bytes を超えていたら、見出しと新しい半分だけを残してから足す。
inline bool AppendMissLine(const std::filesystem::path& file, std::string_view line,
                           std::uintmax_t max_bytes = kMissReportMaxBytes) {
  std::error_code error;
  const std::uintmax_t size = std::filesystem::file_size(file, error);
  const bool exists = !error;
  if (exists && size > max_bytes) {
    std::vector<std::string> lines;
    {
      std::ifstream in(file, std::ios::binary);
      for (std::string l; std::getline(in, l);) {
        if (!l.empty() && l[0] != '#') lines.push_back(std::move(l));
      }
    }
    std::ofstream out(file, std::ios::binary | std::ios::trunc);
    out << kMissReportHeader;
    for (size_t i = lines.size() / 2; i < lines.size(); ++i) out << lines[i] << '\n';
  }
  std::ofstream out(file, std::ios::binary | std::ios::app);
  if (!out) return false;
  if (!exists || size == 0) out << kMissReportHeader;
  out << line;
  return static_cast<bool>(out);
}

// 直前の確定（Session が1つ持つ）。記録したら同じものは二度記録しない。
class LastCommit {
 public:
  using Millis = int64_t;
  static constexpr Millis kDefaultLifetimeMs = 2 * 60 * 1000;

  explicit LastCommit(Millis lifetime_ms = kDefaultLifetimeMs) : lifetime_ms_(lifetime_ms) {}

  void Set(MissEntry entry, Millis now) {
    entry_ = std::move(entry);
    at_ms_ = now;
    valid_ = true;
    reported_ = false;
  }
  // 記録できる（覚えていて、時間内で、まだ記録していない）。
  bool Ready(Millis now) const {
    return valid_ && !reported_ && now >= at_ms_ && now - at_ms_ <= lifetime_ms_;
  }
  const MissEntry& entry() const { return entry_; }
  void MarkReported() { reported_ = true; }
  void Clear() {
    valid_ = false;
    entry_ = MissEntry();
  }
  // 入力欄の印（context の revision）。前と違えば捨てる。
  void NoteRevision(int32_t revision) {
    if (has_revision_ && revision != revision_) Clear();
    has_revision_ = true;
    revision_ = revision;
  }

 private:
  Millis lifetime_ms_;
  Millis at_ms_ = 0;
  bool valid_ = false;
  bool reported_ = false;
  bool has_revision_ = false;
  int32_t revision_ = 0;
  MissEntry entry_;
};

}  // namespace jaen

#endif  // JAEN_MISS_REPORT_H_
