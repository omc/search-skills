# The mechanism: why float64 widening creates useless digits

Read this when you need to explain the bug, judge a borderline case, or write up findings.

## One sentence

A `float32` value is promoted to `float64` (or to a language's only float type) *before* it
is serialized to text, so the encoder prints ~17 significant digits that faithfully describe
the 64-bit conversion residue but carry **zero additional real information** — roughly doubling
the payload for no gain.

## Digit budgets (IEEE 754)

| Real dtype | Mantissa bits | Digits to round-trip exactly | Format |
|-----------|---------------|------------------------------|--------|
| bfloat16  | 8  | 4  | `%.4g` |
| float16   | 11 | 5  | `%.5g` |
| float32   | 24 | **9** | `%.9g` |
| float64   | 53 | 17 | `%.17g` / default shortest |

Round-trip digits = `ceil(mantissa_bits × log10(2)) + 1`. float32 needs **9**; float64 needs 17.

## Why casting up manufactures digits

Every float32 is *exactly* representable as a float64, so the cast is lossless. The trap is
"shortest faithful representation" afterward. The float32 nearest `0.1` has exact value
`0.100000001490116119384765625`.

- As a **float32**, the shortest decimal that round-trips it is `0.1` (or 9 digits `0.100000001`).
- As a **float64**, distinguishing it from its float64 neighbours needs `0.10000000149011612`
  (17 digits). Those digits are **correct** (they round-trip the float64) and **meaningless**
  (they encode the position on the float64 grid, which the up-cast chose — not your data).

That paradox — digits that are correct and useless at once — is the whole bug. The fix is to
serialize at the precision of the **real** dtype, never the accidental wider one.

## The bug is at the CAST boundary, not the serializer

> Most serializers do the right thing if you hand them a genuine float32. The damage is done
> when the value is promoted to float64 *before* it reaches the serializer.

- **Python** has no float32 scalar. `tolist()`, `.item()`, `float(x)` all yield a C double.
  `json.dumps` then prints shortest-round-trip-for-float64 = up to 17 digits.
- **JavaScript / Ruby** have *no float32 type at all*. Reading a `Float32Array` element or
  unpacking float32 bytes yields a 64-bit number. `JSON.stringify` / `to_json` widen.
- **Java / C#** have a real `float`, but tutorials routinely declare `double[]` / cast `(double)`,
  opting into the bug.
- **Rust / Go** keep `f32`/`float32` distinct and their JSON encoders print shortest-float32 —
  **safe unless** you write `x as f64` / `float64(x)` or box into `serde_json::Value` / `interface{}`.

Hunting rule: **find the promotion, then check whether serialization happens on the near side
(safe) or the far side (bug) of it.**

## Per-value, data-dependent

Widening is per value. `0.15` widens to `0.15000000596046448`; some values (e.g. a float32
whose shortest float64 repr is already short) don't widen at all. A payload can be a mix. So a
file that is mostly short with a few blown-up numbers is still a hit — scan values, don't assume
uniformity.

## It is NOT a correctness bug

Widened values still round-trip to the identical float32; nothing downstream computes a wrong
answer *because of the digits*. It is a **size / bandwidth / storage / hygiene** bug. Severity
scales with volume: at embedding/vector-DB scale it is ~1.5–2× egress and storage on the numeric
payload. Frame it honestly — that builds trust and sharpens the pitch.

## Worked example (pure python3, no deps)

```python
import json, struct
def as_f32(x): return struct.unpack('f', struct.pack('f', x))[0]
vals = [as_f32(v) for v in [0.1, 0.15, 1/3, 0.123456789, 2/7]]
print("widened:", json.dumps(vals))
print("correct:", "[" + ",".join("%.9g" % x for x in vals) + "]")
# widened: [0.1, 0.15000000596046448, 0.3333333432674408, 0.12345679104328156, 0.2857142984867096]
# correct: [0.100000001,0.150000006,0.333333343,0.123456791,0.285714298]
```
