"""PDK hotswap check: every installed PDK must re-derive the whole design by itself.

    python3 analog/common/hotswap.py [pdk ...]     (default: every installed PDK)

Per PDK, with $PDK set to it:
  1. pdk_specs: no field the code relies on is unset (declared or pdk_char.py-measured)
  2. gmid.py and specs.py self-checks pass (gm/ID tables are characterised on demand)
  3. every analog/<block>/netlist/<block>.py runs and prints a deck that
     - names only this PDK's devices (no other registered PDK's model names), and
     - differs from the other PDKs' decks (sizing actually re-derived)
Exits non-zero on any failure. A block that fails here has a process number or a
device name hard-coded somewhere — find it and route it through get_pdk()/specs.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ANALOG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANALOG / "docs"))
import pdk_specs  # noqa: E402

MODEL_FIELDS = ("nfet", "pfet", "nfet_lvt", "pfet_lvt", "pfet_hvt", "mim_cap", "res_poly",
                "res_poly_lotc")


def run(cmd, pdk_env):
    env = dict(os.environ, PDK=pdk_env)
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ANALOG.parent)


def installed():
    out = []
    for key, variant in (("sky130", "sky130A"), ("gf180mcu", "gf180mcuD"),
                         ("ihp-sg13g2", "ihp-sg13g2")):
        p = pdk_specs.get_pdk(key)
        try:
            if p.lib_path().exists():
                out.append((key, variant))
        except FileNotFoundError:
            pass
    return out


def main():
    want = sys.argv[1:]
    pdks = [(k, v) for k, v in installed() if not want or k in want]
    names = {k: {getattr(pdk_specs.get_pdk(k), f) for f in MODEL_FIELDS} - {""}
             for k in pdk_specs._REGISTRY}
    blocks = sorted(p.parent.parent.name for p in ANALOG.glob("*/netlist/*.py")
                    if p.stem == p.parent.parent.name)
    ok, decks = True, {}
    for key, variant in pdks:
        print(f"\n== {key} ($PDK={variant})")
        p = pdk_specs.get_pdk(key)
        miss = p.missing()
        print(f"  {'PASS' if not miss else 'FAIL'}  pdk_specs fields" + (f"  unset {miss}" if miss else ""))
        ok &= not miss
        for script in ("docs/gmid.py", "docs/specs.py"):
            r = run([sys.executable, str(ANALOG / script)], variant)
            good = r.returncode == 0
            ok &= good
            print(f"  {'PASS' if good else 'FAIL'}  {script}" +
                  ("" if good else "\n" + (r.stdout + r.stderr)[-600:]))
        foreign = set().union(*(v for k, v in names.items() if k != key))
        for b in blocks:
            r = run([sys.executable, str(ANALOG / b / "netlist" / f"{b}.py")], variant)
            if r.returncode:
                ok = False
                print(f"  FAIL  {b}: {(r.stderr or r.stdout).strip().splitlines()[-1]}")
                continue
            tokens = set(re.findall(r"[\w.]+", r.stdout))
            bad = sorted(tokens & foreign)
            decks.setdefault(b, {})[key] = r.stdout
            ok &= not bad
            print(f"  {'PASS' if not bad else 'FAIL'}  {b}" +
                  (f"  foreign device names {bad}" if bad else ""))
    if len(pdks) > 1:
        print("\n== re-derivation (decks must differ between PDKs)")
        for b, d in sorted(decks.items()):
            if len(d) > 1:
                same = len(set(d.values())) < len(d)
                ok &= not same
                print(f"  {'FAIL' if same else 'PASS'}  {b}")
    print(f"\nHOTSWAP: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
