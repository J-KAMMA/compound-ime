"""ウィンドウズの Microsoft IME の変換（IFELanguage、MSIME.Japan）で試験の文を変換し、コンパウンドIME と比べる。

キーを送らずに変換の中身を直接呼ぶので、画面やキーボードは使わない。ウィンドウズでだけ動く。
  py tools/msime_compare.py tests/conversion/ja400.json --out ms-ja400.tsv [--compound results/ja400.tsv] [--limit 10]
ローマ字は、この台本の中の表（ヘボン式と訓令式の普通の打ち方）でひらがなに直してから渡す。
英字を含む期待の文（英単語をそのまま残すもの）は、Microsoft IME には英字の判定がないので数えるが別に分ける。
"""
import argparse
import ctypes
import json
import re
import subprocess
import sys
from pathlib import Path

VOWELS = {"a": 0, "i": 1, "u": 2, "e": 3, "o": 4}
ROWS = {
    "": "あいうえお", "k": "かきくけこ", "s": "さしすせそ", "t": "たちつてと", "n": "なにぬねの",
    "h": "はひふへほ", "m": "まみむめも", "y": "や\0ゆいぇよ", "r": "らりるれろ", "w": "わうぃうぇを",
    "g": "がぎぐげご", "z": "ざじずぜぞ", "d": "だぢづでど", "b": "ばびぶべぼ", "p": "ぱぴぷぺぽ",
    "x": "ぁぃぅぇぉ", "l": "ぁぃぅぇぉ",
}
YOON = {"ky": "き", "sh": "し", "sy": "し", "ch": "ち", "ty": "ち", "cy": "ち", "ny": "に", "hy": "ひ", "my": "み",
        "ry": "り", "gy": "ぎ", "j": "じ", "jy": "じ", "zy": "じ", "dy": "ぢ", "by": "び", "py": "ぴ"}
SMALL_Y = {"a": "ゃ", "u": "ゅ", "o": "ょ", "e": "ぇ", "i": "ぃ"}
TABLE = {}
for c, kana in ROWS.items():
    for v, i in VOWELS.items():
        if kana[i] != "\0":
            TABLE[c + v] = kana[i]
for c, k in YOON.items():
    for v, s in SMALL_Y.items():
        TABLE[c + v] = k + s
TABLE.update({"shi": "し", "chi": "ち", "tsu": "つ", "fu": "ふ", "ji": "じ", "si": "し", "ti": "ち", "tu": "つ",
              "hu": "ふ", "zi": "じ", "di": "ぢ", "du": "づ", "wo": "を", "fa": "ふぁ", "fi": "ふぃ", "fe": "ふぇ",
              "fo": "ふぉ", "va": "ゔぁ", "vi": "ゔぃ", "vu": "ゔ", "ve": "ゔぇ", "vo": "ゔぉ", "she": "しぇ",
              "che": "ちぇ", "je": "じぇ", "thi": "てぃ", "dhi": "でぃ", "twu": "とぅ", "dwu": "どぅ", "tsa": "つぁ",
              "xtu": "っ", "ltu": "っ", "xtsu": "っ", "xya": "ゃ", "xyu": "ゅ", "xyo": "ょ", "lya": "ゃ", "lyu": "ゅ",
              "lyo": "ょ", "nn": "ん", "n'": "ん", "-": "ー", ",": "、", ".": "。", "wi": "うぃ", "we": "うぇ",
              "ye": "いぇ", "ca": "か", "cu": "く", "co": "こ", "qa": "くぁ", "qi": "くぃ", "qe": "くぇ", "qo": "くぉ"})
MAXLEN = max(len(k) for k in TABLE)


def to_kana(romaji):
    out, i, s = [], 0, romaji.lower()
    while i < len(s):
        c = s[i]
        if c.isdigit():
            out.append(c)
            i += 1
            continue
        if i + 1 < len(s) and c == s[i + 1] and c not in "aiueon" and c.isalpha():
            out.append("っ")  # 子音を重ねた小さい っ
            i += 1
            continue
        for n in range(MAXLEN, 0, -1):
            piece = s[i:i + n]
            if piece in TABLE:
                out.append(TABLE[piece])
                i += n
                break
        else:
            if c == "n":
                out.append("ん")
                i += 1
            else:
                return None  # 読めない
    return "".join(out)


POWERSHELL = r"""
$ErrorActionPreference = 'Stop'
Add-Type @'
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("019F7152-E6DB-11d0-83C3-00C04FDDB82E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IFELanguage {
  int Open(); int Close();
  int GetJMorphResult(uint req, uint mode, int len, [MarshalAs(UnmanagedType.LPWStr)] string s, IntPtr info, out IntPtr res);
  int GetConversionModeCaps(out uint caps);
  int GetPhonetic([MarshalAs(UnmanagedType.BStr)] string s, int start, int len, [MarshalAs(UnmanagedType.BStr)] out string res);
  int GetConversion([MarshalAs(UnmanagedType.BStr)] string s, int start, int len, [MarshalAs(UnmanagedType.BStr)] out string res);
}
public static class Fe {
  static IFELanguage o;
  public static void Open() {
    o = (IFELanguage)Activator.CreateInstance(Type.GetTypeFromProgID("MSIME.Japan"));
    Marshal.ThrowExceptionForHR(o.Open());
  }
  public static string Conv(string s) {
    string r;
    return o.GetConversion(s, 1, -1, out r) == 0 ? r : "";
  }
  public static void Close() { o.Close(); }
}
'@
[Fe]::Open()
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
while ($null -ne ($line = [Console]::In.ReadLine())) {
  [Console]::Out.WriteLine([Fe]::Conv($line))
  [Console]::Out.Flush()
}
[Fe]::Close()
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tests")
    ap.add_argument("--out", required=True)
    ap.add_argument("--compound", help="同じ試験のコンパウンドIME の結果（ローマ字<TAB>…<TAB>結果）")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    items = json.loads(Path(a.tests).read_text(encoding="utf-8"))["items"]
    if a.limit:
        items = items[:a.limit]
    kana = [to_kana(it["romaji"]) for it in items]
    todo = [k for k in kana if k]
    proc = subprocess.run(["powershell", "-NoProfile", "-Command", POWERSHELL], input="\n".join(todo) + "\n",
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        sys.exit(proc.stderr[:2000])
    got = iter(proc.stdout.splitlines())
    ms = {}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for it, k in zip(items, kana):
            r = next(got, "") if k else ""
            ms[it["romaji"]] = r
            f.write(f"{it['romaji']}\t{k or ''}\t{r}\n")

    compound = {}
    if a.compound:
        for line in open(a.compound, encoding="utf-8"):
            p = line.rstrip("\n").split("\t")
            compound[p[0]] = p[-1]

    def ok(it, r):
        return r in [it["intended"]] + it.get("alternatives", [])

    groups = {"日本語だけ": [], "英字入り": []}
    for it in items:
        groups["英字入り" if re.search(r"[A-Za-z]", it["intended"]) else "日本語だけ"].append(it)
    for name, its in groups.items():
        if not its:
            continue
        line = f"{name} {len(its)} 文: Microsoft IME {sum(ok(it, ms[it['romaji']]) for it in its)}"
        if compound:
            line += f"、コンパウンドIME {sum(ok(it, compound.get(it['romaji'], '')) for it in its)}"
        print(line)
    unread = sum(1 for k in kana if not k)
    if unread:
        print(f"ひらがなに直せなかった文: {unread}")


if __name__ == "__main__":
    main()
