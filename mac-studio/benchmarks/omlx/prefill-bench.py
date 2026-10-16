"""prefill-bench.py — same model, Ollama vs oMLX: cold long prompt, then the
"next agent turn" (identical prefix + a little new text), which is where
prefix/KV caching pays off.

  uv run --python 3.12 --no-project prefill-bench.py [ollama|omlx|both]

Ollama numbers come from its own timings (prompt_eval_*/eval_*). oMLX numbers
come from a streamed request: TTFT = first content or reasoning chunk, decode
rate = remaining tokens over the rest of the time; usage gives cached tokens.
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

# Override the model pair with BENCH_OLLAMA_MODEL / BENCH_OMLX_MODEL.
OLLAMA = ("http://127.0.0.1:11434", os.environ.get("BENCH_OLLAMA_MODEL", "agentworld:35b-a3b-q4km"))
OMLX = ("http://127.0.0.1:8000", os.environ.get("BENCH_OMLX_MODEL", "agentworld-oq4"))
CORPUS = Path(__file__).parent / ".venv/lib/python3.12/site-packages/omlx/server.py"
GEN = 200


def post(url, body, stream=False):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json"})
    return urllib.request.urlopen(req, timeout=1800)


def prompt(chars, salt, extra=""):
    # salt goes FIRST so different runs don't share a prefix with each other
    src = CORPUS.read_text()[:chars]
    return (f"[session {salt}]\nHere is a Python source file.\n\n{src}\n\n{extra}"
            "Question: in one sentence, what does this file do?")


def ollama(p):
    t = time.time()
    d = json.load(post(OLLAMA[0] + "/api/chat", {
        "model": OLLAMA[1], "stream": False, "think": False,
        "messages": [{"role": "user", "content": p}],
        "options": {"num_predict": GEN}}))
    return {"prompt_tok": d["prompt_eval_count"], "cached_tok": None,
            "ttft_s": round((d.get("load_duration", 0) + d["prompt_eval_duration"]) / 1e9, 2),
            "prefill_tps": round(d["prompt_eval_count"] / (d["prompt_eval_duration"] / 1e9)),
            "decode_tps": round(d["eval_count"] / (d["eval_duration"] / 1e9), 1),
            "total_s": round(time.time() - t, 2)}


def omlx(p):
    t0 = time.time()
    r = post(OMLX[0] + "/v1/chat/completions", {
        "model": OMLX[1], "stream": True, "max_tokens": GEN,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": p}]})
    first, usage = None, {}
    for raw in r:
        line = raw.decode().strip()
        if not line.startswith("data:") or line == "data: [DONE]":
            continue
        ev = json.loads(line[5:])
        if ev.get("usage"):
            usage = ev["usage"]
        for ch in ev.get("choices", []):
            dl = ch.get("delta", {})
            if first is None and (dl.get("content") or dl.get("reasoning_content")):
                first = time.time()
    end = time.time()
    ct = usage.get("completion_tokens", 0)
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    pt = usage.get("prompt_tokens", 0)
    ttft = (first or end) - t0
    return {"prompt_tok": pt, "cached_tok": cached, "ttft_s": round(ttft, 2),
            "prefill_tps": round((pt - (cached or 0)) / ttft) if ttft else None,
            "decode_tps": round((ct - 1) / (end - first), 1) if first and end > first else None,
            "total_s": round(end - t0, 2)}


def run(name, fn):
    salt = f"{name}-{int(time.time())}"
    fn(prompt(2000, salt + "-warm"))            # load the model; not reported
    rows = []
    for label, chars in (("8K", 30_000), ("30K", 110_000)):
        base = prompt(chars, f"{salt}-{label}")
        rows.append((f"{label} cold", fn(base)))
        nxt = prompt(chars, f"{salt}-{label}", extra="Tool result: 3 files changed, tests pass.\n\n")
        rows.append((f"{label} next turn", fn(nxt)))
    for label, r in rows:
        print(json.dumps({"server": name, "model": (OLLAMA if name == "ollama" else OMLX)[1], "case": label, **r}))


which = sys.argv[1] if len(sys.argv) > 1 else "both"
if which in ("ollama", "both"):
    run("ollama", ollama)
if which in ("omlx", "both"):
    run("omlx", omlx)
