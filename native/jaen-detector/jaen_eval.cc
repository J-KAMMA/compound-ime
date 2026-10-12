// Mozc-linked evaluator (built as //converter:jaen_eval_mozc by
// tools/apply_jaen_integration.py). Reads romaji lines and prints
// "romaji \t english,pieces" using Mozc's romaji table and the built-in English
// lexicon, the same code path as the converter.
//   jaen_eval_mozc [<english-lexicon.txt> <curated-words.txt>]
// With JAEN_CHOICES=<file> (jaen::ChoiceStore format), learned choices apply.
// With JAEN_TYPO=1 it prints "romaji <TAB> fixed romaji <TAB> its kana <TAB> kana" instead
// (empty columns when nothing is fixed); JAEN_TYPO_MARGIN and
// JAEN_TYPO_FLOOR set FixTypo's margin and floor.
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "base/init_mozc.h"
#include "composer/composition.h"
#include "composer/table.h"
#include "converter/english_lexicon.h"
#include "converter/jaen_choices.h"
#include "converter/jaen_detector.h"
#include "converter/jaen_typo.h"

namespace {
std::vector<jaen::Chunk> Chunks(const std::shared_ptr<const mozc::composer::Table>& table,
                                std::string_view raw) {
  mozc::composer::Composition composition(table);
  size_t pos = 0;
  for (char c : raw) pos = composition.InsertAt(pos, std::string(1, c));
  std::vector<jaen::Chunk> chunks;
  for (const auto& chunk : composition.GetCharChunkList()) {
    chunks.push_back({std::string(chunk.raw()), std::string(chunk.conversion()), std::string(chunk.pending())});
  }
  return chunks;
}
}  // namespace

int main(int argc, char** argv) {
  mozc::InitMozc(argv[0], &argc, &argv);
  auto table = std::make_shared<mozc::composer::Table>();
  if (!table->LoadFromFile("system://romanji-hiragana.tsv")) return 2;
  const jaen::RomajiParser parse = [&](std::string_view raw) { return Chunks(table, raw); };
  // Optional: <english-lexicon.txt> <curated-words.txt> replace the built-in list.
  jaen::Lexicon override;
  if (argc == 3) {
    std::ifstream words(argv[1]), curated(argv[2]);
    for (std::string w; std::getline(words, w);) override.Add(w);
    for (std::string w; std::getline(curated, w);) override.Add(w, true);
    // JAEN_PLACES=<file of "spelling TAB surface TAB normal"> adds place names.
    if (const char* places = std::getenv("JAEN_PLACES")) {
      std::ifstream in(places);
      for (std::string l; std::getline(in, l);) {
        const size_t a = l.find('\t');
        const size_t b = a == std::string::npos ? a : l.find('\t', a + 1);
        if (b != std::string::npos) override.AddPlace(l.substr(0, a), l.substr(a + 1, b - a - 1), l.substr(b + 1));
      }
    }
  }
  const jaen::Lexicon& lexicon = argc == 3 ? override : mozc::converter::EnglishLexicon();
  const char* choices_file = std::getenv("JAEN_CHOICES");
  const std::shared_ptr<const jaen::Choices> choices =
      choices_file ? jaen::ChoiceStore(choices_file).Get() : nullptr;
  const bool typo = std::getenv("JAEN_TYPO") != nullptr;
  const char* margin_text = std::getenv("JAEN_TYPO_MARGIN");
  const double margin = margin_text ? std::atof(margin_text) : 3.0;
  const char* floor_text = std::getenv("JAEN_TYPO_FLOOR");
  const double floor = floor_text ? std::atof(floor_text) : -4.5;
  for (std::string line; std::getline(std::cin, line);) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (typo) {
      const std::optional<std::string> fixed =
          jaen::FixTypo(line, parse, mozc::converter::TypoKanaModel(), margin, floor);
      const auto kana = [&](std::string_view raw) {
        std::string out;
        for (const jaen::Chunk& chunk : parse(raw)) out += chunk.conversion + chunk.pending;
        return out;
      };
      std::cout << line << '\t' << fixed.value_or("") << '\t' << (fixed ? kana(*fixed) : "")
                << '\t' << kana(line) << '\n';
      continue;
    }
    const auto pieces = jaen::SplitEnglish(Chunks(table, line), lexicon, parse, choices.get());
    std::cout << line << '\t';
    const char* sep = "";
    for (const jaen::Piece& piece : pieces) {
      if (!piece.english) continue;
      std::cout << sep << line.substr(piece.begin, piece.end - piece.begin);
      sep = ",";
    }
    std::cout << '\n';
  }
  return 0;
}
