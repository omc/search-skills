# Embedding providers: where the bug enters, and the escape hatches

Read this when the vectors come from a hosted embedding API. The headline: **the providers'
models are float32 and their native REST wires are mostly clean** — the widening is almost
always reintroduced client-side (SDK `.tolist()`, OpenAI-compatible wrapper shims, or your own
`json.dumps`). Don't blame the vendor; fix the client boundary. And several vendors offer
`int8` / `binary` / `base64` outputs that delete the problem entirely.

## Rule of thumb

- **Model dtype:** always float32 (no one runs float64 embedding inference). "Is the model f64?"
  is always "no."
- **Native REST wire:** where sampled (OpenAI, Cohere, Voyage, Gemini API), emits shortest
  float32 (~7–9 digits). Clean.
- **Where bloat enters:** the client. Same promotion-before-serialization mechanism as everywhere.

## OpenAI

- Model float32. Raw REST `float` format sends ~8-figure decimals (clean).
- **The official Python SDK defaults to requesting base64, then `np.frombuffer(..., dtype="float32").tolist()`** → promotes to float64 in your process. Example: server `0.033652876` → SDK `0.03365287557244301`. If you then `json.dumps` that list, you ship the bloat.
- Fix: format the SDK's list at `%.9g`, or request `encoding_format="float"` and pass through
  the short values without re-widening, or keep base64 bytes as-is.

## Anthropic

- **No first-party embeddings model.** Anthropic officially recommends **Voyage AI**. Treat
  "Anthropic embeddings" as Voyage.

## Voyage (Anthropic's recommended provider)

- `output_dtype`: `float` (default, 32-bit single precision), `int8`, `uint8`, `binary`, `ubinary`.
- `encoding_format: base64` returns raw float32 bytes.
- Native wire `float` sample is ~8 figures (clean). Best-in-class: for storage, request `int8`
  or `binary` and skip float text entirely.

## Cohere

- `embedding_types`: `float` (default), `int8`, `uint8`, `binary`, `ubinary` (v3.0+). Multiple in
  one call. Float sample ~7–8 figures (clean).
- A 1024-d `binary` vector is 128 bytes vs ~11 KB of widened JSON. Prefer it for storage/index.

## Jina

- `embedding_type`: `float` (default), `binary`, `ubinary`, `base64`. Use `binary`/`base64` for
  storage and transmission.

## Google (Gemini API vs Vertex AI)

- Model float32. Gemini Developer API (`generativelanguage.googleapis.com`) wire sample is short
  (~8 figs, clean).
- Vertex AI docs *render* widened (~15–17 digit) sample values, but that is most likely a
  client-rendered doc artifact, not the live wire — **unconfirmed**. If you consume Vertex, scan
  your actual response with `scan_artifacts.py` rather than trusting the doc sample either way.
- Only size lever exposed is `outputDimensionality` (truncation), not a dtype/base64 option.

## AWS Titan (Bedrock)

- Native format `{"embedding": [...], "inputTextTokenCount": n}`. Titan v2 supports `binary`
  output (the float `embedding` field is omitted when only binary is requested).
- OpenAI-compatible **wrapper** shims have been observed emitting ~16-digit values — that's the
  wrapper re-serializing float64, not Bedrock. Scan your real pipeline output.

## Mistral

- JSON float array; digit count and any binary option unverified. Scan the actual output.

## Takeaway for the fix

If the source is a hosted API: (1) confirm where the widening enters with `scan_artifacts.py` on
real output; (2) if it's the SDK, format at `%.9g` or pass short values through; (3) if the
provider offers `int8`/`binary`/`base64`, that is the smallest and cleanest fix — recommend it.
