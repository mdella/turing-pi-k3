#!/usr/bin/env python3
"""Re-score the already-built comparison projects with the fixed acceptance test.

The builds themselves were fine; only the scoring was wrong (shared-HOME
storage collisions between builds). So this re-judges the existing artifacts
instead of spending another hour regenerating them.
"""
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
PROJECTS = Path("/Users/mdella/projects")
ROWS = []

for tag in ("kimi", "qwen"):
    for i in (1, 2, 3):
        proj = PROJECTS / f"taskcli-cmp-{tag}-{i}"
        if not proj.is_dir():
            continue

        report = (proj / "_run-report.txt").read_text() if (proj / "_run-report.txt").is_file() else ""
        def grab(pat, cast, default=0):
            m = re.search(pat, report)
            return cast(m.group(1)) if m else default

        p = subprocess.run(["python3", str(HERE / "acceptance-test.py"), str(proj)],
                           capture_output=True, text=True, timeout=1800)
        try:
            acc = json.loads(p.stdout)
        except Exception:
            acc = {"defect_count": None, "defects": [{"code": "SCORING-FAILED",
                   "detail": (p.stderr or p.stdout)[:200]}], "notes": {}}

        ROWS.append({
            "model": tag, "run": i,
            "wall_s": grab(r"wall_clock_s: (\d+)", int),
            "tok_s": grab(r"mean=([\d.]+) tok/s", float, 0.0),
            "turns": grab(r"num_turns\s*: (\d+)", int),
            "out_tokens": grab(r"output_tokens\s*: (\d+)", int),
            "defects": acc.get("defect_count"),
            "codes": [d["code"] for d in acc.get("defects", [])],
            "detail": acc.get("defects", []),
            "notes": acc.get("notes", {}),
        })
        print(f"  scored {tag}-{i}: defects={acc.get('defect_count')}", flush=True)

(HERE / "comparison-final.json").write_text(json.dumps(ROWS, indent=2))
print(f"\nwrote {HERE / 'comparison-final.json'}")
