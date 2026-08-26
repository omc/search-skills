#!/usr/bin/env python3
"""Scan source code for the float32->float64 promotion that causes "vector bloat".

The bug lives at the CAST boundary, not usually the serializer: a genuine float32 handed
to a serializer is fine; the damage is done when the value is promoted to float64 *before*
serialization. This tool greps for the high-signal promotion/serialization patterns in each
language so you can then check whether serialization happens on the far side (bug) of the
promotion.

Usage:
    python scan_source.py PATH [PATH ...] [--lang python,js,go,...] [--context 0]

Every hit is a LEAD, not a verdict. Trace it: (1) is the source dtype float32/float16?
(2) does serialization to text happen after this promotion? Only then is it the bug.
Languages with a real float32 + type-preserving encoder (Go, Rust) are safe UNLESS you see
an explicit cast/box -- which is exactly what the Go/Rust patterns below look for.
"""
import argparse, os, re, sys

# Each pattern: (compiled regex, short why-it-matters note). Kept deliberately high-signal.
PATTERNS = {
    'python': [
        (r'\.tolist\(\)', 'numpy/torch float32 array -> Python float (float64) list'),
        (r'\.item\(\)', 'tensor/array scalar -> Python float (float64)'),
        (r'\.astype\(\s*(?:np\.)?float(?:64|_)?\s*\)|\.astype\(\s*[\'"]float64[\'"]\s*\)', 'explicit upcast to float64 before dump'),
        (r'\bfloat\(\s*\w+\[', 'float() on an array element widens it'),
        (r'\.to_json\(|\.to_csv\(', 'pandas export; float32 columns get upcast on many ops'),
        (r'json\.dumps?\(|orjson\.dumps\(|ujson\.dumps\(', 'JSON sink -- check the value handed to it is not float64-promoted'),
    ],
    'js': [
        (r'new\s+Float32Array', 'JS has no float32 scalar; any read out is already float64'),
        (r'Array\.from\(\s*\w*[fF]loat32|\[\s*\.\.\.\s*\w*[fF]loat32', 'spreading a Float32Array -> float64 number[]'),
        (r'JSON\.stringify\(', 'JSON sink -- if fed values read from a Float32Array they are widened'),
        (r'\.map\(', 'map over a typed array yields plain float64 numbers -- check the source'),
    ],
    'java': [
        (r'\(\s*double\s*\)', 'explicit (double) cast widens a float'),
        (r'\bdouble\[\]\s*\w*(?:embed|vector|vec|feat)', 'double[] holding embedding/vector data -- should be float[]'),
        (r'List<Double>', 'boxed Double list -- Jackson emits shortest-double, not shortest-float'),
        (r'writeValue|ObjectMapper|new\s+Gson\(\)|toJson\(', 'JSON sink -- check the field type is float[], not double[]'),
    ],
    'csharp': [
        (r'\bdouble\[\]\s*\w*(?:[Ee]mbed|[Vv]ector|[Vv]ec|[Ff]eat)', 'double[] holding vector data -- should be float[]'),
        (r'\(\s*double\s*\)', 'explicit (double) cast widens a float'),
        (r'JsonSerializer\.Serialize|Newtonsoft', 'JSON sink -- check the array is float[], not double[]'),
    ],
    'ruby': [
        (r'\.unpack1?\(\s*[\'"][ef]\*?[\'"]', 'unpacking float32 bytes -> Ruby Float (64-bit)'),
        (r'\.to_json\b|JSON\.(?:dump|generate)\(', 'JSON sink -- Ruby Float is always 64-bit; format manually to avoid widening'),
    ],
    'go': [
        (r'\bfloat64\(', 'explicit widening cast before serialization'),
        (r'\[\]float64\b', '[]float64 field -- if fed by a float32 model this widens on marshal'),
        (r'interface\{\}\s*=\s*\w*(?:[Ee]mbed|[Vv]ec)|map\[string\]interface\{\}', 'boxing into interface{} stores/marshals as float64'),
    ],
    'rust': [
        (r'\bas\s+f64\b', 'explicit widening cast before serde'),
        (r'Vec<f64>\s*\w*(?:embed|vec|feat)', 'Vec<f64> holding vector data -- should be Vec<f32>'),
        (r'Value::from\(\s*\w*\s*(?:as\s+f64)?\)|\.into\(\)', 'boxing an f32 into serde_json::Value stores it as f64'),
    ],
    'cpp': [
        (r'\(\s*double\s*\)|static_cast<\s*double\s*>', 'explicit widening cast'),
        (r'%\.1[0-9]g|%\.17g|std::setprecision\(\s*1[0-9]\s*\)', 'printing at float64 precision'),
    ],
}

EXT_LANG = {
    '.py': 'python',
    '.js': 'js', '.mjs': 'js', '.cjs': 'js', '.ts': 'js', '.tsx': 'js', '.jsx': 'js',
    '.java': 'java',
    '.cs': 'csharp',
    '.rb': 'ruby',
    '.go': 'go',
    '.rs': 'rust',
    '.c': 'cpp', '.cc': 'cpp', '.cpp': 'cpp', '.cxx': 'cpp', '.h': 'cpp', '.hpp': 'cpp',
}
SKIP_DIRS = {'.git', 'node_modules', 'vendor', 'target', 'dist', 'build', '__pycache__', '.venv', 'venv'}


def compile_patterns():
    return {lang: [(re.compile(rx), note) for rx, note in pats] for lang, pats in PATTERNS.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--lang', default='', help='restrict to comma-separated langs: ' + ','.join(PATTERNS))
    ap.add_argument('--context', type=int, default=0, help='lines of context to print around a hit')
    args = ap.parse_args()

    only = set(l.strip() for l in args.lang.split(',') if l.strip())
    compiled = compile_patterns()

    files = []
    for p in args.paths:
        if os.path.isfile(p):
            files.append(p)
        elif os.path.isdir(p):
            for root, dirs, names in os.walk(p):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for n in sorted(names):
                    if os.path.splitext(n)[1].lower() in EXT_LANG:
                        files.append(os.path.join(root, n))

    total_hits = 0
    for path in files:
        lang = EXT_LANG.get(os.path.splitext(path)[1].lower())
        if not lang or (only and lang not in only):
            continue
        try:
            lines = open(path, 'r', encoding='utf-8', errors='replace').read().splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            if line.lstrip().startswith(('#', '//', '*')):   # skip obvious comments
                continue
            for rx, note in compiled[lang]:
                if rx.search(line):
                    total_hits += 1
                    print(f"{path}:{i+1}: [{lang}] {line.strip()[:120]}")
                    print(f"    -> {note}")
                    for c in range(1, args.context + 1):
                        if i + c < len(lines):
                            print(f"    {i+1+c}: {lines[i+c].strip()[:120]}")
                    break   # one hit per line is enough

    print(f"\n{total_hits} lead(s). Each is a place to CHECK, not a confirmed bug.", file=sys.stderr)
    print("Trace each: is the source float32? does text serialization happen after this point? "
          "See references/fix-patterns.md for the safe rewrite per language.", file=sys.stderr)
    sys.exit(1 if total_hits else 0)


if __name__ == '__main__':
    main()
