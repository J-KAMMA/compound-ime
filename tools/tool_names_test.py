"""開発の道具・サービスの名前の試験を作る（tests/conversion/domain-tools.tsv）。

  python tools/tool_names_test.py > tests/conversion/domain-tools.tsv

名前を小文字のローマ字のまま打ち（opencode、claudecode、geminicli ...）、名前だけの入力と、
文頭・文中・文末・後ろに助詞（を、で、は、が、について）が付く文に入れる。期待するのは
公式の書き方（OpenCode、Claude Code、VS Code ...）。打つ形と期待する形は、日本語のローマ字として
読める語（codex の「こでx」、cursor の「くrそr」）と取り違えやすい形を含む。
列: ローマ字<TAB>期待する文<TAB>出典名（tools）
"""
NAMES = [
    ("opencode", "OpenCode"), ("claudecode", "Claude Code"), ("codex", "Codex"),
    ("cursor", "Cursor"), ("ollama", "Ollama"), ("llamacpp", "llama.cpp"),
    ("huggingface", "Hugging Face"), ("langchain", "LangChain"), ("openai", "OpenAI"),
    ("anthropic", "Anthropic"), ("geminicli", "Gemini CLI"), ("copilot", "Copilot"),
    ("vscode", "VS Code"), ("neovim", "Neovim"), ("tmux", "tmux"), ("wsl", "WSL"),
    ("powershell", "PowerShell"), ("windsurf", "Windsurf"), ("aider", "Aider"),
    ("lmstudio", "LM Studio"), ("qoder", "Qoder"), ("qiita", "Qiita"), ("qwen", "Qwen"),
    ("quora", "Quora"), ("qt", "Qt"), ("qemu", "QEMU"), ("qualcomm", "Qualcomm"),
]
# q + a/i/e/o は日本語のローマ字ではまれ（くぁ、くぉ）。q で始まる名前を、文頭・文中・
# 助詞の前後と、QR コード・QA の担当のような言い方で確かめる。
EXTRA = [
    ("qoderwotsukau.", "Qoderを使う。"),
    ("qiitanikakimasu.", "Qiitaに書きます。"),
    ("qwenwotameshimasu.", "Qwenを試します。"),
    ("qrko-dowotsukau.", "QRコードを使う。"),
    ("qatantouwomakaseta.", "QAの担当を任された。"),
]
TEMPLATES = [
    ("{r}", "{e}"),
    ("{r}wotsukaimasu.", "{e}を使います。"),
    ("{r}dejikkoushimasu.", "{e}で実行します。"),
    ("kinou{r}wotsukaimashita.", "昨日{e}を使いました。"),
    ("{r}hasaikoudesu.", "{e}は最高です。"),
    ("watashiha{r}gasukidesu.", "私は{e}が好きです。"),
    ("kyouha{r}wo", "今日は{e}を"),
    ("korekara{r}nitsuiteshirabemasu.", "これから{e}について調べます。"),
]

if __name__ == "__main__":
    print("# 開発の道具・サービスの名前の試験。tools/tool_names_test.py で作成（手で書いた、実装を見ない打ち方）。名前は小文字のローマ字のまま打ち、公式の書き方で出ることを期待する。")
    for raw, official in NAMES:
        for t_raw, t_exp in TEMPLATES:
            print(f"{t_raw.format(r=raw)}\t{t_exp.format(e=official)}\ttools")
    for raw, expected in EXTRA:
        print(f"{raw}\t{expected}\ttools")
