// 配布ページの目録（manifest.txt）の読み取り。目録は UTF-8 の行（LF）で、タブ区切り:
//   compound-ime-dict-manifest<TAB>1
//   version<TAB>20261101              （年月日の8桁。新しいほど大きい。これより小さい目録は古い版として無視する）
//   created<TAB>2026-11-01
//   pos_table<TAB><id.def の SHA-256>   （辞書の品詞番号の表。本体に焼いた値と同じでなければ受け付けない）
//   file<TAB>種類<TAB>名前<TAB>大きさ<TAB>SHA-256<TAB>URL   （種類: supplement、english）
// 目録の全体に Ed25519 の署名（manifest.txt.sig、16進の128文字）が付く。確かめるのは署名が先。
#ifndef DICT_UPDATE_MANIFEST_H_
#define DICT_UPDATE_MANIFEST_H_

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace dict_update {

struct ManifestFile {
  std::string kind;
  std::string name;
  uint64_t size = 0;
  std::string sha256;  // 小文字の16進
  std::string url;
};

struct Manifest {
  int format = 0;
  uint64_t version = 0;
  std::string created;
  std::string pos_table;
  std::vector<ManifestFile> files;
  const ManifestFile* Find(std::string_view kind) const;
};

// 署名の確かめは済んでいる前提で、中身を読む。url_prefix が空でなければ、URL がそれで始まることも求める。
bool ParseManifest(std::string_view text, std::string_view url_prefix, Manifest* out, std::string* error);

}  // namespace dict_update

#endif  // DICT_UPDATE_MANIFEST_H_
