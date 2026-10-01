from __future__ import annotations

from settings import BIOMES, ISLAND_CENTER


class Boss:
    def __init__(self, map_name: str, wave: int, x: float | None = None, y: float | None = None) -> None:
        self.map_name = map_name
        self.x = float(x if x is not None else ISLAND_CENTER[0] + 430)
        self.y = float(y if y is not None else ISLAND_CENTER[1] - 100)
        self.radius = 78 if map_name == "final" else 70 if map_name != "snow" else 78
        self.max_health = (6000 if map_name == "final" else 1500) + wave * (320 if map_name == "final" else 160)
        self.health = self.max_health
        self.speed = 70 if map_name == "final" else 52
        self.attack_timer = 2.0
        self.attack_index = 0
        self.charge_timer = 0.0
        self.charge_target = (self.x, self.y)
        self.contact_timer = 0.0
        self.hit_flash = 0.0
        self.telegraph = False
        self.name = "El Capitán Fantasma Barbanegra" if map_name == "final" else BIOMES[map_name]["boss"]
        self.color = (73, 75, 113) if map_name == "final" else BIOMES[map_name]["boss_color"]
        self.phase = 1
