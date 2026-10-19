"""選び手の段階3: 学習した小さな選び手を変換エンジンに組み込む。

  python tools/apply_selector_stage3.py <mozc/src> <myime/src> [重み.json]

tools/apply_jaen_integration.py（段階1・2の記録を含む）と tools/apply_selector_trace.py の後に動かす。
変換の最後に、文節ごとに次を行う（MYIME_SELECTOR=0 で切る）。
  1. Zenz を使わない軽い選び手（門）で、1位と違う表記の候補（上位8つのうち先の2つまで）を見る。
     確からしさの最大が門のしきい値（0.07、weights.json の gate_threshold）未満の文節は何もしない。
  2. 門を通った文節だけ、1位と2つの表記で文全体を作り（ほかの文節は1位のまま）、Zenz で採点し直す。
     採点は文どうしの差だけを見るので、全部の文に共通する前半（プロンプトを含む）は KV を使い回して
     1回だけ計算する（新しい入り口 ScoreSentenceSuffixes）。
  3. 学習した選び手（Zenz の点を使う）の確からしさがしきい値（0.85、weights.json の threshold）以上の表記を1位にする。
     判断は全文節で、ほかの文節は替える前の1位のままとして行い、最後にまとめて替える。
  門と判断には、固有名を守る決まり（SelectorGuardOk、selector_stage2.py の guard_ok）を通る候補だけを使う。
特徴の作り方は tools/selector_stage2.py の pair_features と同じ。重みは
tools/data/selector-stage3/weights.json（selector_stage2.py --export-stage3 で作る）。
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
mozc = Path(sys.argv[1])
myime = Path(sys.argv[2])
weights = json.loads(Path(sys.argv[3] if len(sys.argv) > 3 else HERE / "data/selector-stage3/weights.json")
                     .read_text(encoding="utf-8"))


def edit(root, path, old, new):
    p = root / path
    text = p.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected one match for {old[:60]!r}, found {text.count(old)}")
    p.write_text(text.replace(old, new), encoding="utf-8", newline="")


# ---- Swift: 文どうしの差の採点（共通の前半を1回だけ計算する） ----
Z = "AzooKeyKanaKanjiConverter/Sources/KanaKanjiConverterModule/ConversionAlgorithms/Zenzai/Zenz"
edit(myime, Z + "/ZenzContext.swift", "    func decodeTokens(_ tokens: [llama_token]) -> String {\n", r'''    /// 選び手の段階3: 同じプロンプトの下で、各文の「全部の文に共通する語片の前半より後ろ」と文の終わりの
    /// 対数確率の和。共通の前半（プロンプトを含む）は KV を使い回して1回だけ計算する。
    /// 共通の前半の確率は全部の文で同じなので、文どうしの差は文全体の対数確率の差と等しい。
    func suffixLogProbabilities(prompt: String, candidateTexts: [String]) -> [Double?] {
        let failed = candidateTexts.map { _ -> Double? in nil }
        let normalizedPrompt = self.normalizeForModel(prompt)
        let vocab = self.vocabSize
        let eos = self.eosToken
        guard (1...1_000_000).contains(vocab), eos >= 0, Int(eos) < vocab,
              !normalizedPrompt.isEmpty, !normalizedPrompt.contains("\0"), normalizedPrompt.utf8.count <= 16_384 else { return failed }
        func tokenizeChecked(_ text: String, addBOS: Bool) -> [llama_token]? {
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
        guard let promptTokens = tokenizeChecked(normalizedPrompt, addBOS: true), promptTokens.count <= 512 else { return failed }
        var candidates: [[llama_token]] = []
        for text in candidateTexts {
            let normalized = self.normalizeForModel(text)
            guard !normalized.isEmpty, !normalized.contains("\0"), normalized.utf8.count <= 1024,
                  let tokens = tokenizeChecked(normalized, addBOS: false), tokens.count <= 512 else { return failed }
            candidates.append(tokens)
        }
        guard let first = candidates.first else { return failed }
        var common = first.count
        for tokens in candidates.dropFirst() {
            var k = 0
            while k < min(common, tokens.count) && tokens[k] == first[k] { k += 1 }
            common = k
        }
        common = min(common, candidates.map { $0.count }.min() ?? 0)
        var results: [Double?] = []
        for tokens in candidates {
            let all = promptTokens + tokens
            let startOffset = promptTokens.count - 1 + common
            let targets = Array(tokens[common...]) + [eos]
            guard all.count <= 512, all.count <= Int(llama_n_ctx(self.context)),
                  let logits = self.evaluationLogits(tokens: all, startOffset: startOffset) else {
                llama_kv_cache_seq_rm(self.context, self.evalSeqId, 0, -1)
                self.prevInputBySeq.removeValue(forKey: self.evalSeqId)
                self.prevPromptBySeq.removeValue(forKey: self.evalSeqId)
                results.append(nil)
                continue
            }
            var total = 0.0
            var ok = true
            for (rowIndex, target) in targets.enumerated() {
                let row = UnsafeBufferPointer(start: logits.advanced(by: rowIndex * vocab), count: vocab)
                guard let maximum = row.max(), maximum.isFinite else { ok = false; break }
                let maxValue = Double(maximum)
                let sumExp = row.reduce(0.0) { $0 + exp(Double($1) - maxValue) }
                let value = Double(row[Int(target)]) - maxValue - log(sumExp)
                guard value.isFinite else { ok = false; break }
                total += value
            }
            results.append(ok && total.isFinite ? total : nil)
        }
        self.setPreviousEvaluationPrompt(normalizedPrompt)
        return results
    }

    func decodeTokens(_ tokens: [llama_token]) -> String {
''')

edit(myime, Z + "/Zenz.swift", "    func predictNextInputText(\n", r'''    // 選び手の段階3: 文どうしの差の採点（共通の前半を1回だけ計算する）。
    func selectorSuffixScores(reading: String, texts: [String], contextualMode: ConvertRequestOptions.ZenzaiV3DependentMode) -> [Double?] {
        self.inferenceLock.withLock { () -> [Double?] in
            guard !self.useGpu, let context = self.zenzContext else { return texts.map { _ in nil } }
            let version = ConvertRequestOptions.ZenzaiVersionDependentMode.v3(contextualMode)
            let katakana = reading.toKatakana()
            let prompt = ZenzPromptBuilder.candidateEvaluationPrompt(input: katakana, userDictionaryPrompt: "", versionDependentConfig: version)
            let evaluated = texts.map {
                ZenzCandidateEvaluator.candidateTextForEvaluation(candidateText: $0, input: katakana, inputCursorPosition: nil, versionDependentConfig: version)
            }
            return context.suffixLogProbabilities(prompt: prompt, candidateTexts: evaluated)
        }
    }

    func predictNextInputText(
''')

edit(myime, "AzooKeyKanaKanjiConverter/Sources/KanaKanjiConverterModule/ConverterAPI/KanaKanjiConverter.swift",
     "    /// 入力からラティスを構築する関数。状況に応じて呼ぶ関数を分ける。\n", r'''    /// 選び手の段階3: 文どうしの差の採点（共通の前半は1回だけ計算する）。
    public func selectorSuffixScores(reading: String, texts: [String], leftContext: String, rightContext: String) -> [Double?] {
        guard let model = self.zenz, !model.useGpu, self.zenzaiModelLoadError == nil else { return texts.map { _ in nil } }
        let mode = ConvertRequestOptions.ZenzaiV3DependentMode(leftSideContext: leftContext, rightSideContext: rightContext)
        return model.selectorSuffixScores(reading: reading, texts: texts, contextualMode: mode)
    }

    /// 入力からラティスを構築する関数。状況に応じて呼ぶ関数を分ける。
''')

edit(myime, "swift-engine/Sources/azookey-engine/AzookeyEngine.swift", '@_cdecl("FreeString")\n', r'''/// 選び手の段階3: ScoreSentences と同じ形で、文どうしの差だけを見る採点（共通の前半は1回だけ計算する）。
@_cdecl("ScoreSentenceSuffixes")
public func scoreSentenceSuffixes(
    _ reading: UnsafePointer<CChar>?,
    _ leftContext: UnsafePointer<CChar>?,
    _ rightContext: UnsafePointer<CChar>?,
    _ joinedTexts: UnsafePointer<CChar>?
) -> UnsafePointer<CChar>? {
    guard let reading = reading, let joinedTexts = joinedTexts else { return nil }

    engineLock.lock()
    defer { engineLock.unlock() }

    guard let conv = converter else { return nil }
    let texts = String(cString: joinedTexts).components(separatedBy: "\u{01}")
    let left = conversionContext(leftContext.map { String(cString: $0) } ?? "", left: true)
    let right = conversionContext(rightContext.map { String(cString: $0) } ?? "", left: false)
    ZenzaiDeadline.begin(milliseconds: config.zenzaiTimeLimitMs)
    defer { finishZenzaiDeadline() }
    let scores = conv.selectorSuffixScores(reading: String(cString: reading), texts: texts, leftContext: left, rightContext: right)
    let joined = scores.map { score -> String in
        if let score = score, score.isFinite { return String(score) }
        return "nan"
    }.joined(separator: "\t")
    return UnsafePointer(_strdup(joined))
}

@_cdecl("FreeString")
''')

# ---- C++: 変換エンジンの入り口の読み込み ----
A = "converter/azookey_immutable_converter.cc"
edit(mozc, A, "  using GetSelectorTraceFunc = const char* (*)(const char*);\n",
     "  using GetSelectorTraceFunc = const char* (*)(const char*);\n"
     "  using ScoreSentenceSuffixesFunc = const char* (*)(const char*, const char*, const char*, const char*);\n")
edit(mozc, A, "  GetSelectorTraceFunc GetSelectorTrace = nullptr;\n",
     "  GetSelectorTraceFunc GetSelectorTrace = nullptr;\n  ScoreSentenceSuffixesFunc ScoreSentenceSuffixes = nullptr;\n")
edit(mozc, A, """    GetSelectorTrace = reinterpret_cast<GetSelectorTraceFunc>(
        GetProcAddress(dll_handle_, "GetSelectorTrace"));
""", """    GetSelectorTrace = reinterpret_cast<GetSelectorTraceFunc>(
        GetProcAddress(dll_handle_, "GetSelectorTrace"));
    ScoreSentenceSuffixes = reinterpret_cast<ScoreSentenceSuffixesFunc>(
        GetProcAddress(dll_handle_, "ScoreSentenceSuffixes"));
""")
edit(mozc, A, "    MYIME_LOAD(GetSelectorTrace);\n", "    MYIME_LOAD(GetSelectorTrace);\n    MYIME_LOAD(ScoreSentenceSuffixes);\n")
edit(mozc, A, "    GetSelectorTrace = nullptr;\n", "    GetSelectorTrace = nullptr;\n    ScoreSentenceSuffixes = nullptr;\n")
edit(mozc, A, "bool SelectorTraceForText(absl::string_view text, std::string* trace) {\n",
     r'''bool ScoreZenzaiSuffixes(absl::string_view reading, absl::string_view left,
                         absl::string_view right, absl::string_view joined_texts,
                         std::string* scores) {
  if (reading.empty() || joined_texts.empty() || scores == nullptr ||
      reading.find('\0') != absl::string_view::npos ||
      joined_texts.find('\0') != absl::string_view::npos) {
    return false;
  }
  auto& loader = AzooKeyDllLoader::GetInstance();
  const std::lock_guard<std::mutex> operation(loader.operation_mutex());
  if (!loader.IsLoaded() || !loader.ScoreSentenceSuffixes) return false;
  const std::string r(reading), l(left), rt(right), t(joined_texts);
  const char* result = loader.ScoreSentenceSuffixes(r.c_str(), l.c_str(), rt.c_str(), t.c_str());
  if (result == nullptr) return false;
  scores->assign(result);
  loader.FreeString(result);
  return true;
}

bool SelectorTraceForText(absl::string_view text, std::string* trace) {
''')
edit(mozc, "converter/azookey_immutable_converter.h",
     "[[nodiscard]] bool SelectorTraceForText(absl::string_view text, std::string* trace);\n",
     "[[nodiscard]] bool SelectorTraceForText(absl::string_view text, std::string* trace);\n\n"
     "// 選び手の段階3: ScoreZenzaiSentences と同じ形で、文どうしの差だけを見る点（共通の前半は1回だけ計算）。\n"
     "[[nodiscard]] bool ScoreZenzaiSuffixes(absl::string_view reading, absl::string_view left,\n"
     "                                       absl::string_view right, absl::string_view joined_texts,\n"
     "                                       std::string* scores);\n")


# ---- C++: 選び手 ----
def arr(name, values):
    return f"  static constexpr double {name}[{len(values)}] = {{" + ", ".join(repr(float(v)) for v in values) + "};\n"


n = len(weights["features"])
assert n == 63, n
consts = (f"  static constexpr int kSelectorFeatures = {n};\n"
          f"  static constexpr size_t kSelectorMaxAlts = {int(weights['max_alts'])};\n"
          f"  static constexpr double kSelectorGateThreshold = {float(weights['gate_threshold'])!r};\n"
          f"  static constexpr double kSelectorThreshold = {float(weights['threshold'])!r};\n"
          + "".join(arr(f"kSelector{part.capitalize()}{key.capitalize()}", weights[part][key])
                    for part in ("gate", "main") for key in ("mean", "scale", "coef"))
          + f"  static constexpr double kSelectorGateIntercept = {weights['gate']['intercept']!r};\n"
          + f"  static constexpr double kSelectorMainIntercept = {weights['main']['intercept']!r};\n")
digits = ", ".join(f"0x{ord(ch):X}" for ch in "〇一二三四五六七八九十百千万億")
ranges = {"hira": (ord("ぁ"), ord("ゖ")), "kata": (ord("ァ"), ord("ヺ")), "kanji": (ord("一"), ord("龯"))}
assert ranges == {"hira": (0x3041, 0x3096), "kata": (0x30A1, 0x30FA), "kanji": (0x4E00, 0x9FAF)}, ranges

SELECTOR = consts + r'''  static std::vector<char32_t> SelectorCodepoints(std::string_view s) {
    std::vector<char32_t> out;
    for (size_t i = 0; i < s.size();) {
      const unsigned char c = static_cast<unsigned char>(s[i]);
      const int n = c < 0x80 ? 1 : (c >> 5) == 6 ? 2 : (c >> 4) == 14 ? 3 : (c >> 3) == 30 ? 4 : 1;
      char32_t cp = n == 1 ? c : (c & (0x7F >> n));
      for (int k = 1; k < n && i + k < s.size(); ++k) cp = (cp << 6) | (static_cast<unsigned char>(s[i + k]) & 0x3F);
      out.push_back(cp);
      i += n;
    }
    return out;
  }
  static bool SelectorHira(char32_t c) { return c >= 0x3041 && c <= 0x3096; }
  static bool SelectorKata(char32_t c) { return (c >= 0x30A1 && c <= 0x30FA) || c == 0x30FC; }
  static bool SelectorKanji(char32_t c) {
    return (c >= 0x4E00 && c <= 0x9FAF) || c == 0x3005 || c == 0x3006 || c == 0x30F5 || c == 0x30F6;
  }
  static bool SelectorLatin(char32_t c) {
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= 0xFF21 && c <= 0xFF3A) || (c >= 0xFF41 && c <= 0xFF5A);
  }
  static bool SelectorDigit(char32_t c) {
    static constexpr char32_t kNumerals[] = {DIGITS};
    if ((c >= '0' && c <= '9') || (c >= 0xFF10 && c <= 0xFF19)) return true;
    for (char32_t d : kNumerals) if (c == d) return true;
    return false;
  }
  static int SelectorKind(const std::vector<char32_t>& s, bool last) {
    if (s.empty()) return 0;
    const char32_t c = last ? s.back() : s.front();
    if (SelectorHira(c)) return 1;
    if (SelectorKata(c)) return 2;
    if (SelectorKanji(c)) return 3;
    if (SelectorLatin(c)) return 4;
    return 5;
  }
  // tools/selector_stage2.py の char_stats: ひらがな・カタカナ・漢字の割合、英字・数字の有無
  static std::array<double, 5> SelectorCharStats(const std::vector<char32_t>& s) {
    const double n = std::max<size_t>(1, s.size());
    double h = 0, k = 0, j = 0, l = 0, d = 0;
    for (char32_t c : s) {
      h += SelectorHira(c);
      k += SelectorKata(c);
      j += SelectorKanji(c);
      l = l || SelectorLatin(c);
      d = d || SelectorDigit(c);
    }
    return {h / n, k / n, j / n, l, d};
  }
  struct SelectorZenz {
    bool have_top = false, have_alt = false;
    double top = 0, alt = 0, best = 0;
    bool any = false;
  };
  // tools/selector_stage2.py の pair_features と同じ並び（63個）
  static std::array<double, kSelectorFeatures> SelectorFeatures(const Segments& segments, size_t i, size_t j,
                                                                const SelectorZenz& z) {
    const Segment& seg = segments.conversion_segment(i);
    const auto& t = seg.candidate(0);
    const auto& c = seg.candidate(j);
    const size_t nsegs = segments.conversion_segments_size();
    const auto tv = SelectorCodepoints(t.value), cv = SelectorCodepoints(c.value);
    const auto key = SelectorCodepoints(seg.key());
    const std::vector<char32_t> prev = i > 0 && segments.conversion_segment(i - 1).candidates_size() > 0
        ? SelectorCodepoints(segments.conversion_segment(i - 1).candidate(0).value) : std::vector<char32_t>();
    const std::vector<char32_t> next = i + 1 < nsegs && segments.conversion_segment(i + 1).candidates_size() > 0
        ? SelectorCodepoints(segments.conversion_segment(i + 1).candidate(0).value) : std::vector<char32_t>();
    const auto cs = SelectorCharStats(cv), ts = SelectorCharStats(tv);
    const bool have = z.have_top && z.have_alt;
    std::array<double, kSelectorFeatures> f{};
    size_t n = 0;
    f[n++] = static_cast<double>(j);
    f[n++] = j == 1;
    f[n++] = (static_cast<double>(c.cost) - t.cost) / 1000.0;
    f[n++] = (static_cast<double>(c.wcost) - t.wcost) / 1000.0;
    f[n++] = (static_cast<double>(c.structure_cost) - t.structure_cost) / 1000.0;
    f[n++] = t.cost / 1000.0;
    f[n++] = t.wcost / 1000.0;
    f[n++] = t.structure_cost / 1000.0;
    f[n++] = have;
    f[n++] = have ? z.alt - z.top : 0.0;
    f[n++] = have ? z.alt - z.best : 0.0;
    f[n++] = have && z.alt >= z.best;
    f[n++] = z.have_top && z.any && z.top >= z.best;
    f[n++] = static_cast<double>(cv.size()) - static_cast<double>(tv.size());
    f[n++] = static_cast<double>(key.size());
    f[n++] = static_cast<double>(nsegs);
    f[n++] = i == 0;
    f[n++] = i + 1 == nsegs;
    f[n++] = std::string_view(c.content_value) == std::string_view(t.content_value);
    f[n++] = c.lid == t.lid;
    f[n++] = c.rid == t.rid;
    f[n++] = cs[0] == 1.0;
    f[n++] = ts[0] == 1.0;
    f[n++] = cs[1] == 1.0;
    f[n++] = ts[1] == 1.0;
    f[n++] = SelectorKind(prev, true) == 3;
    f[n++] = SelectorKind(next, false) == 1;
    f[n++] = (cv.empty() && tv.empty()) || (!cv.empty() && !tv.empty() && cv.back() == tv.back());
    for (double v : cs) f[n++] = v;
    for (double v : ts) f[n++] = v;
    for (int k = 0; k < 3; ++k) f[n++] = cs[k] - ts[k];
    static constexpr int kBits[] = {0, 1, 4, 5, 8, 9, 12, 15, 22, 23, 24};
    for (int b : kBits) f[n++] = (c.attributes >> b) & 1;
    for (int b : kBits) f[n++] = (t.attributes >> b) & 1;
    return f;
  }
  // 固有名を守る決まり（tools/selector_stage2.py の guard_ok と同じ）。替えてよければ true。
  // 1. 1位の文節にカタカナがあれば替えない。2. 替える先の違う部分にカタカナがあれば替えない。
  // （文全体にひらがなも漢字もなく6文字以上＝全部カタカナになった失敗のときは、1と2と5は当てない）
  // 3. 1位の違う部分がひらがな1文字だけなら替えない。4. 1位に英字・数字があれば替えない。
  // 5. 1位と替える先の違う部分の、片方だけに漢字があれば替えない（漢字とかなの書き分け）。
  // 6. 文のどこかに英字があれば替えない（ApplySelector の頭で見る）。
  static bool SelectorGuardOk(std::string_view top_s, std::string_view alt_s, bool fallback) {
    const auto top = SelectorCodepoints(top_s), alt = SelectorCodepoints(alt_s);
    size_t a = 0, b = 0;
    while (a < std::min(top.size(), alt.size()) && top[a] == alt[a]) ++a;
    while (b < std::min(top.size(), alt.size()) - a && top[top.size() - 1 - b] == alt[alt.size() - 1 - b]) ++b;
    if (!fallback) {
      for (char32_t c : top) if (SelectorKata(c)) return false;
      for (size_t k = a; k < alt.size() - b; ++k) if (SelectorKata(alt[k])) return false;
    }
    if (top.size() - b - a == 1 && SelectorHira(top[a])) return false;
    for (char32_t c : top) {
      if (SelectorLatin(c) || (c >= '0' && c <= '9') || (c >= 0xFF10 && c <= 0xFF19)) return false;
    }
    if (!fallback) {
      bool top_kanji = false, alt_kanji = false;
      for (size_t k = a; k < top.size() - b; ++k) top_kanji = top_kanji || SelectorKanji(top[k]);
      for (size_t k = a; k < alt.size() - b; ++k) alt_kanji = alt_kanji || SelectorKanji(alt[k]);
      if (top_kanji != alt_kanji) return false;
    }
    return true;
  }
  static double SelectorProb(const std::array<double, kSelectorFeatures>& f, const double* mean, const double* scale,
                             const double* coef, double intercept) {
    double z = intercept;
    for (int k = 0; k < kSelectorFeatures; ++k) z += (f[k] - mean[k]) / scale[k] * coef[k];
    return 1.0 / (1.0 + std::exp(-z));
  }
  // 選び手の段階3（MYIME_SELECTOR=0 で切る）。MYIME_SELECTOR_LOG=<ファイル> のときは判断を書き足す。
  static void ApplySelector(Segments* segments, std::string_view left, std::string_view right) {
    static const bool enabled = [] {
      const char* value = std::getenv("MYIME_SELECTOR");
      return !value || std::string_view(value) != "0";
    }();
    if (!enabled) return;
    static const char* log_path = std::getenv("MYIME_SELECTOR_LOG");
    const size_t count = segments->conversion_segments_size();
    if (count == 0) return;
    std::string reading;
    std::vector<std::string> first;
    for (size_t i = 0; i < count; ++i) {
      const Segment& seg = segments->conversion_segment(i);
      if (seg.candidates_size() == 0) return;
      reading += seg.key();
      first.push_back(std::string(seg.candidate(0).value));
    }
    auto clean = [](std::string_view s) {
      return s.find('\t') == std::string_view::npos && s.find('\x01') == std::string_view::npos &&
             s.find('\n') == std::string_view::npos;
    };
    if (!clean(reading)) return;
    // 文全体にひらがなも漢字もなく6文字以上なら、全部カタカナになった失敗とみなす
    bool fallback = false;
    {
      std::string text;
      for (const auto& f : first) text += f;
      const auto cps = SelectorCodepoints(text);
      fallback = cps.size() >= 6;
      for (char32_t c : cps) {
        if (SelectorHira(c) || SelectorKanji(c)) fallback = false;
        // 守りの決まり6: 文のどこかに英字があれば替えない（guard_ok の6と同じ。採点もしない）
        if (SelectorLatin(c)) return;
      }
    }
    std::vector<std::pair<size_t, size_t>> moves;
    std::string log;
    for (size_t i = 0; i < count; ++i) {
      const Segment& seg = segments->conversion_segment(i);
      if (seg.segment_type() != Segment::FREE) continue;
      const auto& top = seg.candidate(0);
      if ((top.attributes & converter::Attribute::USER_SEGMENT_HISTORY_REWRITER) != 0) continue;
      // 1位と違う表記の候補（上位8つのうち先の kSelectorMaxAlts 個）
      std::vector<size_t> alts;
      std::vector<std::string> seen = {first[i]};
      for (size_t j = 1; j < seg.candidates_size() && j < 8 && alts.size() < kSelectorMaxAlts; ++j) {
        const std::string value(seg.candidate(j).value);
        if (std::find(seen.begin(), seen.end(), value) != seen.end()) continue;
        seen.push_back(value);
        alts.push_back(j);
      }
      if (alts.empty()) continue;
      // 固有名を守る決まりで替えてよい候補だけを門と判断に使う（採点には全部の候補を入れる）
      std::vector<size_t> allowed;
      for (size_t j : alts) {
        if (SelectorGuardOk(first[i], seg.candidate(j).value, fallback)) allowed.push_back(j);
      }
      if (allowed.empty()) continue;
      double gate = 0;
      for (size_t j : allowed) {
        gate = std::max(gate, SelectorProb(SelectorFeatures(*segments, i, j, SelectorZenz{}), kSelectorGateMean,
                                           kSelectorGateScale, kSelectorGateCoef, kSelectorGateIntercept));
      }
      if (gate < kSelectorGateThreshold) continue;
      // 門を通った文節だけ採点し直す（1位と別の表記、ほかの文節は1位のまま）
      std::string prefix, suffix, joined;
      for (size_t k = 0; k < i; ++k) prefix += first[k];
      for (size_t k = i + 1; k < count; ++k) suffix += first[k];
      bool ok = true;
      for (size_t s = 0; s <= alts.size(); ++s) {
        const std::string value = s == 0 ? first[i] : std::string(seg.candidate(alts[s - 1]).value);
        if (!clean(value)) ok = false;
        if (s > 0) joined += '\x01';
        joined += prefix + value + suffix;
      }
      std::string scores;
      if (!ok || !clean(prefix) || !clean(suffix) || !ScoreZenzaiSuffixes(reading, left, right, joined, &scores)) continue;
      std::vector<double> values;
      for (size_t at = 0;;) {
        const size_t tab = scores.find('\t', at);
        const std::string piece = scores.substr(at, tab == std::string::npos ? std::string::npos : tab - at);
        values.push_back(piece == "nan" ? std::nan("") : std::strtod(piece.c_str(), nullptr));
        if (tab == std::string::npos) break;
        at = tab + 1;
      }
      if (values.size() != alts.size() + 1 || !std::isfinite(values[0])) continue;
      SelectorZenz z;
      z.have_top = true;
      z.top = values[0];
      z.best = values[0];
      z.any = true;
      for (double v : values) if (std::isfinite(v)) z.best = std::max(z.best, v);
      double best_p = 0;
      size_t best_j = 0;
      for (size_t a = 0; a < alts.size(); ++a) {
        if (!std::isfinite(values[a + 1])) continue;  // Zenz の点のない表記には替えない
        if (std::find(allowed.begin(), allowed.end(), alts[a]) == allowed.end()) continue;
        SelectorZenz za = z;
        za.have_alt = true;
        za.alt = values[a + 1];
        const double p = SelectorProb(SelectorFeatures(*segments, i, alts[a], za), kSelectorMainMean,
                                      kSelectorMainScale, kSelectorMainCoef, kSelectorMainIntercept);
        if (p > best_p) {
          best_p = p;
          best_j = alts[a];
        }
      }
      if (log_path && *log_path) {
        log += reading + '\t' + std::to_string(i) + '\t' + std::to_string(gate) + '\t' + std::to_string(best_p) +
               '\t' + std::to_string(best_j) + '\n';
      }
      if (best_j > 0 && best_p >= kSelectorThreshold) moves.emplace_back(i, best_j);
    }
    for (const auto& [i, j] : moves) {
      segments->mutable_conversion_segment(i)->move_candidate(static_cast<int>(j), 0);
    }
    if (!log.empty()) {
      static std::mutex log_mutex;
      std::lock_guard<std::mutex> lock(log_mutex);
      if (FILE* f = std::fopen(log_path, "ab")) {
        std::fwrite(log.data(), 1, log.size(), f);
        std::fclose(f);
      }
    }
  }
'''.replace("DIGITS", digits)

E = "engine/engine.cc"
edit(mozc, E, "    ScoreCandidates(*segments, left_context, right_context);\n",
     "    ScoreCandidates(*segments, left_context, right_context);\n"
     "    ApplySelector(segments, left_context, right_context);\n")
edit(mozc, E, "  // MYIME_SELECTOR_FEATURES=<ファイル>: 選び手の段階2の材料（記録だけ）。",
     SELECTOR + "  // MYIME_SELECTOR_FEATURES=<ファイル>: 選び手の段階2の材料（記録だけ）。")
edit(mozc, E, "#include <chrono>\n#include <cmath>\n", "#include <array>\n#include <chrono>\n#include <cmath>\n")

print("applied selector stage 3")
