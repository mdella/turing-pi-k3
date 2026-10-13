# PDF exports

PDF copies of the guides in the repo root, rebuilt from the Markdown with [`build.sh`](build.sh):

```bash
pdf/build.sh                       # all four
pdf/build.sh turing-pi-k3s-guide   # one
```

It renders through the cluster's render service (`hermes/k8s/render.yaml`, headless Chromium, US Letter) using the
`render_docs` code in the Hermes gateway image, so it needs kubectl access and nothing else installed. Rebuild after
editing a guide and bump its date/version line. Before October 2026 these were Word exports (different styling).
There is no CI job for this; it's a manual step.
