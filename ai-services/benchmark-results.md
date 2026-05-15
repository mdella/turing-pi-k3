# AI Services Benchmark — ARM64 / RK3588

## Hardware

| Detail | Value |
|---|---|
| Board | Turing Pi 2.5 |
| Compute | 4× RK1 (RK3588) — 4× Cortex-A76 + 4× Cortex-A55 per node |
| RAM | 16 GB LPDDR4x per node (64 GB total) |
| Storage | 1 TB NVMe per node |
| Network | 1 Gbps backplane |
| OS | Ubuntu 24.04 LTS (ARM64) |

## Services Under Test

| Service | Node | Role |
|---|---|---|
| LibreTranslate | k3-node2 | Translation API (Argos Translate / OPUS-MT models) |
| Ollama (direct) | k3-node4 | LLM inference (CPU), port 11434 |
| LiteLLM (proxy) | k3-node3 | OpenAI-compatible proxy, port 4000 |
| RKLLaMA (NPU) | k3-node4 | NPU-accelerated LLM inference, port 8080 |

**Models loaded:**
- Translation: `en`, `es`, `fr`, `de`, `zh` (8 directional OPUS-MT packages, ~2.4 GB total)
- Coding (CPU): `qwen2.5-coder:3b` Q4_K_M (~1.9 GB on disk, ~4 GB RAM when loaded)
- Coding (NPU): `Qwen2.5-3B-Coder-Instruct` W8A8 RKLLM (~3.5 GB on disk, 3–5 GB RAM)

## Methodology

### How to run

```bash
# Deploy benchmark job (delete old run first if re-running)
kubectl delete job llm-benchmark -n ai-services --ignore-not-found
kubectl apply -f ai-services/benchmark.yaml

# Stream results
kubectl logs -n ai-services job/llm-benchmark -f
```

### Translation benchmark

- **Tool:** HTTP POST to LibreTranslate `/translate` endpoint
- **Repetitions:** 5 per measurement
- **Text lengths:**
  - Short: 1 sentence (~60 chars)
  - Medium: 1 paragraph (~230 chars)
  - Long: 3 paragraphs (~730 chars)
- **Language pairs:** en→es, en→fr, en→de, en→zh
- **Metrics reported:** p50 latency, p95 latency, chars/sec throughput at p50

### Coding inference benchmark

- **Model:** `qwen2.5-coder:3b` via both Ollama direct API and LiteLLM proxy
- **Repetitions:** 3 per measurement
- **Prompt types:**
  - Simple: Fibonacci with memoization (~50 token response expected)
  - Medium: Binary search with type hints (~100 tokens)
  - Complex: Thread-safe LRU cache (~200 tokens)
- **Metrics reported:**
  - Tokens/sec (Ollama: from `eval_duration`; LiteLLM: wall-clock / completion_tokens)
  - Time to first token / TTFT (Ollama only: `prompt_eval_duration + load_duration`)
  - Total wall-clock time
  - Average completion tokens

### Notes on measurement

- All requests are made from a pod inside the cluster over ClusterIP — no ingress overhead
- Ollama's `eval_duration` excludes model load time; `load_duration` is reported separately as part of TTFT
- LiteLLM TTFT is not measurable without streaming; n/a is shown
- First rep of each coding prompt may be slower if the model was unloaded (OLLAMA_KEEP_ALIVE=5m)

---

## Results

### Translation Latency

*Run date: 2026-05-14*

```
==================================================================
  LIBRETRANSLATE — Translation Latency
==================================================================
  Reps: 5  |  Languages: en→es, en→fr, en→de, en→zh
  Text lengths: short (59 chars)  medium (277 chars)  long (729 chars)

                           en→es         en→fr         en→de         en→zh
--------------------------------------------------------------------------
  short p50                25 ms          9 ms          9 ms          8 ms
  short p95              1022 ms       1157 ms       1159 ms       1360 ms

  medium p50                9 ms          9 ms         10 ms         10 ms
  medium p95             3185 ms         10 ms         11 ms         16 ms

  long p50                 10 ms          7 ms         19 ms         10 ms
  long p95                 11 ms          9 ms       8579 ms       7832 ms


  Throughput (chars/sec at p50, en→es):
    short     2364 chars/s
    medium    31196 chars/s
    long      76725 chars/s
```

**Translation notes:**
- p50 latency is remarkably fast (7–25 ms) — OPUS-MT models fit entirely in RAM after the first load
- p95 spikes (up to 8.5 s) are caused by Argos Translate lazy-loading each language-pair model on its first request per session; subsequent requests are served from RAM
- The spike pattern is inconsistent across pairs (en→es spikes on medium, en→de/zh spike on long) because 5 × 3 = 15 warm-up requests happen in order — whichever pair gets its first request late in the sequence hits a cold model
- **Mitigation:** send one warm-up request per language pair at pod startup; p95 would drop to match p50

### Coding Inference

*Run date: 2026-05-14*

```
==================================================================
  OLLAMA / LITELLM — Coding Inference
==================================================================
  Model: qwen2.5-coder:3b  |  Reps: 3
  Endpoints: Ollama direct (port 11434) vs LiteLLM proxy (port 4000)

  Prompt      Endpoint           Tok/s        TTFT     Total   Tokens
  -------------------------------------------------------------------
  simple      ollama              6.6    2815 ms   56.6 s      354
  simple      litellm             5.9         n/a   55.5 s      329
  medium      ollama              5.7    1326 ms   95.6 s      533
  medium      litellm             5.5         n/a   90.2 s      497
  complex     ollama              5.6    1513 ms  104.2 s      572
  complex     litellm             5.4         n/a  109.0 s      593
```

**Coding inference notes:**
- Throughput is consistent at **5.4–6.6 tok/s** across all prompt types — CPU-bound on RK3588 A76 cores
- LiteLLM proxy overhead is **3–5%** vs Ollama direct — negligible for interactive use
- TTFT of 1.3–2.8 s is driven by prompt evaluation time; the model was already loaded (warm) for all runs
- Total generation times of 55–104 s reflect the model's verbosity (329–593 tokens per response) more than raw speed — responses could be shortened with a `max_tokens` cap
- TTFT is not measurable via the LiteLLM proxy without streaming; stream the `/v1/chat/completions` endpoint with `stream: true` to observe it

### NPU Inference (RKLLaMA)

*Run date: 2026-05-15*

```
==================================================================
  RKLLAMA — NPU Coding Inference
==================================================================
  Model: Qwen2.5-3B-Coder-Instruct (W8A8 RKLLM)
  Runtime: RKLLM v1.2.3, driver v0.9.7, npu_core_num: 3
  Hardware: RK3588 NPU (6 TOPS INT8), 3 cores active

  Inference   Tokens   Wall-clock   Tok/s
  ----------------------------------------
  short         47       11.8 s      3.97
  medium        385      91.2 s      4.22
  short (2)     9         2.7 s      3.37
  Average                            ~4.1
```

**NPU inference notes:**
- All 3 NPU cores active (confirmed via RKLLM runtime log: `npu_core_num: 3`)
- NPU throughput (~4.1 tok/s) is **28% slower** than CPU/Ollama (5.7 tok/s)
- The W8A8 model is 3.5 GB vs Q4_K_M at 1.9 GB — the NPU path is LPDDR5 memory-bandwidth
  limited despite using dedicated INT8 hardware; llama.cpp's Q4 packs 2× more weights per byte
- RKLLaMA `main` branch has a request-queue isolation bug: responses from one in-progress
  generation can be returned to a subsequent queued request (confirmed via testing)
- RKLLM driver v0.9.8 is recommended upstream; v0.9.7 is the newest available from the
  `ppa:jjriek/rockchip` kernel package. A kernel update may improve performance.
- Net verdict: NPU path works but does not outperform CPU for this model/quantization combo.
  A W4A4 or smaller model with RKLLM-native quantization would be needed to beat CPU throughput.

### Summary

| Metric | Value |
|---|---|
| Translation p50 (en→es, medium) | 9 ms |
| Translation throughput (en→es, medium, p50) | 31,196 chars/s |
| Translation p95 cold-model spike | up to 8,579 ms (warm-up mitigates) |
| Coding tok/s — Ollama direct (CPU, medium) | 5.7 tok/s |
| Coding tok/s — LiteLLM proxy (CPU, medium) | 5.5 tok/s |
| Coding tok/s — RKLLaMA NPU (W8A8, average) | ~4.1 tok/s |
| NPU vs CPU delta | −28% (bandwidth-limited) |
| LiteLLM proxy overhead | ~3–5% |
| TTFT — Ollama direct (medium prompt) | 1,326 ms |
| TTFT — LiteLLM proxy | n/a (requires streaming) |
