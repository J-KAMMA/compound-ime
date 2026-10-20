// 判定の門の模型の推論（C++ だけで書いた、外部の部品を使わない版）と、時間の測定。
//
//   jevgate_infer selftest
//       速い tanh と exp の誤差を調べる
//   jevgate_infer check <jevgate.bin> <case.txt> [スレッド数]
//       tools/jev-gate/jevgate.py dumpcase の見本（torch の出力）と同じ答えが出るか確かめる
//       （門・候補の点・答えを選ぶ頭 b（枠ごとの度合い）と a（v5 と候補の一番）。見本は v5 の出力の枠つき。
//        枠を外した入力の門の出力が枠つきと同じことも確かめる）
//   jevgate_infer bench [--model jevgate.bin] [--d 256 --layers 4 --heads 4 --ffn 1024 --vocab 4096 --gate-hidden 256]
//                       [--k 4] [--prefix 60] [--cand 25] [--threads 1] [--iters 300] [--v5 0]
//       --v5 1 なら v5 の出力の枠を 1 つ足した入力（生成のあとの2回目の通し）の時間を測る
//       1回の推論の時間（ミリ秒）。--model がなければ乱数の重みで同じ形の模型を作って測る（時間は重みの値によらない）
//
// 組み立て: g++ -O3 -std=c++17 -mavx2 -mfma -fopenmp tools/jev-gate/jevgate_infer.cpp -o jevgate_infer
// 重みの表の形式は tools/jev-gate/jevgate.py の export と同じ（JEVG、単精度か半精度）。
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <random>
#include <sstream>
#include <string>
#include <vector>
#include "jevgate_core.h"

namespace {

using namespace jevgate;

// ---------------------------------------------------------------- 入口
std::vector<int> ReadInts(const std::string& line) {
  std::istringstream ss(line);
  std::vector<int> v;
  int x;
  while (ss >> x) v.push_back(x);
  return v;
}

std::vector<float> ReadFloats(const std::string& line) {
  std::istringstream ss(line);
  std::vector<float> v;
  float x;
  while (ss >> x) v.push_back(x);
  return v;
}

int SelfTest() {
  double mt = 0, me = 0;
  for (float x = -9; x <= 9; x += 0.0007f) mt = std::max(mt, static_cast<double>(std::fabs(FastTanh(x) - std::tanh(x))));
  for (float x = -30; x <= 0.5f; x += 0.0007f) {
    const double e = std::exp(static_cast<double>(x));
    me = std::max(me, std::fabs(FastExp(x) - e) / e);
  }
  std::printf("tanh の最大の誤差 %.2e、exp の最大の相対誤差 %.2e\n", mt, me);
  return (mt < 2e-6 && me < 5e-5) ? 0 : 1;
}

int Check(const std::string& model_path, const std::string& case_path, int threads) {
  jevgate::SetThreads(threads);
  Model m;
  if (!LoadModel(model_path, &m)) { std::fprintf(stderr, "重みを読めない\n"); return 1; }
  std::ifstream in(case_path);
  std::string line;
  Runner runner(m);
  double worst = 0;
  int cases = 0;
  while (std::getline(in, line)) {
    if (line.empty()) continue;
    Input x;
    std::getline(in, line); x.tok = ReadInts(line);
    std::getline(in, line); x.typ = ReadInts(line);
    std::getline(in, line); x.pos = ReadInts(line);
    std::getline(in, line); x.rank = ReadInts(line);
    std::getline(in, line); x.src = ReadInts(line);
    std::getline(in, line); x.seg = ReadInts(line);
    std::getline(in, line); const auto gate = ReadFloats(line);
    std::getline(in, line); const auto score = ReadFloats(line);
    std::getline(in, line); const auto item = ReadFloats(line);
    std::getline(in, line); const auto pair = ReadFloats(line);
    Output out;
    runner.Run(x, &out);
    for (size_t i = 0; i < item.size() && i < out.item.size(); ++i)
      worst = std::max(worst, static_cast<double>(std::fabs(item[i] - out.item[i])));
    if (!pair.empty()) worst = std::max(worst, static_cast<double>(std::fabs(pair[0] - out.pair)));
    if (!item.empty() && item.size() != out.item.size()) { std::printf("枠ごとの度合いの数が違う\n"); worst = 1e9; }
    // 生成の前の入力（v5 の出力の枠を外したもの）でも門と点が同じか
    if (out.has_v5) {
      Input y;
      for (size_t i = 0; i < x.tok.size(); ++i) {
        if (x.src[i] == kSrcV5) continue;
        y.tok.push_back(x.tok[i]); y.typ.push_back(x.typ[i]); y.pos.push_back(x.pos[i]);
        y.rank.push_back(x.rank[i]); y.src.push_back(x.src[i]); y.seg.push_back(x.seg[i]);
      }
      Output o2;
      runner.Run(y, &o2);
      double d2 = 0;
      for (size_t i = 0; i < out.gate.size(); ++i) d2 = std::max(d2, static_cast<double>(std::fabs(out.gate[i] - o2.gate[i])));
      for (size_t i = 0; i < out.score.size() && i < o2.score.size(); ++i)
        d2 = std::max(d2, static_cast<double>(std::fabs(out.score[i] - o2.score[i])));
      std::printf("  v5 の枠を外した入力との差 %.2e（門・点）、選ぶ頭 b %zu 個 a %.4f（torch %.4f）\n", d2, out.item.size(), out.pair,
                  pair.empty() ? 0.f : pair[0]);
      worst = std::max(worst, d2);
    }
    for (size_t i = 0; i < gate.size(); ++i) worst = std::max(worst, static_cast<double>(std::fabs(gate[i] - out.gate[i])));
    for (size_t i = 0; i < score.size() && i < out.score.size(); ++i)
      worst = std::max(worst, static_cast<double>(std::fabs(score[i] - out.score[i])));
    std::printf("見本 %d: 門 %.5f %.5f %.5f %.5f（torch %.5f %.5f %.5f %.5f）\n", ++cases, out.gate[0], out.gate[1], out.gate[2],
                out.gate[3], gate[0], gate[1], gate[2], gate[3]);
  }
  std::printf("最大の差 %.2e（%d 見本）\n", worst, cases);
  return worst < 2e-3 ? 0 : 1;
}

Input MakeInput(int prefix, int cand, int k, int vocab, std::mt19937* rng, bool v5 = false) {
  Input in;
  std::uniform_int_distribution<int> tok(5, vocab - 1);
  auto push = [&](int t, int ty, int pos, int rank, int src, int seg) {
    in.tok.push_back(t); in.typ.push_back(ty); in.pos.push_back(pos); in.rank.push_back(rank); in.src.push_back(src); in.seg.push_back(seg);
  };
  for (int i = 0; i < prefix; ++i) push(i == 0 ? 2 : tok(*rng), i == 0 ? 0 : (i < prefix / 3 ? 1 : 2), i, 0, 0, 0);
  for (int s = 0; s < k; ++s)
    for (int i = 0; i < cand; ++i) push(i == cand - 1 ? 4 : tok(*rng), kTypeCand, i, s, 1 + (s > 0), s + 1);
  if (v5)
    for (int i = 0; i < cand; ++i) push(i == cand - 1 ? 4 : tok(*rng), kTypeCand, i, k, kSrcV5, k + 1);
  return in;
}

int Bench(int argc, char** argv) {
  Config c;
  c.d = 256; c.layers = 4; c.heads = 4; c.ffn = 1024; c.vocab = 4096; c.gate_hidden = 256; c.k = 4;
  std::string model_path;
  int k = 4, prefix = 60, cand = 25, threads = 1, iters = 300, v5 = 0;
  for (int i = 2; i + 1 < argc; i += 2) {
    const std::string a = argv[i];
    const int v = std::atoi(argv[i + 1]);
    if (a == "--model") model_path = argv[i + 1];
    else if (a == "--d") c.d = v;
    else if (a == "--layers") c.layers = v;
    else if (a == "--heads") c.heads = v;
    else if (a == "--ffn") c.ffn = v;
    else if (a == "--vocab") c.vocab = v;
    else if (a == "--gate-hidden") c.gate_hidden = v;
    else if (a == "--k") k = v;
    else if (a == "--prefix") prefix = v;
    else if (a == "--cand") cand = v;
    else if (a == "--threads") threads = v;
    else if (a == "--iters") iters = v;
    else if (a == "--v5") v5 = v;
  }
  jevgate::SetThreads(threads);
  Model m;
  if (!model_path.empty()) {
    if (!LoadModel(model_path, &m)) { std::fprintf(stderr, "重みを読めない\n"); return 1; }
  } else {
    RandomModel(c, &m);
  }
  std::mt19937 rng(7);
  Runner runner(m);
  size_t params = 0;
  ForEachTensor(m, [&](std::vector<float>&, size_t n, const char*) { params += n; });
  std::vector<double> ms;
  Output out;
  for (int it = 0; it < iters + 30; ++it) {
    Input in = MakeInput(prefix, cand, k, m.c.vocab, &rng, v5 != 0);
    const auto t0 = std::chrono::steady_clock::now();
    runner.Run(in, &out);
    const double e = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    if (it >= 30) ms.push_back(e);
  }
  std::sort(ms.begin(), ms.end());
  double sum = 0;
  for (double v : ms) sum += v;
  const int T = prefix + (k + (v5 ? 1 : 0)) * cand;
  std::printf("d=%d 層=%d 頭=%d ffn=%d 語彙=%d 数=%.2f百万 | 前置き %d 字 候補 %d 個×%d 字 = %d 語片 | スレッド %d | 平均 %.2f ms、中央値 %.2f、90%%点 %.2f、最小 %.2f\n",
              m.c.d, m.c.layers, m.c.heads, m.c.ffn, m.c.vocab, params / 1e6, prefix, k, cand, T, threads, sum / ms.size(),
              ms[ms.size() / 2], ms[static_cast<size_t>(ms.size() * 0.9)], ms.front());
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "使い方: jevgate_infer selftest | check <jevgate.bin> <case.txt> [スレッド数] | bench [--model f] [--k n] …\n");
    return 2;
  }
  const std::string cmd = argv[1];
  if (cmd == "selftest") return SelfTest();
  if (cmd == "check" && argc >= 4) return Check(argv[2], argv[3], argc > 4 ? std::atoi(argv[4]) : 1);
  if (cmd == "bench") return Bench(argc, argv);
  std::fprintf(stderr, "命令が分かりません\n");
  return 2;
}
