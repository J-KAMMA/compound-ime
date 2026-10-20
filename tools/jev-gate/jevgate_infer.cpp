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
#ifdef _OPENMP
#include <omp.h>
#endif
#if defined(__AVX2__) && defined(__FMA__)
#include <immintrin.h>
#define JEV_AVX2 1
#endif

namespace {

constexpr int kTypeCand = 3;
constexpr int kSrcV5 = 4;  // v5 の出力の枠の src 番号（jevgate.py の V5_SRC）

// ---------------------------------------------------------------- 速い tanh と exp（ベクトル化できる形）
inline float FastTanh(float x) {
  x = std::max(-7.99881172180175781f, std::min(7.99881172180175781f, x));
  const float x2 = x * x;
  float p = x2 * -2.76076847742355e-16f + 2.00018790482477e-13f;
  p = p * x2 + -8.60467152213735e-11f;
  p = p * x2 + 5.12229709037114e-08f;
  p = p * x2 + 1.48572235717979e-05f;
  p = p * x2 + 6.37261928875436e-04f;
  p = p * x2 + 4.89352455891786e-03f;
  p = p * x;
  float q = x2 * 1.19825839466702e-06f + 1.18534705686654e-04f;
  q = q * x2 + 2.26843463243900e-03f;
  q = q * x2 + 4.89352518554385e-03f;
  return p / q;
}

inline float FastExp(float x) {
  x = std::max(-87.0f, std::min(88.0f, x));
  const float t = x * 1.44269504f;
  const float fi = std::floor(t);
  const float f = t - fi;
  float p = 1.5252733e-05f;
  p = p * f + 1.5403530e-04f;
  p = p * f + 1.3333558e-03f;
  p = p * f + 9.6181291e-03f;
  p = p * f + 5.5504109e-02f;
  p = p * f + 2.4022651e-01f;
  p = p * f + 6.9314718e-01f;
  p = p * f + 1.0f;
  const int32_t bits = (static_cast<int32_t>(fi) + 127) << 23;
  float scale;
  std::memcpy(&scale, &bits, sizeof(scale));
  return p * scale;
}

inline float Gelu(float x) {
  return 0.5f * x * (1.0f + FastTanh(0.7978845608028654f * (x + 0.044715f * x * x * x)));
}

// 内積と、活性化（GELU）の一括計算（AVX2 があれば手で書いた版を使う）
inline float Dot(const float* a, const float* b, int n) {
  float s = 0;
  int i = 0;
#ifdef JEV_AVX2
  __m256 acc = _mm256_setzero_ps(), acc2 = acc;
  for (; i + 16 <= n; i += 16) {
    acc = _mm256_fmadd_ps(_mm256_loadu_ps(a + i), _mm256_loadu_ps(b + i), acc);
    acc2 = _mm256_fmadd_ps(_mm256_loadu_ps(a + i + 8), _mm256_loadu_ps(b + i + 8), acc2);
  }
  for (; i + 8 <= n; i += 8) acc = _mm256_fmadd_ps(_mm256_loadu_ps(a + i), _mm256_loadu_ps(b + i), acc);
  acc = _mm256_add_ps(acc, acc2);
  __m128 lo = _mm_add_ps(_mm256_castps256_ps128(acc), _mm256_extractf128_ps(acc, 1));
  lo = _mm_hadd_ps(lo, lo);
  lo = _mm_hadd_ps(lo, lo);
  s = _mm_cvtss_f32(lo);
#endif
  for (; i < n; ++i) s += a[i] * b[i];
  return s;
}

void GeluAll(float* p, int n) {
  int i = 0;
#ifdef JEV_AVX2
  const __m256 lim = _mm256_set1_ps(7.99881172180175781f), nlim = _mm256_set1_ps(-7.99881172180175781f);
  auto c = [](float v) { return _mm256_set1_ps(v); };
#pragma omp parallel for schedule(static)
  for (int blk = 0; blk < n / 8; ++blk) {
    const __m256 x = _mm256_loadu_ps(p + blk * 8);
    const __m256 u = _mm256_mul_ps(c(0.7978845608028654f), _mm256_fmadd_ps(_mm256_mul_ps(c(0.044715f), _mm256_mul_ps(x, x)), x, x));
    const __m256 t = _mm256_max_ps(nlim, _mm256_min_ps(lim, u));
    const __m256 t2 = _mm256_mul_ps(t, t);
    __m256 pn = _mm256_fmadd_ps(t2, c(-2.76076847742355e-16f), c(2.00018790482477e-13f));
    pn = _mm256_fmadd_ps(pn, t2, c(-8.60467152213735e-11f));
    pn = _mm256_fmadd_ps(pn, t2, c(5.12229709037114e-08f));
    pn = _mm256_fmadd_ps(pn, t2, c(1.48572235717979e-05f));
    pn = _mm256_fmadd_ps(pn, t2, c(6.37261928875436e-04f));
    pn = _mm256_fmadd_ps(pn, t2, c(4.89352455891786e-03f));
    pn = _mm256_mul_ps(pn, t);
    __m256 q = _mm256_fmadd_ps(t2, c(1.19825839466702e-06f), c(1.18534705686654e-04f));
    q = _mm256_fmadd_ps(q, t2, c(2.26843463243900e-03f));
    q = _mm256_fmadd_ps(q, t2, c(4.89352518554385e-03f));
    const __m256 th = _mm256_div_ps(pn, q);
    _mm256_storeu_ps(p + blk * 8, _mm256_mul_ps(_mm256_mul_ps(c(0.5f), x), _mm256_add_ps(c(1.0f), th)));
  }
  i = (n / 8) * 8;
#endif
  for (; i < n; ++i) p[i] = Gelu(p[i]);
}

// ---------------------------------------------------------------- 行列の積 Y[T][O] = X[T][I] · W[O][I]^T + b
// 4 行 × 2 列を同時に計算する（累積 8 本で FMA の待ちを隠す）。列ごとに分けて並列にする
#ifdef JEV_AVX2
__attribute__((always_inline)) inline float HSum(__m256 v) {
  __m128 lo = _mm256_castps256_ps128(v), hi = _mm256_extractf128_ps(v, 1);
  lo = _mm_add_ps(lo, hi);
  lo = _mm_hadd_ps(lo, lo);
  lo = _mm_hadd_ps(lo, lo);
  return _mm_cvtss_f32(lo);
}
#endif

void Linear(const float* X, int T, int I, const float* W, const float* b, int O, float* Y) {
  const int I8 = I & ~7;
  const int pairs = (O + 1) / 2;
#pragma omp parallel for schedule(static)
  for (int pp = 0; pp < pairs; ++pp) {
    const int o0 = pp * 2;
    const int on = std::min(2, O - o0);
    const float* w0 = W + static_cast<size_t>(o0) * I;
    const float* w1 = on > 1 ? w0 + I : w0;
    int t = 0;
#ifdef JEV_AVX2
    for (; t + 4 <= T; t += 4) {
      const float* x0 = X + static_cast<size_t>(t) * I;
      const float* x1 = x0 + I;
      const float* x2 = x1 + I;
      const float* x3 = x2 + I;
      __m256 a00 = _mm256_setzero_ps(), a01 = a00, a10 = a00, a11 = a00, a20 = a00, a21 = a00, a30 = a00, a31 = a00;
      for (int i = 0; i < I8; i += 8) {
        const __m256 v0 = _mm256_loadu_ps(w0 + i), v1 = _mm256_loadu_ps(w1 + i);
        __m256 x = _mm256_loadu_ps(x0 + i);
        a00 = _mm256_fmadd_ps(x, v0, a00);
        a01 = _mm256_fmadd_ps(x, v1, a01);
        x = _mm256_loadu_ps(x1 + i);
        a10 = _mm256_fmadd_ps(x, v0, a10);
        a11 = _mm256_fmadd_ps(x, v1, a11);
        x = _mm256_loadu_ps(x2 + i);
        a20 = _mm256_fmadd_ps(x, v0, a20);
        a21 = _mm256_fmadd_ps(x, v1, a21);
        x = _mm256_loadu_ps(x3 + i);
        a30 = _mm256_fmadd_ps(x, v0, a30);
        a31 = _mm256_fmadd_ps(x, v1, a31);
      }
      float r[4][2] = {{HSum(a00), HSum(a01)}, {HSum(a10), HSum(a11)}, {HSum(a20), HSum(a21)}, {HSum(a30), HSum(a31)}};
      for (int i = I8; i < I; ++i)
        for (int r4 = 0; r4 < 4; ++r4) {
          const float xv = X[static_cast<size_t>(t + r4) * I + i];
          r[r4][0] += xv * w0[i];
          r[r4][1] += xv * w1[i];
        }
      for (int r4 = 0; r4 < 4; ++r4)
        for (int c = 0; c < on; ++c) Y[static_cast<size_t>(t + r4) * O + o0 + c] = r[r4][c] + (b ? b[o0 + c] : 0.f);
    }
#endif
    for (; t < T; ++t) {
      const float* x = X + static_cast<size_t>(t) * I;
      for (int c = 0; c < on; ++c) {
        const float* w = c == 0 ? w0 : w1;
        float s = 0;
        for (int i = 0; i < I; ++i) s += x[i] * w[i];
        Y[static_cast<size_t>(t) * O + o0 + c] = s + (b ? b[o0 + c] : 0.f);
      }
    }
  }
}

void LayerNorm(const float* X, int T, int d, const float* g, const float* b, float* Y) {
#pragma omp parallel for schedule(static)
  for (int t = 0; t < T; ++t) {
    const float* x = X + static_cast<size_t>(t) * d;
    float mean = 0;
    for (int i = 0; i < d; ++i) mean += x[i];
    mean /= d;
    float var = 0;
    for (int i = 0; i < d; ++i) var += (x[i] - mean) * (x[i] - mean);
    const float inv = 1.0f / std::sqrt(var / d + 1e-5f);
    float* y = Y + static_cast<size_t>(t) * d;
    for (int i = 0; i < d; ++i) y[i] = (x[i] - mean) * inv * g[i] + b[i];
  }
}

// ---------------------------------------------------------------- 模型
struct Config {
  int version = 1, fp16 = 0, vocab = 0, d = 0, layers = 0, heads = 0, ffn = 0, k = 0, gate_hidden = 0;
  int max_prefix_pos = 128, max_cand_pos = 64, max_rank = 16, n_gate = 4;
};

struct Layer {
  std::vector<float> ln1w, ln1b, qkvw, qkvb, projw, projb, ln2w, ln2b, fc1w, fc1b, fc2w, fc2b;
};

struct Model {
  Config c;
  std::vector<float> tok, typ, pos_prefix, pos_cand, rank, src;
  std::vector<Layer> layers;
  std::vector<float> lnfw, lnfb, s1w, s1b, s2w, s2b, g1w, g1b, g2w, g2b, i1w, i1b, i2w, i2b, p1w, p1b, p2w, p2b;
};

float HalfToFloat(uint16_t h) {
  const uint32_t sign = (h >> 15) & 1, exp = (h >> 10) & 31, man = h & 1023;
  if (exp == 0) return (sign ? -1.0f : 1.0f) * std::ldexp(static_cast<float>(man), -24);
  uint32_t bits;
  if (exp == 31) bits = (sign << 31) | 0x7f800000 | (man << 13);
  else bits = (sign << 31) | ((exp + 112) << 23) | (man << 13);
  float f;
  std::memcpy(&f, &bits, sizeof(f));
  return f;
}

// 各重みの (個数) を、読む順に決める（jevgate.py の tensor_order と同じ）
template <class F>
void ForEachTensor(Model& m, F f) {
  const Config& c = m.c;
  const size_t d = c.d;
  f(m.tok, static_cast<size_t>(c.vocab) * d, "tok");
  f(m.typ, 4 * d, "typ");
  f(m.pos_prefix, static_cast<size_t>(c.max_prefix_pos) * d, "pos_prefix");
  f(m.pos_cand, static_cast<size_t>(c.max_cand_pos) * d, "pos_cand");
  f(m.rank, static_cast<size_t>(c.max_rank) * d, "rank");
  f(m.src, 5 * d, "src");
  const size_t ffn = c.ffn;
  for (auto& L : m.layers) {
    f(L.ln1w, d, "ln1w"); f(L.ln1b, d, "ln1b");
    f(L.qkvw, 3 * d * d, "qkvw"); f(L.qkvb, 3 * d, "qkvb");
    f(L.projw, d * d, "projw"); f(L.projb, d, "projb");
    f(L.ln2w, d, "ln2w"); f(L.ln2b, d, "ln2b");
    f(L.fc1w, ffn * d, "fc1w"); f(L.fc1b, ffn, "fc1b");
    f(L.fc2w, d * ffn, "fc2w"); f(L.fc2b, d, "fc2b");
  }
  f(m.lnfw, d, "lnfw"); f(m.lnfb, d, "lnfb");
  f(m.s1w, (d / 2) * d, "s1w"); f(m.s1b, d / 2, "s1b");
  f(m.s2w, d / 2, "s2w"); f(m.s2b, 1, "s2b");
  const size_t gin = 3 * d + 3, gh = c.gate_hidden;
  f(m.g1w, gh * gin, "g1w"); f(m.g1b, gh, "g1b");
  f(m.g2w, static_cast<size_t>(c.n_gate) * gh, "g2w"); f(m.g2b, c.n_gate, "g2b");
  f(m.i1w, gh * (3 * d + 7), "i1w"); f(m.i1b, gh, "i1b");
  f(m.i2w, gh, "i2w"); f(m.i2b, 1, "i2b");
  f(m.p1w, gh * (3 * d + 6), "p1w"); f(m.p1b, gh, "p1b");
  f(m.p2w, gh, "p2w"); f(m.p2b, 1, "p2b");
}

bool LoadModel(const std::string& path, Model* m) {
  std::ifstream in(path, std::ios::binary);
  char magic[4];
  if (!in.read(magic, 4) || std::memcmp(magic, "JEVG", 4) != 0) return false;
  int32_t h[13];
  if (!in.read(reinterpret_cast<char*>(h), sizeof(h))) return false;
  Config& c = m->c;
  c.version = h[0]; c.fp16 = h[1]; c.vocab = h[2]; c.d = h[3]; c.layers = h[4]; c.heads = h[5]; c.ffn = h[6];
  c.k = h[7]; c.gate_hidden = h[8]; c.max_prefix_pos = h[9]; c.max_cand_pos = h[10]; c.max_rank = h[11]; c.n_gate = h[12];
  m->layers.assign(c.layers, Layer());
  bool ok = true;
  ForEachTensor(*m, [&](std::vector<float>& v, size_t n, const char*) {
    v.resize(n);
    if (c.fp16) {
      std::vector<uint16_t> tmp(n);
      ok &= static_cast<bool>(in.read(reinterpret_cast<char*>(tmp.data()), static_cast<std::streamsize>(n * 2)));
      for (size_t i = 0; i < n; ++i) v[i] = HalfToFloat(tmp[i]);
    } else {
      ok &= static_cast<bool>(in.read(reinterpret_cast<char*>(v.data()), static_cast<std::streamsize>(n * 4)));
    }
  });
  return ok;
}

void RandomModel(const Config& c, Model* m) {
  m->c = c;
  m->layers.assign(c.layers, Layer());
  std::mt19937 rng(1);
  std::normal_distribution<float> nd(0.f, 0.02f);
  ForEachTensor(*m, [&](std::vector<float>& v, size_t n, const char* name) {
    v.resize(n);
    const size_t len = std::strlen(name);
    const bool bias = name[len - 1] == 'b' && std::strncmp(name, "pos", 3) != 0;
    const bool ln_w = std::strncmp(name, "ln", 2) == 0 && name[len - 1] == 'w';
    for (auto& x : v) x = ln_w ? 1.0f : (bias ? 0.f : nd(rng));
  });
}

struct Input {
  std::vector<int> tok, typ, pos, rank, src, seg;
};

struct Output {
  std::vector<float> gate;   // 確率（need、need_k、need_top1、harm_k）
  std::vector<float> score;  // 候補ごとの点（v5 の枠は含めない）
  int best = 0;
  // 答えを選ぶ頭（入力に v5 の出力の枠があるときだけ）
  std::vector<float> item;   // b: 候補ごとの正解の度合い（ロジット）、最後が v5 の出力
  float pair = 0.f;          // a: v5 が正しいほうのロジット（v5 と候補の一番）
  float score_v5 = 0.f;
  bool has_v5 = false;
};

struct Runner {
  const Model& m;
  std::vector<float> x, h, qkv, ctx, ff, pooled, tmp;
  explicit Runner(const Model& model) : m(model) {}

  void Run(const Input& in, Output* out) {
    const Config& c = m.c;
    const int T = static_cast<int>(in.tok.size()), d = c.d, H = c.heads, dh = d / H;
    x.assign(static_cast<size_t>(T) * d, 0.f);
    h.resize(static_cast<size_t>(T) * d);
    qkv.resize(static_cast<size_t>(T) * 3 * d);
    ctx.resize(static_cast<size_t>(T) * d);
    ff.resize(static_cast<size_t>(T) * c.ffn);
    int Lp = 0;
    while (Lp < T && in.seg[Lp] == 0) ++Lp;
    // 枠の範囲
    std::vector<int> cs, ce;
    for (int i = Lp; i < T; ++i) {
      const int s = in.seg[i] - 1;
      if (s >= static_cast<int>(cs.size())) { cs.resize(s + 1, T); ce.resize(s + 1, 0); }
      cs[s] = std::min(cs[s], i);
      ce[s] = std::max(ce[s], i + 1);
    }
    const int nseg = static_cast<int>(cs.size());
    // v5 の出力の枠（src が kSrcV5 の最後の枠）。あれば候補の数は 1 つ少ない
    const bool has_v5 = nseg > 0 && in.src[cs[nseg - 1]] == kSrcV5;
    const int nc = nseg - (has_v5 ? 1 : 0);
    for (int t = 0; t < T; ++t) {
      float* xr = &x[static_cast<size_t>(t) * d];
      const bool cand = in.typ[t] == kTypeCand;
      const float* a = &m.tok[static_cast<size_t>(in.tok[t]) * d];
      const float* b = &m.typ[static_cast<size_t>(in.typ[t]) * d];
      const float* p = cand ? &m.pos_cand[static_cast<size_t>(std::min(in.pos[t], c.max_cand_pos - 1)) * d]
                            : &m.pos_prefix[static_cast<size_t>(std::min(in.pos[t], c.max_prefix_pos - 1)) * d];
      const float* s = &m.src[static_cast<size_t>(in.src[t]) * d];
      const float* r = cand ? &m.rank[static_cast<size_t>(std::min(in.rank[t], c.max_rank - 1)) * d] : nullptr;
      for (int i = 0; i < d; ++i) xr[i] = a[i] + b[i] + p[i] + s[i] + (r ? r[i] : 0.f);
    }
    const float scale = 1.0f / std::sqrt(static_cast<float>(dh));
    for (const Layer& L : m.layers) {
      LayerNorm(x.data(), T, d, L.ln1w.data(), L.ln1b.data(), h.data());
      Linear(h.data(), T, d, L.qkvw.data(), L.qkvb.data(), 3 * d, qkv.data());
      // 注意: 前置きは前置きだけを、候補は前置きと自分だけを見る
#pragma omp parallel for collapse(2) schedule(static)
      for (int hh = 0; hh < H; ++hh) {
        for (int i = 0; i < T; ++i) {
          const bool is_prefix = i < Lp;
          const int seg = is_prefix ? -1 : in.seg[i] - 1;
          const int b0 = is_prefix ? 0 : cs[seg], b1 = is_prefix ? 0 : ce[seg];
          float sc[1024];
          const float* q = &qkv[static_cast<size_t>(i) * 3 * d + hh * dh];
          int n = 0;
          float mx = -1e30f;
          auto dot = [&](int j) {
            const float* k = &qkv[static_cast<size_t>(j) * 3 * d + d + hh * dh];
            return Dot(q, k, dh) * scale;
          };
          for (int j = 0; j < Lp; ++j) { sc[n] = dot(j); mx = std::max(mx, sc[n++]); }
          for (int j = b0; j < b1; ++j) { sc[n] = dot(j); mx = std::max(mx, sc[n++]); }
          float sum = 0;
          for (int e = 0; e < n; ++e) { sc[e] = FastExp(sc[e] - mx); sum += sc[e]; }
          const float inv = 1.0f / sum;
          float* o = &ctx[static_cast<size_t>(i) * d + hh * dh];
          for (int e = 0; e < dh; ++e) o[e] = 0;
          int idx = 0;
          auto acc = [&](int j) {
            const float w = sc[idx++] * inv;
            const float* v = &qkv[static_cast<size_t>(j) * 3 * d + 2 * d + hh * dh];
            for (int e = 0; e < dh; ++e) o[e] += w * v[e];
          };
          for (int j = 0; j < Lp; ++j) acc(j);
          for (int j = b0; j < b1; ++j) acc(j);
        }
      }
      Linear(ctx.data(), T, d, L.projw.data(), L.projb.data(), d, h.data());
      for (size_t i = 0; i < x.size(); ++i) x[i] += h[i];
      LayerNorm(x.data(), T, d, L.ln2w.data(), L.ln2b.data(), h.data());
      Linear(h.data(), T, d, L.fc1w.data(), L.fc1b.data(), c.ffn, ff.data());
      GeluAll(ff.data(), T * c.ffn);
      Linear(ff.data(), T, c.ffn, L.fc2w.data(), L.fc2b.data(), d, h.data());
      for (size_t i = 0; i < x.size(); ++i) x[i] += h[i];
    }
    LayerNorm(x.data(), T, d, m.lnfw.data(), m.lnfb.data(), h.data());
    // 枠ごとの平均と点（v5 の枠も同じ頭で点を付ける）
    const int ns = nc + (has_v5 ? 1 : 0);
    pooled.assign(static_cast<size_t>(std::max(ns, 1)) * d, 0.f);
    std::vector<float> sc_all(ns, 0.f), len_all(ns, 0.f);
    out->score.assign(nc, 0.f);
    std::vector<float> s1(d / 2);
    for (int s = 0; s < ns; ++s) {
      float* pr = &pooled[static_cast<size_t>(s) * d];
      int cnt = 0;
      for (int i = cs[s]; i < ce[s]; ++i) {
        if (in.seg[i] - 1 != s) continue;
        for (int e = 0; e < d; ++e) pr[e] += h[static_cast<size_t>(i) * d + e];
        ++cnt;
      }
      for (int e = 0; e < d; ++e) pr[e] /= std::max(cnt, 1);
      len_all[s] = cnt / 20.0f;
      Linear(pr, 1, d, m.s1w.data(), m.s1b.data(), d / 2, s1.data());
      for (auto& v : s1) v = Gelu(v);
      float sc = m.s2b[0];
      for (int e = 0; e < d / 2; ++e) sc += s1[e] * m.s2w[e];
      sc_all[s] = sc;
      if (s < nc) out->score[s] = sc;
    }
    int best = 0;
    for (int s = 1; s < nc; ++s) if (out->score[s] > out->score[best]) best = s;
    float second = -1e30f;
    for (int s = 0; s < nc; ++s) if (s != best) second = std::max(second, out->score[s]);
    const float margin = nc >= 2 ? out->score[best] - second : 1.0f;
    const int len = nc > 0 ? static_cast<int>(std::lround(len_all[best] * 20.0f)) : 0;
    std::vector<float> gin(3 * d + 3, 0.f);
    std::memcpy(gin.data(), &h[0], sizeof(float) * d);
    if (nc > 0) {
      std::memcpy(gin.data() + d, &pooled[static_cast<size_t>(best) * d], sizeof(float) * d);
      std::memcpy(gin.data() + 2 * d, &pooled[0], sizeof(float) * d);
      gin[3 * d] = out->score[best];
      gin[3 * d + 1] = margin;
      gin[3 * d + 2] = len / 20.0f;
    }
    std::vector<float> g1(c.gate_hidden), g2(c.n_gate);
    Linear(gin.data(), 1, 3 * d + 3, m.g1w.data(), m.g1b.data(), c.gate_hidden, g1.data());
    for (auto& v : g1) v = Gelu(v);
    Linear(g1.data(), 1, c.gate_hidden, m.g2w.data(), m.g2b.data(), c.n_gate, g2.data());
    out->gate.resize(c.n_gate);
    for (int i = 0; i < c.n_gate; ++i) out->gate[i] = 1.0f / (1.0f + std::exp(-g2[i]));
    out->best = best;
    out->has_v5 = has_v5;
    out->item.clear();
    if (!has_v5 || nc == 0) return;
    // 答えを選ぶ頭。v5 の枠は他の枠から見えないので、ここまでの門・点は枠の有無で変わらない
    const int gh = c.gate_hidden, v5 = nc;
    const float* pv5 = &pooled[static_cast<size_t>(v5) * d];
    out->score_v5 = sc_all[v5];
    const float sc_max = out->score[best];
    auto same_as_v5 = [&](int s) {
      int a = 0, b = 0;
      for (int i = cs[s]; i < ce[s]; ++i) a += in.seg[i] - 1 == s;
      for (int i = cs[v5]; i < ce[v5]; ++i) b += in.seg[i] - 1 == v5;
      if (a != b) return 0.f;
      int i = cs[s], j = cs[v5];
      for (int n = 0; n < a; ++n, ++i, ++j) if (in.tok[i] != in.tok[j]) return 0.f;
      return 1.f;
    };
    auto head = [&](const std::vector<float>& x, int dim, const std::vector<float>& w1, const std::vector<float>& b1,
                    const std::vector<float>& w2, const std::vector<float>& b2) {
      std::vector<float> hid(gh);
      Linear(x.data(), 1, dim, w1.data(), b1.data(), gh, hid.data());
      for (auto& v : hid) v = Gelu(v);
      float o = b2[0];
      for (int e = 0; e < gh; ++e) o += hid[e] * w2[e];
      return o;
    };
    out->item.resize(ns);
    std::vector<float> iin(3 * d + 7);
    for (int j = 0; j < ns; ++j) {
      std::memcpy(iin.data(), &h[0], sizeof(float) * d);
      std::memcpy(iin.data() + d, &pooled[static_cast<size_t>(j) * d], sizeof(float) * d);
      std::memcpy(iin.data() + 2 * d, pv5, sizeof(float) * d);
      float* ex = iin.data() + 3 * d;
      ex[0] = sc_all[j]; ex[1] = sc_max; ex[2] = sc_all[v5]; ex[3] = len_all[j]; ex[4] = len_all[v5];
      ex[5] = j == v5 ? 1.f : same_as_v5(j); ex[6] = j == v5 ? 1.f : 0.f;
      out->item[j] = head(iin, 3 * d + 7, m.i1w, m.i1b, m.i2w, m.i2b);
    }
    std::vector<float> pin(3 * d + 6);
    std::memcpy(pin.data(), &h[0], sizeof(float) * d);
    std::memcpy(pin.data() + d, pv5, sizeof(float) * d);
    std::memcpy(pin.data() + 2 * d, &pooled[0], sizeof(float) * d);
    float* ep = pin.data() + 3 * d;
    ep[0] = sc_all[0]; ep[1] = sc_all[v5]; ep[2] = sc_max; ep[3] = len_all[0]; ep[4] = len_all[v5]; ep[5] = same_as_v5(0);
    out->pair = head(pin, 3 * d + 6, m.p1w, m.p1b, m.p2w, m.p2b);
  }
};

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
#ifdef _OPENMP
  omp_set_num_threads(threads);
#endif
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
#ifdef _OPENMP
  omp_set_num_threads(threads);
#endif
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
