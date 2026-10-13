#!/bin/bash
# Regenerate pdf/*.pdf from the Markdown guides in the repo root. Run on a machine with kubectl access (k3-node1).
# Uses the cluster's render service (hermes/k8s/render.yaml: headless Chromium, no egress) through the render_docs
# code already in the Hermes gateway image, so nothing extra to install; the render pod only accepts the gateway pod.
# Usage: pdf/build.sh [name ...]      (default: all four; name = Markdown file without .md)
set -euo pipefail
cd "$(dirname "$0")/.."
DOCS=("$@"); [ ${#DOCS[@]} -gt 0 ] || DOCS=(turing-pi-k3s-guide turing-pi-benchmark-guide openclaw-discord benchmark-comparison)
for d in "${DOCS[@]}"; do
  [ -s "$d.md" ] || { echo "no $d.md"; exit 1; }
  kubectl -n hermes exec -i deploy/hermes -c gateway -- env RENDER_URL=http://hermes-render.hermes.svc.cluster.local:8080 \
    RENDER_OUT_DIR=/tmp/pdf-build RENDER_TIMEOUT=180 /opt/hermes/.venv/bin/python -c '
import sys, re, pathlib; sys.path.insert(0, "/opt/geekstyle/local-mcp")
import render_docs as r
md = sys.stdin.read()
# GitHub-isms Python-Markdown needs spelled out: Markdown inside the centered title <div>, 2-space nested TOC lists.
md = re.sub(r"^<div align=\"center\">", "<div align=\"center\" markdown=\"1\">", md, flags=re.M)
md = re.sub(r"^( +)(- \[)", lambda m: m.group(1) * 2 + m.group(2), md, flags=re.M)
msg = r.t_markdown({"markdown": md, "name": sys.argv[1]})
p = pathlib.Path(re.search(r": (/\S+\.pdf)", msg).group(1))
sys.stdout.buffer.write(p.read_bytes()); p.unlink(); print(msg.splitlines()[0], file=sys.stderr)' "$d" < "$d.md" > "pdf/$d.pdf.new"
  head -c5 "pdf/$d.pdf.new" | grep -q '%PDF-' || { echo "$d: not a PDF"; rm -f "pdf/$d.pdf.new"; exit 1; }
  mv "pdf/$d.pdf.new" "pdf/$d.pdf"
done
