"""Render docs/*.md → public/<slug>/index.html + public/index.html for GitLab Pages (luna/docs project CI).

Raw HTML in Markdown is not trusted: every page carries a CSP that forbids scripts, so injected markup can't run.
"""
import html
import pathlib
import shutil

import markdown

SRC, OUT = pathlib.Path("docs"), pathlib.Path("public")
CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; base-uri 'none'; form-action 'none'"
CSS = """
:root{--bg:#fbfaf7;--fg:#1f2328;--muted:#5f6670;--accent:#5b4bb7;--rule:#e4e1da}
@media (prefers-color-scheme:dark){:root{--bg:#16171b;--fg:#e6e6e6;--muted:#a0a4ab;--accent:#a99cf0;--rule:#2c2e35}}
body{background:var(--bg);color:var(--fg);font:17px/1.65 Georgia,'Iowan Old Style',serif;margin:0}
main{max-width:44rem;margin:0 auto;padding:2.5rem 1rem 4rem}
h1,h2,h3{font-family:system-ui,sans-serif;line-height:1.25}
a{color:var(--accent)} pre,code{font:14px/1.5 ui-monospace,monospace} pre{overflow-x:auto;padding:.8rem;border:1px solid var(--rule)}
table{border-collapse:collapse} td,th{border:1px solid var(--rule);padding:.3rem .6rem}
img{max-width:100%} footer{margin-top:3rem;color:var(--muted);font:14px system-ui,sans-serif}
"""


def page(title, body, home=False):
    nav = "" if home else '<p><a href="../">&larr; All documents</a></p>'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
            f'<title>{html.escape(title)}</title><style>{CSS}</style></head>'
            f'<body><main>{nav}{body}<footer>Published by Luna</footer></main></body></html>')


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    entries = []
    for md in sorted(SRC.glob("*.md")) if SRC.exists() else []:
        text = md.read_text(encoding="utf-8")
        first = text.lstrip().splitlines()[0] if text.strip() else ""
        title = first[2:].strip() if first.startswith("# ") else md.stem
        body = markdown.markdown(text, extensions=["extra", "sane_lists", "toc"])
        (OUT / md.stem).mkdir()
        (OUT / md.stem / "index.html").write_text(page(title, body), encoding="utf-8")
        entries.append((title, md.stem))
    items = "".join(f'<li><a href="{s}/">{html.escape(t)}</a></li>' for t, s in sorted(entries))
    index = "<h1>Documents</h1>" + (f"<ul>{items}</ul>" if items else "<p>Nothing published yet.</p>")
    (OUT / "index.html").write_text(page("Documents", index, home=True), encoding="utf-8")


if __name__ == "__main__":
    main()
