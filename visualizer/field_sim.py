"""Entry point for the keyboard field simulator."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from field_sim.main_window import run


if __name__ == "__main__":
    raise SystemExit(run())
