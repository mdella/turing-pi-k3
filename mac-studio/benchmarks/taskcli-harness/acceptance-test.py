#!/usr/bin/env python3
"""
acceptance-test.py — black-box defect detector for a built taskcli.

    ./acceptance-test.py /Users/mdella/projects/taskcli-kimi35

Why this exists: a model's own test suite is not evidence its CLI works. The
first kimi35 build shipped 26 passing tests while `taskcli list all` was broken
-- the test only asserted argparse ACCEPTED the string, never ran the command.
So this drives the real CLI as a user would and judges by observed behaviour.

FAIRNESS: different models make different, legitimate design choices (hash vs
integer ids; `list --status open` vs `list open`). Those are not defects. Each
capability is therefore probed with several plausible invocations and counts as
working if ANY succeeds. A defect is recorded only when:
  * no invocation form works, or
  * the tool contradicts its own --help (advertises a value, then rejects it), or
  * it crashes with a traceback instead of erroring cleanly.

Emits one JSON object on stdout.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJ = Path(sys.argv[1]).resolve()
TIMEOUT = 90

# Task ids seen across builds: full UUIDs (ac2f6941-5804-...), short hex hashes
# (c22a9bca) and plain integers (1). The hyphen group matters -- matching only
# the first block of a UUID yields a truncated id and a bogus "not found".
ID_RE = r"\b([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|[0-9a-f]{6,}|\d+)\b"


WORKDIR = None      # isolated cwd + fake HOME; set in main()
REAL_HOME = os.environ["HOME"]


def run(args, db):
    """Invoke the CLI in an isolated working directory.

    Storage isolation has to work for any design the model chose, so we cover
    all three: run from a temp cwd (catches a relative default like
    ./tasks.json), pass --storage if the tool offers it, and set the common env
    vars. cwd isolation is what actually does the work for most builds.
    """
    # HOME is redirected into the sandbox. Several builds default to an
    # ABSOLUTE path like ~/.taskcli.json; without this they all share one file
    # in the real home directory, and since their on-disk schemas differ
    # ({"tasks":[...]} vs a bare [...]), one build's data makes the next build
    # look broken. Isolating HOME is what actually separates them -- env vars
    # and cwd are not enough.
    env = dict(os.environ, HOME=WORKDIR or os.environ["HOME"],
               TASKCLI_DB=db, TASKCLI_FILE=db, TASKCLI_PATH=db,
               TASKCLI_STORAGE=db)
    # ...but uv caches under $HOME, so pin it back to the real one or every
    # invocation re-resolves the environment from scratch.
    env["UV_CACHE_DIR"] = os.path.join(REAL_HOME, ".cache", "uv")
    try:
        p = subprocess.run(["uv", "run", "--project", str(PROJ), "taskcli", *args],
                           cwd=WORKDIR or str(PROJ), env=env,
                           capture_output=True, text=True, timeout=TIMEOUT)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "TIMEOUT"
    except Exception as e:                                  # noqa: BLE001
        return 125, "", f"LAUNCH-FAIL {e}"


def any_works(forms, db, expect=None):
    """Try each invocation form; return (ok, winning_form, output)."""
    for f in forms:
        rc, out, err = run(f, db)
        if rc == 0 and (expect is None or expect(out + err)):
            return True, f, out + err
    return False, None, ""


def traceback_in(text):
    return "Traceback (most recent call last)" in text


def main():
    defects = []
    notes = {}

    def defect(code, detail):
        defects.append({"code": code, "detail": detail})

    # A build the watchdog killed is defective by definition: it never finished.
    # Recorded before anything else runs, because a timed-out build often still
    # leaves a partially working CLI behind, and scoring only that would report
    # a model as fine when in practice it never delivered.
    if (PROJ / "_TIMEOUT").is_file():
        defect("build-timeout", (PROJ / "_TIMEOUT").read_text().strip()[:120])

    global WORKDIR
    tmp = tempfile.mkdtemp()
    WORKDIR = tmp
    db = os.path.join(tmp, "tasks.json")

    # ---- 0. does it run at all -------------------------------------------
    rc, out, err = run(["--help"], db)
    if rc != 0:
        defect("cli-unusable", f"--help exited {rc}: {(err or out)[:200]}")
        # defect_count MUST be emitted on this path too. It was omitted here,
        # and run-comparison.sh aggregates with `(defect_count or 0) > 0` -- so a
        # build whose CLI does not even run scored None, which collapsed to 0 and
        # was counted as CLEAN. The worst build in the round was being reported
        # as the best. Caught when qwen3.8 timed out at 1801 s and still came
        # back "defects=None".
        print(json.dumps({"project": PROJ.name, "defect_count": len(defects),
                          "defects": defects, "notes": notes}))
        return
    help_top = out + err

    # ---- 1. add ----------------------------------------------------------
    add_out = ""
    ok, addform, add_out = any_works([["add", "alpha task"], ["add", "--title", "alpha task"]], db)
    if not ok:
        defect("add-broken", "no working form of `add`")
    else:
        _, o2, e2 = run(addform[:-1] + ["beta task"], db)
        add_out += o2 + e2

    # ---- 2. list ---------------------------------------------------------
    ok, listform, listout = any_works([["list"], ["list", "all"], ["list", "--status", "all"]], db,
                                      expect=lambda t: "alpha" in t)
    if not ok:
        defect("list-broken", "`list` does not show added tasks")
        listout = ""
    notes["list_form"] = " ".join(listform) if listform else None

    # ---- 3. persistence across processes ----------------------------------
    if ok:
        rc2, out2, _ = run(listform, db)
        if "alpha" not in out2:
            defect("no-persistence", "tasks absent on a second invocation")
        if not os.path.exists(db):
            # Storage path may be configured differently; only a defect if the
            # data also failed to survive, which is checked above.
            notes["db_path_env_ignored"] = True

    # ---- 4. status filters, incl. self-contradiction check ----------------
    # Which filter values does --help claim to support?
    rc, lh, lhe = run(["list", "--help"], db)
    # Only values argparse DECLARES as choices, i.e. inside {..}, count as
    # advertised. Scraping the whole help text also picks up prose such as
    # "(default: show all)", which is not a promise that `list all` works --
    # a design where bare `list` shows everything is perfectly consistent.
    claimed = set()
    for grp in re.findall(r"\{([a-z,]+)\}", lh + lhe):
        claimed |= {v for v in grp.split(",") if v in ("all", "open", "done")}
    for val in sorted(claimed):
        got = False
        for form in ([["list", val]], [["list", "--status", val]], [["list", "-s", val]]):
            r, o, e = any_works(form, db)
            if r:
                got = True
                break
        if not got:
            # advertised by its own help, yet no form works -> genuine defect
            r2, o2, e2 = run(["list", val], db)
            defect("help-contradiction",
                   f"`list --help` advertises '{val}' but `list {val}` fails: "
                   f"{(e2 or o2).strip()[:120]}")

    # ---- 5. are ids discoverable, and does `done` work -------------------
    # An id the user cannot see is an id they cannot use. If `list` hides ids
    # but `done` requires one, the tool is unusable in normal operation even
    # though every individual command "works".
    ids_from_list = re.findall(ID_RE, listout)
    ids_from_add = re.findall(ID_RE, add_out)
    if not ids_from_list and ids_from_add:
        defect("ids-not-discoverable",
               "`list` never shows task ids, but `done`/`delete` require one — "
               "ids are only visible in `add` output")

    task_id = (ids_from_list or ids_from_add or ["1"])[0]
    ok_done, doneform, _ = any_works(
        [["done", task_id], ["complete", task_id], ["done", "--id", task_id]], db)
    if not ok_done:
        defect("done-broken", f"no working form of `done` (tried id {task_id!r})")
    else:
        _, o, _ = run(listform or ["list"], db)
        if "done" not in o.lower() and "✓" not in o and "[x]" not in o.lower():
            notes["done_not_visible_in_list"] = True

    # ---- 6. delete -------------------------------------------------------
    ok_del, _, _ = any_works([["delete", task_id], ["rm", task_id], ["delete", "--id", task_id]], db)
    if not ok_del:
        defect("delete-broken", f"no working form of `delete` (id {task_id!r})")

    # ---- 7. error handling: bad id must be a clean error, not a crash -----
    rc, out, err = run(["done", "definitely-not-an-id"], db)
    if traceback_in(out + err):
        defect("crash-on-bad-id", "traceback instead of a clean error message")
    elif rc == 0:
        defect("bad-id-silent", "unknown id exited 0 instead of signalling an error")

    # ---- 8. error handling: corrupt storage file -------------------------
    # Corrupt whatever json the build actually persists to -- it may have
    # ignored our env vars and used its own default inside the sandboxed HOME.
    targets = [p for p in Path(WORKDIR).rglob("*.json")] or [Path(db)]
    for t in targets:
        try:
            t.write_text("{ this is not valid json")
        except OSError:
            pass
    rc, out, err = run(listform or ["list"], db)
    if traceback_in(out + err):
        defect("crash-on-corrupt-db", "traceback on malformed JSON storage")

    # ---- 9. the model's own quality gate ---------------------------------
    for name, cmd in (("pytest", ["uv", "run", "pytest", "-q"]),
                      ("ruff", ["uv", "run", "ruff", "check", "."])):
        try:
            p = subprocess.run(cmd, cwd=PROJ, capture_output=True, text=True, timeout=300)
            notes[name] = "pass" if p.returncode == 0 else "FAIL"
            if p.returncode != 0:
                defect(f"{name}-fails", (p.stdout or p.stderr).strip().splitlines()[-1][:160])
        except Exception as e:                              # noqa: BLE001
            notes[name] = f"error: {e}"
            defect(f"{name}-error", str(e)[:120])

    # ---- 10. deliverables -------------------------------------------------
    for label, rel in (("README", "README.md"), ("DESIGN", "docs/DESIGN.md")):
        p = PROJ / rel
        if not p.is_file() or p.stat().st_size == 0:
            defect("missing-doc", f"{rel} absent or empty")
        else:
            notes[f"{label}_lines"] = len(p.read_text().splitlines())
    for rel in ("src/taskcli/core.py", "src/taskcli/storage.py", "src/taskcli/cli.py"):
        if not (PROJ / rel).is_file():
            defect("missing-layer", f"{rel} absent (3-layer split not honoured)")

    if (PROJ / "docs/DESIGN.md").is_file():
        d = (PROJ / "docs/DESIGN.md").read_text().lower()
        if "future" not in d and "extension" not in d:
            defect("missing-future-extensions", "DESIGN.md has no future-extensions section")

    shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps({"project": PROJ.name, "defect_count": len(defects),
                      "defects": defects, "notes": notes}))


if __name__ == "__main__":
    main()
