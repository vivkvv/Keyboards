"""Core data models for the keyboard field simulator."""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class KeyCell:
    """One visible keyboard cell from the loaded layout."""

    source_index: int
    x: float
    y: float
    w: float = 1.0
    h: float = 1.0
    r: float = 0.0

    @property
    def center_x(self) -> float:
        return self.x + self.w / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.h / 2.0


@dataclass
class Particle:
    """One charged particle moving across the keyboard surface."""

    x: float
    y: float
    vx: float
    vy: float
    charge: float
    mass: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Particle":
        return cls(
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            vx=float(data.get("vx", 0.0)),
            vy=float(data.get("vy", 0.0)),
            charge=float(data.get("charge", 1.0)),
            mass=float(data.get("mass", 1.0)),
        )
