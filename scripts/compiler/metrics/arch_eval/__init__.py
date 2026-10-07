"""Architecture evaluator: design JSON -> the four ARCH_METRIC numbers. See README.md."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
for _p in (ROOT / "scripts", ROOT / "scripts/compiler/metrics"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
