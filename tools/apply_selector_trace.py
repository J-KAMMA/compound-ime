"""選び手の段階2b: Zenzai が候補を確かめるときに計算した尤度を、追加の推論なしで記録する改造。

  python tools/apply_selector_trace.py <myime/src>

patches/myime-engine.patch と tools/apply_linux_engine_port.py を当てた後に動かす。
MYIME_SELECTOR_FEATURES が設定されているときだけ、Zenzai の候補の確かめ
（ZenzCandidateEvaluator.evaluate）で計算済みの各位置の次の語片の分布から、上位12個の語片と
その対数確率を、プロンプトと「それまでの語片の列」ごとに覚える（推論は増やさない。語彙を
1回なめるだけ）。変換エンジンの新しい入り口 GetSelectorTrace(文) が、その文をたどった
各位置の記録を返す。出力は変えない。読むのは tools/selector_stage2.py。

返す形: 位置ごとに「バイトの位置:選んだ番号:語片の16進,対数確率;語片の16進,対数確率;…」を空白でつなぐ。
"""
import sys
from pathlib import Path

src = Path(sys.argv[1])


def edit(path, old, new):
    p = src / path
    text = p.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected one match for {old[:60]!r}, found {text.count(old)}")
    p.write_text(text.replace(old, new), encoding="utf-8", newline="")


Z = "AzooKeyKanaKanjiConverter/Sources/KanaKanjiConverterModule/ConversionAlgorithms/Zenzai/Zenz"

(src / Z / "SelectorTrace.swift").write_text('''import Foundation

/// 選び手の段階2b（記録だけ）: Zenzai が候補を確かめるときに計算した次の語片の分布を覚える。
/// MYIME_SELECTOR_FEATURES が空でないときだけ動く。出力は変えない。
public enum SelectorTrace {
    public static let enabled: Bool = {
        guard let value = ProcessInfo.processInfo.environment["MYIME_SELECTOR_FEATURES"] else { return false }
        return !value.isEmpty
    }()
    static let topK = 12

    struct Row {
        var pieces: [[UInt8]]
        var logprobs: [Float]
    }

    private static let lock = NSLock()
    nonisolated(unsafe) private static var rows: [String: [[UInt8]: Row]] = [:]
    nonisolated(unsafe) private static var prompts: [String] = []

    /// logits は prefix の次の語片の分布（語彙の数だけ）。上位 topK 個と正規化した対数確率を覚える。
    static func record(
        prompt: String,
        prefix: [UInt8],
        logits: UnsafeMutablePointer<Float>,
        vocabSize: Int,
        piece: (Int) -> [UInt8]
    ) {
        var maxLogit = -Float.infinity
        for v in 0 ..< vocabSize {
            if logits[v] > maxLogit { maxLogit = logits[v] }
        }
        var sum: Float = 0
        var top: [(Int, Float)] = []
        for v in 0 ..< vocabSize {
            let l = logits[v]
            sum += expf(l - maxLogit)
            if top.count < topK || l > top[top.count - 1].1 {
                var at = top.count
                while at > 0 && top[at - 1].1 < l { at -= 1 }
                top.insert((v, l), at: at)
                if top.count > topK { top.removeLast() }
            }
        }
        let logZ = maxLogit + logf(sum)
        let row = Row(pieces: top.map { piece($0.0) }, logprobs: top.map { $0.1 - logZ })
        lock.lock()
        defer { lock.unlock() }
        if rows[prompt] == nil {
            prompts.append(prompt)
            if prompts.count > 8 { rows[prompts.removeFirst()] = nil }
            rows[prompt] = [:]
        }
        rows[prompt]![prefix] = row
    }

    private static func matches(_ piece: [UInt8], _ target: [UInt8], at: Int) -> Bool {
        for j in 0 ..< piece.count {
            if at + j >= target.count { return true }
            if piece[j] != target[at + j] { return false }
        }
        return true
    }

    private static func hex(_ bytes: [UInt8]) -> String {
        let digits = Array("0123456789abcdef")
        var out = ""
        for b in bytes {
            out.append(digits[Int(b >> 4)])
            out.append(digits[Int(b & 15)])
        }
        return out
    }

    /// text を、覚えた分布の中でたどる。最近のプロンプトのうち、最も長くたどれたものを返す。
    public static func trace(for text: String) -> String {
        let target = Array(text.utf8)
        lock.lock()
        defer { lock.unlock() }
        var best: [String] = []
        for prompt in prompts.reversed() {
            guard let table = rows[prompt] else { continue }
            var prefix: [UInt8] = []
            var out: [String] = []
            while prefix.count < target.count, let row = table[prefix] {
                var chosen = -1
                for (k, p) in row.pieces.enumerated() where !p.isEmpty && matches(p, target, at: prefix.count) {
                    let next = prefix + p
                    if table[next] != nil {
                        chosen = k
                        break
                    }
                    if next.count >= target.count && chosen < 0 { chosen = k }
                }
                guard chosen >= 0 else { break }
                let items = zip(row.pieces, row.logprobs).map { hex($0.0) + "," + String(($0.1 * 1000).rounded() / 1000) }
                out.append("\\(prefix.count):\\(chosen):" + items.joined(separator: ";"))
                prefix += row.pieces[chosen]
            }
            if out.count > best.count { best = out }
        }
        return best.joined(separator: " ")
    }
}
''', encoding="utf-8", newline="\n")

edit(Z + "/ZenzCandidateEvaluator.swift",
     """                let startIndex = (i - 1 - logitsStartIndex) * n_vocab
                let endIndex = startIndex + n_vocab
""",
     """                let startIndex = (i - 1 - logitsStartIndex) * n_vocab
                let endIndex = startIndex + n_vocab
                // 選び手の段階2b: 計算済みの分布を覚える（記録だけ。MYIME_SELECTOR_FEATURES のときだけ）
                if SelectorTrace.enabled {
                    SelectorTrace.record(
                        prompt: normalizedPrompt,
                        prefix: tokens[promptTokens.count ..< i].reduce(into: [UInt8]()) {
                            $0.append(contentsOf: context.tokenToPiece(token: $1).map { UInt8(bitPattern: $0) })
                        },
                        logits: logits + startIndex,
                        vocabSize: n_vocab,
                        piece: { context.tokenToPiece(token: llama_token($0)).map { UInt8(bitPattern: $0) } }
                    )
                }
""")

(src / "swift-engine/Sources/azookey-engine/SelectorTraceExport.swift").write_text('''import Foundation
import KanaKanjiConverterModuleWithDefaultDictionary

/// 選び手の段階2b（記録だけ）: text をたどった Zenzai の分布の記録（SelectorTrace.trace）。
@_cdecl("GetSelectorTrace")
public func getSelectorTrace(_ text: UnsafePointer<CChar>?) -> UnsafePointer<CChar>? {
    guard let text = text else { return nil }
    return UnsafePointer(_strdup(SelectorTrace.trace(for: String(cString: text))))
}
''', encoding="utf-8", newline="\n")

print("applied selector trace")
