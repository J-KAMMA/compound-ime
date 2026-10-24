#include "converter/homophone_cues.h"

#include <cstddef>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace mozc::jaen {
namespace {

#include "converter/homophone_cues_data.inc"  // kHomophoneCues

struct Member {
  std::string stem;
  std::vector<std::string> cues;
};

const std::vector<std::vector<Member>>& Groups() {
  static const auto* groups = [] {
    auto* result = new std::vector<std::vector<Member>>;
    std::string_view data(kHomophoneCues);
    while (!data.empty()) {
      const size_t end = data.find('\n');
      std::string_view line = data.substr(0, end);
      data = end == std::string_view::npos ? std::string_view() : data.substr(end + 1);
      if (line.empty() || line[0] == '#') continue;
      std::vector<std::string_view> fields;
      for (size_t start = 0;;) {
        const size_t tab = line.find('\t', start);
        fields.push_back(line.substr(start, tab == std::string_view::npos ? tab : tab - start));
        if (tab == std::string_view::npos) break;
        start = tab + 1;
      }
      std::vector<Member> group;
      for (size_t i = 0; i < fields.size(); i += 2) {
        Member member{std::string(fields[i]), {}};
        if (i + 1 < fields.size()) {
          std::string_view cues = fields[i + 1];
          for (size_t start = 0; start <= cues.size();) {
            const size_t comma = cues.find(',', start);
            const auto cue = cues.substr(start, comma == std::string_view::npos ? comma : comma - start);
            if (!cue.empty()) member.cues.emplace_back(cue);
            if (comma == std::string_view::npos) break;
            start = comma + 1;
          }
        }
        if (!member.stem.empty()) group.push_back(std::move(member));
      }
      if (group.size() >= 2) result->push_back(std::move(group));
    }
    return result;
  }();
  return *groups;
}

// UTF-8 length of the leading run of CJK ideographs (and 々).
size_t KanjiRun(std::string_view text) {
  size_t i = 0;
  while (i + 3 <= text.size()) {
    const auto b0 = static_cast<unsigned char>(text[i]);
    if (b0 < 0xE0 || b0 >= 0xF0) break;
    const char32_t c = ((b0 & 0x0F) << 12) | ((static_cast<unsigned char>(text[i + 1]) & 0x3F) << 6) |
                       (static_cast<unsigned char>(text[i + 2]) & 0x3F);
    if (!((c >= 0x4E00 && c <= 0x9FFF) || c == 0x3005)) break;
    i += 3;
  }
  return i;
}

// The group member whose stem begins `content` (longest stem wins).
const Member* Find(std::string_view content, size_t* group_index) {
  const size_t run = KanjiRun(content);
  const Member* best = nullptr;
  const auto& groups = Groups();
  for (size_t g = 0; g < groups.size(); ++g) {
    for (const auto& member : groups[g]) {
      const size_t length = member.stem.size();
      if (content.substr(0, length) != member.stem) continue;
      // A single kanji must be the whole kanji run: 会う, not 会議.
      if (length == 3 && run != 3) continue;
      if (!best || length > best->stem.size()) { best = &member; *group_index = g; }
    }
  }
  return best;
}

// 助詞 (〜を担う, 〜になる) は動詞のすぐ前に来る。収縮の
// 〜とく／〜どく と 〜になってる／担ってる の組では、文のどこかに
// あるだけの語ではなく、この文節の直前にある語だけを手がかりにする。
bool EndsWithCue(std::string_view text, std::string_view cue) {
  if (cue.empty() || cue.size() > text.size()) return false;
  if (text.substr(text.size() - cue.size()) != cue) return false;
  return true;
}

// 手がかりの語の直後に助詞が付く形 (役 + を, 楽 + に) も許す。
bool CuedAdjacent(const Member& member, std::string_view context) {
  size_t boundary = context.find('\n');
  if (boundary == std::string_view::npos) boundary = context.size();
  const std::string_view before = context.substr(0, boundary);
  for (const auto& cue : member.cues) {
    if (EndsWithCue(before, cue)) return true;
    for (const std::string_view particle : {"を", "は", "が", "も", "に", "へ", "で", "と", "や", "の"}) {
      if (EndsWithCue(before, cue + std::string(particle))) return true;
    }
  }
  return false;
}

bool Cued(const Member& member, std::string_view context, std::string_view extra,
          bool adjacent) {
  if (adjacent) return CuedAdjacent(member, context);
  const std::string text = std::string(context) + std::string(extra);
  for (const auto& cue : member.cues)
    if (text.find(cue) != std::string_view::npos) return true;
  return false;
}

}  // namespace

size_t PreferByHomophoneCues(const std::vector<HomophoneCandidate>& candidates,
                             std::string_view context) {
  if (candidates.size() < 2 || candidates[0].learned) return 0;
  size_t top_group = 0;
  const Member* top = Find(candidates[0].content_value, &top_group);
  if (!top || candidates[0].value.compare(0, top->stem.size(), top->stem) != 0) return 0;
  const std::string_view top_rest = std::string_view(candidates[0].value).substr(top->stem.size());
  // 〜ておく の縮約など、語幹が「っ」で終わる組は直前の語だけを見る。
  const bool adjacent = top->stem.size() >= 3 && top->stem.substr(top->stem.size() - 3) == "っ";
  if (Cued(*top, context, top_rest, adjacent)) return 0;
  for (size_t i = 1; i < candidates.size(); ++i) {
    size_t group = 0;
    const Member* other = Find(candidates[i].content_value, &group);
    if (!other || group != top_group || other == top ||
        candidates[i].value.compare(0, other->stem.size(), other->stem) != 0 ||
        std::string_view(candidates[i].value).substr(other->stem.size()) != top_rest)
      continue;
    if (Cued(*other, context, top_rest, adjacent)) return i;
  }
  return 0;
}

}  // namespace mozc::jaen
