// 追加の辞書の Mozc 側の部品（SupplementDictionary）の試験。Mozc の dictionary_interface.h にそのまま合うかも確かめる。
// absl と protobuf の入れ物（stub）だけあれば、Bazel なしで組み立てて動く（tools/dict_update_scenarios.py とは別）:
//   g++ -std=c++20 -I <mozc/src> -I <absl・protobuf の stub> <mozc/src>/dictionary/supplement_dictionary.cc \
//       <mozc/src>/dict_update/data.cc supplement_dictionary_test.cc -o supplement_dictionary_test
// stub: absl/strings/string_view.h（absl::string_view = std::string_view）と、protocol/user_dictionary_storage.pb.h
//       （namespace user_dictionary にクラスの宣言だけ）。
#include <iostream>
#include <string>
#include <vector>

#include "dict_update/data.h"
#include "dictionary/supplement_dictionary.h"

using mozc::dictionary::DictionaryInterface;
using mozc::dictionary::SupplementDictionary;

namespace {
int g_failed = 0;
#define CHECK(c) do { if (!(c)) { ++g_failed; std::cerr << __LINE__ << ": " #c "\n"; } } while (0)

struct Recorder : DictionaryInterface::Callback {
  std::vector<std::string> keys, tokens;
  int cost_of_last = 0;
  unsigned lid = 0, rid = 0;
  ResultType stop_at_key = TRAVERSE_CONTINUE;
  ResultType OnKey(absl::string_view key) override {
    keys.emplace_back(key);
    return stop_at_key;
  }
  ResultType OnToken(absl::string_view key, absl::string_view actual, const mozc::dictionary::Token& token) override {
    CHECK(key == actual && key == token.key);
    tokens.push_back(token.value);
    cost_of_last = token.cost;
    lid = token.lid;
    rid = token.rid;
    CHECK(token.attributes == mozc::dictionary::Token::NONE);
    return TRAVERSE_CONTINUE;
  }
};
}  // namespace

int main() {
  SupplementDictionary& dict = SupplementDictionary::Instance();
  Recorder empty;
  dict.LookupExact("ぐーぐる", &empty);
  CHECK(empty.tokens.empty());  // 何も入れていないときは空
  CHECK(!dict.HasKey("ぐーぐる"));

  std::string error;
  dict_update::SupplementLimits limits;
  limits.pos_count = 3000;
  auto table = dict_update::SupplementTable::Parse(
      "ぐーぐる\t1920\t1920\t6000\tGoogle\nぐーぐる\t1920\t1920\t6100\tGOOGLE\nぐーぐるまっぷ\t1921\t1922\t7000\tGoogle Maps\nぐ\t1\t1\t100\tG\n",
      limits, &error);
  CHECK(table != nullptr);
  dict.Set(table);

  Recorder exact;
  dict.LookupExact("ぐーぐる", &exact);
  CHECK(exact.keys.size() == 1 && exact.tokens.size() == 2 && exact.tokens[0] == "GOOGLE");  // (読み, 表記) の順
  CHECK(dict.HasKey("ぐーぐる") && dict.HasValue("Google Maps") && !dict.HasValue("Bing"));

  Recorder prefix;  // 読みの前の部分と一致する語を、短い読みから
  dict.LookupPrefix("ぐーぐるまっぷで", &prefix);
  CHECK(prefix.keys.size() == 3);
  CHECK(prefix.keys[0] == "ぐ" && prefix.keys[1] == "ぐーぐる" && prefix.keys[2] == "ぐーぐるまっぷ");
  CHECK(prefix.tokens.back() == "Google Maps" && prefix.cost_of_last == 7000 && prefix.lid == 1921 && prefix.rid == 1922);

  Recorder predictive;
  dict.LookupPredictive("ぐーぐ", &predictive);
  CHECK(predictive.keys.size() == 2);
  Recorder none;
  dict.LookupPredictive("", &none);
  CHECK(none.tokens.empty());  // 空の読みでは全部を返さない

  Recorder skip;  // 読みごとに打ち切る要求（TRAVERSE_NEXT_KEY）に従う
  skip.stop_at_key = DictionaryInterface::Callback::TRAVERSE_NEXT_KEY;
  dict.LookupPrefix("ぐーぐる", &skip);
  CHECK(skip.keys.size() == 2 && skip.tokens.empty());
  Recorder done;
  done.stop_at_key = DictionaryInterface::Callback::TRAVERSE_DONE;
  dict.LookupPrefix("ぐーぐる", &done);
  CHECK(done.keys.size() == 1);

  dict.Set(nullptr);  // 外す
  Recorder after;
  dict.LookupExact("ぐーぐる", &after);
  CHECK(after.tokens.empty());
  std::cout << (g_failed ? "FAILED" : "ok") << "\n";
  return g_failed ? 1 : 0;
}
