"""render_docs — a small stdio MCP server that turns Mermaid, Markdown, HTML and SVG into files (SVG / PNG / PDF / HTML).

Gives an assistant without terminal or file tools a safe way to produce real documents and diagrams:
  render_mermaid   Mermaid source          -> svg | png | pdf
  render_markdown  Markdown (+ ```mermaid) -> pdf | html        (styled document, diagrams drawn inline)
  render_html      HTML page or <svg>      -> pdf | png | svg

Rendering happens in headless Chromium inside a throw-away Docker container: no network (--network none), read-only
root, all capabilities dropped, memory/CPU/pid limits, only one job directory mounted. Untrusted markup can run
scripts in there but cannot reach anything. Mermaid is a vendored, pinned build (vendor/VERSION), so no CDN either.

Output lands in RENDER_OUT_DIR (a folder inside the profile's media cache), which the s3 and repos MCP servers accept
as an upload source and Hermes accepts for MEDIA: delivery — so the assistant can show a PNG inline, store a file in S3
and hand out a link, or commit it to a GitLab repo.

Transport: MCP over stdio (newline-delimited JSON-RPC). Hermes launches it per profile (mcp_servers.render in that
profile's config.yaml). Repo: turing-pi-k3/hermes/mcp/render_docs.py.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import fcntl
from pathlib import Path

import markdown

OUT_DIR = Path(os.environ["RENDER_OUT_DIR"])
WORK_DIR = Path(os.environ.get("RENDER_WORK_DIR") or (OUT_DIR.parent / "render-work"))
VENDOR = Path(os.environ.get("RENDER_VENDOR_DIR") or (Path(__file__).resolve().parent / "render" / "vendor"))
IMAGE = os.environ["RENDER_IMAGE"]                       # pinned by digest, e.g. zenika/alpine-chrome@sha256:…
TIMEOUT = int(os.environ.get("RENDER_TIMEOUT", "90"))
MAX_INPUT = int(os.environ.get("RENDER_MAX_INPUT", str(1024 * 1024)))
MAX_OUTPUT = int(os.environ.get("RENDER_MAX_OUTPUT", str(50 * 1024 * 1024)))
KEEP_DAYS = int(os.environ.get("RENDER_KEEP_DAYS", "30"))
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

DOCKER = ["docker", "run", "--rm", "--network", "none", "--read-only",
          "--tmpfs", "/tmp:rw,size=512m", "--memory", "1536m", "--cpus", "2", "--pids-limit", "512",
          "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
          "-e", "HOME=/tmp", "--entrypoint", "chromium-browser"]
CHROME = ["--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--no-first-run",
          "--user-data-dir=/tmp/profile", "--allow-file-access-from-files", "--hide-scrollbars",
          "--run-all-compositor-stages-before-draw", "--virtual-time-budget=20000"]

# Headless Chrome under a virtual-time budget does not reliably produce animation frames; libraries that await
# requestAnimationFrame then stall. Timers run on the virtual clock, so map rAF onto them.
RAF_SHIM = ("<script>window.requestAnimationFrame=function(cb){return setTimeout(function(){cb(performance.now())},16)};"
            "window.cancelAnimationFrame=function(id){clearTimeout(id)};</script>")

DOC_CSS = """
@page { size: Letter; margin: 18mm 17mm 20mm; }
html { font-family: "Open Sans", "FreeSans", sans-serif; font-size: 10.5pt; line-height: 1.5; color: #16181a; }
body { margin: 0; }
h1, h2, h3, h4 { line-height: 1.2; margin: 1.3em 0 0.45em; page-break-after: avoid; }
h1 { font-size: 22pt; margin-top: 0; } h2 { font-size: 15pt; border-bottom: 1px solid #cbcec8; padding-bottom: 3px; }
h3 { font-size: 12.5pt; } h4 { font-size: 11pt; }
p, ul, ol, table, pre, blockquote { margin: 0 0 0.8em; }
a { color: #2f5d50; }
code { font-family: "FreeMono", monospace; font-size: 0.92em; background: #eef0ed; padding: 0 3px; border-radius: 3px; }
pre { background: #f4f5f3; border: 1px solid #dfe2dd; border-radius: 4px; padding: 8px 10px; white-space: pre-wrap;
      page-break-inside: avoid; }
pre code { background: none; padding: 0; }
blockquote { border-left: 3px solid #cbcec8; margin-left: 0; padding-left: 12px; color: #4c5459; }
table { border-collapse: collapse; width: 100%; page-break-inside: avoid; }
th, td { border: 1px solid #cbcec8; padding: 4px 7px; text-align: left; vertical-align: top; }
th { background: #eef0ed; }
img, svg { max-width: 100%; }
pre.mermaid, .mermaid { text-align: center; margin: 0.6em 0 1em; page-break-inside: avoid; background: none; border: 0;
                        padding: 0; white-space: normal; }
.mermaid svg { height: auto; }
.render-error { color: #8a1c2b; border: 1px solid #8a1c2b; padding: 6px; white-space: pre-wrap; }
"""

THEMES = ["default", "neutral", "dark", "forest", "base"]
TOOLS = [
    {"name": "render_mermaid", "description": (
        "Draw a Mermaid diagram (flowchart, sequence, class, state, ER, gantt, pie, mindmap, timeline, …) and save it "
        "as SVG, PNG or PDF. Returns the file path. Show a PNG in chat with MEDIA:<path>; store or share any file with "
        "the s3 tools (s3_upload_file) or commit it with the repos tools (repo_upload_file)."),
     "inputSchema": {"type": "object", "properties": {
         "source": {"type": "string", "description": "Mermaid source, without the ``` fence"},
         "format": {"type": "string", "enum": ["svg", "png", "pdf"], "default": "svg"},
         "name": {"type": "string", "description": "File name without extension (letters, digits, . _ -)"},
         "theme": {"type": "string", "enum": THEMES, "default": "default"},
         "background": {"type": "string", "default": "white", "description": "CSS colour, or 'transparent' (svg/png)"},
         "scale": {"type": "number", "default": 2, "description": "PNG pixel density (1–4)"}},
         "required": ["source"]}},
    {"name": "render_markdown", "description": (
        "Turn Markdown into a clean, printable document (PDF, US Letter) or a standalone HTML page. Supports headings, "
        "lists, tables, code, images by https/data URL (no network while rendering, so remote images are left out) "
        "and ```mermaid blocks, which are drawn as diagrams. Returns the file path."),
     "inputSchema": {"type": "object", "properties": {
         "markdown": {"type": "string"},
         "format": {"type": "string", "enum": ["pdf", "html"], "default": "pdf"},
         "name": {"type": "string"},
         "title": {"type": "string", "description": "Document title (default: first heading)"},
         "theme": {"type": "string", "enum": THEMES, "default": "neutral", "description": "Mermaid theme"}},
         "required": ["markdown"]}},
    {"name": "render_html", "description": (
        "Render an HTML page (e.g. an architecture or concept diagram you wrote as HTML + inline SVG) or a bare <svg> "
        "to PDF or PNG, or save a bare <svg> as an .svg file. The page is rendered offline (no network). "
        "Returns the file path."),
     "inputSchema": {"type": "object", "properties": {
         "html": {"type": "string", "description": "A full HTML document, an HTML fragment, or an <svg>…</svg>"},
         "format": {"type": "string", "enum": ["pdf", "png", "svg"], "default": "png"},
         "name": {"type": "string"},
         "width": {"type": "integer", "default": 1280, "description": "Viewport width in CSS px (png/pdf)"},
         "page": {"type": "string", "enum": ["fit", "letter", "a4"], "default": "fit",
                  "description": "PDF page size: fit = one page sized to the content"},
         "scale": {"type": "number", "default": 2, "description": "PNG pixel density (1–4)"}},
         "required": ["html"]}},
]


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- helpers

def _name(raw, default):
    n = (raw or "").strip()
    if n:
        n = re.sub(r"\.(svg|png|pdf|html?)$", "", n, flags=re.I)
        if not NAME_RE.match(n):
            raise ToolError("invalid name: use letters, digits, '.', '_' or '-' (max 100), starting with a letter/digit")
        return n
    return f"{default}-{time.strftime('%Y%m%d-%H%M%S')}"


def _check_size(text, what):
    if len(text.encode()) > MAX_INPUT:
        raise ToolError(f"{what} too large (max {MAX_INPUT // 1024} KB)")


def _cleanup():
    """Drop renders older than KEEP_DAYS and stale job dirs (best effort)."""
    now = time.time()
    for d, age in ((OUT_DIR, KEEP_DAYS * 86400), (WORK_DIR, 3600)):
        if not d.is_dir():
            continue
        for p in d.iterdir():
            try:
                if now - p.stat().st_mtime > age:
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
            except OSError:
                pass


class Job:
    """One render: a private job dir mounted at /job, the vendor dir read-only at /vendor."""

    def __init__(self):
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix="job-", dir=WORK_DIR))
        os.chmod(self.dir, 0o755)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, name, text):
        (self.dir / name).write_text(text, encoding="utf-8")

    def chrome(self, page, *args, dump=False):
        cmd = DOCKER + ["-v", f"{self.dir}:/job", "-v", f"{VENDOR}:/vendor:ro", IMAGE] + CHROME + list(args)
        cmd += ["--dump-dom"] if dump else []
        cmd.append(f"file:///job/{page}")
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ToolError(f"rendering timed out after {TIMEOUT}s")
        if r.returncode != 0:
            tail = r.stderr.decode(errors="replace").strip().splitlines()[-3:]
            raise ToolError("renderer failed: " + " | ".join(tail)[:500])
        return r.stdout.decode("utf-8", errors="replace")

    def finish(self, produced, name, ext):
        src = self.dir / produced
        if not src.is_file() or src.stat().st_size == 0:
            raise ToolError("renderer produced no output")
        if src.stat().st_size > MAX_OUTPUT:
            raise ToolError("output too large")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        dest = OUT_DIR / f"{name}.{ext}"
        shutil.move(str(src), dest)
        return dest


def _page(body, head="", title="render"):
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>{RAF_SHIM}{head}"
            f"</head><body>{body}</body></html>")


# Measures the rendered content and leaves the result in the DOM for --dump-dom to carry back out.
MEASURE_JS = """
<script>
function __measure(){
  var el = document.querySelector('[data-measure]') || document.documentElement;
  var r = el.getBoundingClientRect();
  var w = Math.ceil(Math.max(r.right, el.scrollWidth || 0)), h = Math.ceil(Math.max(r.bottom, el.scrollHeight || 0));
  if (el === document.documentElement) { w = Math.max(w, document.documentElement.scrollWidth); h = Math.max(h, document.documentElement.scrollHeight); }
  var t = document.createElement('textarea'); t.id = '__size'; t.textContent = w + ' ' + h; document.body.appendChild(t);
}
</script>"""


def _dumped(dom, el_id):
    m = re.search(r'<textarea id="%s"[^>]*>(.*?)</textarea>' % el_id, dom, re.S)
    return html.unescape(m.group(1)) if m else None


def _mermaid_page(source, theme, background):
    bg = "transparent" if background == "transparent" else html.escape(background or "white", quote=True)
    head = ("<script src='file:///vendor/mermaid.min.js'></script>"
            f"<style>html,body{{margin:0;background:{bg}}} #d{{display:inline-block;padding:16px}}</style>")
    body = (f"<div id='d' data-measure><pre class='mermaid'>{html.escape(source)}</pre></div>"
            "<script>"
            f"mermaid.initialize({{startOnLoad:false, securityLevel:'strict', theme:{json.dumps(theme)},"
            " htmlLabels:false, flowchart:{htmlLabels:false}, fontFamily:'Open Sans, FreeSans, sans-serif'});"
            "mermaid.run({querySelector:'.mermaid'}).then(function(){"
            "  var svg=document.querySelector('#d svg'); var t=document.createElement('textarea'); t.id='__svg';"
            "  t.textContent=new XMLSerializer().serializeToString(svg); document.body.appendChild(t);"
            "}).catch(function(e){ var t=document.createElement('textarea'); t.id='__err';"
            "  t.textContent=String(e && (e.message||e)); document.body.appendChild(t); });"
            "</script>")
    return _page(body, head)


def _svg_from_mermaid(job, source, theme, background):
    job.write("m.html", _mermaid_page(source, theme, background))
    dom = job.chrome("m.html", dump=True)
    err = _dumped(dom, "__err")
    if err:
        raise ToolError("Mermaid syntax error: " + err.strip()[:600])
    svg = _dumped(dom, "__svg")
    if not svg or "<svg" not in svg:
        raise ToolError("Mermaid produced no diagram")
    if background and background != "transparent":
        # Merge into the root's existing style attribute (a second style="" would make the SVG invalid XML).
        m = re.match(r"\s*<svg\b[^>]*>", svg)
        root = m.group(0)
        bg = f"background-color:{html.escape(background, quote=True)};"
        if re.search(r'\sstyle="', root):
            root = re.sub(r'\sstyle="', lambda x: x.group(0) + bg, root, count=1)
        else:
            root = root.replace("<svg", f'<svg style="{bg}"', 1)
        svg = root + svg[m.end():]
    return svg


def _svg_size(svg):
    m = re.search(r'viewBox="\s*[-\d.]+[ ,]+[-\d.]+[ ,]+([\d.]+)[ ,]+([\d.]+)', svg)
    if m:
        return max(1, int(float(m.group(1)) + 0.999)), max(1, int(float(m.group(2)) + 0.999))
    w = re.search(r'\bwidth="([\d.]+)', svg)
    h = re.search(r'\bheight="([\d.]+)', svg)
    return (int(float(w.group(1))) if w else 800), (int(float(h.group(1))) if h else 600)


def _static_svg_page(svg, background="white", pad=16):
    bg = "transparent" if background == "transparent" else html.escape(background or "white", quote=True)
    w, h = _svg_size(svg)
    # Pin the root <svg> to its natural size (Mermaid emits width="100%" + max-width); inner elements untouched.
    m = re.match(r"\s*<svg\b[^>]*>", svg)
    if m:
        root = re.sub(r'\s(width|height)="[^"]*"', "", m.group(0))
        root = re.sub(r'max-width:\s*[\d.]+px;?', "", root)
        svg = root.replace("<svg", f'<svg width="{w}" height="{h}"', 1) + svg[m.end():]
    # Block-level wrapper (an inline-block sits on a text line whose strut adds height) + no page breaks inside.
    return _page(f"<div id='d' data-measure>{svg}</div>",
                 f"<style>html,body{{margin:0;background:{bg}}} #d{{display:block;width:max-content;padding:{pad}px;"
                 f"break-inside:avoid}} #d>svg{{display:block}} @media print{{html,body{{height:{h + 2 * pad}px;"
                 f"overflow:hidden}}}}</style>"), w + 2 * pad, h + 2 * pad + 4   # +4: PDF px->pt rounding


def _png(job, page, w, h, scale, name):
    scale = max(1.0, min(float(scale or 2), 4.0))
    if w * h * scale * scale > 60_000_000:
        raise ToolError("image too large — reduce width/scale")
    job.chrome(page, f"--window-size={w},{h}", f"--force-device-scale-factor={scale}", "--screenshot=/job/out.png")
    return job.finish("out.png", name, "png")


def _pdf(job, page, name, size_css=None):
    if size_css:
        src = (job.dir / page).read_text(encoding="utf-8")
        job.write(page, src.replace("</head>", f"<style>@page{{size:{size_css};margin:0}}</style></head>", 1))
    job.chrome(page, "--no-pdf-header-footer", "--print-to-pdf=/job/out.pdf")
    return job.finish("out.pdf", name, "pdf")


def _result(path, extra=""):
    size = path.stat().st_size
    kind = path.suffix[1:].upper()
    if path.suffix == ".pdf":
        counts = [int(n) for n in re.findall(rb"/Count (\d+)", path.read_bytes())]
        if counts:
            extra = f", {max(counts)} page(s)" + extra
    hint = []
    if path.suffix == ".png":
        hint.append(f"show it in chat with MEDIA:{path}")
    hint.append(f"store/share with s3_upload_file(path='{path}')")
    hint.append(f"commit with repo_upload_file(path='{path}', …)")
    return f"Saved {kind} ({size // 1024 or 1} KB): {path}{extra}\nNext: " + "; ".join(hint) + "."


# ---------------------------------------------------------------- tools

def t_mermaid(a):
    src = (a.get("source") or "").strip()
    src = re.sub(r"^```(?:mermaid)?\s*\n|\n```\s*$", "", src)
    if not src:
        raise ToolError("source is empty")
    _check_size(src, "source")
    fmt, theme = a.get("format") or "svg", a.get("theme") or "default"
    if fmt not in ("svg", "png", "pdf") or theme not in THEMES:
        raise ToolError("format must be svg|png|pdf; theme one of " + ", ".join(THEMES))
    bg = a.get("background") or "white"
    if not re.match(r"^(transparent|#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20})$", bg):
        raise ToolError("background must be a colour name, #hex, or 'transparent'")
    name = _name(a.get("name"), "diagram")
    with Job() as job:
        svg = _svg_from_mermaid(job, src, theme, bg)
        if fmt == "svg":
            job.write("out.svg", svg if svg.startswith("<?xml") else '<?xml version="1.0" encoding="UTF-8"?>\n' + svg)
            return _result(job.finish("out.svg", name, "svg"))
        page, w, h = _static_svg_page(svg, bg)
        job.write("s.html", page)
        if fmt == "png":
            return _result(_png(job, "s.html", w, h, a.get("scale"), name))
        return _result(_pdf(job, "s.html", name, f"{w}px {h}px"))


def t_markdown(a):
    md = a.get("markdown") or ""
    if not md.strip():
        raise ToolError("markdown is empty")
    _check_size(md, "markdown")
    fmt, theme = a.get("format") or "pdf", a.get("theme") or "neutral"
    if fmt not in ("pdf", "html") or theme not in THEMES:
        raise ToolError("format must be pdf|html")
    title = (a.get("title") or "").strip()
    if not title:
        m = re.search(r"^#\s+(.+)$", md, re.M)
        title = m.group(1).strip() if m else "Document"
    name = _name(a.get("name"), re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()[:60] or "document")
    body = markdown.markdown(md, extensions=["extra", "sane_lists", "toc"], output_format="html")
    n_mermaid = body.count('class="language-mermaid"')
    # ```mermaid fences -> <pre class="mermaid"> for mermaid.run(); the code text is already HTML-escaped.
    body = re.sub(r'<pre><code class="language-mermaid">(.*?)</code></pre>',
                  lambda m: f'<pre class="mermaid">{m.group(1)}</pre>', body, flags=re.S)
    head = f"<style>{DOC_CSS}</style>"
    run = ""
    if n_mermaid:
        head += "<script src='file:///vendor/mermaid.min.js'></script>"
        run = ("<script>"
               f"mermaid.initialize({{startOnLoad:false, securityLevel:'strict', theme:{json.dumps(theme)},"
               " htmlLabels:false, flowchart:{htmlLabels:false}, fontFamily:'Open Sans, FreeSans, sans-serif'});"
               "var n=document.querySelectorAll('pre.mermaid');"
               "Array.prototype.forEach.call(n,function(el){ mermaid.run({nodes:[el]}).catch(function(e){"
               "  el.className='render-error'; el.textContent='Mermaid error: '+(e&&(e.message||e)); }); });"
               "</script>")
    page = _page(body + run, head, title)
    with Job() as job:
        job.write("d.html", page)
        if n_mermaid:
            # Pass 1: let Mermaid draw, keep the resulting static DOM (scripts stripped) for printing / delivery.
            dom = job.chrome("d.html", dump=True)
            dom = re.sub(r"<script\b[^>]*>.*?</script>", "", dom, flags=re.S | re.I)
            errors = len(re.findall(r'class="render-error"', dom))
            job.write("d.html", dom if dom.lstrip().lower().startswith("<!doctype") else "<!doctype html>" + dom)
        else:
            errors = 0
        note = f" ({n_mermaid} diagram(s){', ' + str(errors) + ' with errors' if errors else ''})" if n_mermaid else ""
        if fmt == "html":
            return _result(job.finish("d.html", name, "html"), note)
        return _result(_pdf(job, "d.html", name), note)


def t_html(a):
    src = a.get("html") or ""
    if not src.strip():
        raise ToolError("html is empty")
    _check_size(src, "html")
    fmt = a.get("format") or "png"
    if fmt not in ("pdf", "png", "svg"):
        raise ToolError("format must be pdf|png|svg")
    name = _name(a.get("name"), "page")
    stripped = src.strip()
    is_svg = bool(re.match(r"^(<\?xml[^>]*>\s*)?(<!--.*?-->\s*)*<svg\b", stripped, re.S))
    with Job() as job:
        if fmt == "svg":
            if not is_svg:
                raise ToolError("format 'svg' needs a bare <svg>…</svg> input")
            out = stripped if stripped.startswith("<?xml") else '<?xml version="1.0" encoding="UTF-8"?>\n' + stripped
            if 'xmlns="http://www.w3.org/2000/svg"' not in out[:1000]:
                out = re.sub(r"<svg\b", '<svg xmlns="http://www.w3.org/2000/svg"', out, count=1)
            job.write("out.svg", out)
            return _result(job.finish("out.svg", name, "svg"))
        width = max(200, min(int(a.get("width") or 1280), 4000))
        if is_svg:
            page, w, h = _static_svg_page(re.sub(r"^<\?xml[^>]*>\s*", "", stripped), "white")
        else:
            doc = stripped if re.search(r"<html\b", stripped, re.I) else _page(stripped)
            # rAF shim + measurer go in, so pages that animate in or lay out with rAF finish.
            doc = re.sub(r"<head\b[^>]*>", lambda m: m.group(0) + RAF_SHIM, doc, count=1, flags=re.I) \
                if re.search(r"<head\b", doc, re.I) else RAF_SHIM + doc
            job.write("p.html", doc.replace("</body>", MEASURE_JS + "<script>setTimeout(__measure,500)</script></body>", 1)
                      if "</body>" in doc else doc + MEASURE_JS + "<script>setTimeout(__measure,500)</script>")
            dom = job.chrome("p.html", f"--window-size={width},800", dump=True)
            size = (_dumped(dom, "__size") or f"{width} 800").split()
            w, h = max(width, int(size[0])), max(50, min(int(size[1]), 20000))
            job.write("p.html", doc)
            page = None
        target = "s.html" if page else "p.html"
        if page:
            job.write("s.html", page)
        if fmt == "png":
            return _result(_png(job, target, w, h, a.get("scale"), name))
        size_css = {"letter": "Letter", "a4": "A4"}.get(a.get("page") or "fit") or f"{w}px {h}px"
        return _result(_pdf(job, target, name, size_css))


HANDLERS = {"render_mermaid": t_mermaid, "render_markdown": t_markdown, "render_html": t_html}


def call(name, args):
    fn = HANDLERS.get(name)
    if not fn:
        return "unknown tool", True
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(WORK_DIR / ".lock", "w") as lock:       # one render at a time per profile
            fcntl.flock(lock, fcntl.LOCK_EX)
            _cleanup()
            return fn(args or {}), False
    except ToolError as e:
        return str(e), True
    except (OSError, ValueError) as e:
        return f"render failed: {type(e).__name__}: {str(e)[:300]}", True


def rpc(msg):
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        return None
    if method == "initialize":
        res = {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
               "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "render_docs", "version": "1.0.0"}}
    elif method == "ping":
        res = {}
    elif method == "tools/list":
        res = {"tools": TOOLS}
    elif method == "tools/call":
        text, err = call(params.get("name"), params.get("arguments"))
        res = {"content": [{"type": "text", "text": text}], "isError": err}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        msgs = msg if isinstance(msg, list) else [msg]
        out = [r for r in (rpc(m) for m in msgs) if r is not None]
        for r in out:
            sys.stdout.write(json.dumps(r) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
