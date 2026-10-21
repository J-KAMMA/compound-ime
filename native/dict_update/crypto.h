// 辞書の更新で使う暗号の部品（SHA-256、Ed25519 の署名の確かめ）。標準ライブラリだけで書いてあり、
// どの環境でも同じように動く。署名を「作る」のは tools/make_dict_release.py（python の cryptography）で、
// ここは確かめるだけ。Ed25519 は TweetNaCl（公有）の計算の組み立てに従い、定数は定義から計算して埋めてある。
#ifndef DICT_UPDATE_CRYPTO_H_
#define DICT_UPDATE_CRYPTO_H_

#include <cstdint>
#include <string>
#include <string_view>

namespace dict_update {

// 小文字の16進数の SHA-256。
std::string Sha256Hex(std::string_view data);

// 16進数（大文字小文字どちらでも）を元に戻す。長さが奇数や、16進数以外の文字があれば false。
bool HexDecode(std::string_view hex, std::string* out);

// Ed25519 の署名（64バイト）を、公開鍵（32バイト）で message について確かめる。
// 署名の後ろ半分（S）が群の位数以上のもの（作り変えた署名）も受け付けない。
bool Ed25519Verify(std::string_view signature, std::string_view message, std::string_view public_key);

}  // namespace dict_update

#endif  // DICT_UPDATE_CRYPTO_H_
