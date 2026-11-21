"""Builds docs/PayRight_Judges_Pack.pdf from docs/judges_pack.md.

  pip install markdown
  python docs/make_judges_pdf.py

Edit the Markdown, not the PDF. Rendered with headless Edge/Chrome, so Tamil and
Hindi text would shape correctly too.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

HERE = Path(__file__).parent
SRC, OUT = HERE / "judges_pack.md", HERE / "PayRight_Judges_Pack.pdf"

CSS = """
@page { size: A4; margin: 15mm 16mm; }
body { font-family: 'Segoe UI', 'Nirmala UI', Arial, sans-serif; font-size: 10pt; line-height: 1.45; color: #1d1d1f; }
h1 { font-size: 21pt; margin: 0 0 4px; color: #0b6b3a; }
h2 { font-size: 14pt; color: #0b6b3a; margin: 14px 0 6px; break-after: avoid; }
h3 { font-size: 11pt; margin: 12px 0 4px; break-after: avoid; }
h2:not(:first-of-type) { break-before: page; }
p, li { margin: 3px 0; }
ul { padding-left: 18px; margin: 4px 0 6px; }
hr { display: none; }
code { font-family: Consolas, monospace; font-size: 8.8pt; background: #f1f3f1; padding: 0 3px; border-radius: 3px; }
blockquote { margin: 6px 0; padding: 6px 10px; border-left: 3px solid #c0392b; background: #fbf1ef; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 10px; font-size: 8.8pt; break-inside: auto; }
th { background: #e6f2ea; text-align: left; }
th, td { border: 1px solid #b5c4ba; padding: 4px 6px; vertical-align: top; }
tr { break-inside: avoid; }
"""


def browser():
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              shutil.which("chromium"), shutil.which("google-chrome"), shutil.which("msedge")):
        if p and Path(p).exists():
            return p
    sys.exit("Need Edge or Chrome to make the PDF.")


def github_lists(text):
    """Python-Markdown wants a blank line before a list and 4-space nesting; GitHub does not."""
    out = []
    for line in text.splitlines():
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if stripped.startswith(("- ", "> ")) and indent:
            line = " " * (indent * 2) + stripped  # 2-space nesting -> 4-space
        is_item = stripped.startswith("- ")
        prev = out[-1].lstrip(" ") if out else ""
        if is_item and out and prev and not prev.startswith("- ") and not indent:
            out.append("")
        out.append(line)
    return "\n".join(out)


def main():
    body = markdown.markdown(github_lists(SRC.read_text(encoding="utf-8")), extensions=["tables"])
    html = f"<!doctype html><html><head><meta charset=utf-8><title>PayRight for the judges</title><style>{CSS}</style></head><body>{body}</body></html>"
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "pack.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run([browser(), "--headless=new", "--disable-gpu", f"--user-data-dir={tmp}/profile",
                        "--no-pdf-header-footer", f"--print-to-pdf={OUT}", page.as_uri()],
                       check=True, capture_output=True, timeout=120)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
