#include "dictionary/supplement_dictionary.h"

#include <cstddef>
#include <cstdint>
#include <iterator>
#include <string>
#include <unordered_set>
#include <utility>

#include "absl/strings/string_view.h"
#include "dictionary/dictionary_token.h"

namespace mozc {
namespace dictionary {
namespace {

using ::dict_update::SupplementTable;
using Callback = DictionaryInterface::Callback;

// 本体に焼き込んだ追加の辞書（dictionary14.txt）の行の印（FNV-1a 64。tools/apply_dict_update.py が作る）。
// 取った辞書の行がこれと同じなら、焼き込みの辞書がすでに引くので、ここでは出さない（二重にすると、
// 同じ語が2回のり、費用が同じ候補の並びが変わる）。印の作り方は tools/apply_dict_update.py の bake_hash と同じ。
#include "dictionary/supplement_baked.inc"  // kBakedSupplementHashes

uint64_t EntryHash(const ::dict_update::SupplementEntry& e) {
  uint64_t h = 1469598103934665603ULL;
  auto add = [&h](const std::string& s) {
    for (unsigned char c : s) {
      h ^= c;
      h *= 1099511628211ULL;
    }
    h ^= '\t';
    h *= 1099511628211ULL;
  };
  add(e.key);
  add(e.value);
  add(std::to_string(e.lid));
  add(std::to_string(e.rid));
  add(std::to_string(e.cost));
  return h;
}

const std::unordered_set<uint64_t>& Baked() {
  static const std::unordered_set<uint64_t>* const set =
      new std::unordered_set<uint64_t>(std::begin(kBakedSupplementHashes), std::end(kBakedSupplementHashes));
  return *set;
}

bool IsBaked(const ::dict_update::SupplementEntry& e) { return Baked().count(EntryHash(e)) > 0; }

// [begin, end) の行を、読みごとにまとめて callback に渡す。同じ読みの行は続いて並んでいる。
// 返り値が false なら、callback が打ち切りを求めた（DONE）。
bool Emit(const SupplementTable& table, size_t begin, size_t end, Callback* callback) {
  size_t i = begin;
  while (i < end) {
    const std::string& key = table.at(i).key;
    size_t j = i;
    while (j < end && table.at(j).key == key) ++j;
    bool any = false;  // 焼き込みと同じ行だけの読みは、出さない
    for (size_t k = i; k < j && !any; ++k) any = !IsBaked(table.at(k));
    if (!any) {
      i = j;
      continue;
    }
    const Callback::ResultType on_key = callback->OnKey(key);
    if (on_key == Callback::TRAVERSE_DONE) return false;
    if (on_key == Callback::TRAVERSE_NEXT_KEY || on_key == Callback::TRAVERSE_CULL) {
      i = j;
      continue;
    }
    const Callback::ResultType on_actual = callback->OnActualKey(key, key, /* num_expanded= */ 0);
    if (on_actual == Callback::TRAVERSE_DONE) return false;
    if (on_actual == Callback::TRAVERSE_NEXT_KEY || on_actual == Callback::TRAVERSE_CULL) {
      i = j;
      continue;
    }
    for (size_t k = i; k < j; ++k) {
      const ::dict_update::SupplementEntry& e = table.at(k);
      if (IsBaked(e)) continue;
      const Token token(e.key, e.value, e.cost, e.lid, e.rid, Token::NONE);
      const Callback::ResultType on_token = callback->OnToken(key, key, token);
      if (on_token == Callback::TRAVERSE_DONE) return false;
      if (on_token == Callback::TRAVERSE_NEXT_KEY || on_token == Callback::TRAVERSE_CULL) break;
    }
    i = j;
  }
  return true;
}

}  // namespace

SupplementDictionary& SupplementDictionary::Instance() {
  static SupplementDictionary* const instance = new SupplementDictionary();
  return *instance;
}

void SupplementDictionary::Set(std::shared_ptr<const SupplementTable> table) {
  std::lock_guard<std::mutex> lock(mutex_);
  table_ = std::move(table);
}

std::shared_ptr<const SupplementTable> SupplementDictionary::Get() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return table_;
}

bool SupplementDictionary::HasKey(absl::string_view key) const {
  const auto table = Get();
  return table && !key.empty() && table->HasKey(std::string_view(key.data(), key.size()));
}

bool SupplementDictionary::HasValue(absl::string_view value) const {
  const auto table = Get();
  return table && !value.empty() && table->HasValue(std::string_view(value.data(), value.size()));
}

void SupplementDictionary::LookupPredictive(absl::string_view key, Callback* callback) const {
  const auto table = Get();
  if (!table || key.empty()) return;
  const auto range = table->PredictiveRange(std::string_view(key.data(), key.size()));
  Emit(*table, range.first, range.second, callback);
}

void SupplementDictionary::LookupPrefix(absl::string_view key, Callback* callback) const {
  const auto table = Get();
  if (!table || key.empty()) return;
  // 短い読みから順に（システム辞書と同じ並び）。UTF-8 の文字の切れ目だけで切る。
  for (size_t length = 1; length <= key.size(); ++length) {
    if (length < key.size() && (static_cast<unsigned char>(key[length]) & 0xC0) == 0x80) continue;
    const auto range = table->ExactRange(std::string_view(key.data(), length));
    if (range.first == range.second) continue;
    if (!Emit(*table, range.first, range.second, callback)) return;
  }
}

void SupplementDictionary::LookupExact(absl::string_view key, Callback* callback) const {
  const auto table = Get();
  if (!table || key.empty()) return;
  const auto range = table->ExactRange(std::string_view(key.data(), key.size()));
  Emit(*table, range.first, range.second, callback);
}

}  // namespace dictionary
}  // namespace mozc
