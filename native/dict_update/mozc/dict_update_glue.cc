#include "converter/dict_update_glue.h"

#include <atomic>
#include <cstdlib>
#include <memory>
#include <mutex>
#include <string>

#include "converter/english_lexicon.h"
#include "dict_update/fetcher.h"
#include "dict_update/service.h"
#include "dictionary/supplement_dictionary.h"

namespace mozc::converter {
void InvalidateReadingMemo();  // 読みの費用の記憶を捨てる（converter/converter.cc）
}

namespace mozc::converter {
namespace {

// apply_dict_update.py が、組み立ての元の木（data/dictionary_oss/id.def）と tools/dict-update から書く。
constexpr char kPosTableSha256[] = "@@POS_SHA@@";
constexpr size_t kPosCount = @@POS_COUNT@@;
constexpr int kNounId = @@NOUN_ID@@;  // 名詞,固有名詞,一般（試験の語の品詞）
constexpr char kPublicKeyHex[] = "@@PUBLIC_KEY@@";
constexpr char kManifestUrl[] = "@@MANIFEST_URL@@";
constexpr char kUrlPrefix[] = "@@URL_PREFIX@@";

std::atomic<bool> g_in_update_check{false};

::dict_update::BakedValues Baked() {
  ::dict_update::BakedValues baked;
  baked.manifest_url = kManifestUrl;
  baked.url_prefix = kUrlPrefix;
  baked.public_key_hex = kPublicKeyHex;
  baked.pos_table_sha256 = kPosTableSha256;
  baked.pos_count = kPosCount;
  return baked;
}

// 読み直し: 追加の辞書と英語の一覧を入れ替え、読みの費用の記憶を捨てる。
// 試験のときだけ、MYIME_DICT_UPDATE_FAIL_APPLY で、更新の確かめの中の読み直しの失敗をまねられる。
bool Apply(const ::dict_update::Snapshot& snap) {
  if (g_in_update_check.load() && ::dict_update::IsHermeticTest() && std::getenv("MYIME_DICT_UPDATE_FAIL_APPLY")) {
    return false;
  }
  dictionary::DictTrace("Apply version=" + std::to_string(snap.version) + " in_check=" + (g_in_update_check.load() ? "1" : "0"));
  dictionary::SupplementDictionary::Instance().Set(snap.table);
  SetEnglishExtra(snap.english);
  InvalidateReadingMemo();
  return true;
}

std::mutex g_mutex;
std::unique_ptr<::dict_update::Service> g_service;

// 置き場所などが決められなければ nullptr。
::dict_update::Service* GetService() {
  if (g_service) return g_service.get();
  ::dict_update::Config config;
  if (!::dict_update::MakeConfig(Baked(), &config)) return nullptr;
  std::unique_ptr<::dict_update::Fetcher> fetcher = ::dict_update::MakeFetcher(config);
  g_service = std::make_unique<::dict_update::Service>(std::move(config), [] { return ::dict_update::ReadSettings(); },
                                                       std::move(fetcher), Apply);
  return g_service.get();
}

}  // namespace

void StartDictUpdateService() {
  std::lock_guard<std::mutex> lock(g_mutex);
  ::dict_update::Service* service = GetService();
  if (service == nullptr) return;
  service->Start(/* initial_delay_seconds= */ 120, /* confirm_after_seconds= */ 30);
}

void LoadDictUpdateForTest() {
  if (!::dict_update::IsHermeticTest()) return;
  std::lock_guard<std::mutex> lock(g_mutex);
  ::dict_update::Service* service = GetService();
  if (service == nullptr) return;
  service->Start(/* initial_delay_seconds= */ -1, 0);
}

std::string DictUpdateTestCommand(const std::string& command) {
  if (command == "DICT_UPDATE_INFO") {
    return std::string("DICT_UPDATE_INFO: pos_table_sha256=") + kPosTableSha256 + " pos_count=" + std::to_string(kPosCount) +
           " noun_id=" + std::to_string(kNounId);
  }
  std::lock_guard<std::mutex> lock(g_mutex);
  ::dict_update::Service* service = GetService();
  if (service == nullptr) return "DICT_UPDATE: status=no-config version=0";
  g_in_update_check = true;
  const ::dict_update::UpdateResult result = service->CheckNow(/* force= */ true);
  g_in_update_check = false;
  // 本体なら、30秒落ちずに動いたときに「確かめた」印を付ける。試験は短いので、すぐ付ける
  // （MYIME_DICT_UPDATE_NO_CONFIRM があれば付けない: 確かめる前に落ち続ける場合のまね）
  if (std::getenv("MYIME_DICT_UPDATE_NO_CONFIRM") == nullptr) service->updater().ConfirmTrial();
  return std::string("DICT_UPDATE: status=") + ::dict_update::StatusName(result.status) +
         " version=" + std::to_string(result.version) + " detail=" + result.detail;
}

}  // namespace mozc::converter
