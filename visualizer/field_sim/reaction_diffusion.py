"""Small reaction-diffusion system on keyboard cells."""

from __future__ import annotations

import math
import random

from .models import KeyCell

RDState = tuple[float, float]


class ReactionDiffusion:
    """Gray-Scott-like reaction diffusion over keyboard keys."""

    def __init__(self) -> None:
        self.neighbor_radius = 1.7
        self.wrap = True
        self.diffusion_a = 0.18
        self.diffusion_b = 0.09
        self.feed = 0.044
        self.kill = 0.061
        self.dt = 1.0
        self.noise_rate = 0.03
        self.substeps = 3
        self.injection_strength = 0.55

    def build_neighbors(self, cells: list[KeyCell]) -> list[list[int]]:
        """Build geometry-based neighbors."""
        if not cells:
            return []
        min_x = min(cell.center_x for cell in cells)
        max_x = max(cell.center_x for cell in cells)
        min_y = min(cell.center_y for cell in cells)
        max_y = max(cell.center_y for cell in cells)
        span_x = max(max_x - min_x, 0.1)
        span_y = max(max_y - min_y, 0.1)

        neighbors: list[list[int]] = []
        for i, cell in enumerate(cells):
            current: list[int] = []
            for j, other in enumerate(cells):
                if i == j:
                    continue
                dx = abs(cell.center_x - other.center_x)
                dy = abs(cell.center_y - other.center_y)
                if self.wrap:
                    dx = min(dx, span_x - dx)
                    dy = min(dy, span_y - dy)
                if math.hypot(dx, dy) <= self.neighbor_radius:
                    current.append(j)
            neighbors.append(current)
        return neighbors

    def random_states(self, count: int) -> list[RDState]:
        """Create a seeded state with A dominant and local B blobs."""
        states: list[RDState] = [(1.0, 0.0) for _ in range(count)]
        if count == 0:
            return states

        seed_count = max(2, count // 8)
        for _ in range(seed_count):
            center = random.randrange(count)
            states[center] = (0.15, 0.95)
        return states

    def clear_states(self, count: int) -> list[RDState]:
        """Create a blank state."""
        return [(1.0, 0.0) for _ in range(count)]

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))

    def _inject_burst(self, states: list[RDState], neighbors: list[list[int]]) -> None:
        """Add a small local perturbation so the pattern stays active."""
        if not states or random.random() >= self.noise_rate:
            return

        center = random.randrange(len(states))
        burst_targets = [center] + neighbors[center][: min(3, len(neighbors[center]))]
        for index in burst_targets:
            a, b = states[index]
            states[index] = (
                self._clamp(a - self.injection_strength * 0.45),
                self._clamp(b + self.injection_strength),
            )

    def step(self, states: list[RDState], neighbors: list[list[int]]) -> list[RDState]:
        """Advance one Gray-Scott step."""
        if not states:
            return []

        current = list(states)
        for _ in range(self.substeps):
            self._inject_burst(current, neighbors)
            next_states: list[RDState] = []
            for index, (a, b) in enumerate(current):
                if neighbors[index]:
                    avg_a = sum(current[n][0] for n in neighbors[index]) / len(neighbors[index])
                    avg_b = sum(current[n][1] for n in neighbors[index]) / len(neighbors[index])
                else:
                    avg_a, avg_b = a, b

                lap_a = avg_a - a
                lap_b = avg_b - b
                reaction = a * b * b

                new_a = a + (self.diffusion_a * lap_a - reaction + self.feed * (1.0 - a)) * self.dt
                new_b = b + (self.diffusion_b * lap_b + reaction - (self.kill + self.feed) * b) * self.dt
                next_states.append((self._clamp(new_a), self._clamp(new_b)))
            current = next_states

        return current
