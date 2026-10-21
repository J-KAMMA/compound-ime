// 配布ページからの取得。環境ごとに別の部品を使う:
//   ウィンドウズ: WinInet（既存のモデル取得と同じ。https の証明書の確かめは OS に任せる）
//   Linux・マック: curl の実行ファイルを、シェルを通さずに起動する（引数は配列で渡す）
//   試験専用: file:// を読む（allow_test_transport のとき）
// どれも、打った文字や設定など利用者の情報は何も送らない。送るのは URL への GET と User-Agent だけ。
#ifndef DICT_UPDATE_FETCHER_H_
#define DICT_UPDATE_FETCHER_H_

#include <functional>
#include <memory>

#include "dict_update/updater.h"

namespace dict_update {

constexpr char kUserAgent[] = "CompoundIME-dict-update/1";

std::unique_ptr<Fetcher> MakeDefaultFetcher(bool allow_test_transport);

// 試験用: 1回ごとに呼ばれる関数が答える。
class FunctionFetcher : public Fetcher {
 public:
  explicit FunctionFetcher(std::function<FetchResult(const std::string&, size_t)> fn) : fn_(std::move(fn)) {}
  FetchResult Get(const std::string& url, size_t max_bytes) override { return fn_(url, max_bytes); }

 private:
  std::function<FetchResult(const std::string&, size_t)> fn_;
};

}  // namespace dict_update

#endif  // DICT_UPDATE_FETCHER_H_
