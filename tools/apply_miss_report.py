"""「今の変換は違う」をその場で記録する（Ctrl+Shift+F12、docs/miss-report.md）。

  python tools/apply_miss_report.py <mozc/src>

tools/apply_jaen_integration.py の後に、1回だけ動かす（その script が session に足す RecentScope・
recent_commit_、converter::Corrections を使うため）。

  - 変換中・入力中に押す: その文（打ったキー・読み・今の表示・選んでいる文節）を記録する。キーは IME が受け取る。
  - 何も打っていないときに押す: 直前に確定した文（2分以内、同じ入力欄、まだ記録していないもの）を記録する。
    記録するものがなければ、キーはアプリへそのまま渡す（Word の印刷などを邪魔しない）。
  - 書く先はプロファイルのフォルダの misconversions.tsv（1MB を超えたら古い半分を捨てる）。外へは送らない。
  - パスワードの欄・シークレットモード・MYIME_MISS_REPORT=0 では何も覚えず、キーも横取りしない。
  - 学習の履歴を消す（設定の「入力履歴の消去」）と一緒に消える。
本体は native/jaen-detector/miss_report.h（session/miss_report.h として置く）。単体試験は miss_report_test.cc。
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
src = Path(sys.argv[1])


def edit(path, old, new, count=1):
    # 改行の記号（LF か CRLF）は、ファイルによって違う。LF で探し、見つからなければ CRLF で探す
    p = src / path
    text = p.read_bytes().decode("utf-8")
    for newline in ("\n", "\r\n"):
        o, n = old.replace("\n", newline), new.replace("\n", newline)
        if text.count(o) == count:
            p.write_bytes(text.replace(o, n).encode("utf-8"))
            return
    raise SystemExit(f"{path}: expected {count} match(es) for {old[:70]!r}, found {text.count(old)}")


(src / "session/miss_report.h").write_bytes(
    (REPO / "native/jaen-detector/miss_report.h").read_bytes())

edit("session/BUILD.bazel", """    hdrs = [
        "recent_commit.h",
        "session.h",
    ],
""", """    hdrs = [
        "miss_report.h",
        "recent_commit.h",
        "session.h",
    ],
""")
edit("session/BUILD.bazel", """        ":key_event_transformer",
        ":keymap",
        "//base:clock",
        "//base:util",
""", """        ":key_event_transformer",
        ":keymap",
        "//base:clock",
        "//base:system_util",
        "//base:util",
""")

edit("session/session.h", "#include \"session/recent_commit.h\"\n",
     "#include \"session/miss_report.h\"\n#include \"session/recent_commit.h\"\n")
edit("session/session.h", "  jaen::RecentCommit recent_commit_{jaen::RecentLifetimeMs()};\n",
     """  jaen::RecentCommit recent_commit_{jaen::RecentLifetimeMs()};

  // 「今の変換は違う」の記録（Ctrl+Shift+F12、docs/miss-report.md）。直前の確定と、キーの前の組み立ての写し。
  jaen::LastCommit miss_last_;
  std::string miss_raw_;
  std::string miss_reading_;
  bool MissReportAllowed(const mozc::commands::Command& command) const;
  bool IsMissReportKeyEvent(const mozc::commands::Command& command) const;
  std::string MissContextText(const mozc::commands::Command& command) const;
  void MissBefore(const mozc::commands::Command& command);
  void MissAfter(const mozc::commands::Command& command);
  bool HandleMissReportKey(mozc::commands::Command* command);
""")

S = "session/session.cc"
edit(S, '#include "base/util.h"\n', '#include "base/system_util.h"\n#include "base/util.h"\n')
# どの呼び出し（SendKey・TestSendKey・SendCommand）でも、前に組み立ての写しを取り、後に確定を覚える。
edit(S, """void Session::NoteRecentBefore(const commands::Command& command) {
""", """void Session::NoteRecentBefore(const commands::Command& command) {
  MissBefore(command);
""")
edit(S, """void Session::NoteRecentAfter(const commands::Command& command, bool was_direct) {
""", """void Session::NoteRecentAfter(const commands::Command& command, bool was_direct) {
  MissAfter(command);  // recent_commit_ に今の確定を足す前（直前の文として前の確定を使う）
""")
# ウィンドウズは先に TestSendKey で「受け取るか」を聞く。何も打っていないときは、記録するものがあるときだけ受け取る
# （変換中・入力中は、もともと全部のキーを受け取る）。
edit(S, """  // Precomposition
  if (state == ImeContext::PRECOMPOSITION) {
""", """  if (state == ImeContext::PRECOMPOSITION && IsMissReportKeyEvent(*command) &&
      MissReportAllowed(*command) && miss_last_.Ready(jaen::SteadyNowMs())) {
    return DoNothing(command);
  }

  // Precomposition
  if (state == ImeContext::PRECOMPOSITION) {
""")
edit(S, """  HandleIndirectImeOnOff(command);
""", """  HandleIndirectImeOnOff(command);
  if (HandleMissReportKey(command)) {
    return true;
  }
""")
edit(S, "bool Session::RequestAsyncConversion(commands::Command* command) {\n", r"""// 「今の変換は違う」の記録（native/jaen-detector/miss_report.h、docs/miss-report.md）。
static_assert(commands::KeyEvent::F12 == jaen::kMissKeyF12 && commands::KeyEvent::CTRL == 1 &&
              commands::KeyEvent::ALT == 2 && commands::KeyEvent::SHIFT == 4 &&
              commands::KeyEvent::LEFT_CTRL == 32 && commands::KeyEvent::LEFT_ALT == 64 &&
              commands::KeyEvent::LEFT_SHIFT == 128 && commands::KeyEvent::RIGHT_CTRL == 256 &&
              commands::KeyEvent::RIGHT_ALT == 512 && commands::KeyEvent::RIGHT_SHIFT == 1024 &&
              commands::KeyEvent::KEY_UP == jaen::kMissModKeyUp,
              "miss_report.h: KeyEvent numbers changed");

namespace {
std::filesystem::path MissReportPath() {
  const std::string dir = SystemUtil::GetUserProfileDirectory();  // UTF-8
  return std::filesystem::path(std::u8string(dir.begin(), dir.end())) / jaen::kMissReportFileName;
}
}  // namespace

// パスワードの欄・シークレットモード・MYIME_MISS_REPORT=0 では何もしない。
bool Session::MissReportAllowed(const commands::Command& command) const {
  if (!jaen::MissReportEnabled() || context_ == nullptr) return false;
  if (context_->GetConfig().incognito_mode() || context_->GetRequest().is_incognito_mode()) {
    return false;
  }
  return command.input().context().input_field_type() != commands::Context::PASSWORD &&
         context_->client_context().input_field_type() != commands::Context::PASSWORD &&
         context_->composer().GetInputFieldType() != commands::Context::PASSWORD;
}

bool Session::IsMissReportKeyEvent(const commands::Command& command) const {
  if (!command.input().has_key()) return false;
  const commands::KeyEvent& key = command.input().key();
  return key.has_special_key() &&
         jaen::IsMissReportKey(static_cast<int>(key.special_key()), KeyEventUtil::GetModifiers(key));
}

// 直前の文: アプリが教える入力欄の前の文、組み立ての始めに取った前の文、IME が覚えている直前の確定の順。最後の 40 字。
std::string Session::MissContextText(const commands::Command& command) const {
  const std::string& preceding = command.input().context().preceding_text();
  if (!preceding.empty()) return jaen::MissTail(preceding, 40);
  const std::string& captured = context_->client_context().preceding_text();
  if (!captured.empty()) return jaen::MissTail(captured, 40);
  return jaen::MissTail(recent_commit_.Text(jaen::SteadyNowMs()), 40);
}

// 呼び出しの前: 入力欄が変わったら直前の確定を捨て、組み立て中なら打ったキーと読みを写す（確定すると消えるため）。
void Session::MissBefore(const commands::Command& command) {
  miss_raw_.clear();
  miss_reading_.clear();
  if (!MissReportAllowed(command)) {
    miss_last_.Clear();
    return;
  }
  const commands::Input& input = command.input();
  if (input.has_context() && input.context().has_revision()) {
    miss_last_.NoteRevision(input.context().revision());
  }
  if (context_->state() == ImeContext::COMPOSITION || context_->state() == ImeContext::CONVERSION) {
    miss_raw_ = context_->composer().GetRawString();
    miss_reading_ = context_->composer().GetQueryForConversion();
  }
}

// 呼び出しの後: 組み立てから確定した文を、直前の確定として覚える（ファイルには書かない）。
void Session::MissAfter(const commands::Command& command) {
  if (miss_raw_.empty() && miss_reading_.empty()) return;
  const commands::Output& output = command.output();
  if (!output.has_result() || output.result().type() != commands::Result::STRING ||
      output.result().value().empty()) {
    return;
  }
  jaen::MissEntry entry;
  entry.kind = "commit";
  entry.romaji = miss_raw_;
  entry.reading = output.result().key().empty() ? miss_reading_ : output.result().key();
  entry.shown = output.result().value();
  entry.context = MissContextText(command);
  miss_last_.Set(std::move(entry), jaen::SteadyNowMs());
}

// Ctrl+Shift+F12: 変換中・入力中ならその文、何も打っていなければ直前の確定を1行書く。受け取らないときは false。
bool Session::HandleMissReportKey(commands::Command* command) {
  if (!IsMissReportKeyEvent(*command) || !MissReportAllowed(*command)) return false;
  jaen::MissEntry entry;
  const ImeContext::State state = context_->state();
  if (state == ImeContext::PRECOMPOSITION) {
    if (!miss_last_.Ready(jaen::SteadyNowMs())) return false;  // アプリへ渡す
    entry = miss_last_.entry();
    miss_last_.MarkReported();
    DoNothing(command);
  } else if (state == ImeContext::COMPOSITION || state == ImeContext::CONVERSION) {
    DoNothing(command);  // 受け取って、今の表示をそのまま返す
    entry.kind = state == ImeContext::CONVERSION ? "convert" : "compose";
    entry.romaji = context_->composer().GetRawString();
    entry.reading = context_->composer().GetQueryForConversion();
    for (const commands::Preedit::Segment& segment : command->output().preedit().segment()) {
      entry.shown += segment.value();
      if (state == ImeContext::CONVERSION && entry.selected.empty() &&
          segment.annotation() == commands::Preedit::Segment::HIGHLIGHT) {
        entry.selected = segment.value();
      }
    }
    entry.context = MissContextText(*command);
  } else {
    return false;
  }
  if (!jaen::AppendMissLine(MissReportPath(), jaen::FormatMissLine(jaen::MissStamp(), entry))) {
    LOG(WARNING) << "Failed to write " << jaen::kMissReportFileName;
  }
  return true;
}

bool Session::RequestAsyncConversion(commands::Command* command) {
""")

# 学習の履歴を消すと、この記録も消す（打った文が入っているため）。
edit("converter/english_lexicon.h", "jaen::CorrectionLog& Corrections();\n",
     "jaen::CorrectionLog& Corrections();\n\n"
     "// Removes misconversions.tsv (Ctrl+Shift+F12 reports, session/miss_report.h) from the user profile.\n"
     "void ClearMissReport();\n")
edit("converter/english_lexicon.cc", """                                   "correction_log.tsv");
  }();
  return *log;
}
""", """                                   "correction_log.tsv");
  }();
  return *log;
}

void ClearMissReport() {
  const std::string dir = SystemUtil::GetUserProfileDirectory();  // UTF-8
  std::error_code error;
  std::filesystem::remove(
      std::filesystem::path(std::u8string(dir.begin(), dir.end())) / "misconversions.tsv", error);
}
""")
edit("engine/engine.cc", "  converter::Corrections().Clear();", "  converter::Corrections().Clear();\n  converter::ClearMissReport();")
print("miss report applied")
