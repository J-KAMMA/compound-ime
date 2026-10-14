"""変換エンジン（Swift）を Linux と Mac でも組み立てられるようにする。

  python tools/apply_linux_engine_port.py <MyIME の src>

_strdup（ウィンドウズの関数）を strdup で代わりに用意し、標準エラーへの
書き込みは並行処理の検査に通る書き方にする。Mac では変換部品と同じく
macOS 13 以降を対象にする。
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
pkg = src / "swift-engine/Package.swift"
t = pkg.read_text(encoding="utf-8")
old = """    name: "azookey-engine",
    products: ["""
assert t.count(old) == 1
pkg.write_text(t.replace(old, """    name: "azookey-engine",
    platforms: [.macOS(.v13)],
    products: ["""), encoding="utf-8", newline="")

# 人工知能（zenz 第3版）へのプロフィールと文体: MYIME_ZENZAI_PROFILE・MYIME_ZENZAI_STYLE があれば
# その文（25文字まで）を渡す。
# （実験用。効くと分かれば既定の文を決める）
p = engine / "AzookeyEngine.swift"
t = p.read_text(encoding="utf-8")
old = """            versionDependentMode: .v3(.init(
                leftSideContext: leftContext,
                rightSideContext: rightContext)),"""
new = """            versionDependentMode: .v3(.init(
                profile: ProcessInfo.processInfo.environment["MYIME_ZENZAI_PROFILE"].flatMap { $0.isEmpty ? nil : $0 },
                style: ProcessInfo.processInfo.environment["MYIME_ZENZAI_STYLE"].flatMap { $0.isEmpty ? nil : $0 },
                leftSideContext: leftContext,
                rightSideContext: rightContext)),"""
assert t.count(old) == 1
p.write_text(t.replace(old, new), encoding="utf-8", newline="")
print("engine port ok")
