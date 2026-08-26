---
name: bonsai-fix-float-bloat
description: >-
  Audit a repository for the float32->float64 "vector bloat" serialization bug (a.k.a. the
  17-digit tax) and fix it. This bug promotes float32 values to float64 before they are
  written to text, so JSON/CSV carries ~17 significant digits where 9 suffice -- roughly
  doubling embedding/vector payloads for zero added information. Use this skill whenever the
  user mentions embeddings, embedding/vector storage or serialization, vector search, a vector
  database (pgvector, Qdrant, Milvus, Elasticsearch/OpenSearch, Pinecone, Redis), RAG
  ingestion, ML tensors or model weights being saved to JSON/JSONL/CSV, float32 vs float64,
  .tolist()/Float32Array/np.save, oversized or bloated JSON payloads, or asks to reduce
  embedding bandwidth/egress/storage cost or shrink numeric output. Trigger it proactively even
  if the user does not name the bug -- e.g. "my embeddings JSON is huge", "why is my vector
  export 2x bigger than expected", "audit how we serialize embeddings", or "our OpenAI
  embeddings take too much disk". Also use to explain the bug or vet whether a codebase has it.
---

# Fix Vector Bloat

A `float32` carries ~7 significant decimal digits and needs at most **9** to round-trip. When
it is silently promoted to `float64` before serialization, the encoder prints up to **17**
digits that describe the float32->float64 conversion residue, not the data. The values still
round-trip to the identical float32 — so this is **not a correctness bug**. It is a size,
bandwidth, and storage bug, worth ~1.5–2× the numeric payload, which is real money at
embedding / vector-DB scale. Read `references/mechanism.md` for the full "why."

The single most important idea: **the bug is at the CAST boundary, not usually the serializer.**
A genuine float32 handed to most encoders serializes fine. The damage is done when the value is
promoted to float64 _before_ it reaches the encoder. So the whole job is: find the promotion,
then check whether serialization happens on the far side (bug) or near side (safe) of it.

## Running the bundled scripts

This skill ships three Python scripts (stdlib only — no `pip install` needed) in its own
`scripts/` directory. Invoke them by **absolute path** so they resolve regardless of the current
working directory. Set `VB` to this skill's `scripts/` directory once, then reuse it:

```
# Plugin install: the plugin's install dir is in $CLAUDE_PLUGIN_ROOT
VB="$CLAUDE_PLUGIN_ROOT/skills/fix-vector-bloat/scripts"
# Plain skill install: point VB at wherever this SKILL.md lives, e.g.
#   VB="$HOME/.claude/skills/fix-vector-bloat/scripts"
```

Every `python3 "$VB/..."` command below assumes `VB` is set this way.

## Workflow

Follow these steps in order. Steps 1–3 find it; 4 confirms; 5 fixes; 6 verifies; 7 reports.

### 1. Scope the float sources

Identify every place float data originates and ask whether it is float32-family (float32,
float16, bfloat16) — embeddings, ML tensors/logits, model weights, quantized values, sensor/GPU
readings. If a source is genuinely float64 (physics sim, financial accumulation, geodesy), it is
**out of scope** — 17 digits are legitimate there. Only float32-family sources can bloat.

### 2. Scan output artifacts for the signature

If any serialized output exists (committed sample data, fixtures, `*.json`/`*.jsonl`/`*.csv`
exports, cached embeddings), scan it — this is the fastest confirmation:

```
python3 "$VB/scan_artifacts.py" PATH [PATH ...]
```

It flags numeric tokens with ≥15 significant digits (a float32 never needs >9) and, for each
example, shows the float32-shortest form and the bytes saved. Report the **fraction** of tokens
over threshold plus a couple of examples. A file that is mostly short with a few blown-up values
is still a hit — widening is per-value (see mechanism.md). Exit code 1 = hits found (gates CI).

### 3. Trace the promotion in source

```
python3 "$VB/scan_source.py" PATH [--lang python,js,go,java,csharp,ruby,rust,cpp]
```

This greps the high-signal promotion/serialization patterns per language (`.tolist()`,
`.item()`, `(double)` casts, `Float32Array` + `JSON.stringify`, `float64(...)`, `x as f64`,
`double[]` / `Vec<f64>` / `[]float64` vector fields, JSON sinks, …). **Every hit is a lead, not
a verdict.** For each, trace: is the source float32? does text serialization happen _after_ this
point? Only a "yes" to both is the bug.

Language matters (details in `references/mechanism.md`):

- **Python, JavaScript, Ruby** have no float32 scalar → the promotion is the _default_ the moment
  a value leaves the array/tensor. Highest prior probability of the bug.
- **Java, C#** have a real `float` but code often opts into `double[]` / `(double)` — an
  avoidable, visible cast.
- **Go, Rust** keep a real float32 and their encoders print shortest-float32 → **safe unless** you
  see an explicit `float64(x)` / `x as f64` / boxing into `interface{}` / `serde_json::Value`.

### 4. Confirm before fixing — rule out false positives

Do **not** flag any of these (see mechanism.md §"NOT a correctness bug" and providers.md):

- Data that is genuinely float64 (needs the digits).
- A faithful passthrough that relays already-short values (parse→reserialize of _short_ text does
  not re-widen). Trace to the original float32→float64 promotion; if upstream is already fixed,
  the relay is clean.
- Stale artifacts: if an output file was written in append mode or before a fix, old widened
  lines can sit below new correct ones. Check provenance (when/where each line was produced), not
  just the grep. Re-scan freshly generated output.
- If the source is a hosted embedding API (OpenAI, Cohere, Voyage, Gemini, Bedrock, …), the bug is
  usually reintroduced client-side, not by the provider — read `references/providers.md` before
  attributing it, and prefer a native `int8`/`binary`/`base64` output if offered.

### 5. Fix at the real precision

Apply the highest-preference option that fits, from `references/fix-patterns.md` (per-language
snippets):

1. **Serialize at the real dtype's shortest precision** — float32 → `%.9g` (or the language's
   shortest-float32 formatter). This is lossless and the usual fix at a text boundary.
2. **Skip text entirely** — if both ends are yours, ship base64 float32 bytes or a binary format
   (Arrow / npy / protobuf `repeated float` / vector-DB native binary). Smaller _and_ exact.
3. **Passthrough** — relay already-correct bytes without parse→reserialize.
4. **Quantize deliberately** (int8/float16/binary) if lossy compression is acceptable; many APIs
   offer this natively.

Match the digit count to the **real** dtype: bfloat16→4, float16→5, float32→9, float64→17. Use
`g` (significant digits), never `f`. Never use 6/7 digits for float32 "because it's ~7 digits" —
7 does not round-trip and silently corrupts values.

### 6. Verify the fix round-trips

Round-trip is the acceptance test — `parse(serialize(x)) == x` for the real dtype across an
adversarial sample (denormals, ±0, values near powers of two, 1/3, 0.1):

```
python3 "$VB/verify_roundtrip.py" --dtype float32      # proves %.9g is exact + shows the size win
```

Then re-run `scan_artifacts.py` on freshly generated output to confirm the signature is gone.

### 7. Report

Use this structure:

```
## Vector bloat audit: <repo/path>
**Verdict:** <confirmed | not present | needs a live sample to confirm>

### Evidence
- Artifact scan: <N files flagged; fraction of over-threshold tokens; 1-2 examples with the
  float32-shortest form and bytes saved>
- Source trace: <file:line of the promotion; the float32 source; the serialization sink>

### Impact
- <bytes/value wasted> x <dims> x <vectors> ≈ <GB> per copy, per hop. (~8 wasted bytes/value is
  the rule of thumb; ~1.5–2x the numeric payload.)

### Fix applied / recommended
- <the change, per fix-patterns.md> — <lossless %.9g | binary | quantized>

### Verification
- verify_roundtrip: PASS at %.9g. Re-scan of new output: clean.

### Caveats
- <false positives ruled out; anything needing a live sample; genuine-float64 exclusions>
```

Keep the framing honest: it is a cost/size bug, not corruption. That builds trust.

## Bundled resources

- `scripts/scan_artifacts.py` — scan JSON/JSONL/CSV/text for ≥15-sig-digit tokens (the artifact signature). Exit 1 on hits.
- `scripts/scan_source.py` — grep source for the float32→float64 promotion patterns, per language.
- `scripts/verify_roundtrip.py` — prove a chosen precision round-trips a dtype (and show the size win).
- `references/mechanism.md` — the full "why," digit budgets, worked example, false-positive rules.
- `references/fix-patterns.md` — per-language safe rewrites (Python, JS/TS, Java, C#, Ruby, Go, Rust, C/C++).
- `references/providers.md` — where the bug enters per embedding provider, and native int8/binary/base64 escape hatches.
