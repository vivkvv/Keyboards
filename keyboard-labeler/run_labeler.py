"""Quick launcher for key labeler PySide app."""
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.dirname(__file__))

from src.app.bootstrap import run_app


def resolve_checkpoint() -> str:
    env_checkpoint = os.environ.get("SAM_CHECKPOINT", "").strip()
    if not env_checkpoint:
        raise RuntimeError("SAM_CHECKPOINT environment variable is not set")

    env_path = Path(env_checkpoint)
    if not env_path.exists():
        raise RuntimeError(f"SAM checkpoint not found: {env_path}")

    return str(env_path)


if __name__ == "__main__":
    image_path = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(run_app(resolve_checkpoint(), image_path))
