// Homophone choice by context cues (tools/data/homophone-cues.tsv).
#ifndef MOZC_CONVERTER_HOMOPHONE_CUES_H_
#define MOZC_CONVERTER_HOMOPHONE_CUES_H_

#include <string>
#include <string_view>
#include <vector>

namespace mozc::jaen {

struct HomophoneCandidate {
  std::string value;
  std::string content_value;
  bool learned = false;  // chosen by the user's history: never moved away from
};

// For one segment: the index of the candidate to move first, or 0 to keep the
// order. A candidate qualifies when its leading kanji (a stem of a cue group)
// differs from the first candidate's, the rest of the two values are equal,
// and `context` (the other segments' text) holds a cue of its stem and none of
// the first candidate's stem. Single-kanji stems must be the whole leading
// kanji run (載っ, not 会議 for 会). For contraction stems ending in っ
// (担っ／になっ), a cue counts only when it is the word just before the
// segment (a following particle is allowed), so 静かにその任を keeps 担う.
size_t PreferByHomophoneCues(const std::vector<HomophoneCandidate>& candidates,
                             std::string_view context);

}  // namespace mozc::jaen

#endif  // MOZC_CONVERTER_HOMOPHONE_CUES_H_
