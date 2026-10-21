// 英語の一覧の追加（SetEnglishExtra）の試験。Bazel なしで、作業ツリーの converter/ と dict_update/data.cc で組み立てる:
//   g++ -std=c++20 -w -I <mozc/src> -I <stub: base/system_util.h> <mozc/src>/converter/{english_lexicon,jaen_detector,jaen_choices,correction_log,jaen_typo}.cc \
//       <mozc/src>/dict_update/data.cc english_extra_test.cc -o english_extra_test
#include <iostream>
#include <memory>
#include <thread>
#include <vector>

#include "converter/english_lexicon.h"
#include "dict_update/data.h"

using namespace mozc::converter;

static int g_failed = 0;
#define CHECK(c) do { if (!(c)) { ++g_failed; std::cerr << __LINE__ << ": " #c "\n"; } } while (0)

int main() {
  const jaen::Lexicon* before = &EnglishLexicon();
  CHECK(!before->IsNamed("zzyzxtool"));
  CHECK(BrandCasing("zzyzxtool").empty());
  std::string error;
  auto extra = dict_update::ParseEnglishExtra(
      "named\tzzyzxtool\nsignal\tzzyzxsignal\ncurated\tzzyzxword\nphrase\tzzyzx test phrase\ncasing\tzzyzxtool\tZzyzxTool\n"
      "casing\tgithub\tGitHub!\ncasing2\tzzyzxsignal\tZzyzxSignal\n",
      dict_update::EnglishLimits(), &error);
  CHECK(extra != nullptr);
  SetEnglishExtra(extra);
  const jaen::Lexicon& after = EnglishLexicon();
  CHECK(&after != before);
  CHECK(after.IsNamed("zzyzxtool"));
  CHECK(after.IsSignalOnly("zzyzxsignal"));
  CHECK(after.IsCurated("zzyzxword"));
  CHECK(after.FindPhrase("zzyzxtestphrase") != nullptr);
  CHECK(!before->IsNamed("zzyzxtool"));  // 前の世代は変わらない（使っている処理を妨げない）
  CHECK(BrandCasing("zzyzxtool") == "ZzyzxTool");
  CHECK(BrandCasingSecond("zzyzxsignal") == "ZzyzxSignal");
  CHECK(BrandCasing("github") != "GitHub!");  // 焼き込んだ表にある語の表示の形は変えない（なければ足す）
  // 何度入れ替えても、前の世代が3つのあいだは生きている
  std::vector<const jaen::Lexicon*> seen;
  for (int i = 0; i < 6; ++i) {
    SetEnglishExtra(extra);
    seen.push_back(&EnglishLexicon());
  }
  CHECK(seen.back()->IsNamed("zzyzxtool") && seen[seen.size() - 2]->IsNamed("zzyzxtool"));
  // 引きながら入れ替えても落ちない
  std::thread reader([&] { for (int i = 0; i < 20000; ++i) { (void)EnglishLexicon().IsNamed("zzyzxtool"); (void)BrandCasing("zzyzxtool"); } });
  for (int i = 0; i < 20; ++i) SetEnglishExtra(i % 2 ? extra : nullptr);
  reader.join();
  SetEnglishExtra(nullptr);
  CHECK(&EnglishLexicon() == before);  // 外すと、焼き込んだ一覧に戻る
  CHECK(BrandCasing("zzyzxtool").empty());
  std::cout << (g_failed ? "FAILED" : "ok") << "\n";
  return g_failed ? 1 : 0;
}
