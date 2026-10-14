namespace {
// Full-width digits (１０月) inside a candidate that also has other text become
// half-width (10月), as in newspapers and business writing; a candidate of
// digits only (１０) keeps its form so it stays choosable. A candidate that
// becomes the same as an earlier one is dropped.
void HalfWidthDigitsInText(Segments* segments) {
  static constexpr std::string_view kFull[] = {"０", "１", "２", "３", "４", "５", "６", "７", "８", "９"};
  const auto convert = [](std::string* text) {
    bool digit = false, other = false;
    for (size_t i = 0; i < text->size();) {
      const auto b = static_cast<unsigned char>((*text)[i]);
      const size_t len = b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
      const std::string_view c(text->data() + i, len);
      if (std::ranges::find(kFull, c) != std::end(kFull)) {
        digit = true;
      } else {
        other = true;
      }
      i += len;
    }
    if (!digit || !other) return false;
    std::string out;
    for (size_t i = 0; i < text->size();) {
      const auto b = static_cast<unsigned char>((*text)[i]);
      const size_t len = b < 0x80 ? 1 : b < 0xE0 ? 2 : b < 0xF0 ? 3 : 4;
      const std::string_view c(text->data() + i, len);
      const auto it = std::ranges::find(kFull, c);
      if (it != std::end(kFull)) {
        out += static_cast<char>('0' + (it - std::begin(kFull)));
      } else {
        out += c;
      }
      i += len;
    }
    *text = std::move(out);
    return true;
  };
  for (size_t s = 0; s < segments->conversion_segments_size(); ++s) {
    Segment& segment = *segments->mutable_conversion_segment(s);
    std::vector<std::string> seen;
    for (int i = 0; i < static_cast<int>(segment.candidates_size());) {
      converter::Candidate* candidate = segment.mutable_candidate(i);
      if (convert(&candidate->value)) convert(&candidate->content_value);
      if (std::ranges::find(seen, candidate->value) != seen.end()) {
        segment.erase_candidate(i);
        continue;
      }
      seen.push_back(candidate->value);
      ++i;
    }
  }
}
}  // namespace
