"""辞書の更新（配布ページから辞書だけを取りに行く仕組み）を、Mozc の作業ツリーに足す。

  python tools/apply_dict_update.py <mozc/src>

tools/apply_jaen_integration.py のあとに、1回だけ実行する（Linux の組み立てでは、続く apply_linux_engine_port.py などの前）。
設計は docs/dict-update.md。足すもの:

1. dict_update/ （新しい Bazel の組）: native/dict_update/ の中身（目録の読み取り、署名と SHA-256 の確かめ、
   取得、入れ替えと前の辞書への戻し、背景の確かめ）。Mozc に依存しない。
2. dictionary/supplement_dictionary.{h,cc}: 取った「追加の辞書」を Mozc の辞書の1つに見せる。
   dictionary_impl.cc が、システム辞書・値辞書と利用者辞書の間に並べる。
3. converter/english_lexicon.{h,cc}: 取った「英語の一覧」を足した英単語の一覧と、小文字で打った語の表示の形。
   入れ替えるたびに新しい世代を作り、使っている処理を妨げないよう新しい3世代を残す。
4. converter/dict_update_glue.{h,cc}: 取った辞書を入れ、読みの費用の記憶を捨てる（読み直し）。
   本体に焼き込む値（品詞の表の SHA-256、行数、公開鍵、取る先）をここに書く。
5. server/mozc_server.cc: 起動時に1回、辞書の更新を始める（週1回の確かめ。止める設定 DictUpdate=0）。
6. session/session_handler_main.cc: 試験用の命令 DICT_UPDATE、DICT_UPDATE_INFO と、起動時の読み込み（MYIME_HERMETIC_TEST=1 のときだけ）。

焼き込む値:
- 品詞の表: <src>/data/dictionary_oss/id.def の SHA-256 と行数。目録の pos_table がこれと違う辞書は受け付けない。
- 公開鍵: tools/dict-update/public-key.txt（16進64文字。"UNSET" なら更新しない）。
- 取る先: tools/dict-update/config.txt の manifest_url、url_prefix。
"""
import hashlib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
src = Path(sys.argv[1])
NATIVE = REPO / "native/dict_update"
CONF = REPO / "tools/dict-update"


def edit(path, old, new):
    p = src / path
    text = p.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected one match for {old[:60]!r}, found {text.count(old)}")
    p.write_text(text.replace(old, new), encoding="utf-8", newline="")


def write(path, text):
    p = src / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def read_conf(name):
    rows = {}
    for line in (CONF / name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            rows[key.strip()] = value.strip()
    return rows


# ---- 焼き込む値 ----
id_def = (src / "data/dictionary_oss/id.def").read_bytes()
pos_sha = hashlib.sha256(id_def).hexdigest()
id_lines = id_def.decode("utf-8").splitlines()
noun_id = None
for line in id_lines:
    number, _, pos = line.partition(" ")
    if pos == "名詞,固有名詞,一般,*,*,*,*":
        noun_id = int(number)
        break
if noun_id is None:
    raise SystemExit("id.def に 名詞,固有名詞,一般 がありません")
key_lines = [l.strip() for l in (CONF / "public-key.txt").read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
public_key = key_lines[0] if key_lines else "UNSET"
if public_key != "UNSET" and not re.fullmatch(r"[0-9a-f]{64}", public_key):
    raise SystemExit("tools/dict-update/public-key.txt は UNSET か、16進（小文字）64文字")
conf = read_conf("config.txt")
for k in ("manifest_url", "url_prefix"):
    if not conf.get(k, "").startswith("https://"):
        raise SystemExit(f"tools/dict-update/config.txt の {k} は https:// で始める")

# ---- 1. dict_update/ ----
LIB = ["crypto.h", "crypto.cc", "data.h", "data.cc", "manifest.h", "manifest.cc", "updater.h", "updater.cc",
       "fetcher.h", "fetcher.cc", "service.h", "service.cc"]
for name in LIB:
    write(f"dict_update/{name}", (NATIVE / name).read_text(encoding="utf-8"))
write("dict_update/BUILD.bazel", '''# 辞書の更新（配布ページから辞書だけを取りに行く仕組み）。Mozc に依存しない。docs/dict-update.md
load("//:build_defs.bzl", "mozc_cc_library")

package(default_visibility = ["//visibility:public"])

# 追加の辞書と英語の一覧の読み込み（行の形を確かめる）
mozc_cc_library(
    name = "data",
    srcs = ["data.cc"],
    hdrs = ["data.h"],
)

mozc_cc_library(
    name = "dict_update",
    srcs = [
        "crypto.cc",
        "fetcher.cc",
        "manifest.cc",
        "service.cc",
        "updater.cc",
    ],
    hdrs = [
        "crypto.h",
        "fetcher.h",
        "manifest.h",
        "service.h",
        "updater.h",
    ],
    deps = [":data"],
)
''')

# ---- 2. 追加の辞書 ----
write("dictionary/supplement_dictionary.h", (NATIVE / "mozc/supplement_dictionary.h").read_text(encoding="utf-8"))
write("dictionary/supplement_dictionary.cc", (NATIVE / "mozc/supplement_dictionary.cc").read_text(encoding="utf-8"))
build = (src / "dictionary/BUILD.bazel").read_text(encoding="utf-8")
assert "supplement_dictionary" not in build
start = build.index('    name = "dictionary_impl",')
deps_at = build.index('        ":pos_matcher",\n', start)
build = build[:deps_at] + '        ":pos_matcher",\n        ":supplement_dictionary",\n' + build[deps_at + len('        ":pos_matcher",\n'):]
build += '''
# 辞書の更新で取った「追加の辞書」。DictionaryImpl がシステム辞書と利用者辞書の間に並べる。
mozc_cc_library(
    name = "supplement_dictionary",
    srcs = ["supplement_dictionary.cc"],
    hdrs = ["supplement_dictionary.h"],
    visibility = [
        "//converter:__pkg__",
        "//engine:__pkg__",
    ],
    deps = [
        ":dictionary_interface",
        ":dictionary_token",
        "//dict_update:data",
        "@com_google_absl//absl/strings",
    ],
)
'''
(src / "dictionary/BUILD.bazel").write_text(build, encoding="utf-8", newline="")
edit("dictionary/dictionary_impl.cc", '#include "dictionary/pos_matcher.h"\n',
     '#include "dictionary/pos_matcher.h"\n#include "dictionary/supplement_dictionary.h"\n')
edit("dictionary/dictionary_impl.cc", "  dics_.push_back(value_dictionary_.get());\n  dics_.push_back(&user_dictionary_);\n",
     "  dics_.push_back(value_dictionary_.get());\n"
     "  // 辞書の更新で取った追加の辞書（dict_update）。利用者辞書の前に置く（DCHECK と GetDictionaries は利用者辞書が最後の前提）。\n"
     "  // 利用者の語ではないので、シークレットモードでも引く。\n"
     "  dics_.push_back(&SupplementDictionary::Instance());\n"
     "  dics_.push_back(&user_dictionary_);\n")

# ---- 3. 英語の一覧 ----
edit("converter/english_lexicon.h", "#include <string_view>\n", "#include <memory>\n#include <string_view>\n")
edit("converter/english_lexicon.h", '#include "converter/jaen_typo.h"\n', '#include "converter/jaen_typo.h"\n#include "dict_update/data.h"\n')
edit("converter/english_lexicon.h", """// Built on first use and kept for the process lifetime.
const jaen::Lexicon& EnglishLexicon();
""", """// Built on first use and kept for the process lifetime. After SetEnglishExtra it is the generation that
// holds the words fetched by the dictionary update (the one a caller got stays valid for the next 2 updates).
const jaen::Lexicon& EnglishLexicon();

// The English lists fetched by the dictionary update (dict_update/, docs/dict-update.md): words added to
// the lexicon and display forms for names typed in lowercase. nullptr removes them. The display forms
// that are compiled in (tools/data/brand-casing.tsv ...) are never changed by it.
void SetEnglishExtra(std::shared_ptr<const ::dict_update::EnglishExtra> extra);
""")
edit("converter/english_lexicon.cc", "#include <algorithm>\n#include <iterator>\n",
     "#include <algorithm>\n#include <atomic>\n#include <deque>\n#include <iterator>\n#include <memory>\n#include <mutex>\n#include <unordered_map>\n")
edit("converter/english_lexicon.cc", """const jaen::Lexicon& EnglishLexicon() {
  static const jaen::Lexicon* const lexicon = [] {""", """namespace {

// The lexicon built from the compiled-in lists (the first generation).
const jaen::Lexicon& BaseLexicon() {
  static const jaen::Lexicon* const lexicon = [] {""")
edit("converter/english_lexicon.cc", """    return words;
  }();
  return *lexicon;
}
""", """    return words;
  }();
  return *lexicon;
}

// A generation of the lexicon with the words of the dictionary update added. Old generations are kept
// (the newest 3) so that a conversion that is still using one is not disturbed.
struct ExtraGeneration {
  std::unique_ptr<const jaen::Lexicon> lexicon;
  std::unordered_map<std::string, std::string> casing, casing2;
};
std::atomic<const ExtraGeneration*> g_extra{nullptr};
std::mutex g_extra_mutex;
std::deque<std::unique_ptr<ExtraGeneration>> g_extra_generations;

std::string_view ExtraCasing(bool second, std::string_view typed) {
  const ExtraGeneration* extra = g_extra.load(std::memory_order_acquire);
  if (extra == nullptr || typed.empty()) return std::string_view();
  const auto& table = second ? extra->casing2 : extra->casing;
  const auto it = table.find(std::string(typed));
  return it == table.end() ? std::string_view() : std::string_view(it->second);
}

}  // namespace

const jaen::Lexicon& EnglishLexicon() {
  const ExtraGeneration* extra = g_extra.load(std::memory_order_acquire);
  return extra != nullptr ? *extra->lexicon : BaseLexicon();
}

void SetEnglishExtra(std::shared_ptr<const ::dict_update::EnglishExtra> extra) {
  std::unique_ptr<ExtraGeneration> generation;
  if (extra != nullptr && extra->size() > 0) {
    generation = std::make_unique<ExtraGeneration>();
    auto lexicon = std::make_unique<jaen::Lexicon>(BaseLexicon());
    for (const std::string& word : extra->curated) lexicon->Add(word, true);
    for (const std::string& word : extra->named) lexicon->AddNamed(word);
    for (const std::string& word : extra->signal) lexicon->AddSignalOnly(word);
    for (const std::string& phrase : extra->phrases) lexicon->AddPhrase(phrase);
    for (const auto& pair : extra->casing) generation->casing.emplace(pair.first, pair.second);
    for (const auto& pair : extra->casing2) generation->casing2.emplace(pair.first, pair.second);
    generation->lexicon = std::move(lexicon);
  }
  std::lock_guard<std::mutex> lock(g_extra_mutex);
  const ExtraGeneration* published = generation.get();
  if (generation != nullptr) g_extra_generations.push_back(std::move(generation));
  g_extra.store(published, std::memory_order_release);
  while (g_extra_generations.size() > 3) g_extra_generations.pop_front();
}
""")
edit("converter/english_lexicon.cc", """  return it != end && std::string_view((*it)[0]) == typed ? std::string_view((*it)[1])
                                                          : std::string_view();
}""", """  if (it != end && std::string_view((*it)[0]) == typed) return std::string_view((*it)[1]);
  return ExtraCasing(/* second= */ false, typed);  // not compiled in: the dictionary update's
}""")
edit("converter/english_lexicon.cc", """  return it != end && std::string_view((*it)[0]) == typed && !typed.empty()
             ? std::string_view((*it)[1])
             : std::string_view();
}""", """  if (it != end && std::string_view((*it)[0]) == typed && !typed.empty()) return std::string_view((*it)[1]);
  return ExtraCasing(/* second= */ true, typed);
}""")
edit("converter/BUILD.bazel", """    deps = ["//base:system_util"],
)

mozc_cc_library(
    name = "jaen_preedit",""", """    deps = [
        "//base:system_util",
        "//dict_update:data",
    ],
)

mozc_cc_library(
    name = "jaen_preedit",""")

# ---- 4. 接続 ----
header = (NATIVE / "mozc/dict_update_glue.h").read_text(encoding="utf-8")
body = (NATIVE / "mozc/dict_update_glue.cc").read_text(encoding="utf-8")
for key, value in {"@@POS_SHA@@": pos_sha, "@@POS_COUNT@@": str(len(id_lines)), "@@NOUN_ID@@": str(noun_id),
                   "@@PUBLIC_KEY@@": public_key, "@@MANIFEST_URL@@": conf["manifest_url"],
                   "@@URL_PREFIX@@": conf["url_prefix"]}.items():
    assert key in body
    body = body.replace(key, value)
write("converter/dict_update_glue.h", header)
write("converter/dict_update_glue.cc", body)
build = (src / "converter/BUILD.bazel").read_text(encoding="utf-8")
build += '''
# 辞書の更新と本体の接続（docs/dict-update.md）
mozc_cc_library(
    name = "dict_update_glue",
    srcs = ["dict_update_glue.cc"],
    hdrs = ["dict_update_glue.h"],
    visibility = [
        "//server:__pkg__",
        "//session:__pkg__",
    ],
    deps = [
        ":converter",
        ":jaen_detector",
        "//dict_update",
        "//dictionary:supplement_dictionary",
    ],
)
'''
(src / "converter/BUILD.bazel").write_text(build, encoding="utf-8", newline="")

edit("server/mozc_server.cc", '#include "base/vlog.h"\n', '#include "base/vlog.h"\n#include "converter/dict_update_glue.h"\n')
edit("server/mozc_server.cc", """      LOG(ERROR) << "SessionServer initialization failed";
      return -1;
    }
""", """      LOG(ERROR) << "SessionServer initialization failed";
      return -1;
    }
    // 辞書の更新（配布ページの辞書を、起動時と週1回ほど確かめる。止める設定は DictUpdate=0。docs/dict-update.md）
    mozc::converter::StartDictUpdateService();
""")
edit("server/BUILD.bazel", '        "//converter:engine_config",\n        "//session:session_server",\n',
     '        "//converter:dict_update_glue",\n        "//converter:engine_config",\n        "//session:session_server",\n')

edit("session/session_handler_main.cc", '#include "base/system_util.h"\n', '#include "base/system_util.h"\n#include "converter/dict_update_glue.h"\n')
edit("session/session_handler_main.cc", """  const absl::Status status = handler.Eval(args);
  if (!status.ok()) {""", """  // 辞書の更新の試験（組 s。docs/dict-update.md）
  if (command == "DICT_UPDATE" || command == "DICT_UPDATE_INFO") {
    std::cout << converter::DictUpdateTestCommand(command) << std::endl;
    return true;
  }

  const absl::Status status = handler.Eval(args);
  if (!status.ok()) {""")
edit("session/session_handler_main.cc", "  mozc::session::SessionHandlerInterpreter handler(*std::move(engine));\n",
     "  // 試験のときだけ（MYIME_HERMETIC_TEST=1）、置き場所の辞書を読む\n"
     "  mozc::converter::LoadDictUpdateForTest();\n"
     "  mozc::session::SessionHandlerInterpreter handler(*std::move(engine));\n")
edit("session/BUILD.bazel", """    name = "session_handler_main",
    testonly = 1,
    srcs = ["session_handler_main.cc"],
    tags = ["noandroid"],  # TODO(b/73698251): disabled due to errors
    deps = [
""", """    name = "session_handler_main",
    testonly = 1,
    srcs = ["session_handler_main.cc"],
    tags = ["noandroid"],  # TODO(b/73698251): disabled due to errors
    deps = [
        "//converter:dict_update_glue",
""")
print("dict update applied (pos_table", pos_sha[:12] + ", pos_count", len(id_lines), ", noun_id", noun_id, ", public key",
      "UNSET" if public_key == "UNSET" else public_key[:12] + ")")
