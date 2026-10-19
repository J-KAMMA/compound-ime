"""Zenz の候補の採点（前後の文での並べ替えと選び手）を、候補を全部まとめた1回の評価にする。

  python tools/apply_batch_score.py <MyIME の src>

tools/apply_selector_stage3.py（選び手の採点 suffixLogProbabilities）と tools/apply_zenzai_deadline.py
（時間の上限）と tools/apply_context_gate.py の後、tools/apply_latency_profile.py の前に、1回だけ動かす。

今の採点は、候補ごとに llama.cpp の評価（llama_decode）を1回ずつ行う。並べ替え（contextPriorWinner）は
前の文あり・なしの2組を順に、選び手は表記ごとに順に評価する。これを、候補の語片を「木」にして
1回の評価にまとめる（jev_score.cpp の測定では、候補8つで順より45%、32で60%速い）。

  - 候補どうしで同じ語片の並びは、木の1つの節にして1回だけ計算する。節には、その節を通る候補の列の番号を
    全部付ける（llama.cpp の1つの語片に複数の列を持たせる。KV の1つの場所を、複数の列が共有する）。
  - 問い（プロンプト）の語片は、すべての候補の列に属させて1回だけ計算する。ふつうの評価の列 0 に残っている
    問いの前半の KV は、そのまま使い回す（今の採点と同じ）。評価のあと、列 0 には問いだけが残る
    （今は問いと最後の候補が残る。次の評価は共通の前半だけを使うので、結果は変わらない）。
  - 候補の列の番号は 2 から（0 と 1 は、ふつうの評価と入力予測が使う）。評価のたびに最後に空にする。
  - 評価できない（候補が多い、語片が多すぎる、時間の上限、llama.cpp の失敗）ときは、何もなかったことにして
    今までの順の採点に戻る。時間の上限は今までと同じ ZenzaiDeadline で見る（中断の関数も効く）。
  - 点の作り方は今と同じ: 各行を倍精度で log-softmax し、同じ順に足す。文の終わりの語片は今まで通り
    llama_vocab_eos（変えると出力が変わる）。
  - MYIME_BATCH_SCORE=0 で一括採点を切り、今までの順の採点に戻せる（速さと出力を比べる試験用）。
  - MYIME_CTX_LOG があれば、一括採点のたびに1行（候補の数・問いの語片・使い回した語片・節の数・評価の結果）を
    書く（試験用。tools/apply_context_gate.py の記録の仕組みを使う）。
"""
import sys
from pathlib import Path

src = Path(sys.argv[1])  # MyIME の src
Z = src / "AzooKeyKanaKanjiConverter/Sources/KanaKanjiConverterModule/ConversionAlgorithms/Zenzai/Zenz"


def edit(path, old, new, count=1):
    # 改行の記号（LF か CRLF）は、ファイルによって違う。LF で探し、見つからなければ CRLF で探す
    text = path.read_bytes().decode("utf-8")
    for newline in ("\n", "\r\n"):
        o, n = old.replace("\n", newline), new.replace("\n", newline)
        if text.count(o) == count:
            path.write_bytes(text.replace(o, n).encode("utf-8"))
            return
    raise SystemExit(f"{path}: expected {count} match(es) for {old[:70]!r}, found {text.count(old)}")


ctxfile = Z / "ZenzContext.swift"

# --- 1. 列の数（木の列の分を足す）と、木用の入れ物 ---
edit(ctxfile, "    private var batch: llama_batch\n", "    private var batch: llama_batch\n    /// 一括採点用の入れ物（1つの語片に複数の列を付けられる）\n    private var treeBatch: llama_batch\n")
edit(ctxfile, "        self.batch = llama_batch_init(512, 0, 1)\n",
     "        self.batch = llama_batch_init(512, 0, 1)\n        self.treeBatch = llama_batch_init(512, 0, Int32(Self.treeSequenceBase + Self.treeMaxCandidates))\n")
edit(ctxfile, "        llama_batch_free(self.batch)\n", "        llama_batch_free(self.batch)\n        llama_batch_free(self.treeBatch)\n")
edit(ctxfile, "        ctx_params.n_ubatch = 64\n",
     "        ctx_params.n_ubatch = 64\n        // 一括採点で、候補ごとの列（番号 treeSequenceBase から）を使うための列の数\n"
     "        ctx_params.n_seq_max = UInt32(Self.treeSequenceBase + Self.treeMaxCandidates)\n")

# --- 2. 一括採点の本体 ---
edit(ctxfile, "    func decodeTokens(_ tokens: [llama_token]) -> String {\n", r'''    // MARK: 候補をまとめて1回の評価で採点する（tools/apply_batch_score.py）

    /// 一括採点で使う列の番号の始まり（0 と 1 は、ふつうの評価と入力予測が使う）。
    static let treeSequenceBase = 2
    /// 一括採点できる候補の数の上限。これより多いときは順に採点する。
    static let treeMaxCandidates = 16
    /// 一括採点で新しく計算する語片の数の上限（評価の入れ物は 512 語片）。
    private static let treeMaxNewTokens = 448
    /// MYIME_BATCH_SCORE=0 で一括採点を切り、順の採点に戻す（比べる試験用）。
    static let batchScoreEnabled: Bool = ProcessInfo.processInfo.environment["MYIME_BATCH_SCORE"] != "0"

    private struct TreeNode {
        let token: llama_token
        let parent: Int
        let depth: Int
        var candidates: [Int]
    }

    private func checkedTokens(_ text: String, addBOS: Bool) -> [llama_token]? {
        let vocab = self.vocabSize
        let bytes = text.utf8.count
        var tokens = [llama_token](repeating: 0, count: bytes + 1)
        let count = text.withCString { pointer in
            tokens.withUnsafeMutableBufferPointer { buffer in
                llama_tokenize(self.sharedModel.vocab, pointer, Int32(bytes), buffer.baseAddress, Int32(buffer.count), addBOS, false)
            }
        }
        guard count > 0, Int(count) <= tokens.count else { return nil }
        let result = Array(tokens.prefix(Int(count)))
        guard result.allSatisfy({ $0 >= 0 && Int($0) < vocab }) else { return nil }
        return result
    }

    /// 同じ問いの下の複数の候補を、llama.cpp の1回の評価で採点する。
    /// 戻り値は候補ごとの「共通の前半（common 語片）より後ろの各語片の対数確率と、最後の文の終わりの対数確率」の列。
    /// 評価できないときは nil（呼び出し側は順に採点する形に戻る。その前に、列 0 などの状態は元に戻してある）。
    private func treeLogProbabilities(
        promptTokens: [llama_token],
        candidates: [[llama_token]],
        common: Int,
        eos: llama_token,
        vocab: Int
    ) -> [[Double]]? {
        let count = candidates.count
        guard Self.batchScoreEnabled, (2...Self.treeMaxCandidates).contains(count), !promptTokens.isEmpty,
              common >= 0, common <= (candidates.map { $0.count }.min() ?? 0) else { return nil }
        let promptCount = promptTokens.count
        for tokens in candidates where promptCount + tokens.count > Int(self.n_len) { return nil }
        if ZenzaiDeadline.isExpired() {
            // 上限を過ぎたので、人工知能を使わない（呼び出し側は順の採点に戻り、そこでも評価できなかったものとして扱う）
            ZenzaiDeadline.noteSkip()
            return nil
        }
        // 候補の語片の木（同じ並びは1つの節）
        var nodes: [TreeNode] = []
        var childIndex: [Int64: Int] = [:]
        var paths: [[Int]] = []
        for (candidateIndex, tokens) in candidates.enumerated() {
            var parent = -1
            var path: [Int] = []
            path.reserveCapacity(tokens.count)
            for (depth, token) in tokens.enumerated() {
                let key = (Int64(parent + 1) << 32) | Int64(UInt32(bitPattern: token))
                let id: Int
                if let existing = childIndex[key] {
                    id = existing
                } else {
                    id = nodes.count
                    nodes.append(TreeNode(token: token, parent: parent, depth: depth, candidates: []))
                    childIndex[key] = id
                }
                nodes[id].candidates.append(candidateIndex)
                path.append(id)
                parent = id
            }
            paths.append(path)
        }
        // 列 0 に残っている問いの前半は使い回す（最後の語片は、確率の元になるので計算し直す）
        let previous = self.prevInputBySeq[self.evalSeqId] ?? []
        let reuse = min(previous.commonPrefix(with: promptTokens).count, promptCount - 1)
        let newTokenCount = promptCount - reuse + nodes.count
        guard newTokenCount <= Self.treeMaxNewTokens else {
            ContextPriorGate.log("batch\tcandidates=\(count)\tprompt=\(promptCount)\treuse=\(reuse)\tnodes=\(nodes.count)\tresult=too_many_tokens")
            return nil
        }
        let treeSequences: [llama_seq_id] = (0..<count).map { llama_seq_id(Self.treeSequenceBase + $0) }
        defer {
            for sequence in treeSequences { llama_kv_cache_seq_rm(self.context, sequence, 0, -1) }
        }
        // 列 0 を問いの共通の前半までにして、候補の列へ写す（KV は共有されるので、コピーは起きない）
        llama_kv_cache_seq_rm(self.context, self.evalSeqId, llama_pos(reuse), -1)
        self.prevInputBySeq[self.evalSeqId] = Array(previous.prefix(reuse))
        self.prevPromptBySeq.removeValue(forKey: self.evalSeqId)
        for sequence in treeSequences { llama_kv_cache_seq_cp(self.context, self.evalSeqId, sequence, 0, llama_pos(reuse)) }

        self.treeBatch.n_tokens = 0
        let promptSequences = [self.evalSeqId] + treeSequences
        for index in reuse..<promptCount {
            self.llama_batch_add(&self.treeBatch, promptTokens[index], Int32(index), promptSequences, logits: common == 0 && index == promptCount - 1)
        }
        let base = Int(self.treeBatch.n_tokens)
        for node in nodes {
            self.llama_batch_add(
                &self.treeBatch, node.token, Int32(promptCount + node.depth),
                node.candidates.map { treeSequences[$0] },
                logits: node.depth >= common - 1
            )
        }
        let treeDecodeStatus = llama_decode(context, self.treeBatch)
        guard treeDecodeStatus == 0 else {
            if treeDecodeStatus == 2 {
                // 上限で計算を打ち切った
                ZenzaiDeadline.noteAbort()
            }
            ContextPriorGate.log("batch\tcandidates=\(count)\tprompt=\(promptCount)\treuse=\(reuse)\tnodes=\(nodes.count)\tresult=decode_\(treeDecodeStatus)")
            // 途中までの計算を残さない
            llama_kv_cache_seq_rm(self.context, self.evalSeqId, 0, -1)
            self.prevInputBySeq.removeValue(forKey: self.evalSeqId)
            self.prevPromptBySeq.removeValue(forKey: self.evalSeqId)
            return nil
        }

        // 各行の最大値と指数の和の対数（今の採点と同じ倍精度の計算）。同じ行は1回だけ計算する
        struct Row {
            let pointer: UnsafeMutablePointer<Float>
            let maxValue: Double
            let logSumExp: Double
        }
        var rows: [Int: Row] = [:]
        func row(at index: Int) -> Row? {
            if let cached = rows[index] { return cached }
            guard let pointer = llama_get_logits_ith(self.context, Int32(index)) else { return nil }
            let buffer = UnsafeBufferPointer(start: pointer, count: vocab)
            guard buffer.allSatisfy({ $0.isFinite }), let maximum = buffer.max() else { return nil }
            let maxValue = Double(maximum)
            let sumExp = buffer.reduce(0.0) { $0 + exp(Double($1) - maxValue) }
            guard sumExp.isFinite, sumExp > 0 else { return nil }
            let made = Row(pointer: pointer, maxValue: maxValue, logSumExp: log(sumExp))
            rows[index] = made
            return made
        }
        var nodeValues: [Int: Double] = [:]
        var endValues: [Int: Double] = [:]
        var results: [[Double]] = []
        results.reserveCapacity(count)
        var failed = false
        for (candidateIndex, tokens) in candidates.enumerated() {
            let path = paths[candidateIndex]
            var values: [Double] = []
            values.reserveCapacity(tokens.count - common + 1)
            for depth in common..<tokens.count {
                let id = path[depth]
                if let cached = nodeValues[id] {
                    values.append(cached)
                    continue
                }
                let parent = nodes[id].parent
                guard let parentRow = row(at: parent < 0 ? base - 1 : base + parent) else { failed = true; break }
                let value = Double(parentRow.pointer[Int(tokens[depth])]) - parentRow.maxValue - parentRow.logSumExp
                guard value.isFinite else { failed = true; break }
                nodeValues[id] = value
                values.append(value)
            }
            if failed { break }
            let last = path[path.count - 1]
            if let cached = endValues[last] {
                values.append(cached)
            } else {
                guard let lastRow = row(at: base + last) else { failed = true; break }
                let value = Double(lastRow.pointer[Int(eos)]) - lastRow.maxValue - lastRow.logSumExp
                guard value.isFinite else { failed = true; break }
                endValues[last] = value
                values.append(value)
            }
            results.append(values)
        }
        guard !failed else {
            ContextPriorGate.log("batch\tcandidates=\(count)\tprompt=\(promptCount)\treuse=\(reuse)\tnodes=\(nodes.count)\tresult=bad_logits")
            llama_kv_cache_seq_rm(self.context, self.evalSeqId, 0, -1)
            self.prevInputBySeq.removeValue(forKey: self.evalSeqId)
            self.prevPromptBySeq.removeValue(forKey: self.evalSeqId)
            return nil
        }
        // 列 0 には問いだけが残る（問いの後ろの語片の列は、defer で空にする）
        self.prevInputBySeq[self.evalSeqId] = promptTokens
        ContextPriorGate.log("batch\tcandidates=\(count)\tprompt=\(promptCount)\treuse=\(reuse)\tnodes=\(nodes.count)\tresult=ok")
        return results
    }

    /// contextPriorWinner 用: 同じ問いの下の複数の候補の、文全体の対数確率（文の終わりを含む）。
    /// 一括で評価できないときは、今まで通り候補を順に評価する。どれかが評価できなければ nil。
    func jointLogProbabilities(prompt: String, candidateTexts: [String]) -> [Double]? {
        if let batched = self.batchedJointLogProbabilities(prompt: prompt, candidateTexts: candidateTexts) {
            return batched
        }
        var results: [Double] = []
        for text in candidateTexts {
            guard let score = self.jointLogProbability(prompt: prompt, candidateText: text) else { return nil }
            results.append(score)
        }
        return results
    }

    private func batchedJointLogProbabilities(prompt: String, candidateTexts: [String]) -> [Double]? {
        guard Self.batchScoreEnabled, (2...Self.treeMaxCandidates).contains(candidateTexts.count) else { return nil }
        let normalizedPrompt = self.normalizeForModel(prompt)
        let vocab = self.vocabSize
        let eos = self.eosToken
        guard (1...1_000_000).contains(vocab), eos >= 0, Int(eos) < vocab,
              !normalizedPrompt.isEmpty, !normalizedPrompt.contains("\0"), normalizedPrompt.utf8.count <= 16_384,
              let promptTokens = self.checkedTokens(normalizedPrompt, addBOS: true), promptTokens.count <= 512 else { return nil }
        var candidates: [[llama_token]] = []
        for text in candidateTexts {
            let normalized = self.normalizeForModel(text)
            guard !normalized.isEmpty, !normalized.contains("\0"), normalized.utf8.count <= 1024,
                  let tokens = self.checkedTokens(normalized, addBOS: false), tokens.count <= 512 else { return nil }
            candidates.append(tokens)
        }
        guard let logProbabilities = self.treeLogProbabilities(
            promptTokens: promptTokens, candidates: candidates, common: 0, eos: eos, vocab: vocab
        ) else { return nil }
        var totals: [Double] = []
        for values in logProbabilities {
            var total = 0.0
            for value in values { total += value }
            guard total.isFinite else {
                llama_kv_cache_seq_rm(self.context, self.evalSeqId, 0, -1)
                self.prevInputBySeq.removeValue(forKey: self.evalSeqId)
                self.prevPromptBySeq.removeValue(forKey: self.evalSeqId)
                return nil
            }
            totals.append(total)
        }
        self.setPreviousEvaluationPrompt(normalizedPrompt)
        return totals
    }

    func decodeTokens(_ tokens: [llama_token]) -> String {
''')

# --- 3. 選び手の採点（suffixLogProbabilities）を一括にする ---
edit(ctxfile, "        var results: [Double?] = []\n        for tokens in candidates {\n", r'''        if let logProbabilities = self.treeLogProbabilities(
            promptTokens: promptTokens, candidates: candidates, common: common, eos: eos, vocab: vocab
        ) {
            self.setPreviousEvaluationPrompt(normalizedPrompt)
            return logProbabilities.map { values -> Double? in
                var total = 0.0
                for value in values { total += value }
                return total.isFinite ? total : nil
            }
        }
        var results: [Double?] = []
        for tokens in candidates {
''')

# --- 4. 前後の文での並べ替え（contextPriorWinner）の採点を一括にする ---
edit(Z / "Zenz.swift", """            var contextual: [Double] = []
            var prior: [Double] = []
            for text in texts {
                guard let score = context.jointLogProbability(prompt: contextualPrompt, candidateText: text) else { return nil }
                contextual.append(score)
            }
            for text in texts {
                guard let score = context.jointLogProbability(prompt: priorPrompt, candidateText: text) else { return nil }
                prior.append(score)
            }
""", """            guard let contextual = context.jointLogProbabilities(prompt: contextualPrompt, candidateTexts: texts),
                  let prior = context.jointLogProbabilities(prompt: priorPrompt, candidateTexts: texts) else { return nil }
""")

# --- 5. 人工知能なしの組み立て（llama.cpp の見せかけ）の追加分 ---
mock = Z / "llama-mock.swift"
edit(mock, "package func llama_get_logits(_: llama_context) -> UnsafeMutablePointer<Float>? { unimplemented() }\n",
     "package func llama_get_logits(_: llama_context) -> UnsafeMutablePointer<Float>? { unimplemented() }\n"
     "package func llama_get_logits_ith(_: llama_context, _: Int32) -> UnsafeMutablePointer<Float>? { unimplemented() }\n")
print("batch score ok")
