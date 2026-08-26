#!/usr/bin/env python3
"""Scan data artifacts (JSON/JSONL/CSV/TSV/text) for float64-widening "vector bloat".

A float32 value carries ~7 significant decimal digits and needs at most 9 to round-trip.
When it is silently promoted to float64 before serialization, the encoder prints up to 17
digits that describe the float32->float64 conversion residue, not the data. This scanner
flags numeric tokens whose significant-digit count is too high to have come from a float32,
which is the tell-tale signature of the bug in an output artifact.

Usage:
    python scan_artifacts.py PATH [PATH ...] [--threshold 15] [--ext .json,.jsonl,.csv]
                                  [--examples 5] [--min-hit-fraction 0.0] [--quiet]

Exit code 1 if any file is flagged (fraction of over-threshold tokens > --min-hit-fraction),
else 0 -- so it can gate CI.

This is a HEURISTIC. A hit means "these numbers have more digits than a float32 can justify."
Confirm the source dtype is really float32/float16 before declaring the bug (genuine float64
data -- physics, finance, geodesy -- legitimately needs 15-17 digits). See references/.
"""
import argparse, os, re, struct, sys

# A JSON/CSV numeric token: optional sign, digits with a fractional part, optional exponent.
# We only care about numbers with a fractional part -- integers never trigger this bug.
NUM = re.compile(r'[-+]?(?:\d+\.\d+|\.\d+)(?:[eE][-+]?\d+)?')
DEFAULT_EXTS = ('.json', '.jsonl', '.ndjson', '.csv', '.tsv', '.txt')
CHUNK = 4 << 20          # 4 MiB
CARRY = 64               # overlap so a token split across chunk boundaries isn't missed


def significant_digits(tok: str) -> int:
    """Count significant decimal digits in a numeric token (ignore sign/exponent/point)."""
    m = tok.lstrip('+-')
    m = re.split('[eE]', m, 1)[0]          # drop exponent
    digits = m.replace('.', '')
    digits = digits.lstrip('0')            # leading zeros are not significant
    digits = digits.rstrip('0')            # trailing zeros are not significant here
    return len(digits)


def float32_shortest(tok: str):
    """Return the shortest float32-faithful rendering, or None if not finite."""
    try:
        x = float(tok)
        x32 = struct.unpack('<f', struct.pack('<f', x))[0]   # round-trip through float32
        return '%.9g' % x32
    except (ValueError, OverflowError, struct.error):
        return None


def scan_stream(fh, threshold, cap_examples):
    total = flagged = 0
    examples = []
    carry = ''
    while True:
        block = fh.read(CHUNK)
        if not block:
            break
        text = carry + block
        # keep the tail so a token straddling the boundary is caught next round
        carry = text[-CARRY:]
        scan_region = text[:-CARRY] if len(text) > CARRY else text
        for m in NUM.finditer(scan_region):
            tok = m.group(0)
            total += 1
            if significant_digits(tok) >= threshold:
                flagged += 1
                if len(examples) < cap_examples:
                    examples.append(tok)
    # final carry
    for m in NUM.finditer(carry):
        tok = m.group(0)
        total += 1
        if significant_digits(tok) >= threshold:
            flagged += 1
            if len(examples) < cap_examples:
                examples.append(tok)
    return total, flagged, examples


def iter_files(paths, exts):
    for p in paths:
        if os.path.isfile(p):
            yield p
        elif os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in sorted(names):
                    if exts is None or n.lower().endswith(exts):
                        yield os.path.join(root, n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--threshold', type=int, default=15,
                    help='min significant digits to flag a token (float32 never needs >9; default 15)')
    ap.add_argument('--ext', default=','.join(DEFAULT_EXTS),
                    help='comma-separated extensions to scan, or "all" for every file')
    ap.add_argument('--examples', type=int, default=5)
    ap.add_argument('--min-hit-fraction', type=float, default=0.0,
                    help='only report/gate files whose flagged fraction exceeds this (default 0)')
    ap.add_argument('--quiet', action='store_true', help='only print flagged files')
    args = ap.parse_args()

    exts = None if args.ext.lower() == 'all' else tuple(
        e if e.startswith('.') else '.' + e for e in args.ext.split(','))

    any_hit = False
    for path in iter_files(args.paths, exts):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                total, flagged, examples = scan_stream(fh, args.threshold, args.examples)
        except (OSError, UnicodeError) as e:
            print(f"skip {path}: {e}", file=sys.stderr)
            continue
        if total == 0:
            if not args.quiet:
                print(f"  ok    {path}: no fractional numbers")
            continue
        frac = flagged / total
        if flagged and frac > args.min_hit_fraction:
            any_hit = True
            print(f"FLAG  {path}: {flagged}/{total} tokens ({frac:.1%}) have >= {args.threshold} sig digits")
            for ex in examples:
                fix = float32_shortest(ex)
                if fix is not None:
                    saved = len(ex) - len(fix)
                    note = f"saves {saved} bytes" if saved > 0 else "no size win -- may be genuine float64"
                    print(f"        {ex}  ->  {fix}   (float32-shortest, {note})")
                else:
                    print(f"        {ex}")
        elif not args.quiet:
            print(f"  ok    {path}: {flagged}/{total} over threshold ({frac:.1%})")

    sys.stdout.flush()
    if any_hit:
        print("\nHits are candidates, not proof. Confirm the source dtype is float32/float16 "
              "(embeddings, tensors, sensor data, quantized weights) before fixing. See references/.",
              file=sys.stderr)
    sys.exit(1 if any_hit else 0)


if __name__ == '__main__':
    main()
