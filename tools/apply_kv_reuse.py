"""打鍵をまたいで、問い（プロンプト）の共通の前半の KV キャッシュを使い回す。

  python tools/apply_kv_reuse.py <MyIME の src>

tools/apply_batch_score.py のあと、tools/apply_latency_profile.py の前に1回だけ動かす
（.github/workflows/linux-test.yml などが、この順で呼ぶ）。足すもの:

1. 問いの前半（前の文・読み・特別な語片の並び）だけを入れる列（promptPrefixSeqId）を
   ZenzContext に持つ。評価のたびに、その列の先頭から今回の語片と一致する長さまでを
   evalSeqId（列 0）へ写し、違う後ろだけを llama_decode する。問いの後ろ（候補の表記）は
   この列に入れないので、次の打鍵で読みが伸びても、前回の読みの KV をそのまま使える。
   評価の前に、この列の今回使わない後ろを消して容量を空ける（llama.cpp の KV は全列で
   512 語片を共有するため）。写す前にこの列のセルを全部消す（seq_cp は写す先を消さない
   ので、消さないと同じ位置に2つのセルができる）。
2. 評価の入り口（evaluationLogits）に「問いの語片の数」を渡せるようにし、jointLogProbability、
   選び手の suffixLogProbabilities、ZenzCandidateEvaluator から渡す。問いの境目が分かるので、
   候補の表記を問いの列に混ぜない。
3. MYIME_KV_REUSE=0 で、この使い回しを止めて今までと同じ動きに戻せる（比べる試験用）。
   止めたときは列も問いの記憶も触らないので、出力は変更前と1語片も変わらない。
4. 使い回した語片の数は、MYIME_PROFILE の <段>_tok / <段>_new（tools/apply_latency_profile.py）
   にそのまま出る。新しく計算した語片が減った分が、使い回しの割合になる。

並べ方は変えない。ZenzPromptBuilder の問いの形（条件・左の文脈・右の文脈・読み・出力の印）は
そのままで、読みが伸びる限り前半が共通になる。並べ替えによる出力の変化はない。
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


ctx = Z / "ZenzContext.swift"

# --- 1. 問いの前半を残す列と、止めるための環境変数 ---
edit(ctx, """    private let evalSeqId: llama_seq_id = 0
    private let inputPredictionSeqId: llama_seq_id = 1
""", """    private let evalSeqId: llama_seq_id = 0
    private let inputPredictionSeqId: llama_seq_id = 1
    /// 打鍵をまたいで残す問いの前半（前の文・読み・特別な語片）の列。
    /// 一括採点の列（treeSequenceBase..treeSequenceBase+treeMaxCandidates-1）の次を使う。
    private let promptPrefixSeqId: llama_seq_id = 18
    /// 問いの前半の語片（列 promptPrefixSeqId の中身と対応する）。
    private var prevPromptPrefix: [llama_token] = []
    /// MYIME_KV_REUSE=0 で、打鍵をまたぐ使い回しを止める（比べる試験用）。
    static let kvReuseEnabled: Bool = ProcessInfo.processInfo.environment["MYIME_KV_REUSE"] != "0"
""")

# 一括採点の列に、問いの前半の列（18）を足す。n_seq_max は列の「数」なので 19。
edit(ctx, "        ctx_params.n_seq_max = UInt32(Self.treeSequenceBase + Self.treeMaxCandidates)\n",
     "        ctx_params.n_seq_max = UInt32(Self.treeSequenceBase + Self.treeMaxCandidates + (Self.kvReuseEnabled ? 1 : 0))\n")

# 文脈を作り直したら、残した問いの前半も捨てる（新しい列には古い KV はない）。
edit(ctx, """        self.prevInputBySeq = [:]
        self.prevPromptBySeq = [:]
""", """        self.prevInputBySeq = [:]
        self.prevPromptBySeq = [:]
        self.prevPromptPrefix = []
""")

# --- 2. 評価の入り口に、問いの語片の数を足す ---
edit(ctx, "    private func getLogits(tokens: [llama_token], logits_start_index: Int = 0, seqId: llama_seq_id = 0) -> UnsafeMutablePointer<Float>? {\n",
     """    /// 列 promptPrefixSeqId を指定の長さまでに縮め、その先のセルを解放する。
    /// llama.cpp の KV は全列で 512 語片を共有するので、使わない古いセルを残すと評価に失敗する。
    private func trimPromptPrefix(to count: Int) {
        guard Self.kvReuseEnabled else { return }
        if count < self.prevPromptPrefix.count {
            llama_kv_cache_seq_rm(self.context, self.promptPrefixSeqId, llama_pos(count), -1)
            self.prevPromptPrefix = Array(self.prevPromptPrefix.prefix(count))
        }
    }

    private func getLogits(tokens: [llama_token], logits_start_index: Int = 0, seqId: llama_seq_id = 0, promptTokenCount: Int? = nil, retainPrompt: Bool = true) -> UnsafeMutablePointer<Float>? {
""")

# ほかの列（入力予測）から写したあと、問いの前半の列のほうが長く一致するなら、そちらから写す。
edit(ctx, """        // Manage KV cache: remove entries that differ from previous input
""", """        // 打鍵をまたいで残した問いの前半のほうが長く一致するなら、そこから写す。
        // 問いの後ろ（候補の表記）はこの列に入れていないので、読みが伸びても前回の読みまで使える。
        if Self.kvReuseEnabled, retainPrompt, seqId == self.evalSeqId, !self.prevPromptPrefix.isEmpty {
            let currentPrefix = effectivePrevInput.commonPrefix(with: tokens).count
            let promptPrefix = self.prevPromptPrefix.commonPrefix(with: tokens).count
            if promptPrefix > currentPrefix {
                let copiedPrefixCount = min(promptPrefix, logits_start_index)
                if copiedPrefixCount > 0 {
                    llama_kv_cache_seq_rm(context, seqId, 0, -1)
                    llama_kv_cache_seq_cp(context, self.promptPrefixSeqId, seqId, 0, llama_pos(copiedPrefixCount))
                    effectivePrevInput = self.prevPromptPrefix
                }
            }
        }

        // Manage KV cache: remove entries that differ from previous input
""")

# 評価の前に、この評価で使わない古い問いの後ろを列 18 から消す。llama.cpp の KV は全列で
# 512 語片を共有するので、残すと新しい問いと一括採点のセルが入らなくなる。
edit(ctx, """            prefixCacheCount = min(commonTokens.count, logits_start_index)
            llama_kv_cache_seq_rm(context, seqId, llama_pos(prefixCacheCount), -1)
            debug("new pos max:", llama_kv_cache_seq_pos_max(self.context, seqId), "commonTokens:", commonTokens.count)
""", """            prefixCacheCount = min(commonTokens.count, logits_start_index)
            llama_kv_cache_seq_rm(context, seqId, llama_pos(prefixCacheCount), -1)
            if Self.kvReuseEnabled, seqId == self.evalSeqId {
                if retainPrompt, promptTokenCount != nil {
                    // この評価で使わない古い問いの後ろを、評価の前に解放する。
                    // 問いの語片の数が分かる評価だけ、あとで列 18 を置き直せる。
                    let promptMatch = self.prevPromptPrefix.commonPrefix(with: tokens).count
                    self.trimPromptPrefix(to: min(prefixCacheCount, promptMatch))
                } else if !retainPrompt {
                    // 違う問い（前の文を外した問いなど）なので、残した問いは使わない。
                    // 容量を空けるために捨てる。
                    llama_kv_cache_seq_rm(context, self.promptPrefixSeqId, 0, -1)
                    self.prevPromptPrefix = []
                }
            }
            debug("new pos max:", llama_kv_cache_seq_pos_max(self.context, seqId), "commonTokens:", commonTokens.count)
""")

# 評価が済んだら、問いの前半だけを別の列に残す。問いが同じなら写さない（候補ごとの評価で増やさない）。
edit(ctx, """        // update cached input for next call (for KV cache management)
        self.prevInputBySeq[seqId] = tokens
        return llama_get_logits(context)
""", """        // update cached input for next call (for KV cache management)
        self.prevInputBySeq[seqId] = tokens
        if Self.kvReuseEnabled, retainPrompt, seqId == self.evalSeqId, let promptTokenCount,
           promptTokenCount > 0, promptTokenCount <= tokens.count {
            // 問いの前半だけを残す。次の打鍵では読みが伸びるので、前回の読みの KV がそのまま使える。
            let prompt = Array(tokens.prefix(promptTokenCount))
            let common = self.prevPromptPrefix.commonPrefix(with: prompt).count
            if common < prompt.count || common < self.prevPromptPrefix.count {
                // seq_cp は写す先の列を消さずに列の番号を足すだけなので、先にこの列の
                // セルを全部消す。消さないと同じ位置に2つのセルができる。
                llama_kv_cache_seq_rm(context, self.promptPrefixSeqId, 0, -1)
                llama_kv_cache_seq_cp(context, seqId, self.promptPrefixSeqId, 0, llama_pos(prompt.count))
                self.prevPromptPrefix = prompt
            }
        }
        return llama_get_logits(context)
""")

# 一括採点も llama_decode を直接呼ぶので、評価の前に列 18 の使わない後ろを消す。
# useEvalSequence が false の問い（前の文を外した問い）は、残した問いを使わないので全部消す。
edit(ctx, """        var newTokenCount = max(promptCount - reuse, 0)
""", """        if Self.kvReuseEnabled {
            if useEvalSequence {
                let promptMatch = self.prevPromptPrefix.commonPrefix(with: promptTokens).count
                self.trimPromptPrefix(to: min(reuse, promptMatch))
            } else {
                llama_kv_cache_seq_rm(self.context, self.promptPrefixSeqId, 0, -1)
                self.prevPromptPrefix = []
            }
        }
        var newTokenCount = max(promptCount - reuse, 0)
""")

edit(ctx, """    func evaluationLogits(tokens: [llama_token], startOffset: Int) -> UnsafeMutablePointer<Float>? {
        self.getLogits(tokens: tokens, logits_start_index: startOffset, seqId: evalSeqId)
    }
""", """    func evaluationLogits(tokens: [llama_token], startOffset: Int, promptTokenCount: Int? = nil, retainPrompt: Bool = true) -> UnsafeMutablePointer<Float>? {
        self.getLogits(
            tokens: tokens,
            logits_start_index: startOffset,
            seqId: evalSeqId,
            promptTokenCount: promptTokenCount,
            retainPrompt: retainPrompt
        )
    }
""")

# 問いの前半を残すかどうかを、全文の採点にも通す。
edit(ctx, """    func jointLogProbability(prompt: String, candidateText: String) -> Double? {
""", """    func jointLogProbability(prompt: String, candidateText: String, retainPrompt: Bool = true) -> Double? {
""")
edit(ctx, "        guard let logits = self.evaluationLogits(tokens: tokens, startOffset: startOffset) else { return nil }\n",
     "        guard let logits = self.evaluationLogits(\n"
     "            tokens: tokens,\n"
     "            startOffset: startOffset,\n"
     "            promptTokenCount: promptTokens.count,\n"
     "            retainPrompt: retainPrompt\n"
     "        ) else { return nil }\n")

# 選び手の文どうしの差の採点（tools/apply_selector_stage3.py が足したもの）
stage3 = """                  let logits = self.evaluationLogits(tokens: all, startOffset: startOffset) else {
"""
if ctx.read_bytes().decode("utf-8").count(stage3):
    edit(ctx, stage3,
         """                  let logits = self.evaluationLogits(tokens: all, startOffset: startOffset, promptTokenCount: promptTokens.count) else {
""")

# 一括採点の入り口にも「問いの前半を残すか」を通す。前の文を外した問い（priorPrompt）は残さない。
edit(ctx, """    func jointLogProbabilities(prompt: String, candidateTexts: [String], useEvalSequence: Bool = true) -> [Double]? {
        if let batched = self.batchedJointLogProbabilities(prompt: prompt, candidateTexts: candidateTexts, useEvalSequence: useEvalSequence) {
            return batched
        }
        var results: [Double] = []
        for text in candidateTexts {
            guard let score = self.jointLogProbability(prompt: prompt, candidateText: text) else { return nil }
            results.append(score)
        }
        return results
    }

    private func batchedJointLogProbabilities(prompt: String, candidateTexts: [String], useEvalSequence: Bool) -> [Double]? {
""", """    func jointLogProbabilities(
        prompt: String,
        candidateTexts: [String],
        useEvalSequence: Bool = true,
        retainPrompt: Bool = true
    ) -> [Double]? {
        if let batched = self.batchedJointLogProbabilities(
            prompt: prompt,
            candidateTexts: candidateTexts,
            useEvalSequence: useEvalSequence,
            retainPrompt: retainPrompt
        ) {
            return batched
        }
        var results: [Double] = []
        for text in candidateTexts {
            guard let score = self.jointLogProbability(prompt: prompt, candidateText: text, retainPrompt: retainPrompt) else { return nil }
            results.append(score)
        }
        return results
    }

    private func batchedJointLogProbabilities(
        prompt: String,
        candidateTexts: [String],
        useEvalSequence: Bool,
        retainPrompt: Bool
    ) -> [Double]? {
""")

edit(Z / "Zenz.swift", """                  let prior = context.jointLogProbabilities(prompt: priorPrompt, candidateTexts: texts, useEvalSequence: false) else { return nil }
""", """                  let prior = context.jointLogProbabilities(prompt: priorPrompt, candidateTexts: texts, useEvalSequence: false, retainPrompt: false) else { return nil }
""")

# 候補の評価（all_zenzai などの本体）。問いの境目をそのまま渡す。
edit(Z / "ZenzCandidateEvaluator.swift", """            guard let logits = context.evaluationLogits(
                tokens: evaluationTokens,
                startOffset: startOffset
            ) else {
""", """            guard let logits = context.evaluationLogits(
                tokens: evaluationTokens,
                startOffset: startOffset,
                promptTokenCount: promptTokens.count
            ) else {
""")

print("kv reuse ok")
