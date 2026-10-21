// 配布された「追加の辞書」（dict_update::SupplementTable）を、Mozc の辞書の1つとして見せる。
// DictionaryImpl が、システム辞書・値辞書と利用者辞書の間に並べる（apply_dict_update.py が差し込む）。
// 表は変えられない形で持ち、入れ替えは shared_ptr の差し替えだけ。引いている途中の処理は古い表を最後まで使う。
#ifndef MOZC_DICTIONARY_SUPPLEMENT_DICTIONARY_H_
#define MOZC_DICTIONARY_SUPPLEMENT_DICTIONARY_H_

#include <memory>
#include <mutex>

#include "absl/strings/string_view.h"
#include "dict_update/data.h"
#include "dictionary/dictionary_interface.h"

namespace mozc {
namespace dictionary {

class SupplementDictionary : public DictionaryInterface {
 public:
  // 処理全体で1つ。辞書の更新（converter/dict_update_glue.cc）が表を入れ替える。
  static SupplementDictionary& Instance();

  // nullptr で空にする。
  void Set(std::shared_ptr<const ::dict_update::SupplementTable> table);

  bool HasKey(absl::string_view key) const override;
  bool HasValue(absl::string_view value) const override;
  void LookupPredictive(absl::string_view key, Callback* callback) const override;
  void LookupPrefix(absl::string_view key, Callback* callback) const override;
  void LookupExact(absl::string_view key, Callback* callback) const override;

 private:
  std::shared_ptr<const ::dict_update::SupplementTable> Get() const;

  mutable std::mutex mutex_;
  std::shared_ptr<const ::dict_update::SupplementTable> table_;
};

}  // namespace dictionary
}  // namespace mozc

#endif  // MOZC_DICTIONARY_SUPPLEMENT_DICTIONARY_H_
