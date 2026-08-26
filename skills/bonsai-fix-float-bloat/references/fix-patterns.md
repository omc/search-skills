# Fix patterns, by language

Read this during the Fix step. Pick the highest-preference option that fits; each snippet is a
safe rewrite of the widening path. Match the digit count to the **real** dtype (float32 → 9;
float16 → 5; bfloat16 → 4), never the wider type it was promoted into.

## Order of preference (applies to every language)

1. **Serialize at the real precision** — shortest float32 form (details per language below).
2. **Don't leave binary at all** — if both ends are yours, ship base64 float32 bytes or a binary
   format (Arrow, `.npy`, protobuf `repeated float`, or a vector DB's native binary). Smaller
   *and* exact. Best for internal service-to-service and for vector-DB ingest.
3. **Round-trip-preserving passthrough** — if only relaying already-correct text, stream bytes
   through; don't parse→reserialize. If you must re-encode, ensure upstream is already fixed.
4. **Quantize deliberately** (int8 / float16 / binary) — different trade-off; reduces *real*
   precision. Many embedding APIs offer this natively (see providers.md).

Pitfalls: use `g` (significant digits), never `f` (post-decimal). 9 is the *max* for float32;
don't use 6/7 "because float32 is ~7 digits" — 7 does **not** round-trip and silently corrupts
values (prove it: `verify_roundtrip.py --dtype float32 --digits 7`). Decide a policy for
`NaN`/`Inf` (JSON has no representation).

---

## Python (numpy / torch / tf / jax / pandas)

The promotion is `.tolist()` / `.item()` / `float(x)` — Python has no float32 scalar.

```python
# BUG: torch/numpy float32 -> Python float64 -> 17-digit JSON
vec = feats.float().cpu().tolist()
return JSONResponse(content=vectors)          # each value ~17 sig digits

# FIX 1: format at float32 shortest, bypass the default encoder
def embeddings_response(vectors):
    body = "[" + ",".join(
        "[" + ",".join("%.9g" % x for x in vec) + "]" for vec in vectors
    ) + "]"
    return Response(content=body, media_type="application/json")

# FIX 2 (both ends yours): ship raw float32 bytes as base64 -- smaller AND exact
import base64, numpy as np
b64 = base64.b64encode(np.asarray(vectors, dtype=np.float32).tobytes()).decode()
```

`orjson.dumps(arr, option=orjson.OPT_SERIALIZE_NUMPY)` serializes a numpy **float32** array
directly at float32 precision — but only if you hand it the array, not a `.tolist()`ed float64 list.
pandas upcasts float32 to float64 on many ops; cast the column back (`.astype('float32')`) or
format explicitly before `to_json`/`to_csv`.

## JavaScript / TypeScript

No float32 scalar — any read out of a `Float32Array` is already float64.

```js
// BUG
const vals = Array.from(f32arr);              // float64 number[]
const body = JSON.stringify(vals);            // ~17 digits

// FIX 1: shortest string that still round-trips the float32
const shortestF32 = (x) => {
  for (let p = 1; p <= 9; p++) {
    const s = x.toPrecision(p);
    if (Math.fround(parseFloat(s)) === x) return parseFloat(s).toString();
  }
  return x.toString();
};
const body = "[" + [...f32arr].map(shortestF32).join(",") + "]";

// FIX 2 (both ends yours): keep it binary
const b64 = Buffer.from(f32arr.buffer).toString("base64");
```

## Java

Has a real `float`. The bug is opt-in: `double[]` fields or `(double)` casts. Keep `float[]`.

```java
// BUG: (double) cast + double[] -> Jackson emits shortest-double
double[] v = new double[n];
for (int i = 0; i < n; i++) v[i] = (double) model[i];   // widen

// FIX: keep float[]; Jackson/Gson print shortest-float32 for a real float
float[] v = model;                                       // no cast
mapper.writeValueAsString(v);                            // shortest-float32 per value
```

If you must build strings by hand, use `Float.toString(f)` (shortest-float32), never
`Double.toString((double) f)`.

## C# / .NET

Has `float`/`Single`. Declare `float[]` (or `ReadOnlyMemory<float>`, what the built-in
embedding APIs return), not `double[]`.

```csharp
// BUG
public double[] Embedding { get; set; }
var json = JsonSerializer.Serialize(embedding);          // shortest-double

// FIX
public float[] Embedding { get; set; }
var json = JsonSerializer.Serialize(embedding);          // shortest-float32
```

For binary stores (sqlite-vec, etc.) prefer sending float32 bytes over JSON text entirely.

## Ruby

`Float` is always 64-bit — there is no float32 scalar. Format manually or stay binary.

```ruby
# BUG
JSON.dump(vectors)                             # Float#to_s = shortest-double

# FIX 1: format at float32 shortest
body = "[" + vectors.map { |v| "[" + v.map { |x| format('%.9g', x) }.join(',') + "]" }.join(',') + "]"

# FIX 2: pack raw float32 little-endian and base64 it (both ends yours)
require 'base64'
Base64.strict_encode64(vectors.flatten.pack('e*'))
```

## Go

Safe by default: `encoding/json` prints `[]float32` at shortest-float32. The bug needs an
explicit cast or boxing. Keep the type `[]float32`.

```go
// BUG: cast widens; or boxing into interface{}/map[string]any stores float64
vec64 := make([]float64, len(vec)); for i, x := range vec { vec64[i] = float64(x) }
json.Marshal(vec64)                            // shortest-double

// FIX: keep []float32
json.Marshal(vec)                              // shortest-float32
// or for pgvector etc.: pgvector.NewVector(vec) -- binary, requires []float32
```

If a struct field arrives as `[]float64` from an SDK (OpenAI Go, Bedrock) but the model is
float32, downcast to `[]float32` before persisting to a text sink.

## Rust

Safe by default: serde_json / ryu print `Vec<f32>` at shortest-float32. The bug needs
`x as f64` or boxing into `serde_json::Value`. Keep `Vec<f32>`.

```rust
// BUG
let v64: Vec<f64> = v.iter().map(|&x| x as f64).collect();
serde_json::to_string(&v64)?;                  // shortest-double

// FIX: keep Vec<f32>
serde_json::to_string(&v)?;                    // shortest-float32 (ryu)
```

## C / C++

```c
// BUG
printf("%.17g", (double) f);                   // float64 precision on a float
// FIX
printf("%.9g", (double) f);                    // float32 shortest (cast is fine; the WIDTH is the fix)
```
(The `(double)` cast for varargs is unavoidable in C; the fix is the **precision spec**, `%.9g`.)

---

## Verify every fix

Round-trip is the acceptance test: `parse(serialize(x)) == x` for the **real** dtype across a
fuzz sample (denormals, ±0, near powers of two, 1/3, 0.1). Use:

```
python scripts/verify_roundtrip.py --dtype float32      # proves %.9g is exact + shows size win
```
