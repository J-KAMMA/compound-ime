#include "dict_update/crypto.h"

#include <cstddef>
#include <cstring>
#include <vector>

namespace dict_update {
namespace {

// ---- SHA-256 / SHA-512 ----
// 定数は素数の平方根・立方根の小数部（FIPS 180-4）。
static const uint64_t kSha512K[80] = {
    0x428a2f98d728ae22ULL,
    0x7137449123ef65cdULL,
    0xb5c0fbcfec4d3b2fULL,
    0xe9b5dba58189dbbcULL,
    0x3956c25bf348b538ULL,
    0x59f111f1b605d019ULL,
    0x923f82a4af194f9bULL,
    0xab1c5ed5da6d8118ULL,
    0xd807aa98a3030242ULL,
    0x12835b0145706fbeULL,
    0x243185be4ee4b28cULL,
    0x550c7dc3d5ffb4e2ULL,
    0x72be5d74f27b896fULL,
    0x80deb1fe3b1696b1ULL,
    0x9bdc06a725c71235ULL,
    0xc19bf174cf692694ULL,
    0xe49b69c19ef14ad2ULL,
    0xefbe4786384f25e3ULL,
    0x0fc19dc68b8cd5b5ULL,
    0x240ca1cc77ac9c65ULL,
    0x2de92c6f592b0275ULL,
    0x4a7484aa6ea6e483ULL,
    0x5cb0a9dcbd41fbd4ULL,
    0x76f988da831153b5ULL,
    0x983e5152ee66dfabULL,
    0xa831c66d2db43210ULL,
    0xb00327c898fb213fULL,
    0xbf597fc7beef0ee4ULL,
    0xc6e00bf33da88fc2ULL,
    0xd5a79147930aa725ULL,
    0x06ca6351e003826fULL,
    0x142929670a0e6e70ULL,
    0x27b70a8546d22ffcULL,
    0x2e1b21385c26c926ULL,
    0x4d2c6dfc5ac42aedULL,
    0x53380d139d95b3dfULL,
    0x650a73548baf63deULL,
    0x766a0abb3c77b2a8ULL,
    0x81c2c92e47edaee6ULL,
    0x92722c851482353bULL,
    0xa2bfe8a14cf10364ULL,
    0xa81a664bbc423001ULL,
    0xc24b8b70d0f89791ULL,
    0xc76c51a30654be30ULL,
    0xd192e819d6ef5218ULL,
    0xd69906245565a910ULL,
    0xf40e35855771202aULL,
    0x106aa07032bbd1b8ULL,
    0x19a4c116b8d2d0c8ULL,
    0x1e376c085141ab53ULL,
    0x2748774cdf8eeb99ULL,
    0x34b0bcb5e19b48a8ULL,
    0x391c0cb3c5c95a63ULL,
    0x4ed8aa4ae3418acbULL,
    0x5b9cca4f7763e373ULL,
    0x682e6ff3d6b2b8a3ULL,
    0x748f82ee5defb2fcULL,
    0x78a5636f43172f60ULL,
    0x84c87814a1f0ab72ULL,
    0x8cc702081a6439ecULL,
    0x90befffa23631e28ULL,
    0xa4506cebde82bde9ULL,
    0xbef9a3f7b2c67915ULL,
    0xc67178f2e372532bULL,
    0xca273eceea26619cULL,
    0xd186b8c721c0c207ULL,
    0xeada7dd6cde0eb1eULL,
    0xf57d4f7fee6ed178ULL,
    0x06f067aa72176fbaULL,
    0x0a637dc5a2c898a6ULL,
    0x113f9804bef90daeULL,
    0x1b710b35131c471bULL,
    0x28db77f523047d84ULL,
    0x32caab7b40c72493ULL,
    0x3c9ebe0a15c9bebcULL,
    0x431d67c49c100d4cULL,
    0x4cc5d4becb3e42b6ULL,
    0x597f299cfc657e2aULL,
    0x5fcb6fab3ad6faecULL,
    0x6c44198c4a475817ULL};
static const uint64_t kSha512H0[8] = {
    0x6a09e667f3bcc908ULL,
    0xbb67ae8584caa73bULL,
    0x3c6ef372fe94f82bULL,
    0xa54ff53a5f1d36f1ULL,
    0x510e527fade682d1ULL,
    0x9b05688c2b3e6c1fULL,
    0x1f83d9abfb41bd6bULL,
    0x5be0cd19137e2179ULL};
static const uint32_t kSha256K[64] = {
    0x428a2f98U,
    0x71374491U,
    0xb5c0fbcfU,
    0xe9b5dba5U,
    0x3956c25bU,
    0x59f111f1U,
    0x923f82a4U,
    0xab1c5ed5U,
    0xd807aa98U,
    0x12835b01U,
    0x243185beU,
    0x550c7dc3U,
    0x72be5d74U,
    0x80deb1feU,
    0x9bdc06a7U,
    0xc19bf174U,
    0xe49b69c1U,
    0xefbe4786U,
    0x0fc19dc6U,
    0x240ca1ccU,
    0x2de92c6fU,
    0x4a7484aaU,
    0x5cb0a9dcU,
    0x76f988daU,
    0x983e5152U,
    0xa831c66dU,
    0xb00327c8U,
    0xbf597fc7U,
    0xc6e00bf3U,
    0xd5a79147U,
    0x06ca6351U,
    0x14292967U,
    0x27b70a85U,
    0x2e1b2138U,
    0x4d2c6dfcU,
    0x53380d13U,
    0x650a7354U,
    0x766a0abbU,
    0x81c2c92eU,
    0x92722c85U,
    0xa2bfe8a1U,
    0xa81a664bU,
    0xc24b8b70U,
    0xc76c51a3U,
    0xd192e819U,
    0xd6990624U,
    0xf40e3585U,
    0x106aa070U,
    0x19a4c116U,
    0x1e376c08U,
    0x2748774cU,
    0x34b0bcb5U,
    0x391c0cb3U,
    0x4ed8aa4aU,
    0x5b9cca4fU,
    0x682e6ff3U,
    0x748f82eeU,
    0x78a5636fU,
    0x84c87814U,
    0x8cc70208U,
    0x90befffaU,
    0xa4506cebU,
    0xbef9a3f7U,
    0xc67178f2U};
static const uint32_t kSha256H0[8] = {
    0x6a09e667U,
    0xbb67ae85U,
    0x3c6ef372U,
    0xa54ff53aU,
    0x510e527fU,
    0x9b05688cU,
    0x1f83d9abU,
    0x5be0cd19U};

inline uint32_t Rotr32(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }
inline uint64_t Rotr64(uint64_t x, int n) { return (x >> n) | (x << (64 - n)); }

std::string Sha256Raw(std::string_view data) {
  uint32_t h[8];
  std::memcpy(h, kSha256H0, sizeof(h));
  std::string msg(data);
  const uint64_t bit_len = static_cast<uint64_t>(data.size()) * 8;
  msg.push_back(static_cast<char>(0x80));
  while (msg.size() % 64 != 56) msg.push_back('\0');
  for (int i = 7; i >= 0; --i) msg.push_back(static_cast<char>((bit_len >> (8 * i)) & 0xff));
  for (size_t off = 0; off < msg.size(); off += 64) {
    uint32_t w[64];
    for (int i = 0; i < 16; ++i) {
      const unsigned char* p = reinterpret_cast<const unsigned char*>(msg.data()) + off + 4 * i;
      w[i] = (uint32_t{p[0]} << 24) | (uint32_t{p[1]} << 16) | (uint32_t{p[2]} << 8) | uint32_t{p[3]};
    }
    for (int i = 16; i < 64; ++i) {
      const uint32_t s0 = Rotr32(w[i - 15], 7) ^ Rotr32(w[i - 15], 18) ^ (w[i - 15] >> 3);
      const uint32_t s1 = Rotr32(w[i - 2], 17) ^ Rotr32(w[i - 2], 19) ^ (w[i - 2] >> 10);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 64; ++i) {
      const uint32_t s1 = Rotr32(e, 6) ^ Rotr32(e, 11) ^ Rotr32(e, 25);
      const uint32_t ch = (e & f) ^ (~e & g);
      const uint32_t t1 = hh + s1 + ch + kSha256K[i] + w[i];
      const uint32_t s0 = Rotr32(a, 2) ^ Rotr32(a, 13) ^ Rotr32(a, 22);
      const uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
      const uint32_t t2 = s0 + maj;
      hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
  }
  std::string out;
  for (int i = 0; i < 8; ++i)
    for (int j = 3; j >= 0; --j) out.push_back(static_cast<char>((h[i] >> (8 * j)) & 0xff));
  return out;
}

std::string Sha512Raw(std::string_view data) {
  uint64_t h[8];
  std::memcpy(h, kSha512H0, sizeof(h));
  std::string msg(data);
  const uint64_t bit_len = static_cast<uint64_t>(data.size()) * 8;
  msg.push_back(static_cast<char>(0x80));
  while (msg.size() % 128 != 112) msg.push_back('\0');
  for (int i = 0; i < 8; ++i) msg.push_back('\0');  // 長さの上位64ビット
  for (int i = 7; i >= 0; --i) msg.push_back(static_cast<char>((bit_len >> (8 * i)) & 0xff));
  for (size_t off = 0; off < msg.size(); off += 128) {
    uint64_t w[80];
    for (int i = 0; i < 16; ++i) {
      const unsigned char* p = reinterpret_cast<const unsigned char*>(msg.data()) + off + 8 * i;
      uint64_t v = 0;
      for (int j = 0; j < 8; ++j) v = (v << 8) | p[j];
      w[i] = v;
    }
    for (int i = 16; i < 80; ++i) {
      const uint64_t s0 = Rotr64(w[i - 15], 1) ^ Rotr64(w[i - 15], 8) ^ (w[i - 15] >> 7);
      const uint64_t s1 = Rotr64(w[i - 2], 19) ^ Rotr64(w[i - 2], 61) ^ (w[i - 2] >> 6);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint64_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 80; ++i) {
      const uint64_t s1 = Rotr64(e, 14) ^ Rotr64(e, 18) ^ Rotr64(e, 41);
      const uint64_t ch = (e & f) ^ (~e & g);
      const uint64_t t1 = hh + s1 + ch + kSha512K[i] + w[i];
      const uint64_t s0 = Rotr64(a, 28) ^ Rotr64(a, 34) ^ Rotr64(a, 39);
      const uint64_t maj = (a & b) ^ (a & c) ^ (b & c);
      const uint64_t t2 = s0 + maj;
      hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
  }
  std::string out;
  for (int i = 0; i < 8; ++i)
    for (int j = 7; j >= 0; --j) out.push_back(static_cast<char>((h[i] >> (8 * j)) & 0xff));
  return out;
}

// ---- Ed25519（確かめだけ） ----
// 体 GF(2^255-19) の数は、16進の16桁（1桁16ビット）の int64 の並びで持つ（TweetNaCl と同じ）。
using i64 = int64_t;
using u8 = uint8_t;
using gf = i64[16];

static const gf kD = {0x78a3, 0x1359, 0x4dca, 0x75eb, 0xd8ab, 0x4141, 0x0a4d, 0x0070, 0xe898, 0x7779, 0x4079, 0x8cc7, 0xfe73, 0x2b6f, 0x6cee, 0x5203};
static const gf kD2 = {0xf159, 0x26b2, 0x9b94, 0xebd6, 0xb156, 0x8283, 0x149a, 0x00e0, 0xd130, 0xeef3, 0x80f2, 0x198e, 0xfce7, 0x56df, 0xd9dc, 0x2406};
static const gf kX = {0xd51a, 0x8f25, 0x2d60, 0xc956, 0xa7b2, 0x9525, 0xc760, 0x692c, 0xdc5c, 0xfdd6, 0xe231, 0xc0a4, 0x53fe, 0xcd6e, 0x36d3, 0x2169};
static const gf kY = {0x6658, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666, 0x6666};
static const gf kI = {0xa0b0, 0x4a0e, 0x1b27, 0xc4ee, 0xe478, 0xad2f, 0x1806, 0x2f43, 0xd7a7, 0x3dfb, 0x0099, 0x2b4d, 0xdf0b, 0x4fc1, 0x2480, 0x2b83};
static const gf kGf0 = {0};
static const gf kGf1 = {1};

void Set25519(gf r, const gf a) { for (int i = 0; i < 16; ++i) r[i] = a[i]; }

void Car25519(gf o) {
  for (int i = 0; i < 16; ++i) {
    o[i] += (i64{1} << 16);
    const i64 c = o[i] >> 16;
    o[(i + 1) * (i < 15)] += c - 1 + 37 * (c - 1) * (i == 15);
    o[i] -= c << 16;
  }
}

void Sel25519(gf p, gf q, int b) {
  const i64 c = ~(b - 1);
  for (int i = 0; i < 16; ++i) {
    const i64 t = c & (p[i] ^ q[i]);
    p[i] ^= t;
    q[i] ^= t;
  }
}

void Pack25519(u8* o, const gf n) {
  gf m, t;
  for (int i = 0; i < 16; ++i) t[i] = n[i];
  Car25519(t); Car25519(t); Car25519(t);
  for (int j = 0; j < 2; ++j) {
    m[0] = t[0] - 0xffed;
    for (int i = 1; i < 15; ++i) {
      m[i] = t[i] - 0xffff - ((m[i - 1] >> 16) & 1);
      m[i - 1] &= 0xffff;
    }
    m[15] = t[15] - 0x7fff - ((m[14] >> 16) & 1);
    const int b = static_cast<int>((m[15] >> 16) & 1);
    m[14] &= 0xffff;
    Sel25519(t, m, 1 - b);
  }
  for (int i = 0; i < 16; ++i) {
    o[2 * i] = static_cast<u8>(t[i] & 0xff);
    o[2 * i + 1] = static_cast<u8>(t[i] >> 8);
  }
}

int Neq25519(const gf a, const gf b) {
  u8 c[32], d[32];
  Pack25519(c, a);
  Pack25519(d, b);
  int diff = 0;
  for (int i = 0; i < 32; ++i) diff |= c[i] ^ d[i];
  return diff != 0;
}

u8 Par25519(const gf a) {
  u8 d[32];
  Pack25519(d, a);
  return d[0] & 1;
}

void Unpack25519(gf o, const u8* n) {
  for (int i = 0; i < 16; ++i) o[i] = n[2 * i] + (i64{n[2 * i + 1]} << 8);
  o[15] &= 0x7fff;
}

void A(gf o, const gf a, const gf b) { for (int i = 0; i < 16; ++i) o[i] = a[i] + b[i]; }
void Z(gf o, const gf a, const gf b) { for (int i = 0; i < 16; ++i) o[i] = a[i] - b[i]; }

void M(gf o, const gf a, const gf b) {
  i64 t[31];
  for (int i = 0; i < 31; ++i) t[i] = 0;
  for (int i = 0; i < 16; ++i)
    for (int j = 0; j < 16; ++j) t[i + j] += a[i] * b[j];
  for (int i = 0; i < 15; ++i) t[i] += 38 * t[i + 16];
  for (int i = 0; i < 16; ++i) o[i] = t[i];
  Car25519(o);
  Car25519(o);
}

void S(gf o, const gf a) { M(o, a, a); }

void Inv25519(gf o, const gf i) {
  gf c;
  for (int a = 0; a < 16; ++a) c[a] = i[a];
  for (int a = 253; a >= 0; --a) {
    S(c, c);
    if (a != 2 && a != 4) M(c, c, i);
  }
  for (int a = 0; a < 16; ++a) o[a] = c[a];
}

void Pow2523(gf o, const gf i) {
  gf c;
  for (int a = 0; a < 16; ++a) c[a] = i[a];
  for (int a = 250; a >= 0; --a) {
    S(c, c);
    if (a != 1) M(c, c, i);
  }
  for (int a = 0; a < 16; ++a) o[a] = c[a];
}

void Add(gf p[4], gf q[4]) {
  gf a, b, c, d, t, e, f, g, h;
  Z(a, p[1], p[0]);
  Z(t, q[1], q[0]);
  M(a, a, t);
  A(b, p[0], p[1]);
  A(t, q[0], q[1]);
  M(b, b, t);
  M(c, p[3], q[3]);
  M(c, c, kD2);
  M(d, p[2], q[2]);
  A(d, d, d);
  Z(e, b, a);
  Z(f, d, c);
  A(g, d, c);
  A(h, b, a);
  M(p[0], e, f);
  M(p[1], h, g);
  M(p[2], g, f);
  M(p[3], e, h);
}

void CSwap(gf p[4], gf q[4], u8 b) {
  for (int i = 0; i < 4; ++i) Sel25519(p[i], q[i], b);
}

void Pack(u8* r, gf p[4]) {
  gf tx, ty, zi;
  Inv25519(zi, p[2]);
  M(tx, p[0], zi);
  M(ty, p[1], zi);
  Pack25519(r, ty);
  r[31] ^= Par25519(tx) << 7;
}

void ScalarMult(gf p[4], gf q[4], const u8* s) {
  Set25519(p[0], kGf0);
  Set25519(p[1], kGf1);
  Set25519(p[2], kGf1);
  Set25519(p[3], kGf0);
  for (int i = 255; i >= 0; --i) {
    const u8 b = (s[i / 8] >> (i & 7)) & 1;
    CSwap(p, q, b);
    Add(q, p);
    Add(p, p);
    CSwap(p, q, b);
  }
}

void ScalarBase(gf p[4], const u8* s) {
  gf q[4];
  Set25519(q[0], kX);
  Set25519(q[1], kY);
  Set25519(q[2], kGf1);
  M(q[3], kX, kY);
  ScalarMult(p, q, s);
}

const i64 kL[32] = {0xed, 0xd3, 0xf5, 0x5c, 0x1a, 0x63, 0x12, 0x58, 0xd6, 0x9c, 0xf7, 0xa2, 0xde, 0xf9, 0xde, 0x14,
                    0,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0x10};

void ModL(u8* r, i64 x[64]) {
  i64 carry;
  for (int i = 63; i >= 32; --i) {
    carry = 0;
    int j;
    for (j = i - 32; j < i - 12; ++j) {
      x[j] += carry - 16 * x[i] * kL[j - (i - 32)];
      carry = (x[j] + 128) >> 8;
      x[j] -= carry << 8;
    }
    x[j] += carry;
    x[i] = 0;
  }
  carry = 0;
  for (int j = 0; j < 32; ++j) {
    x[j] += carry - (x[31] >> 4) * kL[j];
    carry = x[j] >> 8;
    x[j] &= 255;
  }
  for (int j = 0; j < 32; ++j) x[j] -= carry * kL[j];
  for (int i = 0; i < 32; ++i) {
    x[i + 1] += x[i] >> 8;
    r[i] = static_cast<u8>(x[i] & 255);
  }
}

void Reduce(u8* r) {  // 64バイトの数を位数 L で割った余り（先頭32バイトに）
  i64 x[64];
  for (int i = 0; i < 64; ++i) x[i] = r[i];
  for (int i = 0; i < 64; ++i) r[i] = 0;
  ModL(r, x);
}

int UnpackNeg(gf r[4], const u8* p) {
  gf t, chk, num, den, den2, den4, den6;
  Set25519(r[2], kGf1);
  Unpack25519(r[1], p);
  S(num, r[1]);
  M(den, num, kD);
  Z(num, num, r[2]);
  A(den, r[2], den);
  S(den2, den);
  S(den4, den2);
  M(den6, den4, den2);
  M(t, den6, num);
  M(t, t, den);
  Pow2523(t, t);
  M(t, t, num);
  M(t, t, den);
  M(t, t, den);
  M(r[0], t, den);
  S(chk, r[0]);
  M(chk, chk, den);
  if (Neq25519(chk, num)) M(r[0], r[0], kI);
  S(chk, r[0]);
  M(chk, chk, den);
  if (Neq25519(chk, num)) return -1;
  if (Par25519(r[0]) == (p[31] >> 7)) Z(r[0], kGf0, r[0]);
  M(r[3], r[0], r[1]);
  return 0;
}

bool ScalarBelowL(const u8* s) {  // 小さい桁（先頭）から数えて、後ろの桁から比べる
  for (int i = 31; i >= 0; --i) {
    if (s[i] < kL[i]) return true;
    if (s[i] > kL[i]) return false;
  }
  return false;  // 等しい
}

}  // namespace

std::string Sha256Hex(std::string_view data) {
  static const char* kDigits = "0123456789abcdef";
  const std::string raw = Sha256Raw(data);
  std::string hex;
  for (unsigned char c : raw) {
    hex.push_back(kDigits[c >> 4]);
    hex.push_back(kDigits[c & 15]);
  }
  return hex;
}

bool HexDecode(std::string_view hex, std::string* out) {
  if (hex.size() % 2 != 0) return false;
  out->clear();
  auto nibble = [](char c) -> int {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
  };
  for (size_t i = 0; i < hex.size(); i += 2) {
    const int hi = nibble(hex[i]), lo = nibble(hex[i + 1]);
    if (hi < 0 || lo < 0) return false;
    out->push_back(static_cast<char>(hi * 16 + lo));
  }
  return true;
}

bool Ed25519Verify(std::string_view signature, std::string_view message, std::string_view public_key) {
  if (signature.size() != 64 || public_key.size() != 32) return false;
  const u8* sig = reinterpret_cast<const u8*>(signature.data());
  const u8* pk = reinterpret_cast<const u8*>(public_key.data());
  if (!ScalarBelowL(sig + 32)) return false;
  gf q[4], p[4];
  if (UnpackNeg(q, pk) != 0) return false;
  // h = SHA-512(R || A || M) mod L
  std::string buf;
  buf.append(signature.substr(0, 32));
  buf.append(public_key);
  buf.append(message);
  const std::string digest = Sha512Raw(buf);
  u8 h[64];
  std::memcpy(h, digest.data(), 64);
  Reduce(h);
  ScalarMult(p, q, h);          // p = h * (-A)
  gf r[4];
  ScalarBase(r, sig + 32);      // r = S * B
  Add(p, r);
  u8 t[32];
  Pack(t, p);
  int diff = 0;
  for (int i = 0; i < 32; ++i) diff |= t[i] ^ sig[i];
  return diff == 0;
}

}  // namespace dict_update
