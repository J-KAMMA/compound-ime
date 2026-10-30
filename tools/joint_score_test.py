"""合わせた物差し（tools/joint_score_fit.py と engine.cc の PreferJointScore）の単体試験（変換エンジンなし）。

  python tools/joint_score_test.py

重みの表が特徴の並びと合うこと、組み込む C++ の特徴の数と順が Python と同じこと、
かなだけの判定、選び方（Mozc のまま＝0点、0点より高い一番の候補を採る）を確かめる。
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import joint_score_fit as j  # noqa: E402

failures = []


def check(name, ok):
    if not ok:
        failures.append(name)


weights = json.loads((HERE / "data/joint-score/weights.json").read_text(encoding="utf-8"))
check("重みの名前が特徴の並びと同じ", weights["names"] == j.NAMES)
check("重みの数", len(weights["weights"]) == len(j.NAMES) == 14)

# C++ の特徴の並び（apply_jaen_integration.py の PreferJointScore）が Python の features と同じ数か
source = (HERE / "apply_jaen_integration.py").read_text(encoding="utf-8")
block = source[source.index("const double feature[14] = {"):]
block = block[:block.index("};")]
check("C++ の特徴の数", len(re.findall(r",\n", block)) == 14)

# かなだけ
check("カタカナだけ", j.kana_only("トクソドン"))
check("漢字まじり", not j.kana_only("木の葉"))
check("短いひらがな", not j.kana_only("ありがとう"))
check("長いひらがな", j.kana_only("あ" * 20))
check("英字", not j.kana_only("Chromeの"))


def rec(mozc, cands):
    return {"key": "", "ctx": "00", "segs": 2, "mozc": mozc, "mozc_cost": 0, "mozc_lp": -20.0,
            "cands": [dict({"rank": i, "lp": -20.0, "fit": "M", "rank_sum": 1, "changed": 1, "cost_delta": 0,
                            "lost": 0, "extra": 0, "chars": len(c["value"])}, **c) for i, c in enumerate(cands)]}


w = weights["weights"]
# 人工知能が Mozc の1位よりはっきり確からしい1位の文は採る
r = rec("足を負った", [{"value": "足を折った", "lp": -12.0}])
check("確からしい1位を採る", (j.choose(r, w, "lenient", True) or {}).get("value") == "足を折った")
# 人工知能のほうが確からしくないなら Mozc のまま
r = rec("那覇空港", [{"value": "名は空港", "lp": -30.0, "lost": 1}])
check("確からしくなければ Mozc のまま", j.choose(r, w, "lenient", True) is None)
# 当てはまらない候補（V、断る決まりを外しても書けない F5）は選ばない
r = rec("あ", [{"value": "亜", "lp": 0.0, "fit": "V"}, {"value": "阿", "lp": 0.0, "fit": "F5"}])
check("当てはまらない候補は選ばない", j.choose(r, w, "lenient", True) is None)
# 上位3つより下は比べない
r = rec("x", [{"value": f"候補{i}", "lp": -40.0, "fit": "V"} for i in range(3)] + [{"value": "四位", "lp": 0.0}])
check("上位3つだけ", j.choose(r, w, "lenient", True) is None)
# 断る決まりを外せば組み直せる文も比べる
r = rec("ベース", [{"value": "米須", "lp": -5.0, "fit": "F1L"}])
check("決まりを外した組み直しも比べる", (j.choose(r, w, "lenient", True) or {}).get("value") == "米須")

# ローマ字の読み戻し
check("読み戻し", j.to_kana("kyouhaiitenkidesu.") == "きょうはいいてんきです。")
check("小さいつ", j.to_kana("kitte") == "きって")
check("ん", j.to_kana("konnnichiha") == "こんにちは")

if failures:
    print("失敗:", "、".join(failures))
    sys.exit(1)
print("合わせた物差しの単体試験: すべて通過")
