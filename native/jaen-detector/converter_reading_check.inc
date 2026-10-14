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
// that is not katakana (褒め, なめ, 0), or the katakana of the kana itself as a
// common word (メモ, カフェ). Rare katakana of the kana itself (サフェ, ボンス,
// イデア) and other katakana (リモート for れもて, a spelled English reading)
// do not count: remote, safe, bonus and idea stay English.
bool ReadsAsJapanese(const engine::Modules& modules, absl::string_view kana) {
  constexpr int kCommonKatakanaCost = 5000;
  const std::string katakana = KatakanaOf(kana);
  bool japanese = false;
  dictionary::InlineCallback callback;
  callback.OnToken([&](absl::string_view, absl::string_view, const dictionary::Token& token) {
    if (Util::GetScriptType(token.value) != Util::KATAKANA ||
        (token.value == katakana && token.cost < kCommonKatakanaCost)) {
      japanese = true;
      return dictionary::DictionaryInterface::Callback::TRAVERSE_DONE;
    }
    return dictionary::DictionaryInterface::Callback::TRAVERSE_CONTINUE;
  });
  modules.GetDictionary().LookupExact(kana, &callback);
  return japanese;
}
}  // namespace
