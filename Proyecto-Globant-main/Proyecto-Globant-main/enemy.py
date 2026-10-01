from __future__ import annotations

import random


class Enemy:
    TYPES = {
        "crab": {"radius": 14, "speed": 77, "health": 32, "damage": 7, "color": (220, 104, 81), "xp": 1},
        "pirate": {"radius": 18, "speed": 54, "health": 76, "damage": 12, "color": (175, 123, 83), "xp": 2},
        "sea": {"radius": 24, "speed": 34, "health": 180, "damage": 21, "color": (112, 100, 166), "xp": 3},
        "gull": {"radius": 13, "speed": 125, "health": 27, "damage": 8, "color": (220, 217, 195), "xp": 2},
        "octopus": {"radius": 22, "speed": 27, "health": 112, "damage": 8, "color": (157, 86, 129), "xp": 3},
        "skeleton": {"radius": 16, "speed": 108, "health": 46, "damage": 10, "color": (207, 199, 164), "xp": 2},
        "sand_snake": {"radius": 18, "speed": 102, "health": 66, "damage": 13, "color": (203, 157, 75), "xp": 3},
        "scorpion": {"radius": 24, "speed": 49, "health": 190, "damage": 23, "color": (137, 91, 51), "xp": 4},
        "polar_bear": {"radius": 30, "speed": 54, "health": 245, "damage": 27, "color": (222, 231, 217), "xp": 5},
        "ice_wraith": {"radius": 19, "speed": 48, "health": 96, "damage": 14, "color": (117, 206, 221), "xp": 4},
        "ash_imp": {"radius": 17, "speed": 87, "health": 120, "damage": 21, "color": (191, 79, 54), "xp": 5},
        "fire_wraith": {"radius": 19, "speed": 53, "health": 108, "damage": 18, "color": (240, 115, 54), "xp": 5},
    }

    def __init__(self, kind: str, x: float, y: float, wave: int, map_name: str, elapsed: float = 0.0) -> None:
        self.reset(kind, x, y, wave, map_name, elapsed)

    def reset(
        self,
        kind: str,
        x: float,
        y: float,
        wave: int,
        map_name: str,
        elapsed: float = 0.0,
        elite: bool = False,
    ) -> None:
        stats = self.TYPES[kind]
        difficulty = 1 + min(elapsed, 1800.0) / 900.0
        self.kind = kind
        self.x, self.y = x, y
        self.elite = elite
        self.radius = round(stats["radius"] * (1.3 if elite else 1.0))
        self.speed = stats["speed"] * (1 + min(elapsed, 1800.0) / 2400.0)
        self.max_health = stats["health"] * difficulty * (3 if elite else 1)
        self.health = self.max_health
        self.damage = stats["damage"] * difficulty * (2 if elite else 1)
        self.color = stats["color"]
        self.xp = stats["xp"] * (3 if elite else 1)
        self.attack_timer = 0.0
        self.hit_flash = 0.0
        self.knockback = 0.0
        self.knockback_angle = 0.0
        self.phase = random.random() * 6.283185307179586
        self.slow_timer = 0.0
        self.burn_timer = 0.0
        self.burn_tick = 0.0
        self.burn_damage = 0.0
        self.reaction = max(0.18, 0.8 - elapsed / 2400)
