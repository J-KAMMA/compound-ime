// ---- 判定の門の設定（tools/apply_jev_gate.py）。既定は無効（今の動きを変えない）。
//   MYIME_JEV_GATE=<しきい値>          門が出す「生成が要る」確率がこの値以上なら今まで通り生成する。0 や空なら無効（既定）
//   MYIME_JEV_GATE_MODEL=<jevgate.bin>  重みの表（隣に <表>.vocab.json）。読めなければ無効
//   MYIME_JEV_GATE_SELECT=zenz|student  生成を省くときの選び方。zenz（既定）は上位の候補を zenz で採点、student は模型の点
//   MYIME_JEV_GATE_SCORE_N=<数>         採点する候補の数（既定は模型の k）
//   MYIME_JEV_GATE_THREADS=<数>         模型の計算のスレッド数（既定は 4。計算機の数が少なければそれ）
//   MYIME_JEV_GATE_LOG=<ファイル>       門の判断を1行ずつ書き足す（試験用）
struct JevGateSettings {
  bool enabled = false;
  double threshold = 0.2;
  bool student = false;
  int score_n = 0;
  std::string log;
};

static const JevGateSettings& JevGateConfig() {
  static const JevGateSettings settings = [] {
    JevGateSettings s;
    // 記録は門が無効でも書く（生成した変換の数を、門ありと同じ形で数えるため）
    if (const char* log = std::getenv("MYIME_JEV_GATE_LOG")) s.log = log;
    const char* threshold = std::getenv("MYIME_JEV_GATE");
    if (threshold == nullptr || *threshold == '\0') return s;
    char* end = nullptr;
    const double value = std::strtod(threshold, &end);
    if (end == threshold || !(value > 0.0)) return s;
    const char* model = std::getenv("MYIME_JEV_GATE_MODEL");
    int threads = 4;
    if (const char* t = std::getenv("MYIME_JEV_GATE_THREADS")) threads = std::atoi(t);
    if (model == nullptr || !jev_gate::Load(model, threads)) {
      LOG(WARNING) << "MYIME_JEV_GATE is set but the gate model could not be loaded; the gate stays off";
      return s;
    }
    s.enabled = true;
    s.threshold = value;
    if (const char* select = std::getenv("MYIME_JEV_GATE_SELECT")) s.student = std::string_view(select) == "student";
    if (const char* n = std::getenv("MYIME_JEV_GATE_SCORE_N")) s.score_n = std::atoi(n);
    return s;
  }();
  return settings;
}

static bool JevGateEnabled() { return JevGateConfig().enabled; }

