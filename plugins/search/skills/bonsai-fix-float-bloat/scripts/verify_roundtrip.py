#!/usr/bin/env python3
"""Verify that a serialization precision round-trips a given dtype -- the Verify step of a fix.

The fix for vector bloat is to serialize at the REAL dtype's shortest round-trip precision:
bfloat16->4, float16->5, float32->9, float64->17 significant digits (the "%.Ng" width).
Using FEWER digits than that silently corrupts some values; using more is the bug. This tool
proves a chosen width is exactly right for the dtype across an adversarial sample -- denormals,
+/-0, values near powers of two, 1/3, 0.1 -- so a fix can be signed off with evidence.

Usage:
    python verify_roundtrip.py --dtype float32              # prove %.9g round-trips, show sizes
    python verify_roundtrip.py --dtype float32 --digits 7   # show that 7 digits is NOT enough
    python verify_roundtrip.py --dtype float16
"""
import argparse, struct, sys

DTYPE = {
    # name: (shortest round-trip sig digits, pack/unpack fn producing the real-dtype value)
    'bfloat16': 4,
    'float16': 5,
    'float32': 9,
    'float64': 17,
}


def to_float32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def to_float16(x):
    try:
        return struct.unpack('<e', struct.pack('<e', x))[0]
    except (OverflowError, struct.error):
        return None


def to_bfloat16(x):
    # bf16 = top 16 bits of float32 (round-to-nearest-even, simplified truncation-with-round)
    b = struct.unpack('<I', struct.pack('<f', to_float32(x)))[0]
    r = (b + 0x7FFF + ((b >> 16) & 1)) & 0xFFFF0000
    return struct.unpack('<f', struct.pack('<I', r))[0]


CAST = {'float32': to_float32, 'float16': to_float16, 'bfloat16': to_bfloat16, 'float64': float}


def sample_values(dtype):
    raw = [0.0, -0.0, 1.0, -1.0, 0.1, 0.15, 1/3, 2/7, 0.123456789,
           1.9999999, 2.0000002, 65504.0 if dtype == 'float16' else 3.4e38,
           1e-7, 1.5e-5, 0.0019082502, 0.8433808, 123456.78, 9.999999]
    cast = CAST[dtype]
    out = []
    for v in raw:
        c = cast(v)
        if c is not None:
            out.append(c)
    # a few denormals / tiny values
    for e in (-38, -40, -44):
        c = cast(10.0 ** e)
        if c is not None and c != 0.0:
            out.append(c)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dtype', choices=list(DTYPE), default='float32')
    ap.add_argument('--digits', type=int, default=None,
                    help='override the digit width to test (default = correct width for dtype)')
    args = ap.parse_args()

    correct = DTYPE[args.dtype]
    digits = args.digits if args.digits is not None else correct
    cast = CAST[args.dtype]

    vals = sample_values(args.dtype)
    fmt = f'%.{digits}g'
    widened_fmt = '%.17g'   # what the buggy path emits (float64 shortest-ish)

    fails = []
    short_bytes = wide_bytes = 0
    for v in vals:
        s = fmt % v
        short_bytes += len(s)
        wide_bytes += len(widened_fmt % float(v))
        # does the string round-trip back to the SAME real-dtype value?
        back = cast(float(s))
        if back != v and not (v != v and back != back):   # allow NaN==NaN
            fails.append((v, s, back))

    print(f"dtype={args.dtype}  testing width={fmt!r}  (correct width = %.{correct}g)")
    print(f"sample size: {len(vals)} adversarial values")
    if fails:
        print(f"\nFAIL: {len(fails)} value(s) do NOT round-trip at {digits} digits:")
        for v, s, back in fails[:10]:
            print(f"    {v!r:24} --{fmt}--> {s:16} --parse--> {back!r}   (changed!)")
        print(f"\n{digits} digits is too few for {args.dtype}. Use %.{correct}g.")
        sys.exit(1)

    print(f"\nPASS: all {len(vals)} values round-trip exactly at {digits} digits.")
    print(f"size on this sample:  {fmt}={short_bytes} bytes   vs   %.17g(widened)={wide_bytes} bytes "
          f"({wide_bytes/short_bytes:.2f}x)")
    if args.digits is not None and digits > correct:
        print(f"NOTE: {digits} > {correct}: round-trips, but you are printing more digits than "
              f"{args.dtype} needs -- that is the bloat. Use %.{correct}g.")
    sys.exit(0)


if __name__ == '__main__':
    main()
