"""Make sibling modules importable as flat modules, matching how private_benchmark.py itself
resolves them when run directly (``python scripts/benchmark/private_benchmark.py``)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
