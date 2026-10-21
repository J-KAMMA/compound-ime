// 辞書の更新（dict_update）と本体の接続。取った辞書を、追加の辞書（dictionary::SupplementDictionary）と
// 英語の一覧（EnglishLexicon の追加分）に入れ、読みの費用の記憶を捨てる（＝読み直し）。
#ifndef MOZC_CONVERTER_DICT_UPDATE_GLUE_H_
#define MOZC_CONVERTER_DICT_UPDATE_GLUE_H_

#include <string>

namespace mozc::converter {

// mozc_server の起動時に1回: 置き場所の辞書を読み、背景で週1回ほど確かめる。設定（DictUpdate=0）で確かめは止まる。
void StartDictUpdateService();

// session_handler_main（試験）用。MYIME_HERMETIC_TEST=1 で MYIME_DICT_UPDATE_DIR などがあるときだけ、置き場所の辞書を読む
// （背景の確かめはしない）。
void LoadDictUpdateForTest();

// session_handler_main の試験用の命令。
//   DICT_UPDATE       すぐ確かめて入れる（間隔は見ない。止める設定なら何もしない）
//   DICT_UPDATE_INFO  本体に焼いた品詞の表の SHA-256、行数、名詞の番号
// 結果の1行を返す。
std::string DictUpdateTestCommand(const std::string& command);

}  // namespace mozc::converter

#endif  // MOZC_CONVERTER_DICT_UPDATE_GLUE_H_
