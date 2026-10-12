"""節: 変換エンジン（Swift）を Linux でも組み立てられるようにする。

_strdup（ウィンドウズの関数）を Linux では strdup で代わりに用意し、
標準エラーへの書き込みは並行処理の検査に通る書き方にする。
"""
import sys
from pathlib import Path

src = Path(sys.argv[1])  # MyIME の src
engine = src / "swift-engine/Sources/azookey-engine"

(engine / "LinuxCompat.swift").write_text("""// Linux 用の互換関数（ウィンドウズの CRT 関数の代わり）
#if !os(Windows)
#if canImport(Glibc)
import Glibc
#elseif canImport(Darwin)
import Darwin
#endif

@inline(__always)
func _strdup(_ text: UnsafePointer<CChar>) -> UnsafeMutablePointer<CChar>? {
    strdup(text)
}
#endif
""", encoding="utf-8", newline="\n")

p = engine / "TypoCorrectionPass.swift"
t = p.read_text(encoding="utf-8")
old = """#endif
    fputs(line, stderr)
}"""
new = """#endif
    FileHandle.standardError.write(Data(line.utf8))
}"""
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="")
print("engine port ok")
