from __future__ import annotations

from profile import ProfileStore
from settings import ISLAND_CENTER


CHARACTERS = {
    "captain": {
        "name": "El Capitán",
        "description": "Equilibrado · atrae recursos",
        "price": 0,
        "health": 100.0,
        "speed": 230.0,
        "damage": 23.0,
        "crit": 0.05,
        "magnet": 1.15,
        "pierce": 0,
        "weapon": "pistol",
    },
    "corsair": {
        "name": "La Corsaria",
        "description": "Rápida · crítica · dagas perforantes",
        "price": 90,
        "health": 75.0,
        "speed": 276.0,
        "damage": 23.0,
        "crit": 0.20,
        "magnet": 1.0,
        "pierce": 1,
        "weapon": "dagger",
    },
    "sailor": {
        "name": "El Viejo Marinero",
        "description": "Resistente · daño de área · repulsión",
        "price": 120,
        "health": 140.0,
        "speed": 207.0,
        "damage": 27.6,
        "crit": 0.05,
        "magnet": 1.0,
        "pierce": 0,
        "weapon": "bomb",
    },
}

WEAPONS = {
    "pistol": {"name": "Pistola de chispa", "price": 0},
    "dagger": {"name": "Dagas arrojadizas", "price": 35},
    "bomb": {"name": "Bombas de pólvora", "price": 35},
    "shell": {"name": "Bumerán de concha", "price": 50},
    "fire": {"name": "Llama de ron", "price": 55},
}


class Player:
    def __init__(self, profile: ProfileStore, map_name: str = "forest") -> None:
        character_id = profile.data.get("selected_character", "captain")
        if character_id not in profile.data.get("unlocked_characters", ["captain"]):
            character_id = "captain"
        character = CHARACTERS[character_id]
        self.character_id = character_id
        self.x = float(ISLAND_CENTER[0])
        self.y = float(ISLAND_CENTER[1])
        self.radius = 18
        self.speed = character["speed"]
        self.max_health = character["health"]
        self.health = self.max_health
        self.damage = character["damage"]
        self.area_multiplier = 1.2 if character_id == "sailor" else 1.0
        self.synergy_used = False
        self.fire_rate = 0.72
        self.projectiles = 1
        self.card_damage_multiplier = 1.0
        self.card_speed = 510.0
        self.card_size = 1.0
        self.card_pierce = 0
        self.card_burn_chance = 0.0
        self.armor = 0.0
        self.healing_multiplier = 1.0
        self.attack_range = 620.0
        self.crit_chance = character["crit"]
        self.magnet_radius = 145.0 * character["magnet"]
        self.regen = 0.0
        self.level = 1
        self.xp = 0
        self.xp_to_next = 6
        self.invulnerable = 0.0
        self.facing = 1
        self.walk_time = 0.0
        self.gender = profile.data["gender"]
        self.hat = profile.data["selected_hat"]
        self.map_name = map_name
        self.weapon_levels = {"dagger": 0, "bomb": 0, "shell": 0, "fire": 0}
        initial_weapon = profile.data.get("selected_weapon", character["weapon"])
        if initial_weapon not in profile.data.get("unlocked_weapons", ["pistol"]):
            initial_weapon = character["weapon"]
        if initial_weapon in self.weapon_levels:
            self.weapon_levels[initial_weapon] = 1
        self.pierce_bonus = character["pierce"]
        self.freeze_chance = 0.0
        self.fire_damage_multiplier = 1.0
        self.dagger_timer = 0.5
        self.bomb_timer = 1.2
        self.shell_angle = 0.0
        self.shell_hit_timers: dict[int, float] = {}
        self.bombs: list[dict] = []
        self.fire_trail: list[dict] = []
        self.fire_timer = 0.0
        self.bloodlust = 0
        self.banked = False
        self.shallow = False
        self.footstep_timer = 0.0
        self.vegetation_timer = 0.0
        self.dash_cooldown = 0.0
        self.dash_remaining = 0.0
        self.dash_direction = (1.0, 0.0)
        self.velocity = (0.0, 0.0)
