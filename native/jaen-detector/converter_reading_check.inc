namespace {
// Hiragana to katakana (ぁ..ゖ to ァ..ヶ); other characters are kept.
std::string KatakanaOf(absl::string_view kana) {
  std::string out;
  for (size_t i = 0; i < kana.size();) {
    const auto b = static_cast<unsigned char>(kana[i]);
    const size_t len = b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
    if (len == 3 && i + 3 <= kana.size()) {
      uint32_t c = ((b & 0x0F) << 12) | ((static_cast<unsigned char>(kana[i + 1]) & 0x3F) << 6) |
                   (static_cast<unsigned char>(kana[i + 2]) & 0x3F);
      if (c >= 0x3041 && c <= 0x3096) c += 0x60;
      out += static_cast<char>(0xE0 | (c >> 12));
      out += static_cast<char>(0x80 | ((c >> 6) & 0x3F));
      out += static_cast<char>(0x80 | (c & 0x3F));
    } else {
      out.append(kana.substr(i, len));
    }
    i += len;
  }
  return out;
}

// Whether |kana| reads as Japanese for the English check: a dictionary word
// that is not katakana (褒め, なめ, 0), or the katakana of the kana itself
// (メモ, ウォレット, キテ: Mozc keeps no inflected forms such as 来て, so the
// katakana entry is what tells きて is read). Only other katakana (リモート for
// れもて, ポーズ for ぱうせ: readings added for English spellings) and English
// values (watch for うぉっち) do not count: remote and pause stay English.
bool ReadsAsJapanese(const engine::Modules& modules, absl::string_view kana) {
  const std::string katakana = KatakanaOf(kana);
  bool japanese = false;
  dictionary::InlineCallback callback;
  callback.OnToken([&](absl::string_view, absl::string_view, const dictionary::Token& token) {
    const Util::ScriptType script = Util::GetScriptType(token.value);
    if ((script != Util::KATAKANA && script != Util::ALPHABET) || token.value == katakana) {
      japanese = true;
      return dictionary::DictionaryInterface::Callback::TRAVERSE_DONE;
    }
    return dictionary::DictionaryInterface::Callback::TRAVERSE_CONTINUE;
  });
  modules.GetDictionary().LookupExact(kana, &callback);
  return japanese;
}

// 文脈で決める段（native/jaen-detector の JapaneseModel）に渡す辞書の引き方: かなの先頭を読む日本語の語
// （ReadsAsJapanese と同じ考えで、英語の別名や、かなと違うカタカナの語は入れない）。
class JapanesePrefixCollector : public dictionary::DictionaryInterface::Callback {
 public:
  explicit JapanesePrefixCollector(std::vector<jaen::JapaneseWord>* out) : out_(out) {}
  ResultType OnToken(absl::string_view key, absl::string_view actual_key, const dictionary::Token& token) override {
    if (key != actual_key) return TRAVERSE_CONTINUE;
    const Util::ScriptType script = Util::GetScriptType(token.value);
    if ((script == Util::KATAKANA || script == Util::ALPHABET) && token.value != KatakanaOf(key)) {
      return TRAVERSE_CONTINUE;
    }
    out_->push_back({key.size(), token.lid, token.rid, token.cost});
    return TRAVERSE_CONTINUE;
  }

 private:
  std::vector<jaen::JapaneseWord>* out_;
};

// MYIME_ALL_ENGLISH=off で、文脈で英語にする段（ローマ字として日本語に読める英単語）を止める（前後の比べ用）。
bool AllEnglishContextEnabled() {
  static const bool enabled = [] {
    const char* value = std::getenv("MYIME_ALL_ENGLISH");
    return value == nullptr || std::string_view(value) != "off";
  }();
  return enabled;
}

// MYIME_ENGLISH_FOLLOW=off で、直前に確定した文字が英語の語で終わるときの英語寄せ（docs/english-follow.md）を止める。
bool EnglishFollowEnabled() {
  static const bool enabled = [] {
    const char* value = std::getenv("MYIME_ENGLISH_FOLLOW");
    return value == nullptr || std::string_view(value) != "off";
  }();
  return enabled;
}

// 直前に確定した文字が英字の語で終わっているか。次の順で、取れたものだけを見る。
//   1. 入力欄の前の文（クライアントが渡した preceding_text）
//   2. session が覚えている「さっき確定した文字」（recent_committed_text。session/session.cc が、前の文がないときだけ
//      詰める。確定・変換を通らなかった空白や英字を足し、入力欄が変わる・カーソルが動く・60 秒たつと捨てる）
//   3. 変換の履歴（直前に確定した文節の先頭の候補。Mozc は空白を打つと履歴を消すので、実際にはほぼ空）
bool PreviousEndsInEnglish(const ConversionRequest& request, const Segments& segments) {
  if (!EnglishFollowEnabled()) return false;
  const auto [left, right] = request.GetSurroundingContext();
  static_cast<void>(right);
  if (!left.empty()) return jaen::EndsWithEnglishWord(left);
  const std::string& remembered = request.context().recent_committed_text();
  if (!remembered.empty()) return jaen::EndsWithEnglishWord(remembered);
  const size_t history = segments.history_segments_size();
  if (history == 0) return false;
  const Segment& last = segments.history_segment(history - 1);
  if (last.candidates_size() == 0) return false;
  return jaen::EndsWithEnglishWord(last.candidate(0).value);
}
}  // namespace
