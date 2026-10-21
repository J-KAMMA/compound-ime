// 辞書の更新を、Mozc なしで端から端まで動かす道具（試験用）。実際の取得の部品（curl）と同じ経路を通る。
//   dict_update_tool info
//   dict_update_tool update <読み>...      起動時の読み込み → 更新の確かめ（force）→ 読みの候補、を出力する
//   dict_update_tool load <読み>...        起動時の読み込みだけ → 読みの候補を出力する
// 環境変数は MYIME_HERMETIC_TEST=1 と MYIME_DICT_UPDATE_DIR、MYIME_DICT_UPDATE_BASE、MYIME_DICT_UPDATE_PUBKEY
// （MYIME_DICT_UPDATE=0 で止める、MYIME_DICT_UPDATE_FAIL_APPLY=1 で読み直しの失敗をまね、MYIME_DICT_UPDATE_NO_CONFIRM=1 で「確かめた」印を付けない）。
// 出力の形は session_handler_main の DICT_UPDATE と同じ（tools/dict_update_scenarios.py が読む）。
#include <cstdlib>
#include <iostream>
#include <memory>

#include "dict_update/crypto.h"
#include "dict_update/fetcher.h"
#include "dict_update/service.h"

using namespace dict_update;

namespace {
std::shared_ptr<const SupplementTable> g_table;
std::shared_ptr<const EnglishExtra> g_english;

BakedValues Baked() {
  BakedValues b;
  b.pos_table_sha256 = Sha256Hex("tool id.def");
  b.pos_count = 2000;
  b.public_key_hex = "UNSET";
  return b;
}

void PrintCandidates(const std::string& reading) {
  std::cout << "candidates " << reading << ":";
  if (g_table) {
    const auto range = g_table->ExactRange(reading);
    for (size_t i = range.first; i < range.second; ++i) std::cout << "\t" << g_table->at(i).value;
  }
  std::cout << "\n";
}
}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) return 2;
  const std::string command = argv[1];
  if (command == "info") {
    const BakedValues b = Baked();
    std::cout << "DICT_UPDATE_INFO: pos_table_sha256=" << b.pos_table_sha256 << " pos_count=" << b.pos_count
              << " noun_id=1851\n";
    return 0;
  }
  Config config;
  if (!MakeConfig(Baked(), &config)) {
    std::cout << "DICT_UPDATE: status=no-config\n";
    return 0;
  }
  const bool fail_apply = IsHermeticTest() && std::getenv("MYIME_DICT_UPDATE_FAIL_APPLY") != nullptr;
  ApplyFn apply = [fail_apply](const Snapshot& snap) {
    if (fail_apply) return false;
    g_table = snap.table;
    g_english = snap.english;
    return true;
  };
  Service service(config, [] { return ReadSettings(); }, MakeFetcher(config), apply);
  // 起動時の読み込みは、読み直しの失敗をまねる設定の影響を受けない（前の辞書を読む）
  ApplyFn load_apply = [](const Snapshot& snap) {
    g_table = snap.table;
    g_english = snap.english;
    return true;
  };
  {
    Updater& updater = service.updater();
    Snapshot snap;
    if (updater.LoadInstalled(&snap)) load_apply(snap);
  }
  std::cout << "loaded version=" << (g_table ? service.updater().InstalledVersion() : 0) << "\n";
  if (command == "update") {
    const UpdateResult r = service.CheckNow(true);
    std::cout << "DICT_UPDATE: status=" << StatusName(r.status) << " version=" << r.version << " detail=" << r.detail << "\n";
  }
  for (int i = 2; i < argc; ++i) PrintCandidates(argv[i]);
  // 本体なら、30秒落ちずに動いたときに「確かめた」印を付ける。試験の道具は短いので、すぐ付ける
  // （MYIME_DICT_UPDATE_NO_CONFIRM があれば付けない: 確かめる前に落ち続ける場合のまね）
  if (std::getenv("MYIME_DICT_UPDATE_NO_CONFIRM") == nullptr) service.updater().ConfirmTrial();
  if (g_english) std::cout << "english named=" << g_english->named.size() << " casing=" << g_english->casing.size() << "\n";
  return 0;
}
