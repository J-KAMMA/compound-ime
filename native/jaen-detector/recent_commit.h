// 直前に確定した文字の短い記憶（docs/english-follow.md）。Mozc の session（入力欄ごとの会話）が1つずつ持つ。
//
// 入力欄の前の文（GetSurroundingContext の左側）を渡さないアプリでも、「さっき確定した語が英字で終わる」を
// 変換へ伝えるためのもの。確定した文字、変換を通らずに入力された空白・英字（session が見たキー）をつなぎ、
// 最後の 64 字だけを覚える。次のときは捨てる:
//   - 入力欄が変わった（context の revision が変わった）、会話の作り直し（この物が作り直される）、RESET_CONTEXT
//   - カーソルが動いた（矢印・Home・End・マウスでの位置変更の知らせ、Enter・Tab・Delete など、覚えた分より前に
//     戻る Backspace、覚えた文字を消す取り消し）
//   - 最後に足してから 60 秒たった
// 打った文字は記憶の中（この物の文字列）にだけあり、記録にもファイルにも書かない。
//
// 環境変数 MYIME_ENGLISH_FOLLOW=off で、この記憶ごと止まる（RecentCommitEnabled）。
// 標準だけで書いてあり、単体試験は jaen_detector_test.cc。時刻は呼ぶ側が渡す（試験で進められる）。
#ifndef JAEN_RECENT_COMMIT_H_
#define JAEN_RECENT_COMMIT_H_

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <string>
#include <string_view>

namespace jaen {

// commands::KeyEvent（protocol/commands.proto）の値。session.cc に同じ番号の static_assert がある。
inline constexpr int kKeyOn = 2;
inline constexpr int kKeyOff = 3;
inline constexpr int kKeySpace = 4;
inline constexpr int kKeyBackspace = 12;
inline constexpr int kKeyHenkan = 13;
inline constexpr int kKeyMuhenkan = 14;
inline constexpr int kKeyKana = 15;
inline constexpr int kKeyEisu = 46;
inline constexpr int kKeyTextInput = 64;
inline constexpr int kKeyHankaku = 65;
inline constexpr int kKeyKanji = 66;
inline constexpr int kKeyKatakana = 67;
inline constexpr int kKeyCapsLock = 68;
inline constexpr uint32_t kModShift = 4 | 128 | 1024;  // SHIFT, LEFT_SHIFT, RIGHT_SHIFT
inline constexpr uint32_t kModKeyDown = 8;
inline constexpr uint32_t kModKeyUp = 16;
inline constexpr uint32_t kModCaps = 2048;

// session が「アプリへそのまま返した」キー（変換を通らない）。
struct EchoedKey {
  int special_key = 0;       // KeyEvent::special_key（なければ 0）
  uint32_t key_code = 0;     // KeyEvent::key_code（なければ 0）
  uint32_t modifiers = 0;    // KeyEventUtil::GetModifiers
  std::string_view key_string;
};

class RecentCommit {
 public:
  using Millis = int64_t;
  static constexpr size_t kMaxChars = 64;
  static constexpr Millis kDefaultLifetimeMs = 60 * 1000;

  explicit RecentCommit(Millis lifetime_ms = kDefaultLifetimeMs) : lifetime_ms_(lifetime_ms) {}

  // 確定した文字を足す（最後の kMaxChars 字だけ残る）。
  void Append(std::string_view text, Millis now) {
    Expire(now);
    if (text.empty()) return;
    text_.append(text);
    TrimToLastChars();
    last_ms_ = now;
  }

  // 覚えた最後の1字を消す。覚えた分がなくなったら（それより前に戻ったら）捨てる。
  void Backspace(Millis now) {
    Expire(now);
    if (text_.empty()) return;
    DropLastChar();
    last_ms_ = now;
  }

  void Clear() { text_.clear(); }

  // 入力欄の印（context の revision）。前と違えば捨てる。最初に見た値は覚えるだけ。
  void NoteRevision(int32_t revision) {
    if (has_revision_ && revision != revision_) Clear();
    has_revision_ = true;
    revision_ = revision;
  }

  // session がアプリへそのまま返したキーを見て、足す・消す・捨てる・何もしない。
  void NoteEchoedKey(const EchoedKey& key, Millis now) {
    if (key.modifiers & kModKeyUp) return;  // 離したときの知らせ（修飾キーだけ）。字は動かない
    const uint32_t others = key.modifiers & ~(kModShift | kModKeyDown | kModKeyUp | kModCaps);
    const bool has_key = key.special_key != 0 || key.key_code != 0;
    if (!has_key) return;  // 修飾キーだけ
    if (others != 0) {     // Ctrl・Alt つき（貼り付け・単語の削除など）。何が起きたか分からない
      Clear();
      return;
    }
    switch (key.special_key) {
      case 0:
        break;
      case kKeySpace:
        Append(" ", now);
        return;
      case kKeyBackspace:
        Backspace(now);
        return;
      case kKeyTextInput:
        AppendKeyString(key.key_string, now);
        return;
      case kKeyOn: case kKeyOff: case kKeyHenkan: case kKeyMuhenkan: case kKeyKana: case kKeyEisu:
      case kKeyHankaku: case kKeyKanji: case kKeyKatakana: case kKeyCapsLock:
        return;  // 入力の方式を替えるだけで、字もカーソルも動かない
      default:
        Clear();  // 矢印・Home・End・Enter・Tab・Delete・Escape など
        return;
    }
    if (key.key_code >= 0x20 && key.key_code < 0x7f) {
      const char c = static_cast<char>(key.key_code);
      Append(std::string_view(&c, 1), now);
      return;
    }
    AppendKeyString(key.key_string, now);
  }

  // 覚えている文字。時間が過ぎていれば空（内容は変えない）。
  std::string Text(Millis now) const {
    if (text_.empty() || Expired(now)) return std::string();
    return text_;
  }

  bool empty() const { return text_.empty(); }

 private:
  bool Expired(Millis now) const { return now - last_ms_ > lifetime_ms_ || now < last_ms_; }
  void Expire(Millis now) {
    if (!text_.empty() && Expired(now)) Clear();
  }

  // 制御文字の入らない（1字以上の）文字列だけを足す。それ以外は、何が入ったか分からないので捨てる。
  void AppendKeyString(std::string_view s, Millis now) {
    if (s.empty()) {
      Clear();
      return;
    }
    for (const char c : s) {
      if (static_cast<unsigned char>(c) < 0x20 || c == 0x7f) {
        Clear();
        return;
      }
    }
    Append(s, now);
  }

  static bool IsContinuation(char c) { return (static_cast<unsigned char>(c) & 0xC0) == 0x80; }

  void DropLastChar() {
    while (!text_.empty() && IsContinuation(text_.back())) text_.pop_back();
    if (!text_.empty()) text_.pop_back();
  }

  void TrimToLastChars() {
    size_t chars = 0;
    for (const char c : text_) chars += IsContinuation(c) ? 0 : 1;
    if (chars <= kMaxChars) return;
    size_t drop = chars - kMaxChars, pos = 0;
    while (drop > 0 && pos < text_.size()) {
      ++pos;
      while (pos < text_.size() && IsContinuation(text_[pos])) ++pos;
      --drop;
    }
    text_.erase(0, pos);
  }

  Millis lifetime_ms_;
  Millis last_ms_ = 0;
  std::string text_;
  bool has_revision_ = false;
  int32_t revision_ = 0;
};

// MYIME_ENGLISH_FOLLOW=off（直前の確定を見る仕組み全体）のとき false。MYIME_ENGLISH_FOLLOW_MEMORY=off なら、この記憶だけを止める
// （前の文・変換の履歴から取る道は残る。履歴の道が効かない理由を切り分ける試験用）。
inline bool RecentCommitEnabled() {
  static const bool enabled = [] {
    const char* all = std::getenv("MYIME_ENGLISH_FOLLOW");
    const char* memory = std::getenv("MYIME_ENGLISH_FOLLOW_MEMORY");
    return (all == nullptr || std::string_view(all) != "off") &&
           (memory == nullptr || std::string_view(memory) != "off");
  }();
  return enabled;
}

// 覚えておく時間（ミリ秒）。試験のためだけに MYIME_ENGLISH_FOLLOW_TTL_MS で替えられる（既定 60 秒）。
inline RecentCommit::Millis RecentLifetimeMs() {
  static const RecentCommit::Millis value = [] {
    const char* text = std::getenv("MYIME_ENGLISH_FOLLOW_TTL_MS");
    if (text == nullptr) return RecentCommit::kDefaultLifetimeMs;
    char* end = nullptr;
    const long long parsed = std::strtoll(text, &end, 10);
    return (end != text && *end == '\0' && parsed > 0) ? static_cast<RecentCommit::Millis>(parsed)
                                                       : RecentCommit::kDefaultLifetimeMs;
  }();
  return value;
}

inline RecentCommit::Millis SteadyNowMs() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

}  // namespace jaen

#endif  // JAEN_RECENT_COMMIT_H_
