"""前後の文での候補の並べ替え（contextPriorWinner）を「迷うときだけ」にする門を足す。

  python tools/apply_context_gate.py <MyIME の src>

tools/apply_latency_profile.py より前に、1回だけ動かす。
並べ替えは、前後の文がある変換で、候補ごとに人工知能の評価を2回（前後の文あり・なし）行うため重い。
先頭を替えるのは稀（測定では 5/145）なので、次の2つの門で評価を減らす。値は環境変数で上書きして比べられる。
  MYIME_CTX_TOPK=<数>: 並べ替える候補を先頭からこの個数までにする（0 なら絞らない）
  MYIME_CTX_GAP=<数>: 先頭と次の候補の点（value）の差がこの値より大きいときは並べ替えない（0 なら門なし）
  MYIME_CTX_LOG=<ファイル>: 並べ替えのたびに、候補の数・点の差・選んだ番号を1行ずつ書き足す（試験用）
既定値は ContextPriorGate.swift の defaultTopK（3）、defaultGap（8）。従来の動きに戻すには MYIME_CTX_TOPK=0 MYIME_CTX_GAP=0。
"""
import sys
from pathlib import Path

src = Path(sys.argv[1])  # MyIME の src
conv = src / "AzooKeyKanaKanjiConverter/Sources/KanaKanjiConverterModule"


def edit(path, old, new, count=1):
    # 改行の記号（LF か CRLF）は、ファイルによって違う。LF で探し、見つからなければ CRLF で探す
    text = path.read_bytes().decode("utf-8")
    for newline in ("\n", "\r\n"):
        o, n = old.replace("\n", newline), new.replace("\n", newline)
        if text.count(o) == count:
            path.write_bytes(text.replace(o, n).encode("utf-8"))
            return
    raise SystemExit(f"{path}: expected {count} match(es) for {old[:70]!r}, found {text.count(old)}")


(conv / "ConverterAPI/ContextPriorGate.swift").write_text('''import Foundation

/// 前後の文での候補の並べ替えを「迷うときだけ」にする門（tools/apply_context_gate.py）。
enum ContextPriorGate {
    /// 並べ替える候補を先頭からこの個数までにする。nil なら絞らない。
    /// 句の試験（tools/clause_gate_test.py、932 句）では 3 でも正解の数は変わらず、先頭を替える 15 回も残る。
    static let defaultTopK: Int? = 3
    /// 先頭と次の候補の点の差がこの値より大きいときは並べ替えない。nil なら門なし。
    /// 句の試験では 8 で並べ替えの呼び出しが 55% に減り、正解の数は変わらず、先頭を替えて正解になった句も残る（4 では 1 句を失う）。
    static let defaultGap: Double? = 8

    static let topK: Int? = {
        guard let text = ProcessInfo.processInfo.environment["MYIME_CTX_TOPK"], let value = Int(text) else { return defaultTopK }
        return value >= 2 ? value : nil
    }()

    static let maxGap: Double? = {
        guard let text = ProcessInfo.processInfo.environment["MYIME_CTX_GAP"], let value = Double(text) else { return defaultGap }
        return value > 0 ? value : nil
    }()

    private static let logPath: String? = {
        guard let path = ProcessInfo.processInfo.environment["MYIME_CTX_LOG"], !path.isEmpty else { return nil }
        return path
    }()

    private static let logLock = NSLock()

    /// 試験用の記録。MYIME_CTX_LOG があるときだけ書く。
    static func log(_ line: @autoclosure () -> String) {
        guard let path = logPath else { return }
        logLock.lock()
        defer { logLock.unlock() }
        guard let data = (line() + "\\n").data(using: .utf8) else { return }
        if let handle = FileHandle(forWritingAtPath: path) {
            handle.seekToEndOfFile()
            handle.write(data)
            handle.closeFile()
        } else {
            FileManager.default.createFile(atPath: path, contents: data)
        }
    }
}
''', encoding="utf-8", newline="\n")

kk = conv / "ConverterAPI/KanaKanjiConverter.swift"
edit(kk, """        guard eligible.count > 1,
              let winner = model.contextPriorWinner(input: reading, candidates: eligible.map { candidates[$0] }, contextualMode: contextualMode),
              winner > 0, winner < eligible.count else { return candidates }
""", """        guard eligible.count > 1 else { return candidates }
        // 迷うときだけ並べ替える: 候補を先頭から数個に絞り、先頭が次の候補を大きく引き離しているときは何もしない
        let gateCount = eligible.count
        if let limit = ContextPriorGate.topK, eligible.count > limit { eligible = Array(eligible.prefix(limit)) }
        let gateGap = abs(Double(candidates[eligible[0]].value) - Double(candidates[eligible[1]].value))
        if let maxGap = ContextPriorGate.maxGap, gateGap > maxGap { return candidates }
        let gateWinner = model.contextPriorWinner(input: reading, candidates: eligible.map { candidates[$0] }, contextualMode: contextualMode)
        ContextPriorGate.log("ctx\\tcount=\\(gateCount)\\tused=\\(eligible.count)\\tgap=\\(gateGap)\\twinner=\\(gateWinner.map { "\\($0)" } ?? "nil")")
        guard let winner = gateWinner, winner > 0, winner < eligible.count else { return candidates }
""")
