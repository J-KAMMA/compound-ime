#include "dictionary/supplement_dictionary.h"

#include <cstddef>
#include <string>
#include <utility>

#include "absl/strings/string_view.h"
#include "dictionary/dictionary_token.h"

namespace mozc {
namespace dictionary {
namespace {

using ::dict_update::SupplementTable;
using Callback = DictionaryInterface::Callback;

// [begin, end) の行を、読みごとにまとめて callback に渡す。同じ読みの行は続いて並んでいる。
// 返り値が false なら、callback が打ち切りを求めた（DONE）。
bool Emit(const SupplementTable& table, size_t begin, size_t end, Callback* callback) {
  size_t i = begin;
  while (i < end) {
    const std::string& key = table.at(i).key;
    size_t j = i;
    while (j < end && table.at(j).key == key) ++j;
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
