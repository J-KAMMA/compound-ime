namespace {
// MYIME_TYPO_MARGIN: how much cheaper (in Mozc's cost units) a one-key fix of
// readable romaji must read than what was typed; "off" turns the fix off.
std::optional<int> ReadableTypoMargin() {
  static const std::optional<int> margin = []() -> std::optional<int> {
    constexpr int kDefault = 3000;
    const char* value = std::getenv("MYIME_TYPO_MARGIN");
    if (value == nullptr || *value == '\0') return kDefault;
    if (std::string_view(value) == "off") return std::nullopt;
    const long parsed = std::strtol(value, nullptr, 10);
    return parsed > 0 ? static_cast<int>(parsed) : kDefault;
  }();
  return margin;
}

// Words of the dictionary at the start of a kana string: (bytes, lid, rid, cost).
using PrefixWords = std::vector<std::tuple<size_t, uint16_t, uint16_t, int>>;

class PrefixCollector : public dictionary::DictionaryInterface::Callback {
 public:
  explicit PrefixCollector(PrefixWords* out) : out_(out) {}
  ResultType OnToken(absl::string_view key, absl::string_view actual_key,
                     const dictionary::Token& token) override {
    if (key == actual_key) out_->emplace_back(key.size(), token.lid, token.rid, token.cost);
    return TRAVERSE_CONTINUE;
  }

 private:
  PrefixWords* out_;
};

// Only the words whose reading is exactly |bytes| long: a word reading shorter
// than that is skipped before its tokens are decoded.
class ExactLengthCollector : public dictionary::DictionaryInterface::Callback {
 public:
  ExactLengthCollector(size_t bytes, PrefixWords* out) : bytes_(bytes), out_(out) {}
  ResultType OnKey(absl::string_view key) {
    return key.size() == bytes_ ? TRAVERSE_CONTINUE : TRAVERSE_NEXT_KEY;
  }
  ResultType OnToken(absl::string_view key, absl::string_view actual_key,
                     const dictionary::Token& token) override {
    if (key == actual_key && key.size() == bytes_) {
      out_->emplace_back(key.size(), token.lid, token.rid, token.cost);
    }
    return TRAVERSE_CONTINUE;
  }

 private:
  size_t bytes_;
  PrefixWords* out_;
};

// 読みの費用の途中経過の記憶（打鍵をまたいで使い回す）。
// ReadingCost は、読みの先頭から j 文字目までの状態（次の語の左の番号 -> 費用）を
// j 文字目までの文字列だけで決める。そこで先頭からの文字列ごとに状態を覚え、打鍵で
// 読みが1文字伸びたら、増えた分の位置だけを計算する。辞書と接続の費用が同じなら、
// 覚えた値は計算し直した値と一致する（純粋な関数の使い回し）。
// 辞書や学習の更新（InvalidateReadingMemo）、辞書の作り直し、数分の経過、大きさの上限で捨てる。
using ReadingStates = std::unordered_map<uint16_t, int64_t>;
struct ReadingNode {
  std::shared_ptr<const ReadingStates> full;    // その位置の状態そのまま（最後の位置の答えに使う）
  std::shared_ptr<const ReadingStates> pruned;  // 次の語へ進むときの元（安い30個まで）
};
struct ReadingMemo {
  std::mutex mutex;
  std::unordered_map<std::string, ReadingNode> nodes;
  const void* owner = nullptr;
  uint64_t generation = 0;
  std::chrono::steady_clock::time_point started;
};
std::atomic<uint64_t> g_reading_generation{0};
ReadingMemo& GetReadingMemo() {
  static ReadingMemo* const memo = new ReadingMemo;
  return *memo;
}

// The cheapest way to read |kana| as dictionary words, with word costs and
// connection costs from the sentence start to its end; a kana no word covers
// costs kUnknownCost as a common noun. The 30 cheapest states are kept at each
// position. The states at each prefix of |kana| are remembered (ReadingMemo), so a
// reading that only grew by a key costs the new positions only. |cache| is unused.
int64_t ReadingCost(const engine::Modules& modules, absl::string_view kana,
                    std::unordered_map<std::string, PrefixWords>* /*cache*/) {
  constexpr uint16_t kUnknownPos = 1851;  // 名詞,一般
  constexpr int kUnknownCost = 8000;
  constexpr size_t kBeam = 30;
  constexpr size_t kMaxNodes = 16000;
  constexpr auto kMaxAge = std::chrono::minutes(5);
  std::vector<size_t> at;  // byte offset of each kana, and the end
  for (size_t i = 0; i < kana.size();) {
    at.push_back(i);
    const auto b = static_cast<unsigned char>(kana[i]);
    i += b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
  }
  at.push_back(kana.size());
  const size_t n = at.size() - 1;
  const Connector& connector = modules.GetConnector();

  ReadingMemo& memo = GetReadingMemo();
  std::lock_guard<std::mutex> lock(memo.mutex);
  const void* const owner = static_cast<const void*>(&modules);
  const uint64_t generation = g_reading_generation.load();
  const auto now = std::chrono::steady_clock::now();
  if (memo.owner != owner || memo.generation != generation || memo.nodes.size() > kMaxNodes ||
      now - memo.started > kMaxAge) {
    memo.nodes.clear();
    memo.owner = owner;
    memo.generation = generation;
    memo.started = now;
  }

  std::vector<std::shared_ptr<const ReadingStates>> full(n + 1), pruned(n + 1);
  for (size_t k = 0; k <= n; ++k) {
    std::string prefix(kana.substr(0, at[k]));
    const auto found = memo.nodes.find(prefix);
    if (found != memo.nodes.end()) {
      full[k] = found->second.full;
      pruned[k] = found->second.pruned;
      continue;
    }
    ReadingStates states;  // rid -> cost
    if (k == 0) states[0] = 0;
    for (size_t i = 0; i < k; ++i) {
      const ReadingStates& here = *pruned[i];
      if (here.empty()) continue;
      const absl::string_view piece = kana.substr(at[i], at[k] - at[i]);
      PrefixWords words;
      ExactLengthCollector collect(piece.size(), &words);
      modules.GetDictionary().LookupPrefix(piece, &collect);
      for (const auto& [rid, cost] : here) {
        const auto step = [&](uint16_t lid, uint16_t next_rid, int word_cost) {
          const int64_t total = cost + word_cost + connector.GetTransitionCost(rid, lid);
          auto [it, added] = states.try_emplace(next_rid, total);
          if (!added && total < it->second) it->second = total;
        };
        for (const auto& [bytes, lid, next_rid, word_cost] : words) {
          step(lid, next_rid, word_cost);
        }
        if (i + 1 == k) step(kUnknownPos, kUnknownPos, kUnknownCost);
      }
    }
    std::shared_ptr<const ReadingStates> all(new ReadingStates(std::move(states)));
    std::shared_ptr<const ReadingStates> kept = all;
    if (all->size() > kBeam) {
      std::vector<std::pair<uint16_t, int64_t>> sorted(all->begin(), all->end());
      std::nth_element(sorted.begin(), sorted.begin() + kBeam, sorted.end(),
                       [](const auto& a, const auto& b) { return a.second < b.second; });
      sorted.resize(kBeam);
      kept.reset(new ReadingStates(sorted.begin(), sorted.end()));
    }
    full[k] = all;
    pruned[k] = kept;
    memo.nodes.emplace(std::move(prefix), ReadingNode{all, kept});
  }
  int64_t best = std::numeric_limits<int64_t>::max();
  for (const auto& [rid, cost] : *full[n]) {
    best = std::min(best, cost + connector.GetTransitionCost(rid, 0));
  }
  return best;
}

// A slip in romaji that still reads as kana ("tsuduukete": つづうけて): the
// edit (jaen::ReadableTypoEdits) whose reading plus its prior is cheapest,
// when it is at least |margin| cheaper than what was typed.
std::optional<std::string> FixReadableTypo(const engine::Modules& modules, absl::string_view raw,
                                           const jaen::RomajiParser& parse, int margin) {
  std::vector<jaen::TypoEdit> edits = jaen::ReadableTypoEdits(raw, parse);
  if (edits.empty()) return std::nullopt;
  const std::vector<jaen::Chunk> chunks = parse(raw);
  std::string typed;
  for (size_t i = 0; i < chunks.size(); ++i) {
    const bool final_n = i + 1 == chunks.size() && chunks[i].conversion.empty() && chunks[i].pending == "n";
    typed += final_n ? std::string("ん") : chunks[i].conversion + chunks[i].pending;
  }
  std::unordered_map<std::string, PrefixWords> cache;
  int64_t best = ReadingCost(modules, typed, &cache) - margin;
  std::optional<std::string> fixed;
  for (jaen::TypoEdit& edit : edits) {
    const int64_t cost = ReadingCost(modules, edit.kana, &cache) + edit.prior;
    if (cost < best) {
      best = cost;
      fixed = std::move(edit.keys);
    }
  }
  return fixed;
}
}  // namespace

// 辞書や学習が更新されたとき（利用者辞書の再読み込み、履歴の消去など）に呼び、読みの費用の記憶を捨てる。
void InvalidateReadingMemo() { g_reading_generation.fetch_add(1); }
