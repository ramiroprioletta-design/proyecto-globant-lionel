from __future__ import annotations

import math
import random

import pygame

from settings import MAX_PARTICLES


class VFXManager:
    def __init__(self, particle_limit: int = MAX_PARTICLES) -> None:
        self.particle_limit = particle_limit
        self.particles: list[dict] = []
        self.pool: list[dict] = []
        self.shake_time = 0.0
        self.shake_duration = 0.0
        self.shake_strength = 0.0
        self.hit_stop = 0.0
        self._last_offset = (0, 0)

    def burst(
        self,
        x: float,
        y: float,
        color: tuple[int, int, int],
        count: int,
        kind: str = "spark",
        speed_range: tuple[float, float] = (35, 155),
        life_range: tuple[float, float] = (0.2, 0.54),
    ) -> None:
        available = min(count, self.particle_limit - len(self.particles))
        for _ in range(max(0, available)):
            angle = random.random() * math.tau
            speed = random.uniform(*speed_range)
            particle = self.pool.pop() if self.pool else {}
            particle.clear()
            particle.update({
                "x": x,
                "y": y,
                "vx": math.cos(angle) * speed,
                "vy": math.sin(angle) * speed,
                "life": random.uniform(*life_range),
                "max_life": life_range[1],
                "color": color,
                "radius": random.uniform(2, 5),
                "kind": kind,
            })
            self.particles.append(particle)

    def update(self, dt: float) -> None:
        index = 0
        while index < len(self.particles):
            particle = self.particles[index]
            particle["x"] += particle["vx"] * dt
            particle["y"] += particle["vy"] * dt
            particle["vx"] *= max(0.0, 1.0 - dt * 1.8)
            particle["vy"] *= max(0.0, 1.0 - dt * 1.8)
            particle["life"] -= dt
            if particle["life"] <= 0:
                self.particles[index] = self.particles[-1]
                self.particles.pop()
                particle.clear()
                if len(self.pool) < self.particle_limit:
                    self.pool.append(particle)
                continue
            index += 1
        self.shake_time = max(0.0, self.shake_time - dt)
        if self.shake_time == 0:
            self.shake_duration = 0.0
            self.shake_strength = 0.0
        self.hit_stop = max(0.0, self.hit_stop - dt)

    def request_shake(self, strength: float, duration: float = 0.09) -> None:
        self.shake_strength = min(3.0, max(self.shake_strength, strength))
        self.shake_duration = min(0.18, max(self.shake_duration, duration))
        self.shake_time = max(self.shake_time, self.shake_duration)

    def request_hit_stop(self, duration: float = 0.045) -> None:
        self.hit_stop = min(0.08, max(self.hit_stop, duration))

    def clear(self) -> None:
        for particle in self.particles:
            particle.clear()
            if len(self.pool) < self.particle_limit:
                self.pool.append(particle)
        self.particles.clear()
        self.shake_time = 0.0
        self.shake_duration = 0.0
        self.shake_strength = 0.0
        self.hit_stop = 0.0

    def camera_offset(self) -> tuple[int, int]:
        if self.shake_time <= 0 or self.shake_duration <= 0:
            self._last_offset = (0, 0)
            return self._last_offset
        strength = self.shake_strength * self.shake_time / self.shake_duration
        phase = pygame.time.get_ticks() * 0.071
        self._last_offset = (
            round(math.sin(phase * 1.7) * strength),
            round(math.cos(phase * 2.3) * strength),
        )
        return self._last_offset

    def draw(self, surface: pygame.Surface, camera: tuple[int, int]) -> None:
        camera_x, camera_y = camera
        width, height = surface.get_size()
        for particle in self.particles:
            x = round(particle["x"] - camera_x)
            y = round(particle["y"] - camera_y)
            if not (-12 <= x <= width + 12 and -12 <= y <= height + 12):
                continue
            fraction = max(0.0, particle["life"] / particle["max_life"])
            radius = max(1, round(particle["radius"] * fraction))
            if particle["kind"] == "shard":
                pygame.draw.line(surface, particle["color"], (x - radius, y + radius), (x + radius, y - radius), max(1, radius // 2))
            elif particle["kind"] == "ember":
                pygame.draw.circle(surface, (255, 206, 119), (x, y), radius + 1)
                pygame.draw.circle(surface, particle["color"], (x, y), radius)
            else:
                pygame.draw.circle(surface, particle["color"], (x, y), radius)
