"""interleave-bench.py — 3 conversations of ~30K tokens take turns (A, B, C,
then A again), the shape of several agents/chats sharing one server; then two
requests at once.  uv run --python 3.12 --no-project interleave-bench.py <ollama|omlx>"""
import importlib.util, json, sys, time
from concurrent.futures import ThreadPoolExecutor
spec = importlib.util.spec_from_file_location("pb", __file__.replace("interleave-bench.py", "prefill-bench.py"))
pb = importlib.util.module_from_spec(spec); sys.argv, argv = [sys.argv[0], "none"], sys.argv; spec.loader.exec_module(pb)
name = argv[1]; fn = pb.ollama if name == "ollama" else pb.omlx
salt = f"il-{int(time.time())}"
fn(pb.prompt(2000, salt + "-warm"))
for s in "ABC":
    print(json.dumps({"server": name, "case": f"30K cold {s}", **fn(pb.prompt(110_000, f"{salt}-{s}"))}))
extra = "Tool result: 3 files changed, tests pass.\n\n"
print(json.dumps({"server": name, "case": "A next turn after B,C", **fn(pb.prompt(110_000, f"{salt}-A", extra=extra))}))
t = time.time()
with ThreadPoolExecutor(2) as ex:
    rs = list(ex.map(lambda s: fn(pb.prompt(30_000, f"{salt}-par{s}")), "12"))
print(json.dumps({"server": name, "case": "2 x 8K cold, concurrent", "wall_s": round(time.time() - t, 2),
                  "ttft_s": [r["ttft_s"] for r in rs], "decode_tps": [r["decode_tps"] for r in rs]}))
