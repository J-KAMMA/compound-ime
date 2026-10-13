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

// The cheapest way to read |kana| as dictionary words, with word costs and
// connection costs from the sentence start to its end; a kana no word covers
// costs kUnknownCost as a common noun. The 30 cheapest states are kept at each
// position. |cache| holds the dictionary words found at each remaining string.
int64_t ReadingCost(const engine::Modules& modules, absl::string_view kana,
                    std::unordered_map<std::string, PrefixWords>* cache) {
  constexpr uint16_t kUnknownPos = 1851;  // 名詞,一般
  constexpr int kUnknownCost = 8000;
  constexpr size_t kBeam = 30;
  std::vector<size_t> at;  // byte offset of each kana, and the end
  for (size_t i = 0; i < kana.size();) {
    at.push_back(i);
    const auto b = static_cast<unsigned char>(kana[i]);
    i += b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
  }
  at.push_back(kana.size());
  const size_t n = at.size() - 1;
  std::vector<std::unordered_map<uint16_t, int64_t>> states(n + 1);  // rid -> cost
  states[0][0] = 0;
  const Connector& connector = modules.GetConnector();
  for (size_t i = 0; i < n; ++i) {
    auto& here = states[i];
    if (here.empty()) continue;
    if (here.size() > kBeam) {
      std::vector<std::pair<uint16_t, int64_t>> sorted(here.begin(), here.end());
      std::nth_element(sorted.begin(), sorted.begin() + kBeam, sorted.end(),
                       [](const auto& a, const auto& b) { return a.second < b.second; });
      sorted.resize(kBeam);
      here = std::unordered_map<uint16_t, int64_t>(sorted.begin(), sorted.end());
    }
    const std::string rest(kana.substr(at[i]));
    auto found = cache->find(rest);
    if (found == cache->end()) {
      PrefixWords words;
      PrefixCollector collect(&words);
      modules.GetDictionary().LookupPrefix(rest, &collect);
      found = cache->emplace(rest, std::move(words)).first;
    }
    for (const auto& [rid, cost] : here) {
      const auto step = [&](size_t end, uint16_t lid, uint16_t next_rid, int word_cost) {
        const int64_t total = cost + word_cost + connector.GetTransitionCost(rid, lid);
        auto [it, added] = states[end].try_emplace(next_rid, total);
        if (!added && total < it->second) it->second = total;
      };
      for (const auto& [bytes, lid, next_rid, word_cost] : found->second) {
        const auto end = std::lower_bound(at.begin(), at.end(), at[i] + bytes);
        if (end != at.end() && *end == at[i] + bytes) {
          step(static_cast<size_t>(end - at.begin()), lid, next_rid, word_cost);
        }
      }
      step(i + 1, kUnknownPos, kUnknownPos, kUnknownCost);
    }
  }
  int64_t best = std::numeric_limits<int64_t>::max();
  for (const auto& [rid, cost] : states[n]) {
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
