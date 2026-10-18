"""変換1回の時間を段ごとに測る仕組みを足す（測るだけ。普段は何もしない）。

  python tools/apply_latency_profile.py <mozc/src> <MyIME の src>

tools/apply_jaen_integration.py、tools/apply_selector_stage3.py（それが呼ぶ人工知能の時間の上限も含む）の
あとに、1回だけ動かす。環境変数 MYIME_PROFILE=<ファイル> のときだけ、変換エンジンの入り口
（engine.cc の MozcWithAzooKeyConverter::ConvertWithContext）ごとに1行を書き足す。
MYIME_PROFILE がなければ、時計を読むことも書くこともしない（変換の結果は変わらない）。

1行は「名前=値」を tab で区切った形（読み方は tools/latency_report.py）:
  kind: conv（空白キーの変換）、pred（打っている途中の予測）、other、between（入り口と入り口の間の裏の仕事）
  total_us: 入り口の全体、mozc_us: Mozc の変換、dll_us/dll_n: 人工知能側の変換エンジンの呼び出し（時間と回数）、
  sel_cpp_us: 選び手（C++ の処理と、その中の人工知能の採点）、key_chars/left_chars/right_chars: 読みと前後の文の字数、
  segs: Mozc の変換のあとの文節の数、t0_us/t1_us: 入り口の始まりと終わりの時計の値
  （TIMED_KEY の TIMED_US と同じ時計）
  以下は変換エンジン（Swift）の記録。段は allz（all_zenzai）、ctx（contextPriorWinner）、sel（選び手の採点）、
  proc（候補作り processResult。ctx を含む）、tpass（打ち間違いの補正の探索。中の段は数えない）、
  typo（人工知能による打ち間違いの補正）、other（ほかの人工知能の使い道）。
  MYIME_PROFILE_THREADS=<数> を足すと、llama.cpp のスレッド数をその値にして比べられる。
    call_n/call_us: 変換エンジンの入り口の回数と時間
    <段>_n/<段>_us: その段に入った回数と時間
    <段>_dec_n/<段>_dec_us: そのうち llama.cpp の評価（llama_decode）の回数と時間
    <段>_tok/<段>_new: 評価に渡した語片の全部と、前の計算を使い回せずに新しく計算した語片

変換エンジン（Swift）は MYIME_PROFILE があるときだけ記録し、ProfileTake で取り出して空にする。
"""
import sys
from pathlib import Path

mozc = Path(sys.argv[1])  # Mozc の src
src = Path(sys.argv[2])  # MyIME の src
conv = src / "AzooKeyKanaKanjiConverter/Sources/KanaKanjiConverterModule"
engine = src / "swift-engine/Sources/azookey-engine"


def edit(path, old, new, count=1):
    # 改行の記号（LF か CRLF）は、ファイルによって違う。LF で探し、見つからなければ CRLF で探す
    text = path.read_bytes().decode("utf-8")
    for newline in ("\n", "\r\n"):
        o, n = old.replace("\n", newline), new.replace("\n", newline)
        if text.count(o) == count:
            path.write_bytes(text.replace(o, n).encode("utf-8"))
            return
    raise SystemExit(f"{path}: expected {count} match(es) for {old[:70]!r}, found {text.count(old)}")


def write(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")


# ---- Swift: 段ごとの記録 ----
write(conv / "ConversionAlgorithms/Zenzai/Zenz/ZenzaiProfile.swift", '''import Dispatch
import Foundation

/// 変換1回の時間を段ごとに測る記録（試験用）。環境変数 MYIME_PROFILE があるときだけ動く。
///
/// 段に入るとき `enter`、出るとき `leave` を呼ぶ。llama.cpp の評価（llama_decode）は、そのときの段に数える。
/// 数えた値は `take` で取り出して空にする（変換エンジンの入り口 ProfileTake から、C++ 側が変換のたびに呼ぶ）。
/// 変換は engineLock の中で1つずつ行われるが、裏の先回りの変換と重なっても数えられるよう、小さな鍵で守る。
public enum ZenzaiProfile {
    public enum Stage: Int {
        case other = 0, allZenzai, contextPrior, selector, typo, process, typoPass
    }

    public struct Token {
        let previous: Int
        let start: UInt64
        let skip: Bool
    }

    /// 試験用: 環境変数 MYIME_PROFILE_THREADS があれば、llama.cpp のスレッド数をその値にする
    /// （MYIME_PROFILE があるときだけ。測るときの比べ用で、普段は使わない）。
    public static let threadOverride: Int? = {
        guard let profile = ProcessInfo.processInfo.environment["MYIME_PROFILE"], !profile.isEmpty,
              let value = ProcessInfo.processInfo.environment["MYIME_PROFILE_THREADS"],
              let count = Int(value), (1...64).contains(count) else {
            return nil
        }
        return count
    }()

    static let enabled: Bool = {
        guard let value = ProcessInfo.processInfo.environment["MYIME_PROFILE"] else {
            return false
        }
        return !value.isEmpty
    }()

    private static let names = ["other", "allz", "ctx", "sel", "typo", "proc", "tpass"]
    private static let lock = NSLock()
    nonisolated(unsafe) private static var current = 0
    nonisolated(unsafe) private static var stageNanos = [Int](repeating: 0, count: 7)
    nonisolated(unsafe) private static var stageCalls = [Int](repeating: 0, count: 7)
    nonisolated(unsafe) private static var decodeCalls = [Int](repeating: 0, count: 7)
    nonisolated(unsafe) private static var decodeNanos = [Int](repeating: 0, count: 7)
    nonisolated(unsafe) private static var tokensAll = [Int](repeating: 0, count: 7)
    nonisolated(unsafe) private static var tokensNew = [Int](repeating: 0, count: 7)
    nonisolated(unsafe) private static var callCount = 0
    nonisolated(unsafe) private static var contextChanged = 0
    nonisolated(unsafe) private static var callNanos = 0
    nonisolated(unsafe) private static var callStart: UInt64 = 0

    private static func now() -> UInt64 {
        DispatchTime.now().uptimeNanoseconds
    }

    public static func enter(_ stage: Stage) -> Token {
        guard self.enabled else {
            return Token(previous: 0, start: 0, skip: true)
        }
        self.lock.lock()
        defer { self.lock.unlock() }
        // 打ち間違いの探索（typoPass）の中の段は、探索の時間に含めて数える（二重に数えない）
        if self.current == Stage.typoPass.rawValue {
            return Token(previous: 0, start: 0, skip: true)
        }
        let token = Token(previous: self.current, start: self.now(), skip: false)
        self.current = stage.rawValue
        return token
    }

    public static func leave(_ token: Token) {
        guard self.enabled, !token.skip else {
            return
        }
        self.lock.lock()
        defer { self.lock.unlock() }
        let stage = self.current
        self.stageNanos[stage] += Int(self.now() &- token.start)
        self.stageCalls[stage] += 1
        self.current = token.previous
    }

    /// llama_decode の前に呼ぶ。`newTokens` は今回新しく計算する語片、`totalTokens` は渡した語片の全部。
    static func decodeBegin(newTokens: Int, totalTokens: Int) -> UInt64 {
        guard self.enabled else {
            return 0
        }
        self.lock.lock()
        defer { self.lock.unlock() }
        self.tokensNew[self.current] += newTokens
        self.tokensAll[self.current] += totalTokens
        return self.now()
    }

    static func decodeEnd(_ start: UInt64) {
        guard self.enabled, start != 0 else {
            return
        }
        self.lock.lock()
        defer { self.lock.unlock() }
        self.decodeCalls[self.current] += 1
        self.decodeNanos[self.current] += Int(self.now() &- start)
    }

    /// 前後の文での並べ替えが、先頭の候補を替えたか（替えなかった並べ替えは、時間だけかかったことになる）。
    static func noteContextOutcome(changed: Bool) {
        guard self.enabled, changed else {
            return
        }
        self.lock.lock()
        defer { self.lock.unlock() }
        self.contextChanged += 1
    }

    /// 変換エンジンの入り口の始まりと終わり（ZenzaiDeadline.begin/end から呼ぶ）。
    public static func callBegin() {
        guard self.enabled else {
            return
        }
        self.lock.lock()
        defer { self.lock.unlock() }
        self.callStart = self.now()
    }

    public static func callEnd() {
        guard self.enabled else {
            return
        }
        self.lock.lock()
        defer { self.lock.unlock() }
        if self.callStart != 0 {
            self.callNanos += Int(self.now() &- self.callStart)
            self.callCount += 1
            self.callStart = 0
        }
    }

    /// これまでの記録を「名前=値」を空白で区切った1行にして返し、空にする。MYIME_PROFILE がなければ空の文字列。
    public static func take() -> String {
        guard self.enabled else {
            return ""
        }
        self.lock.lock()
        defer { self.lock.unlock() }
        var parts = ["call_n=\\(self.callCount)", "call_us=\\(self.callNanos / 1000)"]
        for (index, name) in self.names.enumerated() {
            parts.append("\\(name)_n=\\(self.stageCalls[index])")
            parts.append("\\(name)_us=\\(self.stageNanos[index] / 1000)")
            parts.append("\\(name)_dec_n=\\(self.decodeCalls[index])")
            parts.append("\\(name)_dec_us=\\(self.decodeNanos[index] / 1000)")
            parts.append("\\(name)_tok=\\(self.tokensAll[index])")
            parts.append("\\(name)_new=\\(self.tokensNew[index])")
        }
        parts.append("ctx_changed=\\(self.contextChanged)")
        self.contextChanged = 0
        self.callCount = 0
        self.callNanos = 0
        for index in 0..<7 {
            self.stageNanos[index] = 0
            self.stageCalls[index] = 0
            self.decodeCalls[index] = 0
            self.decodeNanos[index] = 0
            self.tokensAll[index] = 0
            self.tokensNew[index] = 0
        }
        return parts.joined(separator: " ")
    }
}
''')

# 入り口の始まりと終わり
deadline = conv / "ConversionAlgorithms/Zenzai/Zenz/ZenzaiDeadline.swift"
edit(deadline, "        self.conversions += 1\n", "        self.conversions += 1\n        ZenzaiProfile.callBegin()\n")
edit(deadline, "    public static func end() {\n", "    public static func end() {\n        ZenzaiProfile.callEnd()\n")

# 全文の変換（all_zenzai）
kk = conv / "ConverterAPI/KanaKanjiConverter.swift"
# 候補作り（processResult。前後の文での並べ替えはこの中）
edit(kk, "        return self.processResult(inputData: inputData, result: result, options: options)\n",
     "        let profileProcessToken = ZenzaiProfile.enter(.process)\n        defer { ZenzaiProfile.leave(profileProcessToken) }\n"
     "        return self.processResult(inputData: inputData, result: result, options: options)\n")
edit(kk, "            let (result, nodes, cache) = self.converter.all_zenzai(\n",
     "            let profileToken = ZenzaiProfile.enter(.allZenzai)\n            let (result, nodes, cache) = self.converter.all_zenzai(\n")
edit(kk, """            self.updateCurrentSessionState {
                $0.previousInputData = inputData
                $0.zenzaiCache = cache
            }
            return (result, nodes)""", """            ZenzaiProfile.leave(profileToken)
            self.updateCurrentSessionState {
                $0.previousInputData = inputData
                $0.zenzaiCache = cache
            }
            return (result, nodes)""")

Z = conv / "ConversionAlgorithms/Zenzai/Zenz"
# 前後の文での並べ替えが先頭の候補を替えたかの記録（動きは同じ。winner を一度受けてから同じ条件で判定する）
edit(kk, """        guard eligible.count > 1,
              let winner = model.contextPriorWinner(input: reading, candidates: eligible.map { candidates[$0] }, contextualMode: contextualMode),
              winner > 0, winner < eligible.count else { return candidates }
""", """        guard eligible.count > 1 else { return candidates }
        let profileWinner = model.contextPriorWinner(input: reading, candidates: eligible.map { candidates[$0] }, contextualMode: contextualMode)
        ZenzaiProfile.noteContextOutcome(changed: (profileWinner ?? 0) > 0)
        guard let winner = profileWinner, winner > 0, winner < eligible.count else { return candidates }
""")
# 前後の文を使った候補の並べ替え
edit(Z / "Zenz.swift", "            guard !self.useGpu, let context = self.zenzContext, (2...16).contains(candidates.count) else { return nil }\n",
     "            guard !self.useGpu, let context = self.zenzContext, (2...16).contains(candidates.count) else { return nil }\n"
     "            let profileToken = ZenzaiProfile.enter(.contextPrior)\n            defer { ZenzaiProfile.leave(profileToken) }\n")
# 選び手の採点
edit(Z / "Zenz.swift", """    func selectorSuffixScores(reading: String, texts: [String], contextualMode: ConvertRequestOptions.ZenzaiV3DependentMode) -> [Double?] {
        self.inferenceLock.withLock { () -> [Double?] in
""", """    func selectorSuffixScores(reading: String, texts: [String], contextualMode: ConvertRequestOptions.ZenzaiV3DependentMode) -> [Double?] {
        self.inferenceLock.withLock { () -> [Double?] in
            let profileToken = ZenzaiProfile.enter(.selector)
            defer { ZenzaiProfile.leave(profileToken) }
""")
# 打ち間違いの補正
edit(Z / "Zenz.swift", "            return ZenzaiTypoCandidateGenerator.generate(\n",
     "            let profileToken = ZenzaiProfile.enter(.typo)\n            defer { ZenzaiProfile.leave(profileToken) }\n"
     "            return ZenzaiTypoCandidateGenerator.generate(\n")
# llama.cpp の評価
edit(Z / "ZenzContext.swift", "        let decodeStatus = llama_decode(context, self.batch)\n",
     "        let profileDecodeStart = ZenzaiProfile.decodeBegin(newTokens: Int(self.batch.n_tokens), totalTokens: tokens.count)\n"
     "        let decodeStatus = llama_decode(context, self.batch)\n        ZenzaiProfile.decodeEnd(profileDecodeStart)\n")

# 打ち間違いの補正の探索（別の変換器で読みを何通りも変換する。人工知能を使う設定もここに含まれる）
edit(engine / "TypoCorrectionPass.swift",
     "func makeTypoCandidates(for key: String, existingCandidates: [Candidate]) -> [TypoCandidate] {\n",
     "func makeTypoCandidates(for key: String, existingCandidates: [Candidate]) -> [TypoCandidate] {\n"
     "    let profileToken = ZenzaiProfile.enter(.typoPass)\n    defer { ZenzaiProfile.leave(profileToken) }\n")

# llama.cpp のスレッド数を比べるための上書き（MYIME_PROFILE と MYIME_PROFILE_THREADS の両方があるときだけ）
edit(Z / "ZenzContext.swift", "        let n_threads = self.inferenceThreadCount\n",
     "        let n_threads = ZenzaiProfile.threadOverride ?? self.inferenceThreadCount\n")

# 変換エンジンの入り口: 記録の取り出し
edit(engine / "AzookeyEngine.swift", '@_cdecl("FreeString")\n', '''/// 試験用: 段ごとの時間の記録を取り出して空にする（MYIME_PROFILE がなければ空の文字列）。engineLock は取らない。
@_cdecl("ProfileTake")
public func profileTake() -> UnsafePointer<CChar>? {
    UnsafePointer(_strdup(ZenzaiProfile.take()))
}

@_cdecl("FreeString")
''')

# ---- C++: 変換エンジンの読み込みと、1行の書き出し ----
A = "converter/azookey_immutable_converter.cc"
cc = mozc / A
edit(cc, "  using ScoreSentenceSuffixesFunc = const char* (*)(const char*, const char*, const char*, const char*);\n",
     "  using ScoreSentenceSuffixesFunc = const char* (*)(const char*, const char*, const char*, const char*);\n"
     "  using ProfileTakeFunc = const char* (*)();\n")
edit(cc, "  ScoreSentenceSuffixesFunc ScoreSentenceSuffixes = nullptr;\n",
     "  ScoreSentenceSuffixesFunc ScoreSentenceSuffixes = nullptr;\n  ProfileTakeFunc ProfileTake = nullptr;\n")
edit(cc, """    ScoreSentenceSuffixes = reinterpret_cast<ScoreSentenceSuffixesFunc>(
        GetProcAddress(dll_handle_, "ScoreSentenceSuffixes"));
""", """    ScoreSentenceSuffixes = reinterpret_cast<ScoreSentenceSuffixesFunc>(
        GetProcAddress(dll_handle_, "ScoreSentenceSuffixes"));
    ProfileTake = reinterpret_cast<ProfileTakeFunc>(
        GetProcAddress(dll_handle_, "ProfileTake"));
""")
edit(cc, "    MYIME_LOAD(ScoreSentenceSuffixes);\n", "    MYIME_LOAD(ScoreSentenceSuffixes);\n    MYIME_LOAD(ProfileTake);\n")
edit(cc, "    ScoreSentenceSuffixes = nullptr;\n", "    ScoreSentenceSuffixes = nullptr;\n    ProfileTake = nullptr;\n")
edit(cc, "#include <mutex>\n", "#include <atomic>\n#include <chrono>\n#include <mutex>\n")

# 人工知能側の変換エンジンの呼び出しの時間
edit(cc, """      const char* candidates_json = loader.ConvertTextWithContext
          ? loader.ConvertTextWithContext(key.c_str(), left.c_str(), right.c_str(), allow_learning)
          : loader.ConvertText(key.c_str(), allow_learning);
""", """      const int64_t profile_start = latency_profile::Start();
      const char* candidates_json = loader.ConvertTextWithContext
          ? loader.ConvertTextWithContext(key.c_str(), left.c_str(), right.c_str(), allow_learning)
          : loader.ConvertText(key.c_str(), allow_learning);
      latency_profile::AddSince(latency_profile::kDll, profile_start);
      latency_profile::AddCount(latency_profile::kDllCalls);
""")

PROFILE_CC = r'''namespace latency_profile {
namespace {
std::atomic<int64_t> g_counters[kCounterCount];
std::mutex g_frame_mutex;  // 入り口の入れ子の深さと、ファイルへの書き出しを守る
int g_depth = 0;

const char* ProfilePath() {
  static const char* path = [] {
    const char* value = std::getenv("MYIME_PROFILE");
    return value != nullptr && value[0] != '\0' ? value : nullptr;
  }();
  return path;
}

std::string TakeEngineProfile() {
  auto& loader = AzooKeyDllLoader::GetInstance();
  if (!loader.IsLoaded() || !loader.ProfileTake || !loader.FreeString) return "";
  const char* text = loader.ProfileTake();
  if (text == nullptr) return "";
  std::string result(text);
  loader.FreeString(text);
  return result;
}

int64_t TakeCounter(Counter counter) { return g_counters[counter].exchange(0); }

std::string CounterFields() {
  std::string out;
  out += "\tmozc_us=" + std::to_string(TakeCounter(kMozc));
  out += "\tdll_us=" + std::to_string(TakeCounter(kDll));
  out += "\tdll_n=" + std::to_string(TakeCounter(kDllCalls));
  out += "\tsel_cpp_us=" + std::to_string(TakeCounter(kSelector));
  out += "\tsegs=" + std::to_string(TakeCounter(kSegments));
  return out;
}

void AppendLine(const std::string& line) {
  if (FILE* f = std::fopen(ProfilePath(), "ab")) {
    std::fwrite(line.data(), 1, line.size(), f);
    std::fclose(f);
  }
}

std::string EngineFields(const std::string& engine) {
  std::string out;
  for (char c : engine) out += c == ' ' ? '\t' : c;
  return out;
}
}  // namespace

bool Enabled() { return ProfilePath() != nullptr; }

void Set(Counter counter, int64_t value) {
  if (Enabled()) g_counters[counter] = value;
}

int64_t Start() {
  if (!Enabled()) return 0;
  return std::chrono::duration_cast<std::chrono::microseconds>(
             std::chrono::steady_clock::now().time_since_epoch()).count();
}

void AddSince(Counter counter, int64_t start) {
  if (start == 0) return;
  g_counters[counter] += Start() - start;
}

void AddCount(Counter counter) {
  if (Enabled()) g_counters[counter] += 1;
}

Frame::Frame(const char* kind, size_t key_chars, size_t left_chars, size_t right_chars)
    : kind_(kind), key_chars_(key_chars), left_chars_(left_chars), right_chars_(right_chars) {
  if (!Enabled()) return;
  std::lock_guard<std::mutex> lock(g_frame_mutex);
  counted_ = true;
  if (g_depth++ > 0) return;  // 入れ子の内側は書かない
  outermost_ = true;
  // 前の入り口のあとからここまでの裏の仕事（打っている間の先回りの変換など）
  const std::string engine = TakeEngineProfile();
  const bool idle = g_counters[kDllCalls].load() == 0 && engine.rfind("call_n=0 ", 0) == 0;
  std::string line = "kind=between\tpid=" + std::to_string(static_cast<long>(getpid())) + CounterFields();
  line += "\t" + EngineFields(engine) + "\n";
  if (!idle) AppendLine(line);
  start_ = Start();
}

Frame::~Frame() {
  if (!counted_) return;
  std::lock_guard<std::mutex> lock(g_frame_mutex);
  --g_depth;
  if (!outermost_) return;
  const int64_t total = Start() - start_;
  const std::string engine = TakeEngineProfile();
  std::string line = std::string("kind=") + kind_ + "\tpid=" + std::to_string(static_cast<long>(getpid())) +
                     "\ttotal_us=" + std::to_string(total) + "\tt0_us=" + std::to_string(start_) +
                     "\tt1_us=" + std::to_string(start_ + total) + CounterFields() +
                     "\tkey_chars=" + std::to_string(key_chars_) + "\tleft_chars=" + std::to_string(left_chars_) +
                     "\tright_chars=" + std::to_string(right_chars_);
  line += "\t" + EngineFields(engine) + "\n";
  AppendLine(line);
}

Scope::Scope(Counter counter) : counter_(counter), start_(Start()) {}
Scope::~Scope() { AddSince(counter_, start_); }
}  // namespace latency_profile

'''
edit(cc, "bool SelectorTraceForText(absl::string_view text, std::string* trace) {\n",
     PROFILE_CC + "bool SelectorTraceForText(absl::string_view text, std::string* trace) {\n")
# getpid
edit(cc, "#include <dlfcn.h>\n", "#include <dlfcn.h>\n#include <unistd.h>\n")

hdr = mozc / "converter/azookey_immutable_converter.h"
edit(hdr, "#include <memory>\n#include <string>\n", "#include <cstddef>\n#include <cstdint>\n#include <memory>\n#include <string>\n")
edit(hdr, "[[nodiscard]] bool SelectorTraceForText(absl::string_view text, std::string* trace);\n",
     "[[nodiscard]] bool SelectorTraceForText(absl::string_view text, std::string* trace);\n\n"
     '''// 変換1回の時間を段ごとに測る（試験用）。環境変数 MYIME_PROFILE=<ファイル> のときだけ動き、なければ何もしない。
// 入り口（Frame）ごとに1行を書く。tools/apply_latency_profile.py の説明を参照。
namespace latency_profile {
enum Counter { kMozc = 0, kDll, kDllCalls, kSelector, kSegments, kCounterCount };
bool Enabled();
// 値を置く（kSegments: Mozc の変換のあとの文節の数）。
void Set(Counter counter, int64_t value);
// 時計の値（マイクロ秒）。MYIME_PROFILE がなければ 0。
int64_t Start();
// Start() から今までの時間を加える（start が 0 なら何もしない）。
void AddSince(Counter counter, int64_t start);
void AddCount(Counter counter);

class Frame {
 public:
  Frame(const char* kind, size_t key_chars, size_t left_chars, size_t right_chars);
  ~Frame();
  Frame(const Frame&) = delete;
  Frame& operator=(const Frame&) = delete;

 private:
  const char* kind_;
  size_t key_chars_, left_chars_, right_chars_;
  bool counted_ = false;
  bool outermost_ = false;
  int64_t start_ = 0;
};

class Scope {
 public:
  explicit Scope(Counter counter);
  ~Scope();
  Scope(const Scope&) = delete;
  Scope& operator=(const Scope&) = delete;

 private:
  Counter counter_;
  int64_t start_;
};
}  // namespace latency_profile
''')

# ---- C++: 変換エンジンの入り口 ----
E = mozc / "engine/engine.cc"
edit(E, """  bool ConvertWithContext(const ConversionOptions& options, Segments* segments,
                          std::string_view left_context,
                          std::string_view right_context) const override {
    if (!segments || !mozc_->Convert(options, segments)) return false;
""", """  bool ConvertWithContext(const ConversionOptions& options, Segments* segments,
                          std::string_view left_context,
                          std::string_view right_context) const override {
    // 時間を測る入り口（MYIME_PROFILE があるときだけ。なければ何もしない）
    size_t profile_key_chars = 0;
    if (latency_profile::Enabled() && segments) {
      for (const auto& segment : segments->conversion_segments()) profile_key_chars += Util::CharsLen(segment.key());
    }
    latency_profile::Frame profile_frame(
        options.used_in_predictor_realtime_conversion ? "pred"
            : options.request_type == RequestType::CONVERSION ? "conv" : "other",
        profile_key_chars, latency_profile::Enabled() ? Util::CharsLen(left_context) : 0,
        latency_profile::Enabled() ? Util::CharsLen(right_context) : 0);
    return ConvertWithContextUnprofiled(options, segments, left_context, right_context);
  }

  bool ConvertWithContextUnprofiled(const ConversionOptions& options, Segments* segments,
                                    std::string_view left_context,
                                    std::string_view right_context) const {
    if (!segments) return false;
    {
      latency_profile::Scope profile_mozc(latency_profile::kMozc);
      if (!mozc_->Convert(options, segments)) return false;
    }
    latency_profile::Set(latency_profile::kSegments, segments->conversion_segments_size());
""")
edit(E, "    ApplySelector(segments, left_context, right_context);\n",
     "    {\n      latency_profile::Scope profile_selector(latency_profile::kSelector);\n"
     "      ApplySelector(segments, left_context, right_context);\n    }\n")
# 試験の道具: TIMED_KEY の始まりと終わりの時計の値（Frame の t0_us/t1_us と同じ時計）も書く
edit(mozc / "session/session_handler_tool.cc",
     "    MOZC_ASSERT_TRUE(client_->SendKey(key_event, last_output_.get()));\n    std::cout << \"ELAPSED \"",
     "    MOZC_ASSERT_TRUE(client_->SendKey(key_event, last_output_.get()));\n"
     "    std::cout << \"TIMED_US \" << std::chrono::duration_cast<std::chrono::microseconds>(start.time_since_epoch()).count()\n"
     "              << \" \" << std::chrono::duration_cast<std::chrono::microseconds>(\n"
     "                     std::chrono::steady_clock::now().time_since_epoch()).count() << std::endl;\n"
     "    std::cout << \"ELAPSED \"")
print("latency profile ok")
