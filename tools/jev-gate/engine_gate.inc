  // ---- 判定の門（tools/apply_jev_gate.py、docs/jev-gate-ime.md）-------------------------------
  // 全文の人工知能の生成（PreferWholePhrase の問い合わせ）が要るかを、小さな模型で当てる。
  // 要らないと当てたら、生成なしの候補（Mozc の第一候補、AzooKey の辞書の文全体、Mozc の組）のうち上位の数個を
  // zenz で採点して（MYIME_JEV_GATE_SELECT=student なら模型自身の点で）最大のものを選び、生成を飛ばす。
  // 候補の作り方と並びは tools/jev_gate_build.py の make_candidates（学習のときの作り方）と同じ:
  // 人工知能なしの出力 n、辞書の文全体 w（最大32）、組 c（Mozc の文節ごとの上位16を、費用の和の小さい順に最大32）を、
  // この順に並べて表記が同じものを1つにする。出どころの番号は c があれば 3、なければ n なら 1、なければ 2。
  struct GateEntry {
    std::string text;                              // 正規化した文全体（半角の ? ! は全角）
    std::vector<int> indices;                      // n と c の候補: 文節ごとの候補の番号。w だけなら空
    const converter::Candidate* whole = nullptr;   // w の候補（AzooKey の辞書の文全体）
    bool n = false, w = false, c = false;
  };

  static std::string GateNorm(std::string_view text) {
    std::string out;
    for (const char ch : text) {
      if (ch == '?') out += "\xEF\xBC\x9F";
      else if (ch == '!') out += "\xEF\xBC\x81";
      else out.push_back(ch);
    }
    return out;
  }

  static double GateMs(std::chrono::steady_clock::time_point since) {
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - since).count();
  }

  static void GateLog(const std::string& line) {
    const auto& cfg = JevGateConfig();
    if (cfg.log.empty()) return;
    static std::mutex mutex;
    std::lock_guard<std::mutex> lock(mutex);
    if (FILE* f = std::fopen(cfg.log.c_str(), "ab")) {
      std::fwrite(line.data(), 1, line.size(), f);
      std::fputc('\n', f);
      std::fclose(f);
    }
  }

  // Mozc の組: 文節ごとの上位16を費用の小さい順に並べ、費用の和の小さい順に違う表記の文を limit 個
  // （tools/jev_ceiling.py の kbest と同じ。同じ費用の並びも同じ）。
  static std::vector<std::pair<std::string, std::vector<int>>> GateCombos(const Segments& segments, size_t limit) {
    struct Item { std::string value; long long cost; int index; };
    std::vector<std::vector<Item>> lists;
    for (const auto& segment : segments.conversion_segments()) {
      std::vector<Item> items;
      for (size_t c = 0; c < segment.candidates_size() && c < 16; ++c)
        items.push_back({segment.candidate(c).value, static_cast<long long>(segment.candidate(c).cost), static_cast<int>(c)});
      if (items.empty()) return {};
      std::stable_sort(items.begin(), items.end(), [](const Item& a, const Item& b) { return a.cost < b.cost; });
      lists.push_back(std::move(items));
    }
    using Key = std::pair<long long, std::vector<int>>;
    std::priority_queue<Key, std::vector<Key>, std::greater<Key>> heap;
    std::set<std::vector<int>> seen_index;
    std::set<std::string> seen_text;
    std::vector<int> start(lists.size(), 0);
    long long start_cost = 0;
    for (const auto& list : lists) start_cost += list[0].cost;
    heap.push({start_cost, start});
    seen_index.insert(start);
    std::vector<std::pair<std::string, std::vector<int>>> out;
    while (!heap.empty() && out.size() < limit && seen_index.size() < 20000) {
      const Key top = heap.top();
      heap.pop();
      std::string text;
      std::vector<int> original_index;
      for (size_t i = 0; i < lists.size(); ++i) {
        text += lists[i][top.second[i]].value;
        original_index.push_back(lists[i][top.second[i]].index);
      }
      if (seen_text.insert(text).second) out.emplace_back(std::move(text), std::move(original_index));
      for (size_t i = 0; i < lists.size(); ++i) {
        if (static_cast<size_t>(top.second[i]) + 1 >= lists[i].size()) continue;
        std::vector<int> next = top.second;
        ++next[i];
        if (!seen_index.insert(next).second) continue;
        heap.push({top.first - lists[i][top.second[i]].cost + lists[i][top.second[i] + 1].cost, std::move(next)});
      }
    }
    return out;
  }

  // 選んだ候補を、文節ごとの候補の番号にする（PreferWholePhrase の選び方と同じ確かめ）。できなければ false。
  static bool GateRealize(const GateEntry& entry, const dictionary::PosMatcher& pos, const Segments& segments,
                          std::string_view key,
                          const std::vector<std::vector<const converter::Candidate*>>& original,
                          std::vector<int>* indices) {
    const size_t count = segments.conversion_segments_size();
    if (entry.n) {
      indices->assign(count, 0);
      return true;
    }
    if (const Util::ScriptType script = Util::GetScriptType(entry.text);
        script == Util::KATAKANA || script == Util::HIRAGANA) return false;
    if (!entry.indices.empty()) {
      *indices = entry.indices;
    } else if (entry.whole != nullptr) {
      const char* rejection = "";
      bool selected = MatchWholePhrase(*entry.whole, segments, key, indices, &rejection);
      if (!selected && Compatible(*entry.whole, key) &&
          !(entry.whole->attributes & (converter::Attribute::COMMAND_CANDIDATE | converter::Attribute::PARTIALLY_KEY_CONSUMED))) {
        if (auto path = private_surface::Find(segments, key, entry.whole->value, original)) {
          *indices = std::move(*path);
          selected = true;
        }
      }
      if (!selected) return false;
    } else {
      return false;
    }
    if (indices->size() != count || original.size() != count) return false;
    for (size_t i = 0; i < count; ++i) {
      const auto& segment = segments.conversion_segment(i);
      if ((*indices)[i] < 0 || static_cast<size_t>((*indices)[i]) >= segment.candidates_size() ||
          std::find(original[i].begin(), original[i].end(), segment.candidates()[(*indices)[i]]) == original[i].end())
        return false;
      // As in PreferWholePhrase: never turn Mozc's first name or place into kana.
      const Util::ScriptType script = Util::GetScriptType(segment.candidate((*indices)[i]).value);
      if ((*indices)[i] != 0 && pos.IsUniqueNoun(segment.candidate(0).lid) &&
          (script == Util::HIRAGANA || script == Util::KATAKANA)) return false;
    }
    return true;
  }

  // 戻り値 true: 生成を省いて候補を選び終えた（segments を更新した）。false: 今まで通り生成する。
  static bool JevGateSkipGeneration(const ConversionOptions& options, const ImmutableConverterInterface& azoo,
                                    const dictionary::PosMatcher& pos, Segments* segments, const std::string& key,
                                    std::string_view left, std::string_view right,
                                    const std::vector<std::vector<const converter::Candidate*>>& original) {
    const auto& cfg = JevGateConfig();
    if (g_whole_phrase_min_segments != 2) return false;
    if (!cfg.enabled) {
      // 門が無効（今の動き）。記録の指定があるときだけ、全文の生成が走る変換を1行書く
      if (!cfg.log.empty())
        GateLog("gate\tchars=" + std::to_string(Util::CharsLen(key)) + "\tsegs=" +
                std::to_string(segments->conversion_segments_size()) + "\tdecision=generate_nogate");
      return false;
    }
    const size_t count = segments->conversion_segments_size();
    if (count < 2 || count > 32 || original.size() != count) return false;
    const auto t_all = std::chrono::steady_clock::now();
    const int limit = jev_gate::CandidateLimit();
    if (limit <= 0) return false;
    std::string log = "gate\tchars=" + std::to_string(Util::CharsLen(key)) + "\tsegs=" + std::to_string(count);
    // n: Mozc の第一候補をつないだ文（人工知能なしの出力）
    std::vector<GateEntry> entries;
    std::map<std::string, size_t> where;
    auto add = [&](const std::string& raw, char tag, const std::vector<int>& indices, const converter::Candidate* whole) {
      std::string text = GateNorm(raw);
      if (text.empty()) return;
      auto found = where.find(text);
      if (found == where.end()) {
        found = where.emplace(text, entries.size()).first;
        entries.emplace_back();
        entries.back().text = text;
      }
      GateEntry& entry = entries[found->second];
      if (tag == 'n') {
        entry.n = true;
        entry.indices = indices;
      } else if (tag == 'w') {
        entry.w = true;
        if (entry.whole == nullptr) entry.whole = whole;
      } else {
        entry.c = true;
        if (entry.indices.empty()) entry.indices = indices;
      }
    };
    {
      std::string noai;
      for (const auto& segment : segments->conversion_segments()) {
        if (segment.candidates_size() == 0) return false;
        noai += segment.candidate(0).value;
      }
      add(noai, 'n', std::vector<int>(count, 0), nullptr);
    }
    // w: AzooKey の辞書の文全体（人工知能なし）
    const auto t_noai = std::chrono::steady_clock::now();
    Segments full(*segments);
    full.InitForConvert(key);
    full.set_max_history_segments_size(segments->max_history_segments_size());
    bool noai_ok = false;
    {
      ScopedAzooKeyNoAI no_ai;
      noai_ok = azoo.ConvertWithContext(options, &full, left, right);
    }
    if (noai_ok && full.conversion_segments_size() == 1 && full.conversion_segment(0).candidates_size() <= 4096) {
      std::set<std::string> seen;
      size_t taken = 0;
      for (const auto* candidate : full.conversion_segment(0).candidates()) {
        if (candidate == nullptr || candidate->value.empty()) continue;
        if (!seen.insert(candidate->value).second) continue;
        add(candidate->value, 'w', {}, candidate);
        if (++taken >= 32) break;
      }
    }
    log += "\tnoai_ms=" + std::to_string(GateMs(t_noai));
    // c: Mozc の組
    for (const auto& combo : GateCombos(*segments, 32)) add(combo.first, 'c', combo.second, nullptr);
    // 模型に渡す（先頭の limit 個）
    std::vector<jev_gate::Cand> cands;
    for (size_t i = 0; i < entries.size() && static_cast<int>(i) < limit; ++i)
      cands.push_back({entries[i].text, entries[i].c ? 3 : (entries[i].n ? 1 : 2)});
    jev_gate::Result result;
    std::string prev(left);
    if (!jev_gate::Predict(prev, key, cands, &result)) {
      GateLog(log + "\tdecision=error_predict");
      return false;
    }
    log += "\tcands=" + std::to_string(entries.size()) + "\tneed_k=" + std::to_string(result.need_k) +
           "\tpredict_ms=" + std::to_string(result.ms);
    if (result.need_k >= cfg.threshold || cands.size() < 2) {
      // 生成が要る（候補が1つだけのときは選ぶ余地がないので、今まで通り）
      GateLog(log + "\tdecision=generate\ttotal_ms=" + std::to_string(GateMs(t_all)));
      return false;
    }
    // 生成を省く: 上位 M 個から最大の点を選ぶ
    const size_t scored = std::min<size_t>({cands.size(), static_cast<size_t>(cfg.score_n > 0 ? cfg.score_n : limit)});
    std::vector<double> points(scored, -1e300);
    const auto t_score = std::chrono::steady_clock::now();
    if (cfg.student) {
      for (size_t i = 0; i < scored && i < result.score.size(); ++i) points[i] = result.score[i];
    } else {
      std::string joined;
      for (size_t i = 0; i < scored; ++i) {
        if (i > 0) joined += '\x01';
        joined += entries[i].text;
      }
      std::string reply;
      if (!ScoreZenzaiSuffixes(key, left, right, joined, &reply)) {
        GateLog(log + "\tdecision=fallback_score\ttotal_ms=" + std::to_string(GateMs(t_all)));
        return false;
      }
      size_t at = 0, i = 0;
      while (i < scored) {
        const size_t tab = reply.find('\t', at);
        const std::string field = reply.substr(at, tab == std::string::npos ? std::string::npos : tab - at);
        const double value = std::strtod(field.c_str(), nullptr);
        if (!field.empty() && value == value) points[i] = value;
        ++i;
        if (tab == std::string::npos) break;
        at = tab + 1;
      }
      if (i < scored) {
        GateLog(log + "\tdecision=fallback_score_count\ttotal_ms=" + std::to_string(GateMs(t_all)));
        return false;
      }
    }
    log += "\tscore_ms=" + std::to_string(GateMs(t_score)) + "\tscored=" + std::to_string(scored);
    std::vector<size_t> order(scored);
    for (size_t i = 0; i < scored; ++i) order[i] = i;
    std::stable_sort(order.begin(), order.end(), [&](size_t a, size_t b) { return points[a] > points[b]; });
    bool best_unrealizable = false;
    for (size_t rank = 0; rank < order.size(); ++rank) {
      const GateEntry& entry = entries[order[rank]];
      if (points[order[rank]] <= -1e299) break;
      std::vector<int> indices;
      if (!GateRealize(entry, pos, *segments, key, original, &indices)) {
        if (rank == 0) best_unrealizable = true;
        continue;
      }
      for (size_t i = 0; i < count; ++i)
        if (indices[i] != 0) segments->mutable_conversion_segment(i)->move_candidate(indices[i], 0);
      GateLog(log + "\tdecision=skip\tchosen_rank=" + std::to_string(order[rank]) + "\tchosen=" +
              std::string(entry.n ? "n" : "") + (entry.w ? "w" : "") + (entry.c ? "c" : "") +
              "\tbest_unrealizable=" + (best_unrealizable ? "1" : "0") + "\ttotal_ms=" + std::to_string(GateMs(t_all)));
      return true;
    }
    GateLog(log + "\tdecision=fallback_realize\ttotal_ms=" + std::to_string(GateMs(t_all)));
    return false;
  }
