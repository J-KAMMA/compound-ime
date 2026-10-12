#ifndef MYIME_PRIVATE_WHOLE_SURFACE_PATH_V2_H_
#define MYIME_PRIVATE_WHOLE_SURFACE_PATH_V2_H_
#include <algorithm>
#include <optional>
#include <string>
#include <string_view>
#include <vector>
#include "base/strings/unicode.h"
#include "base/util.h"
#include "converter/attribute.h"
#include "converter/inner_segment.h"
#include "converter/segments.h"
namespace mozc::private_surface {
inline bool Text(std::string_view s) { return !s.empty() && s.find('\0') == s.npos && strings::IsValidUtf8(s); }
inline bool Safe(const converter::Candidate& c, std::string_view key) {
  if (c.key != key || !Text(c.value) || c.value.size() > 512 || c.effective_converted_segment_count() != 1 ||
      (c.attributes & (converter::Attribute::COMMAND_CANDIDATE | converter::Attribute::PARTIALLY_KEY_CONSUMED)) ||
      (c.consumed_key_size && c.consumed_key_size != Util::CharsLen(key)) ||
      (!c.content_key.empty() && !Text(c.content_key)) || (!c.content_value.empty() && !Text(c.content_value)) ||
      c.key.compare(0,c.content_key.size(),c.content_key) || c.value.compare(0,c.content_value.size(),c.content_value)) return false;
  size_t k=0,v=0;
  for (uint32_t encoded:c.inner_segment_boundary) {
    const auto b=converter::DecodeLengths(encoded);
    if (!b.key_len || !b.value_len || !b.content_key_len || !b.content_value_len ||
        b.content_key_len>b.key_len || b.content_value_len>b.value_len || b.key_len>key.size()-k || b.value_len>c.value.size()-v ||
        !Text(key.substr(k,b.key_len)) || !Text(key.substr(k,b.content_key_len)) ||
        !Text(std::string_view(c.value).substr(v,b.value_len)) || !Text(std::string_view(c.value).substr(v,b.content_value_len))) return false;
    k+=b.key_len;v+=b.value_len;
  }
  return c.inner_segment_boundary.empty() || (k==key.size() && v==c.value.size());
}
inline std::optional<std::vector<int>> Find(const Segments& s, std::string_view key, std::string_view value, const std::vector<std::vector<const converter::Candidate*>>& original) {
  const size_t count=s.conversion_segments_size();
  if (original.size()!=count || s.resized() || !count || count>128 || !Text(key) || key.size()>512 || Util::CharsLen(key)>128 || !Text(value) || value.size()>512) return std::nullopt;
  std::string joined;
  for (const auto& segment:s.conversion_segments()) {
    if (segment.segment_type()!=Segment::FREE || !Text(segment.key()) || segment.key().size()>512-joined.size() ||
        !segment.candidates_size() || segment.candidates_size()>4096 ||
        std::any_of(segment.candidates().begin(),segment.candidates().end(),[](const auto* c) {
          return !c || (c->attributes & (converter::Attribute::RERANKED | converter::Attribute::USER_SEGMENT_HISTORY_REWRITER | converter::Attribute::USER_DICTIONARY));
        })) return std::nullopt;
    joined+=segment.key();
  }
  if (joined!=key) return std::nullopt;
  struct Edge { int previous=-1, candidate=-1; };
  std::vector<std::vector<Edge>> paths(count+1,std::vector<Edge>(value.size()+1));paths[0][0].previous=0;
  for (size_t i=0;i<count;++i) {
    const auto& segment=s.conversion_segment(i);
    std::vector<int> safe;
    for (size_t c=0;c<segment.candidates_size();++c) if (Safe(segment.candidate(c),segment.key()) && std::find(original[i].begin(),original[i].end(),segment.candidates()[c])!=original[i].end()) safe.push_back(static_cast<int>(c));
    for (size_t at=0;at<value.size();++at) {
      if (paths[i][at].previous<0) continue;
      for (int c:safe) {
        const auto& text=segment.candidate(c).value;
        if (text.size()>value.size()-at || value.compare(at,text.size(),text)!=0) continue;
        const size_t end=at+text.size();
        if (paths[i+1][end].previous<0) paths[i+1][end]={static_cast<int>(at),c};
      }
    }
  }
  if (paths[count][value.size()].previous<0) return std::nullopt;
  std::vector<int> result(count);size_t at=value.size();
  for (size_t i=count;i>0;--i) {const auto& edge=paths[i][at];result[i-1]=edge.candidate;at=static_cast<size_t>(edge.previous);}
  return at==0 ? std::optional<std::vector<int>>(std::move(result)) : std::nullopt;
}
}
#endif
