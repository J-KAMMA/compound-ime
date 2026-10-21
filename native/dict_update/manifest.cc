#include "dict_update/manifest.h"

#include <set>

namespace dict_update {
namespace {

std::vector<std::string_view> SplitTabs(std::string_view line) {
  std::vector<std::string_view> fields;
  size_t start = 0;
  while (true) {
    const size_t tab = line.find('\t', start);
    if (tab == std::string_view::npos) {
      fields.push_back(line.substr(start));
      return fields;
    }
    fields.push_back(line.substr(start, tab - start));
    start = tab + 1;
  }
}

bool AllOf(std::string_view s, bool (*pred)(char)) {
  for (char c : s)
    if (!pred(c)) return false;
  return !s.empty();
}

bool IsDigit(char c) { return c >= '0' && c <= '9'; }
bool IsHexLower(char c) { return IsDigit(c) || (c >= 'a' && c <= 'f'); }
bool IsNameChar(char c) {
  return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || IsDigit(c) || c == '.' || c == '_' || c == '-';
}
bool IsKindChar(char c) { return c >= 'a' && c <= 'z'; }
bool IsUrlChar(char c) { return static_cast<unsigned char>(c) > 0x20 && static_cast<unsigned char>(c) < 0x7f && c != '"' && c != '\\'; }

}  // namespace

const ManifestFile* Manifest::Find(std::string_view kind) const {
  for (const ManifestFile& f : files)
    if (f.kind == kind) return &f;
  return nullptr;
}

bool ParseManifest(std::string_view text, std::string_view url_prefix, Manifest* out, std::string* error) {
  auto fail = [&](const std::string& why) {
    if (error) *error = why;
    return false;
  };
  if (text.size() > 65536) return fail("manifest too large");
  Manifest m;
  bool seen_magic = false, seen_version = false, seen_pos = false;
  std::set<std::string> kinds, names;
  size_t start = 0, number = 0;
  while (start < text.size()) {
    size_t end = text.find('\n', start);
    if (end == std::string_view::npos) end = text.size();
    std::string_view line = text.substr(start, end - start);
    start = end + 1;
    ++number;
    if (!line.empty() && line.back() == '\r') line.remove_suffix(1);
    if (line.empty() || line[0] == '#') continue;
    const std::vector<std::string_view> f = SplitTabs(line);
    const std::string where = "manifest line " + std::to_string(number) + ": ";
    if (!seen_magic) {
      if (f.size() != 2 || f[0] != "compound-ime-dict-manifest" || f[1] != "1") return fail(where + "unsupported format");
      seen_magic = true;
      m.format = 1;
    } else if (f[0] == "version") {
      if (seen_version || f.size() != 2 || f[1].size() != 8 || !AllOf(f[1], IsDigit)) return fail(where + "bad version");
      m.version = std::stoull(std::string(f[1]));
      if (m.version < 20200101 || m.version > 99991231) return fail(where + "bad version");
      seen_version = true;
    } else if (f[0] == "created") {
      if (f.size() != 2 || f[1].size() > 32) return fail(where + "bad created");
      m.created = std::string(f[1]);
    } else if (f[0] == "pos_table") {
      if (seen_pos || f.size() != 2 || f[1].size() != 64 || !AllOf(f[1], IsHexLower)) return fail(where + "bad pos_table");
      m.pos_table = std::string(f[1]);
      seen_pos = true;
    } else if (f[0] == "file") {
      if (f.size() != 6) return fail(where + "bad file row");
      ManifestFile file;
      file.kind = std::string(f[1]);
      file.name = std::string(f[2]);
      if (!AllOf(f[1], IsKindChar) || f[1].size() > 16) return fail(where + "bad kind");
      if (!AllOf(f[2], IsNameChar) || f[2].size() > 64 || f[2][0] == '.') return fail(where + "bad name");
      if (f[3].size() > 10 || !AllOf(f[3], IsDigit)) return fail(where + "bad size");
      file.size = std::stoull(std::string(f[3]));
      if (f[4].size() != 64 || !AllOf(f[4], IsHexLower)) return fail(where + "bad sha256");
      file.sha256 = std::string(f[4]);
      if (f[5].size() > 400 || !AllOf(f[5], IsUrlChar)) return fail(where + "bad url");
      file.url = std::string(f[5]);
      if (!url_prefix.empty() && file.url.compare(0, url_prefix.size(), url_prefix) != 0) {
        return fail(where + "url outside the allowed place");
      }
      if (!kinds.insert(file.kind).second || !names.insert(file.name).second) return fail(where + "duplicate file");
      if (file.name == "manifest.txt" || file.name == "manifest.txt.sig") return fail(where + "reserved name");
      m.files.push_back(std::move(file));
    }
    // 知らない行は読み飛ばす（あとの版で足した項目を、古い本体が無視できるように）
  }
  if (!seen_magic || !seen_version || !seen_pos) return fail("manifest lacks version or pos_table");
  if (m.files.empty()) return fail("manifest lists no files");
  *out = std::move(m);
  return true;
}

}  // namespace dict_update
