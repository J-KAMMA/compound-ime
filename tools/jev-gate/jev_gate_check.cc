// jev_gate.cc の確かめ: tools/jev-gate/jev_gate_cases.py の見本を読み、torch の出力と同じになるか調べる（と、1回の時間を測る）。
//   jev_gate_check <jevgate.bin> <cases.tsv> [スレッド数]
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "jev_gate.h"

static std::vector<std::string> Split(const std::string& s, char sep) {
  std::vector<std::string> out;
  std::string cur;
  for (char c : s) {
    if (c == sep) { out.push_back(cur); cur.clear(); } else cur.push_back(c);
  }
  out.push_back(cur);
  return out;
}

static std::string Unesc(const std::string& s) {
  std::string out;
  for (size_t i = 0; i < s.size(); ++i) {
    if (s[i] == '\\' && i + 1 < s.size()) {
      ++i;
      out.push_back(s[i] == 'n' ? '\n' : s[i]);
    } else {
      out.push_back(s[i]);
    }
  }
  return out;
}

static std::vector<float> Floats(const std::string& s) {
  std::istringstream ss(s);
  std::vector<float> v;
  float x;
  while (ss >> x) v.push_back(x);
  return v;
}

int main(int argc, char** argv) {
  if (argc < 3) { std::fprintf(stderr, "使い方: jev_gate_check <jevgate.bin> <cases.tsv> [スレッド数]\n"); return 2; }
  if (!jev_gate::Load(argv[1], argc > 3 ? std::atoi(argv[3]) : 1)) { std::fprintf(stderr, "模型を読めない\n"); return 1; }
  std::ifstream in(argv[2]);
  std::string line;
  double worst = 0, total_ms = 0;
  int n = 0;
  while (std::getline(in, line)) {
    if (line.empty()) continue;
    const auto f = Split(line, '\t');
    size_t hash = 0;
    for (size_t i = 0; i < f.size(); ++i) if (f[i] == "#") { hash = i; break; }
    if (hash < 2) continue;
    std::vector<jev_gate::Cand> cands;
    for (size_t i = 2; i + 1 < hash; i += 2) cands.push_back({Unesc(f[i]), std::atoi(f[i + 1].c_str())});
    const auto gate = Floats(f[hash + 1]);
    const auto score = Floats(hash + 2 < f.size() ? f[hash + 2] : "");
    jev_gate::Result r;
    if (!jev_gate::Predict(Unesc(f[0]), Unesc(f[1]), cands, &r)) { std::printf("推論に失敗\n"); return 1; }
    double d = 0;
    const float got[4] = {r.need, r.need_k, r.need_top1, r.harm_k};
    for (int i = 0; i < 4 && i < static_cast<int>(gate.size()); ++i) d = std::max(d, static_cast<double>(std::fabs(got[i] - gate[i])));
    for (size_t i = 0; i < score.size() && i < r.score.size(); ++i) d = std::max(d, static_cast<double>(std::fabs(r.score[i] - score[i])));
    if (score.size() != r.score.size()) d = 1e9;
    if (d > 2e-3) std::printf("差 %.2e: %s\n", d, f[1].c_str());
    worst = std::max(worst, d);
    total_ms += r.ms;
    ++n;
  }
  std::printf("見本 %d 件、最大の差 %.2e、1件の平均 %.2f ms\n", n, worst, n ? total_ms / n : 0.0);
  return worst < 2e-3 ? 0 : 1;
}
