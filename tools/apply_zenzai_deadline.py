"""人工知能（Zenzai）の時間の上限と、重みのメモリ固定を、変換エンジン（Swift）に足す。

  python tools/apply_zenzai_deadline.py <MyIME の src>

patches/myime-engine.patch を当てたあとの作業ツリーに、1回だけ実行する
（tools/apply_jaen_integration.py が呼ぶ）。足すもの:

1. 変換1回あたりの人工知能の時間の上限（ZenzaiDeadline）。人工知能を使い始めてから
   上限を過ぎたら、それ以上の評価をやめ、そこまでの結果（人工知能なしの変換結果）を返す。
   llama.cpp の計算の途中でも、中断の関数（abort callback）で打ち切る。
   上限は SetZenzaiTimeLimit（ミリ秒、0 で無制限）で決める。既定は 1000。
2. 重みの読み込みで use_mlock を指定し、メモリに固定する（SetZenzaiMemoryLock、既定は有効）。
   固定できなくても（ウィンドウズの VirtualLock の上限など）読み込みは続く。結果は
   ZenzaiMemoryLock.status と GetZenzaiStatus の memoryLock に出し、標準エラーにも1行書く。
   標準エラーへは ZenzaiMemoryLock.writeStandardError で書く（標準エラーのない処理でも落ちない）。
   FileHandle.standardError.write(_:) は使わない（書けないと try! で落ちる。1.144 の不具合）。
3. 試験用: 環境変数 MYIME_ZENZAI_STATS_FILE があれば、変換のたびに「<値>.<処理番号>」へ
   上限に当たった回数などを書く。
"""
import sys
from pathlib import Path

src = Path(sys.argv[1])  # MyIME の src
conv = src / "AzooKeyKanaKanjiConverter/Sources/KanaKanjiConverterModule"
engine = src / "swift-engine/Sources/azookey-engine"


def edit(path, old, new, count=1):
    # 改行の記号（LF か CRLF）は、ファイルによって違う（作業ツリーにより、1つのファイルに両方あることもある）。
    # LF で探し、見つからなければ CRLF で探す
    text = path.read_bytes().decode("utf-8")
    for newline in ("\n", "\r\n"):
        o, n = old.replace("\n", newline), new.replace("\n", newline)
        if text.count(o) == count:
            path.write_bytes(text.replace(o, n).encode("utf-8"))
            return
    raise SystemExit(f"{path}: expected {count} match(es) for {old[:70]!r}, found {text.count(old)}")


def write(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")


# --- 1. 時間の上限と、メモリ固定の状態（llama.cpp の型を使わない部分） ---
write(conv / "ConversionAlgorithms/Zenzai/Zenz/ZenzaiDeadline.swift", '''import Dispatch
import Foundation
#if os(Windows)
import CRT
#endif

/// 変換1回あたりの人工知能（Zenzai）の時間の上限。
///
/// `begin` で上限（ミリ秒）を決め、人工知能を最初に使うとき（`isExpired` の最初の呼び出し）から
/// 数え始める。辞書の読み込みなど、人工知能より前の時間は数えない。過ぎたら `isExpired` が
/// true になり、評価をやめて、そこまでの結果を返す。変換は engineLock の中で1つずつ
/// 行われるので、状態は1つだけ持つ。
public enum ZenzaiDeadline {
    nonisolated(unsafe) private static var limitNanos: UInt64 = 0
    nonisolated(unsafe) private static var endNanos: UInt64 = 0
    nonisolated(unsafe) private static var callStartNanos: UInt64 = 0
    nonisolated(unsafe) private static var active = false
    nonisolated(unsafe) private static var hitInCurrent = false
    nonisolated(unsafe) public private(set) static var conversions = 0
    /// 上限に当たった変換の数（上限を過ぎてから、人工知能を使おうとした変換）。
    nonisolated(unsafe) public private(set) static var hits = 0
    /// 計算の途中で打ち切った評価の数。
    nonisolated(unsafe) public private(set) static var aborts = 0
    /// 評価に入る前に、上限を過ぎていたので見送った数。
    nonisolated(unsafe) public private(set) static var skips = 0
    nonisolated(unsafe) public private(set) static var totalMilliseconds = 0
    nonisolated(unsafe) public private(set) static var maxMilliseconds = 0

    private static func nowNanos() -> UInt64 {
        DispatchTime.now().uptimeNanoseconds
    }

    /// 変換の前に呼ぶ。`milliseconds` が 0 以下なら上限なし。
    public static func begin(milliseconds: Int) {
        self.conversions += 1
        self.hitInCurrent = false
        self.callStartNanos = self.nowNanos()
        self.active = milliseconds > 0
        self.limitNanos = UInt64(min(max(milliseconds, 0), 600_000)) &* 1_000_000
        self.endNanos = 0
    }

    /// 変換のあとに呼ぶ。
    public static func end() {
        if self.hitInCurrent {
            self.hits += 1
        }
        let elapsed = Int((self.nowNanos() &- self.callStartNanos) / 1_000_000)
        self.totalMilliseconds += elapsed
        self.maxMilliseconds = max(self.maxMilliseconds, elapsed)
        self.active = false
        self.endNanos = 0
    }

    /// 上限を過ぎたか。最初の呼び出しで時計を動かし始める。
    static func isExpired() -> Bool {
        guard self.active else {
            return false
        }
        let now = self.nowNanos()
        if self.endNanos == 0 {
            self.endNanos = now &+ self.limitNanos
            return false
        }
        if now >= self.endNanos {
            self.hitInCurrent = true
            return true
        }
        return false
    }

    static func noteAbort() {
        self.aborts += 1
    }

    static func noteSkip() {
        self.skips += 1
    }

    /// 試験の集計用の1行。
    public static var summary: String {
        "conversions=\\(self.conversions) hits=\\(self.hits) aborts=\\(self.aborts) skips=\\(self.skips) "
            + "total_ms=\\(self.totalMilliseconds) max_ms=\\(self.maxMilliseconds)"
    }
}

/// 重みのメモリ固定（llama.cpp の use_mlock）の状態。
///
/// 固定できなくても読み込みは続く（llama.cpp が警告を出すだけ）。その警告を見て、
/// 固定できたかどうかを `status` に残す。
public enum ZenzaiMemoryLock {
    /// 固定を頼むか。モデルを読む前に決める。
    nonisolated(unsafe) public static var requested = true
    /// "pending"（まだ読んでいない）、"off"、"locked"、"failed: ..." のどれか。
    nonisolated(unsafe) public private(set) static var status = "pending"
    nonisolated(unsafe) private static var failure: String?

    static func beginLoad() {
        self.failure = nil
    }

    /// 読み込み中の llama.cpp の記録を見る。
    static func observe(_ message: String) {
        guard self.requested, self.failure == nil else {
            return
        }
        for marker in ["failed to mlock", "VirtualLock", "WorkingSetSize", "mlock not supported"]
        where message.contains(marker) {
            self.failure = message.trimmingCharacters(in: .whitespacesAndNewlines)
                .replacingOccurrences(of: "\\n", with: " ")
            return
        }
    }

    static func finishLoad(modelBytes: Int) {
        let megabytes = modelBytes / 1_048_576
        if !self.requested {
            self.status = "off"
        } else if let failure = self.failure {
            self.status = "failed: \\(failure)"
        } else {
            self.status = "locked"
        }
        self.writeStandardError("[zenzai] memory lock: \\(self.status) (model \\(megabytes) MB)\\n")
    }

    /// 標準エラーへ書く。書けなくても何もしない。
    ///
    /// ウィンドウズの変換エンジン（mozc_server.exe、画面だけの処理）には標準エラーがない。
    /// FileHandle.standardError.write(_:) は中で try! を使うので、書けないと処理ごと落ちる
    /// （1.144 で、人工知能の重みを読み込むたびに変換エンジンが落ち、打っていた文が消えた）。
    /// ウィンドウズでは llama.cpp の既定の記録と同じく C の関数で書き（1.143 まで落ちなかった書き方）、
    /// ほかでは書けなかった誤りを握りつぶす。
    static func writeStandardError(_ text: String) {
        #if os(Windows)
        _ = fputs(text, stderr)
        #else
        try? FileHandle.standardError.write(contentsOf: Data(text.utf8))
        #endif
    }
}
''')

# --- 2. llama.cpp との接続（ZenzContext.swift） ---
zc = conv / "ConversionAlgorithms/Zenzai/Zenz/ZenzContext.swift"

# 重みの読み込み: メモリ固定を頼む（Vulkan から CPU に戻す読み直しの2か所とも）
edit(zc, "modelParams.use_mmap = true\n", """modelParams.use_mmap = true
        #if Zenzai || ZenzaiCPU
        modelParams.use_mlock = ZenzaiMemoryLock.requested
        #endif
""", count=2)
# 読み込みの前後で、llama.cpp の記録（固定できなかった警告）を見る
edit(zc, """        var modelParams = llama_model_default_params()
""", """        #if Zenzai || ZenzaiCPU
        ZenzaiMemoryLock.beginLoad()
        llama_log_set({ _, text, _ in
            guard let text else {
                return
            }
            let message = String(cString: text)
            ZenzaiMemoryLock.observe(message)
            // 標準の動作（標準エラーへ出す）を保つ。標準エラーがなくても落ちない書き方で
            ZenzaiMemoryLock.writeStandardError(message)
        }, nil)
        #endif
        var modelParams = llama_model_default_params()
""")
edit(zc, """        #endif
        guard let model = loadedModel else {
            debug("Could not load model at \\(path)")""", """        #endif
        #if Zenzai || ZenzaiCPU
        llama_log_set(nil, nil)
        if let loadedModel {
            ZenzaiMemoryLock.finishLoad(modelBytes: Int(llama_model_size(loadedModel)))
        }
        #endif
        guard let model = loadedModel else {
            debug("Could not load model at \\(path)")""")

# 計算の途中の打ち切り
edit(zc, """    private static var ctx_params: llama_context_params {
""", """    /// 上限（ZenzaiDeadline）を過ぎたら、llama.cpp の計算を途中でやめさせる。
    private static func installAbortCallback(_ context: OpaquePointer) {
        #if Zenzai || ZenzaiCPU
        llama_set_abort_callback(context, { _ in ZenzaiDeadline.isExpired() }, nil)
        #endif
    }

    private static var ctx_params: llama_context_params {
""")
edit(zc, """        self.context = context
        self.batch = llama_batch_init(512, 0, 1)
    }
""", """        self.context = context
        self.batch = llama_batch_init(512, 0, 1)
        Self.installAbortCallback(context)
    }
""")
edit(zc, """        self.context = context
        self.prevInputBySeq = [:]
""", """        self.context = context
        Self.installAbortCallback(context)
        self.prevInputBySeq = [:]
""")
edit(zc, """    private func getLogits(tokens: [llama_token], logits_start_index: Int = 0, seqId: llama_seq_id = 0) -> UnsafeMutablePointer<Float>? {
""", """    private func getLogits(tokens: [llama_token], logits_start_index: Int = 0, seqId: llama_seq_id = 0) -> UnsafeMutablePointer<Float>? {
        if ZenzaiDeadline.isExpired() {
            // 上限を過ぎたので、人工知能を使わない（呼び出し側は評価できなかったものとして扱う）
            ZenzaiDeadline.noteSkip()
            debug("Zenzai deadline passed; evaluation skipped")
            return nil
        }
""")
edit(zc, """        if llama_decode(context, self.batch) != 0 {
            debug("llama_decode() failed")
            return nil
        }
""", """        let decodeStatus = llama_decode(context, self.batch)
        if decodeStatus != 0 {
            debug("llama_decode() failed")
            if decodeStatus == 2 {
                // 上限で計算を打ち切った。途中までの計算を残さないよう、この列の記憶を捨てる
                ZenzaiDeadline.noteAbort()
                llama_kv_cache_seq_rm(context, seqId, 0, -1)
                self.prevInputBySeq.removeValue(forKey: seqId)
            }
            return nil
        }
""")

# --- 3. 変換の組み立て（zenzai.swift）: 上限を過ぎたら、評価をやめて、そこまでの結果を返す ---
edit(conv / "ConversionAlgorithms/Zenzai/zenzai.swift", """                if inferenceLimit == 0 {
                    debug("inference limit! \\(candidate.text) is used for excuse")""", """                if inferenceLimit == 0 || ZenzaiDeadline.isExpired() {
                    debug("inference limit or deadline! \\(candidate.text) is used for excuse")""")

# --- 4. DLL の入り口（AzookeyEngine.swift） ---
write(engine / "ZenzaiDeadlineSupport.swift", '''import Foundation
import KanaKanjiConverterModuleWithDefaultDictionary

/// 試験用: 環境変数 MYIME_ZENZAI_STATS_FILE があれば、その名前に処理番号を付けたファイルへ、
/// 上限に当たった回数などを書く（処理ごとに別のファイル。呼び出しのたびに上書きする）。
nonisolated(unsafe) private let zenzaiStatsPath: String? = {
    guard let value = ProcessInfo.processInfo.environment["MYIME_ZENZAI_STATS_FILE"], !value.isEmpty else {
        return nil
    }
    return value + "." + String(ProcessInfo.processInfo.processIdentifier)
}()

/// 変換の終わりに呼ぶ（engineLock を持ったまま）。
func finishZenzaiDeadline() {
    ZenzaiDeadline.end()
    if let path = zenzaiStatsPath {
        try? ZenzaiDeadline.summary.write(toFile: path, atomically: false, encoding: .utf8)
    }
}
''')
ae = engine / "AzookeyEngine.swift"
edit(ae, "    var zenzaiInferenceLimit: Int = 10\n", """    var zenzaiInferenceLimit: Int = 10
    /// 変換1回あたりの人工知能の時間の上限（ミリ秒）。0 で上限なし。
    var zenzaiTimeLimitMs: Int = 1000
""")
edit(ae, """@_cdecl("SetZenzaiWeightPath")""", """@_cdecl("SetZenzaiTimeLimit")
public func setZenzaiTimeLimit(_ milliseconds: Int32) {
    engineLock.lock()
    defer { engineLock.unlock() }
    config.zenzaiTimeLimitMs = max(0, Int(milliseconds))
}

@_cdecl("SetZenzaiMemoryLock")
public func setZenzaiMemoryLock(_ enabled: Bool) {
    engineLock.lock()
    defer { engineLock.unlock() }
    ZenzaiMemoryLock.requested = enabled
}

@_cdecl("SetZenzaiWeightPath")""")
# 変換の入り口: 単発の変換、旧来の2つ
edit(ae, """    conv.stopComposition()
    let result = conv.requestCandidates(text, options: options)""", """    conv.stopComposition()
    ZenzaiDeadline.begin(milliseconds: config.zenzaiTimeLimitMs)
    defer { finishZenzaiDeadline() }
    let result = conv.requestCandidates(text, options: options)""")
edit(ae, """    guard let conv = converter else { return nil }

    let result = conv.requestCandidates(composingText, options: getOptions())
    currentCandidates = result.mainResults
    currentTypoCandidates = []

    // Return best candidate""", """    guard let conv = converter else { return nil }

    ZenzaiDeadline.begin(milliseconds: config.zenzaiTimeLimitMs)
    defer { finishZenzaiDeadline() }
    let result = conv.requestCandidates(composingText, options: getOptions())
    currentCandidates = result.mainResults
    currentTypoCandidates = []

    // Return best candidate""")
edit(ae, """    guard let conv = converter else { return nil }

    let result = conv.requestCandidates(composingText, options: getOptions())
    currentCandidates = result.mainResults
    currentTypoCandidates = []

    return candidatesJson()""", """    guard let conv = converter else { return nil }

    ZenzaiDeadline.begin(milliseconds: config.zenzaiTimeLimitMs)
    defer { finishZenzaiDeadline() }
    let result = conv.requestCandidates(composingText, options: getOptions())
    currentCandidates = result.mainResults
    currentTypoCandidates = []

    return candidatesJson()""")
# 状態の問い合わせ
edit(ae, """        "inferenceLimit": config.zenzaiInferenceLimit,
""", """        "inferenceLimit": config.zenzaiInferenceLimit,
        "timeLimitMs": config.zenzaiTimeLimitMs,
        "memoryLock": ZenzaiMemoryLock.status,
        "deadlineConversions": ZenzaiDeadline.conversions,
        "deadlineHits": ZenzaiDeadline.hits,
        "deadlineAborts": ZenzaiDeadline.aborts,
        "deadlineSkips": ZenzaiDeadline.skips,
""")
# 選び手の採点（ScoreSentences）も、変換と同じ上限で囲む。上限に当たったら採点は nan になる（選び手が働かないだけ）
edit(ae, """    let scores = conv.selectorSentenceScores(""", """    ZenzaiDeadline.begin(milliseconds: config.zenzaiTimeLimitMs)
    defer { finishZenzaiDeadline() }
    let scores = conv.selectorSentenceScores(""")
print("zenzai deadline ok")
