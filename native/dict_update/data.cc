#include "dict_update/data.h"

#include <algorithm>
#include <cstdlib>

namespace dict_update {
namespace {

std::vector<std::string_view> SplitTabs(std::string_view line) {
  std::vector<std::string_view> fields;
  size_t start = 0;
  while (true) {
    const size_t tab = line.find('\t', start);
    if (tab == std::string_view::npos) {
      fields.push_back(line.substr(start));
      return fields;
    }
    fields.push_back(line.substr(start, tab - start));
    start = tab + 1;
  }
}

bool ParseUint(std::string_view s, size_t max_digits, uint64_t* out) {
  if (s.empty() || s.size() > max_digits) return false;
  uint64_t v = 0;
  for (char c : s) {
    if (c < '0' || c > '9') return false;
    v = v * 10 + static_cast<uint64_t>(c - '0');
  }
  *out = v;
  return true;
}

std::string LineError(size_t number, const char* reason) {
  return "line " + std::to_string(number) + ": " + reason;
}

// text を行に分ける（CRLF も受け付ける）。最後の行に改行がなくてもよい。
template <typename Fn>
bool ForEachLine(std::string_view text, Fn&& fn) {
  size_t number = 0, start = 0;
  while (start <= text.size()) {
    size_t end = text.find('\n', start);
    if (end == std::string_view::npos) end = text.size();
    std::string_view line = text.substr(start, end - start);
    if (!line.empty() && line.back() == '\r') line.remove_suffix(1);
    ++number;
    if (!line.empty() && line[0] != '#') {
      if (!fn(number, line)) return false;
    }
    if (end == text.size()) break;
    start = end + 1;
  }
  return true;
}

bool IsLowerWord(std::string_view w, size_t max_len) {
  if (w.empty() || w.size() > max_len) return false;
  for (char c : w) {
    if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '\'')) return false;
  }
  return true;
}

// 小文字で打った名前（空白は語の間に1つ。new york）
bool IsCasingKey(std::string_view w) {
  if (w.empty() || w.size() > 80 || w.front() == ' ' || w.back() == ' ') return false;
  for (size_t i = 0; i < w.size(); ++i) {
    const char c = w[i];
    if (c == ' ') {
      if (w[i - 1] == ' ') return false;
    } else if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '\'')) {
      return false;
    }
  }
  return true;
}

// 表示の形（Google、Hermès）。引用符とバックスラッシュは本体の表に書けない形なので受け付けない。
bool IsShownForm(std::string_view w) {
  if (w.empty() || w.size() > 64 || !IsCleanUtf8(w)) return false;
  return w.find('"') == std::string_view::npos && w.find('\\') == std::string_view::npos;
}

}  // namespace

bool IsCleanUtf8(std::string_view s) {
  size_t i = 0;
  while (i < s.size()) {
    const unsigned char c = static_cast<unsigned char>(s[i]);
    size_t len;
    uint32_t cp;
    if (c < 0x80) {
      len = 1;
      cp = c;
    } else if (c >= 0xC2 && c <= 0xDF) {
      len = 2;
      cp = c & 0x1F;
    } else if (c >= 0xE0 && c <= 0xEF) {
      len = 3;
      cp = c & 0x0F;
    } else if (c >= 0xF0 && c <= 0xF4) {
      len = 4;
      cp = c & 0x07;
    } else {
      return false;
    }
    if (i + len > s.size()) return false;
    for (size_t k = 1; k < len; ++k) {
      const unsigned char d = static_cast<unsigned char>(s[i + k]);
      if ((d & 0xC0) != 0x80) return false;
      cp = (cp << 6) | (d & 0x3F);
    }
    if ((len == 3 && cp < 0x800) || (len == 4 && (cp < 0x10000 || cp > 0x10FFFF))) return false;
    if (cp >= 0xD800 && cp <= 0xDFFF) return false;
    if (cp < 0x20 || cp == 0x7F) return false;  // 制御文字（タブ・改行を含む）
    i += len;
  }
  return true;
}

std::shared_ptr<const SupplementTable> SupplementTable::Parse(std::string_view text,
                                                              const SupplementLimits& limits, std::string* error) {
  auto table = std::make_shared<SupplementTable>();
  std::vector<SupplementEntry>& entries = table->entries_;
  std::string failure;
  const bool ok = ForEachLine(text, [&](size_t number, std::string_view line) {
    const std::vector<std::string_view> f = SplitTabs(line);
    if (f.size() != 5) {
      failure = LineError(number, "5 columns expected");
      return false;
    }
    uint64_t lid, rid, cost;
    if (!ParseUint(f[1], 5, &lid) || !ParseUint(f[2], 5, &rid) || lid >= limits.pos_count ||
        rid >= limits.pos_count) {
      failure = LineError(number, "bad part-of-speech id");
      return false;
    }
    if (!ParseUint(f[3], 6, &cost) || cost > static_cast<uint64_t>(limits.max_cost)) {
      failure = LineError(number, "bad cost");
      return false;
    }
    if (f[0].empty() || f[0].size() > limits.max_key_bytes || !IsCleanUtf8(f[0])) {
      failure = LineError(number, "bad reading");
      return false;
    }
    if (f[4].empty() || f[4].size() > limits.max_value_bytes || !IsCleanUtf8(f[4])) {
      failure = LineError(number, "bad surface");
      return false;
    }
    if (entries.size() >= limits.max_entries) {
      failure = LineError(number, "too many entries");
      return false;
    }
    SupplementEntry e;
    e.key = std::string(f[0]);
    e.value = std::string(f[4]);
    e.lid = static_cast<uint16_t>(lid);
    e.rid = static_cast<uint16_t>(rid);
    e.cost = static_cast<int>(cost);
    entries.push_back(std::move(e));
    return true;
  });
  if (!ok) {
    if (error) *error = failure;
    return nullptr;
  }
  std::sort(entries.begin(), entries.end(), [](const SupplementEntry& a, const SupplementEntry& b) {
    if (a.key != b.key) return a.key < b.key;
    if (a.value != b.value) return a.value < b.value;
    return a.cost < b.cost;
  });
  entries.erase(std::unique(entries.begin(), entries.end(),
                            [](const SupplementEntry& a, const SupplementEntry& b) {
                              return a.key == b.key && a.value == b.value;  // 費用の小さいほうが先に残る
                            }),
                entries.end());
  for (const SupplementEntry& e : entries) table->values_sorted_.push_back(e.value);
  std::sort(table->values_sorted_.begin(), table->values_sorted_.end());
  table->values_sorted_.erase(std::unique(table->values_sorted_.begin(), table->values_sorted_.end()),
                              table->values_sorted_.end());
  return table;
}

std::pair<size_t, size_t> SupplementTable::ExactRange(std::string_view key) const {
  auto lo = std::lower_bound(entries_.begin(), entries_.end(), key,
                             [](const SupplementEntry& e, std::string_view k) { return e.key < k; });
  auto hi = std::upper_bound(lo, entries_.end(), key,
                             [](std::string_view k, const SupplementEntry& e) { return k < e.key; });
  return {static_cast<size_t>(lo - entries_.begin()), static_cast<size_t>(hi - entries_.begin())};
}

std::pair<size_t, size_t> SupplementTable::PredictiveRange(std::string_view key) const {
  auto lo = std::lower_bound(entries_.begin(), entries_.end(), key,
                             [](const SupplementEntry& e, std::string_view k) { return e.key < k; });
  auto hi = lo;
  while (hi != entries_.end() && std::string_view(hi->key).substr(0, key.size()) == key) ++hi;
  return {static_cast<size_t>(lo - entries_.begin()), static_cast<size_t>(hi - entries_.begin())};
}

bool SupplementTable::HasKey(std::string_view key) const {
  const auto r = ExactRange(key);
  return r.first != r.second;
}

bool SupplementTable::HasValue(std::string_view value) const {
  return std::binary_search(values_sorted_.begin(), values_sorted_.end(), std::string(value));
}

std::shared_ptr<const EnglishExtra> ParseEnglishExtra(std::string_view text, const EnglishLimits& limits,
                                                      std::string* error) {
  auto extra = std::make_shared<EnglishExtra>();
  std::string failure;
  size_t rows = 0;
  const bool ok = ForEachLine(text, [&](size_t number, std::string_view line) {
    const std::vector<std::string_view> f = SplitTabs(line);
    if (++rows > limits.max_rows) {
      failure = LineError(number, "too many rows");
      return false;
    }
    const std::string_view kind = f[0];
    if (kind == "curated" || kind == "named" || kind == "signal") {
      if (f.size() != 2 || !IsLowerWord(f[1], 40)) {
        failure = LineError(number, "bad word");
        return false;
      }
      auto& list = kind == "curated" ? extra->curated : kind == "named" ? extra->named : extra->signal;
      list.emplace_back(f[1]);
    } else if (kind == "phrase") {
      if (f.size() != 2 || f[1].size() > 80 || f[1].find(' ') == std::string_view::npos) {
        failure = LineError(number, "bad phrase");
        return false;
      }
      size_t start = 0;
      while (start <= f[1].size()) {  // 語は小文字の語を1つの空白で区切ったもの
        size_t end = f[1].find(' ', start);
        if (end == std::string_view::npos) end = f[1].size();
        if (!IsLowerWord(f[1].substr(start, end - start), 24)) {
          failure = LineError(number, "bad phrase");
          return false;
        }
        if (end == f[1].size()) break;
        start = end + 1;
      }
      extra->phrases.emplace_back(f[1]);
    } else if (kind == "casing" || kind == "casing2") {
      if (f.size() != 3 || !IsCasingKey(f[1]) || !IsShownForm(f[2])) {
        failure = LineError(number, "bad casing");
        return false;
      }
      (kind == "casing" ? extra->casing : extra->casing2).emplace_back(std::string(f[1]), std::string(f[2]));
    } else {
      failure = LineError(number, "unknown kind");
      return false;
    }
    return true;
  });
  if (!ok) {
    if (error) *error = failure;
    return nullptr;
  }
  for (auto* list : {&extra->casing, &extra->casing2}) {
    std::stable_sort(list->begin(), list->end(),
                     [](const auto& a, const auto& b) { return a.first < b.first; });
    list->erase(std::unique(list->begin(), list->end(),
                            [](const auto& a, const auto& b) { return a.first == b.first; }),
                list->end());  // 同じ打った形は最初の1つだけ
  }
  return extra;
}

}  // namespace dict_update
