"""Save/load helpers for reaction-diffusion scenes."""

from __future__ import annotations

import json
from pathlib import Path

from .reaction_diffusion import RDState


def save_scene(
    path: str | Path,
    layout_path: str,
    states: list[RDState],
    neighbor_radius: float,
    wrap: bool,
    diffusion_a: float,
    diffusion_b: float,
    feed: float,
    kill: float,
    dt: float,
    noise_rate: float,
) -> None:
    """Save a scene to JSON."""
    data = {
        "layout_path": layout_path,
        "states": [list(state) for state in states],
        "neighbor_radius": neighbor_radius,
        "wrap": wrap,
        "diffusion_a": diffusion_a,
        "diffusion_b": diffusion_b,
        "feed": feed,
        "kill": kill,
        "dt": dt,
        "noise_rate": noise_rate,
    }
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_scene(
    path: str | Path,
) -> tuple[str | None, list[RDState], float | None, bool | None, float | None, float | None, float | None, float | None, float | None, float | None]:
    """Load a scene from JSON."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    states = [tuple(float(x) for x in state[:2]) for state in data.get("states", [])]
    return (
        data.get("layout_path"),
        states,
        float(data["neighbor_radius"]) if "neighbor_radius" in data else None,
        bool(data["wrap"]) if "wrap" in data else None,
        float(data["diffusion_a"]) if "diffusion_a" in data else None,
        float(data["diffusion_b"]) if "diffusion_b" in data else None,
        float(data["feed"]) if "feed" in data else None,
        float(data["kill"]) if "kill" in data else None,
        float(data["dt"]) if "dt" in data else None,
        float(data["noise_rate"]) if "noise_rate" in data else None,
    )
