// Copyright 2010-2021, Google Inc.
// All rights reserved.
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are
// met:
//
//     * Redistributions of source code must retain the above copyright
// notice, this list of conditions and the following disclaimer.
//     * Redistributions in binary form must reproduce the above
// copyright notice, this list of conditions and the following disclaimer
// in the documentation and/or other materials provided with the
// distribution.
//     * Neither the name of Google Inc. nor the names of its
// contributors may be used to endorse or promote products derived from
// this software without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
// "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
// LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
// A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
// OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
// SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
// LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
// DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
// THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
// (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
// OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

#include "engine/engine.h"

#include <algorithm>
#include <cstdint>
#include <limits>
#include <memory>
#include <vector>
#include <string>
#include <string_view>
#include <cstdlib>
#include <utility>

#include "absl/log/check.h"
#include "absl/log/log.h"
#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "absl/strings/string_view.h"
#include "base/file_util.h"
#include "base/strings/unicode.h"
#include "base/util.h"
#include "converter/attribute.h"
#include "converter/azookey_async_converter.h"
#include "converter/inner_segment.h"
#include "converter/converter.h"
#include "converter/converter_interface.h"
#include "converter/immutable_converter.h"
#include "converter/immutable_converter_interface.h"
#include "converter/azookey_immutable_converter.h"
#include "converter/azookey_user_dictionary.h"
#include "converter/engine_config.h"
#include "data_manager/data_manager.h"
#include "dictionary/pos_matcher.h"
#include "whole_surface_path_v2.h"
#include "dictionary/user_dictionary.h"
#include "engine/data_loader.h"
#include "engine/minimal_converter.h"
#include "engine/modules.h"
#include "engine/supplemental_model_interface.h"
#include "prediction/predictor.h"
#include "protocol/engine_builder.pb.h"
#include "request/options.h"
#include "rewriter/rewriter.h"
#include "rewriter/rewriter_interface.h"

namespace mozc { namespace converter { void InvalidateReadingMemo(); }  // 読みの費用の記憶を捨てる（converter/converter.cc）

static bool HasConfiguredNeuralModel(const AzooKeyConfig& config) {
  return config.zenzai_enabled && !config.zenzai_weight_path.empty() &&
      FileUtil::FileExists(config.zenzai_weight_path).ok();
}

// Mozc owns conversion segments. AzooKey supplies compatible optional candidates.
class MozcWithAzooKeyConverter final : public ImmutableConverterInterface {
 public:
  MozcWithAzooKeyConverter(
      std::unique_ptr<const ImmutableConverterInterface> mozc,
      std::unique_ptr<const ImmutableConverterInterface> azoo,
      bool configured_neural, dictionary::PosMatcher pos_matcher)
      : mozc_(std::move(mozc)), azoo_(std::move(azoo)),
        configured_neural_(configured_neural), pos_matcher_(pos_matcher) {}

  bool Convert(const ConversionOptions& options, Segments* segments) const override {
    return ConvertWithContext(options, segments, {}, {});
  }
  bool ConvertWithContext(const ConversionOptions& options, Segments* segments,
                          std::string_view left_context,
                          std::string_view right_context) const override {
    // The text before the cursor may be long (the page on the screen). The neural model
    // reads only the near part of it; the whole of it names the words already in use.
    const std::string_view screen = left_context;
    left_context = NearContext(left_context);
    if (!ConvertNear(options, segments, left_context, right_context)) return false;
    PreferScreenWords(screen, segments);
    return true;
  }
 private:
  // MYIME_CTX_NEAR: the most characters of the left context the neural model reads (the
  // end of it); unset or 0 passes all of it.
  static std::string_view NearContext(std::string_view left) {
    static const size_t limit = [] {
      const char* value = std::getenv("MYIME_CTX_NEAR");
      return value != nullptr ? static_cast<size_t>(std::strtol(value, nullptr, 10)) : size_t{0};
    }();
    if (limit == 0 || Util::CharsLen(left) <= limit) return left;
    return Util::Utf8SubString(left, Util::CharsLen(left) - limit);
  }
  // MYIME_SCREEN_WORDS=1: a segment whose first candidate is not in the text before the
  // cursor, but another candidate of the same reading is (a word of two or more
  // characters with kanji or katakana, among the first 30), takes that one first.
  static void PreferScreenWords(std::string_view screen, Segments* segments) {
    static const bool enabled = [] {
      const char* value = std::getenv("MYIME_SCREEN_WORDS");
      return value != nullptr && std::string_view(value) == "1";
    }();
    if (!enabled || screen.empty()) return;
    const auto on_screen = [&](const converter::Candidate& candidate) {
      const std::string& word = candidate.content_value;
      if (Util::CharsLen(word) < 2 ||
          !(Util::ContainsScriptType(word, Util::KANJI) || Util::ContainsScriptType(word, Util::KATAKANA)))
        return false;
      return screen.find(word) != std::string_view::npos;
    };
    for (size_t i = 0; i < segments->conversion_segments_size(); ++i) {
      auto* segment = segments->mutable_conversion_segment(i);
      if (segment->candidates_size() < 2 || segment->segment_type() == Segment::FIXED_VALUE ||
          segment->segment_type() == Segment::SUBMITTED || on_screen(segment->candidate(0)))
        continue;
      const size_t count = std::min<size_t>(segment->candidates_size(), 30);
      for (size_t j = 1; j < count; ++j) {
        if (segment->candidate(j).key == segment->candidate(0).key && on_screen(segment->candidate(j))) {
          segment->move_candidate(static_cast<int>(j), 0);
          break;
        }
      }
    }
  }
  bool ConvertNear(const ConversionOptions& options, Segments* segments,
                   std::string_view left_context, std::string_view right_context) const {
    if (!segments || !mozc_->Convert(options, segments)) return false;
    if (!azoo_ || options.request_type != RequestType::CONVERSION ||
        options.used_in_predictor_realtime_conversion || options.create_partial_candidates ||
        options.max_conversion_candidates_size <= 0)
      return true;
    const bool compare_context = configured_neural_ &&
        (!left_context.empty() || !right_context.empty());
    std::vector<std::vector<const converter::Candidate*>> original;
    if (compare_context && segments->conversion_segments_size() <= 128) {
      for (const auto& segment : segments->conversion_segments()) {
        if (segment.candidates_size() > 4096) { original.clear(); break; }
        original.emplace_back(segment.candidates().begin(), segment.candidates().end());
      }
    }
    std::vector<std::string> values;
    for (const auto& segment : segments->conversion_segments())
      values.push_back(segment.candidates_size() ? segment.candidate(0).value : "");
    std::string preceding;
    for (size_t i = 0; i < segments->conversion_segments_size(); ++i) {
      auto* segment = segments->mutable_conversion_segment(i);
      const std::string previous = std::exchange(preceding, preceding + values[i]);
      if (segment->candidates_size() == 0 ||
          segment->segment_type() == Segment::FIXED_VALUE ||
          segment->segment_type() == Segment::SUBMITTED) continue;
      Segments supplemental(*segments);
      supplemental.InitForConvert(segment->key());
      supplemental.set_max_history_segments_size(segments->max_history_segments_size());
      std::string left(left_context), right(right_context);
      if (!left_context.empty() || !right_context.empty()) {
        left += previous;
        for (size_t j = values.size(); j > i + 1; --j) right = values[j - 1] + right;
      }
      if (!azoo_->ConvertWithContext(options, &supplemental, left, right) ||
          supplemental.conversion_segments_size() != 1) continue;
      bool rerank = false;
      bool literal_first = false;
      if (compare_context) {
        const auto contextual = ExistingSequence(*segment, supplemental.conversion_segment(0));
        if (!contextual.empty()) {
          // Keep normal reranking; a complete verb literal only moves itself first.
          // Loaded status is not per-request NN application proof.
          Segments without_context(*segments);
          without_context.InitForConvert(segment->key());
          without_context.set_max_history_segments_size(segments->max_history_segments_size());
          if (azoo_->ConvertWithContext(options, &without_context, {}, {}) &&
              without_context.conversion_segments_size() == 1) {
            const auto ordinary = ExistingSequence(*segment, without_context.conversion_segment(0));
            rerank = (!ordinary.empty() && contextual != ordinary) ||
                (contextual.front().second != segment->key() &&
                 HasLoadedZenzaiModelForReading(segment->key()));
            literal_first = !rerank && contextual.front().second == segment->key() &&
                CompleteLiteralVerb(*segment, supplemental.conversion_segment(0)) &&
                HasLoadedZenzaiModelForReading(segment->key());
          }
        }
      }
      const size_t original_count = segment->candidates_size();
      if (original_count > static_cast<size_t>(std::numeric_limits<int>::max())) continue;
      const std::vector<const converter::Candidate*> original_candidates(
          segment->candidates().begin(), segment->candidates().end());
      const bool allow_novel_promotion = std::none_of(original_candidates.begin(), original_candidates.end(),
          [](const auto* candidate) { return !candidate || (candidate->attributes &
              (converter::Attribute::RERANKED | converter::Attribute::USER_SEGMENT_HISTORY_REWRITER)); });
      int32_t floor = segment->candidate(0).cost;
      for (const auto& c : segment->candidates()) floor = std::max(floor, c->cost);
      size_t preferred = 0;
      std::vector<std::string> seen;
      for (const auto& ptr : supplemental.conversion_segment(0).candidates()) {
        const auto& candidate = *ptr;
        if (!Compatible(candidate, segment->key()) ||
            std::find(seen.begin(), seen.end(), candidate.value) != seen.end()) continue;
        seen.push_back(candidate.value);
        const auto found = std::find_if(segment->candidates().begin(),
            segment->candidates().end(), [&](const auto& existing) {
              return existing->key == candidate.key && existing->value == candidate.value;
            });
        if (found != segment->candidates().end()) {
          const size_t index = found - segment->candidates().begin();
          const bool matched_original = std::find(original_candidates.begin(), original_candidates.end(),
              *found) != original_candidates.end();
#if defined(PRIVATE_NOVEL_DIAGNOSTIC)
          NovelDiagnostic(seen.size()-1, original_count, index, rerank, literal_first, matched_original,
              candidate, segment->candidate(0).value, std::numeric_limits<size_t>::max(), (*found)->cost,
              matched_original && (rerank || (literal_first && candidate.value == segment->key() && index > 0)));
#endif
          if (matched_original) {
            if (rerank) segment->move_candidate(index, preferred++);
            else if (literal_first && candidate.value == segment->key() && index > 0)
              segment->move_candidate(index, 0);
          }
          continue;
        }
        if (segment->candidates_size() >=
            static_cast<size_t>(options.max_conversion_candidates_size)) continue;
        if (segment->candidates_size() >= static_cast<size_t>(std::numeric_limits<int>::max())) continue;
        auto* added = segment->add_candidate();
        *added = candidate;
        floor = static_cast<int32_t>(std::min<int64_t>(
            static_cast<int64_t>(floor) + 100, std::numeric_limits<int32_t>::max()));
        added->cost = std::max(floor, added->cost);
        floor = added->cost;
        const size_t added_index = segment->candidates_size()-1;
        const bool promote = rerank && allow_novel_promotion;
#if defined(PRIVATE_NOVEL_DIAGNOSTIC)
        NovelDiagnostic(seen.size()-1, original_count, std::numeric_limits<size_t>::max(), rerank,
            literal_first, false, candidate, segment->candidate(0).value, added_index, added->cost, promote);
#endif
        if (promote) segment->move_candidate(static_cast<int>(added_index), static_cast<int>(preferred++));
      }
      preceding = previous + segment->candidate(0).value;
    }
    if (compare_context) PreferWholePhrase(options, *azoo_, segments, left_context, right_context, original);
    return true;
  }
  bool CompleteLiteralVerb(const Segment& original, const Segment& supplemental) const {
    if (original.candidates_size() == 0 ||
        !pos_matcher_.IsWeakCompoundVerbSuffix(original.candidate(0).lid) ||
        !pos_matcher_.IsWeakCompoundVerbSuffix(original.candidate(0).rid) ||
        original.candidate(0).content_key != original.key() ||
        original.candidate(0).content_value != original.candidate(0).value) return false;
    const auto key = original.key();
    const auto literal = std::find_if(supplemental.candidates().begin(),
        supplemental.candidates().end(), [key](const auto& candidate) {
          return candidate->key == key && candidate->value == key && Compatible(*candidate, key);
        });
    if (literal == supplemental.candidates().end()) return false;
    return (*literal)->content_key == key && (*literal)->content_value == (*literal)->value;
  }
  static bool Text(std::string_view text) {
    return !text.empty() && text.find('\0') == std::string_view::npos &&
        strings::IsValidUtf8(text);
  }
  static bool Compatible(const converter::Candidate& candidate, std::string_view key) {
    if (!Text(key) || candidate.key != key || !Text(candidate.value) ||
        !Text(candidate.content_key) || !Text(candidate.content_value) ||
        candidate.key.compare(0, candidate.content_key.size(), candidate.content_key) != 0 ||
        candidate.value.compare(0, candidate.content_value.size(), candidate.content_value) != 0 ||
        candidate.consumed_key_size != Util::CharsLen(key) ||
        (candidate.attributes & converter::Attribute::PARTIALLY_KEY_CONSUMED) ||
        candidate.effective_converted_segment_count() != 1 ||
        candidate.inner_segment_boundary.empty()) return false;
    size_t key_offset = 0, value_offset = 0;
    for (uint32_t encoded : candidate.inner_segment_boundary) {
      const auto length = converter::DecodeLengths(encoded);
      if (!length.key_len || !length.value_len || !length.content_key_len ||
          !length.content_value_len || length.content_key_len > length.key_len ||
          length.content_value_len > length.value_len ||
          length.key_len > key.size() - key_offset ||
          length.value_len > candidate.value.size() - value_offset) return false;
      if (!Text(key.substr(key_offset, length.key_len)) ||
          !Text(key.substr(key_offset, length.content_key_len)) ||
          !Text(std::string_view(candidate.value).substr(value_offset, length.value_len)) ||
          !Text(std::string_view(candidate.value).substr(value_offset, length.content_value_len)))
        return false;
      key_offset += length.key_len;
      value_offset += length.value_len;
    }
    return key_offset == key.size() && value_offset == candidate.value.size();
  }
#if defined(PRIVATE_NOVEL_DIAGNOSTIC)
  static std::string NovelHex(std::string_view value) {
    std::string hex; if (value.size() > 512) return hex;
    constexpr char digits[] = "0123456789abcdef";
    for (unsigned char byte : value) { hex += digits[byte >> 4]; hex += digits[byte & 15]; }
    return hex;
  }
  static void NovelDiagnostic(size_t rank, size_t original_count, size_t found_index,
                              bool rerank, bool literal_first, bool matched_original,
                              const converter::Candidate& source, std::string_view top,
                              size_t added_index, int32_t cost, bool moved) {
    LOG(INFO) << "PRIVATE_NOVEL_DIAGNOSTIC rank=" << rank << " original_count=" << original_count
              << " found_index=" << found_index << " rerank=" << rerank << " literal_first=" << literal_first
              << " matched_original=" << matched_original << " value_hex=" << NovelHex(source.value)
              << " value_bytes=" << source.value.size() << " current_top_hex=" << NovelHex(top)
              << " current_top_bytes=" << top.size() << " added_index=" << added_index
              << " cost=" << cost << " move=" << moved;
  }
#endif
  static bool MatchWholePhrase(const converter::Candidate& candidate,
                               const Segments& segments, std::string_view whole_key,
                               std::vector<int>* indices, const char** rejection) {
    if (!indices || !rejection) return false;
    indices->clear(); *rejection = "boundary";
    const size_t count = segments.conversion_segments_size();
    if (segments.resized() || count < 2 || count > 128 || !Text(whole_key) ||
        whole_key.size() > 512 || Util::CharsLen(whole_key) > 128) return false;
    std::string joined;
    for (const auto& segment : segments.conversion_segments()) {
      if (segment.segment_type() != Segment::FREE || !Text(segment.key()) ||
          segment.key().size() > 512 - joined.size() || segment.candidates_size() == 0 ||
          segment.candidates_size() > 4096 ||
          segment.candidates_size() > static_cast<size_t>(std::numeric_limits<int>::max()) ||
          std::any_of(segment.candidates().begin(), segment.candidates().end(), [](const auto* existing) {
            return !existing || (existing->attributes & (converter::Attribute::RERANKED |
                converter::Attribute::USER_SEGMENT_HISTORY_REWRITER));
          })) return false;
      joined += segment.key();
    }
    if (joined != whole_key) return false;
    *rejection = "Compatible";
    if (candidate.value.size() > 512 || candidate.inner_segment_boundary.size() > 128 ||
        !Compatible(candidate, whole_key)) return false;
    *rejection = "boundary";
    // Only split a neural inner segment where its suffix is byte-identical in
    // reading and surface. Converted heads remain indivisible.
    std::vector<std::pair<size_t, size_t>> boundaries{{0, 0}};
    size_t key_offset = 0, value_offset = 0;
    for (uint32_t encoded : candidate.inner_segment_boundary) {
      const auto length = converter::DecodeLengths(encoded);
      const auto key_suffix = std::string_view(candidate.key).substr(
          key_offset + length.content_key_len, length.key_len - length.content_key_len);
      const auto value_suffix = std::string_view(candidate.value).substr(
          value_offset + length.content_value_len, length.value_len - length.content_value_len);
      if (key_suffix == value_suffix) {
        for (size_t offset = 0; offset <= key_suffix.size(); ++offset) {
          if (strings::IsValidUtf8(key_suffix.substr(0, offset)))
            boundaries.emplace_back(key_offset + length.content_key_len + offset,
                                    value_offset + length.content_value_len + offset);
        }
      }
      key_offset += length.key_len; value_offset += length.value_len;
      boundaries.emplace_back(key_offset, value_offset);
    }
    std::vector<int> selected;
    size_t key_end = 0, value_begin = 0;
    for (const auto& segment : segments.conversion_segments()) {
      key_end += segment.key().size();
      const auto boundary = std::find_if(boundaries.begin(), boundaries.end(),
          [key_end](const auto& point) { return point.first == key_end; });
      if (boundary == boundaries.end() || boundary->second <= value_begin ||
          boundary->second > candidate.value.size()) return false;
      const auto value = std::string_view(candidate.value).substr(
          value_begin, boundary->second - value_begin);
      const auto found = std::find_if(segment.candidates().begin(), segment.candidates().end(),
          [&](const auto* existing) {
            return existing && existing->key == segment.key() && existing->value == value &&
                existing->effective_converted_segment_count() == 1 &&
                !(existing->attributes & converter::Attribute::PARTIALLY_KEY_CONSUMED);
          });
      if (found == segment.candidates().end()) { *rejection = "missing existing"; return false; }
      selected.push_back(static_cast<int>(found - segment.candidates().begin()));
      value_begin = boundary->second;
    }
    if (selected.size() != count || key_end != whole_key.size() ||
        key_offset != whole_key.size() || value_offset != candidate.value.size() ||
        value_begin != candidate.value.size()) return false;
    *indices = std::move(selected); *rejection = "selected"; return true;
  }
#if defined(MYIME_PRIVATE_WHOLE_PHRASE_DIAGNOSTIC)
  static void WholePhraseDiagnostic(size_t index, const converter::Candidate& candidate,
                                    const char* reason) {
    std::string hex;
    if (candidate.value.size() <= 512) {
      constexpr char digits[] = "0123456789abcdef";
      for (unsigned char byte : candidate.value) { hex += digits[byte >> 4]; hex += digits[byte & 15]; }
    }
    LOG(INFO) << "PRIVATE_WHOLE_PHRASE candidate=" << index << " value_hex=" << hex
              << " value_bytes=" << candidate.value.size() << " result=" << reason;
  }
#endif
  static void PreferWholePhrase(const ConversionOptions& options,
                                const ImmutableConverterInterface& azoo, Segments* segments,
                                std::string_view left, std::string_view right,
                                const std::vector<std::vector<const converter::Candidate*>>& original) {
    const size_t count = segments->conversion_segments_size();
    if (segments->resized() || count < 2 || count > 128 || original.size() != count) return;
    std::string key;
    for (const auto& segment : segments->conversion_segments()) {
      if (segment.segment_type() != Segment::FREE || !Text(segment.key()) ||
          segment.key().size() > 512 - key.size() || segment.candidates_size() == 0 ||
          segment.candidates_size() > 4096 ||
          segment.candidates_size() > static_cast<size_t>(std::numeric_limits<int>::max()) ||
          std::any_of(segment.candidates().begin(), segment.candidates().end(), [](const auto* existing) {
            return !existing || (existing->attributes & (converter::Attribute::RERANKED |
                converter::Attribute::USER_SEGMENT_HISTORY_REWRITER));
          })) return;
      key += segment.key();
    }
    // Loaded status only qualifies this optional query; it does not prove request NN execution.
    if (!HasLoadedZenzaiModelForReading(key)) return;
    Segments full(*segments); full.InitForConvert(key);
    full.set_max_history_segments_size(segments->max_history_segments_size());
    if (!azoo.ConvertWithContext(options, &full, left, right) ||
        full.conversion_segments_size() != 1 || full.conversion_segment(0).candidates_size() > 4096) return;
    size_t candidate_index = 0;
    for (const auto* candidate : full.conversion_segment(0).candidates()) {
      if (!candidate) return;
      std::vector<int> indices; const char* rejection = "Compatible";
      bool selected = MatchWholePhrase(*candidate, *segments, key, &indices, &rejection);
      if (!selected && Compatible(*candidate, key) &&
          !(candidate->attributes & (converter::Attribute::COMMAND_CANDIDATE | converter::Attribute::PARTIALLY_KEY_CONSUMED))) {
        if (auto path = private_surface::Find(*segments, key, candidate->value, original)) {
          indices = std::move(*path); selected = true; rejection = "existing surface path";
        }
      }
#if defined(MYIME_PRIVATE_WHOLE_PHRASE_DIAGNOSTIC)
      WholePhraseDiagnostic(candidate_index, *candidate, rejection);
#endif
      ++candidate_index;
      if (selected) {
        for (size_t i = 0; i < indices.size(); ++i) {
          if (i >= original.size() || indices[i] < 0 ||
              static_cast<size_t>(indices[i]) >= segments->conversion_segment(i).candidates_size() ||
              std::find(original[i].begin(), original[i].end(),
                        segments->conversion_segment(i).candidates()[indices[i]]) == original[i].end()) {
            selected = false; break;
          }
        }
      }
      if (!selected) continue;
#if defined(MYIME_PRIVATE_WHOLE_PHRASE_DIAGNOSTIC)
      std::string selected_indices;
      for (int index : indices) { if (!selected_indices.empty()) selected_indices += ','; selected_indices += std::to_string(index); }
      LOG(INFO) << "PRIVATE_WHOLE_PHRASE selected_indices=" << selected_indices;
#endif
      if (indices.size() != count) return;
      // All indices belong to independent outer segments and are verified before any move.
      for (size_t i = 0; i < count; ++i) segments->mutable_conversion_segment(i)->move_candidate(indices[i], 0);
      return;
    }
  }
  static std::vector<std::pair<std::string, std::string>> ExistingSequence(
      const Segment& original, const Segment& supplemental) {
    std::vector<std::pair<std::string, std::string>> sequence;
    for (const auto& candidate : supplemental.candidates()) {
      if (!Compatible(*candidate, original.key())) continue;
      const std::pair identity{candidate->key, candidate->value};
      if (std::find(sequence.begin(), sequence.end(), identity) != sequence.end()) continue;
      if (std::any_of(original.candidates().begin(), original.candidates().end(),
          [&](const auto& c) { return c->key == identity.first && c->value == identity.second; }))
        sequence.push_back(identity);
    }
    return sequence;
  }
  std::unique_ptr<const ImmutableConverterInterface> mozc_;
  std::unique_ptr<const ImmutableConverterInterface> azoo_;
  bool configured_neural_;
  const dictionary::PosMatcher pos_matcher_;
};

absl::StatusOr<std::unique_ptr<Engine>> Engine::CreateEngine(
    std::unique_ptr<const DataManager> data_manager) {
  absl::StatusOr<std::unique_ptr<engine::Modules>> modules_status =
      engine::Modules::Create(std::move(data_manager));
  if (!modules_status.ok()) {
    return modules_status.status();
  }
  return CreateEngine(std::move(modules_status.value()));
}

absl::StatusOr<std::unique_ptr<Engine>> Engine::CreateEngine(
    std::unique_ptr<engine::Modules> modules) {
  auto engine = std::make_unique<Engine>();
  absl::Status engine_status = engine->Init(std::move(modules));
  if (!engine_status.ok()) {
    return engine_status;
  }
  return engine;
}

std::unique_ptr<Engine> Engine::CreateEngine() {
  return std::make_unique<Engine>();
}

Engine::Engine() : minimal_converter_(CreateMinimalConverter()) {}

absl::Status Engine::ReloadModules(std::unique_ptr<engine::Modules> modules) {
  ReloadAndWait();
  return Init(std::move(modules));
}

absl::Status Engine::Init(std::unique_ptr<engine::Modules> modules) {
  const char* async_profile = std::getenv("MYIME_ASYNC_CONVERSION");
  // Rank with context before selecting the first candidate by default.
  // Explicit "1" retains dictionary-first asynchronous delivery.
  const bool use_async = async_profile && std::string_view(async_profile) == "1";
  auto immutable_converter_factory = [this, use_async](const engine::Modules& modules)
      -> std::unique_ptr<const ImmutableConverterInterface> {
    AzooKeyConfig config;
    config.dictionary_path = GetAzooKeyDictionaryPath();
    // ユーザー学習 (候補選択の履歴反映)。空の場合は学習無効
    config.memory_path = GetAzooKeyMemoryPath();
    config.zenzai_enabled = IsZenzaiEnabled();
    config.zenzai_use_gpu = IsZenzaiGpuEnabled();
    config.zenzai_inference_limit = GetZenzaiInferenceLimit();
    config.zenzai_weight_path = GetZenzaiWeightPath();

    if (async_converter_) {
      async_last_token_ = async_converter_->Retire();
      async_converter_.reset();
    }
    auto azookey_converter = CreateAzooKeyImmutableConverter(config);
    if (azookey_converter) {
      // myime: Mozc storage is the source of truth. The DLL keeps only an
      // in-memory copy, so seed it whenever an AzooKey engine is created.
      PushMozcUserDictionaryToAzooKey(modules.GetUserDictionary(),
                                      modules.GetDataManager());
      LOG(INFO) << "Using Mozc base with optional AzooKey, configured Zenzai="
                << (config.zenzai_enabled ? "enabled" : "disabled")
                << ", GPU="
                << (config.zenzai_use_gpu ? "enabled" : "disabled");
      if (use_async && HasConfiguredNeuralModel(config)) {
        async_converter_ = std::make_shared<AzooKeyAsyncConverter>(
            std::move(azookey_converter), async_last_token_);
        return std::make_unique<ImmutableConverter>(modules);
      }
      return std::make_unique<MozcWithAzooKeyConverter>(
          std::make_unique<ImmutableConverter>(modules),
          std::move(azookey_converter), HasConfiguredNeuralModel(config), modules.GetPosMatcher());
    }
    // The Mozc base remains available when the optional engine fails.
    LOG(WARNING) << "AzooKey unavailable; retaining Mozc conversion";
    return std::make_unique<ImmutableConverter>(modules);
  };

  auto predictor_factory =
      [](const engine::Modules& modules, const ConverterInterface& converter,
         const ImmutableConverterInterface& immutable_converter) {
        return std::make_unique<prediction::Predictor>(modules, converter,
                                                       immutable_converter);
      };

  auto rewriter_factory = [](const engine::Modules& modules) {
    return std::make_unique<Rewriter>(modules);
  };

  async_user_dictionary_importer_ =
      std::make_unique<user_dictionary::AsyncUserDictionaryImporter>(
          modules->GetUserDictionary());

  auto converter = std::make_shared<converter::Converter>(
      std::move(modules), immutable_converter_factory, predictor_factory,
      rewriter_factory);

  if (!converter) {
    return absl::ResourceExhaustedError("engine.cc: converter_ is null");
  }

  converter_ = std::move(converter);

  return absl::OkStatus();
}

bool Engine::Reload() { converter::InvalidateReadingMemo();
  if (async_converter_) async_converter_->Cancel();
  return converter_ && converter_->Reload();
}

bool Engine::Sync() { return converter_ && converter_->Sync(); }

bool Engine::Wait() { return converter_ && converter_->Wait(); }

bool Engine::ReloadAndWait() { return Reload() && Wait(); }

bool Engine::ClearUserHistory() {
  if (converter_) {
    converter_->rewriter().Clear();
  }
  return true;
}

bool Engine::ClearUserPrediction() {
  return converter_ && converter_->predictor().ClearAllHistory();
}

bool Engine::ClearUnusedUserPrediction() {
  return converter_ && converter_->predictor().ClearUnusedHistory();
}

bool Engine::AddUserHistory(absl::string_view key, absl::string_view value) {
  return converter_ && converter_->AddUserHistory(key, value);
}

bool Engine::MaybeReloadEngine(EngineReloadResponse* response) {
  if (!converter_ || always_wait_for_testing_) {
    loader_.Wait();
  }

  if (loader_.IsRunning() || !loader_response_) {
    return false;
  }

  *response = std::move(loader_response_->response);

  const absl::Status reload_status =
      ReloadModules(std::move(loader_response_->modules));
  if (reload_status.ok()) {
    response->set_status(EngineReloadResponse::RELOADED);
  }
  loader_response_.reset();

  return reload_status.ok();
}

bool Engine::SendEngineReloadRequest(const EngineReloadRequest& request) {
  return loader_.StartNewDataBuildTask(
      request, [this](std::unique_ptr<DataLoader::Response> response) {
        loader_response_ = std::move(response);
        return absl::OkStatus();
      });
}

bool Engine::SendSupplementalModelReloadRequest(
    const EngineReloadRequest& request) {
  if (converter_) {
    converter_->modules().GetSupplementalModel().LoadAsync(request);
  }
  return true;
}

void Engine::ClearOldSupplementalModels() {
  if (converter_) {
    converter_->modules().GetSupplementalModel().ClearOldModels();
  }
}

void Engine::ImportUserDictionary(std::string name, std::string tsv) { converter::InvalidateReadingMemo();
  if (async_converter_) async_converter_->Cancel();
  if (async_user_dictionary_importer_) {
    async_user_dictionary_importer_->Import(std::move(name), std::move(tsv));
  }
}

}  // namespace mozc
