// 判定の門（「この変換で人工知能の生成が要るか」を当てる小さな模型）を IME から呼ぶための入り口。
// 推論の核は tools/jev-gate/jevgate_core.h、入力の作り方は tools/jev-gate/jevgate.py の featurize と collate（with_v5=False）と同じ。
// tools/apply_jev_gate.py が mozc の engine/ に写して使う。IME の外（Linux の g++）でも組み立てて確かめられる。
#ifndef JEV_GATE_H_
#define JEV_GATE_H_

#include <string>
#include <vector>

namespace jev_gate {

// 生成なしの候補 1 つ。src は出どころ（1 = 人工知能なしの出力、2 = 辞書の文全体、3 = Mozc の組）。
struct Cand {
  std::string text;
  int src = 3;
};

struct Result {
  float need = 0.f;       // 全部の候補から決めた「生成が要る」確率
  float need_k = 0.f;     // 入力の上位 k 個だけで決めた「生成が要る」確率（IME が使う）
  float need_top1 = 0.f;
  float harm_k = 0.f;
  std::vector<float> score;  // 候補ごとの点（zenz の点の蒸留。大きいほど良い）
  int best = 0;              // 点が最大の候補の番号
  double ms = 0.0;           // 推論にかかった時間
};

// 模型を読む（重みの表と、その隣の <表>.vocab.json）。thread は計算のスレッド数（0 なら自動、最大 4）。
// 2 回目以降の呼び出しは何もしない（最初の結果を返す）。
bool Load(const std::string& model_path, int threads);
bool Loaded();
// 模型の候補の数 k（これより多い候補は使わない）。読めていなければ 0。
int CandidateLimit();
// prev は前の文（最後の行の終わり 24 字を使う）、reading は読み（ひらがな、先頭 64 字）。
// cands は先頭の CandidateLimit() 個を使う。スレッドごとの排他は中で行う。
bool Predict(const std::string& prev, const std::string& reading, const std::vector<Cand>& cands, Result* out);

// 試験用: 入力の並び（tok typ pos rank src seg）を返す。jevgate.py dumpcase と同じ並びになるかを確かめる。
bool DebugInput(const std::string& prev, const std::string& reading, const std::vector<Cand>& cands,
                std::vector<std::vector<int>>* arrays);

}  // namespace jev_gate

#endif  // JEV_GATE_H_
