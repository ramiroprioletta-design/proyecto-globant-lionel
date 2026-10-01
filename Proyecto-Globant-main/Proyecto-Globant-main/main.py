from __future__ import annotations

import math
import random
import sys
from collections import OrderedDict
from pathlib import Path

import pygame
from pygame.math import Vector2

from boss import Boss
from enemy import Enemy
from profile import HATS, ProfileStore
from game_state import GameStateManager
from player import CHARACTERS, WEAPONS, Player
from settings import (
    BIOMES,
    COLORS,
    FIXED_DT,
    FPS,
    HAT_ORDER,
    HEIGHT,
    ISLAND_CENTER,
    MAX_ENEMIES,
    MAX_ORBS,
    MAX_PARTICLES,
    MAX_PROJECTILES,
    UPGRADES,
    WIDTH,
    WORLD_HEIGHT,
    WORLD_WIDTH,
)
from world import biome_at as world_biome_at, biome_weights, clip_polygon_to_rect, coastline, keep_inside, world_contains
from ui import UPGRADE_RARITIES, choose_rarity
from vfx import VFXManager

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def format_time(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def distance_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    segment_x, segment_y = end[0] - start[0], end[1] - start[1]
    length_squared = segment_x * segment_x + segment_y * segment_y
    if length_squared == 0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    projection = clamp(
        ((point[0] - start[0]) * segment_x + (point[1] - start[1]) * segment_y) / length_squared,
        0,
        1,
    )
    closest = (start[0] + projection * segment_x, start[1] + projection * segment_y)
    return math.hypot(point[0] - closest[0], point[1] - closest[1])


class Audio:
    """Loads optional audio files from assets/audio; the game remains silent if absent."""

    def __init__(self) -> None:
        self.master = 0.7
        self.effects_volume = 0.75
        self.music_volume = 0.35
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self.enabled = False
        self.music_loaded = False
        audio_dir = Path(__file__).parent / "assets" / "audio"
        try:
            pygame.mixer.init()
            self.enabled = True
        except pygame.error as error:
            print(f"Audio desactivado: {error}", file=sys.stderr)
            return

        for name in ("shot", "damage", "enemy", "level", "game_over"):
            path = audio_dir / f"{name}.ogg"
            if path.is_file():
                try:
                    self.sounds[name] = pygame.mixer.Sound(path)
                except pygame.error as error:
                    print(f"No se pudo cargar {path.name}: {error}", file=sys.stderr)

        music_path = audio_dir / "music.ogg"
        if music_path.is_file():
            try:
                pygame.mixer.music.load(music_path)
                self.music_loaded = True
            except pygame.error as error:
                print(f"No se pudo cargar {music_path.name}: {error}", file=sys.stderr)

    def play(self, name: str) -> None:
        sound = self.sounds.get(name)
        if not self.enabled or sound is None:
            return
        sound.set_volume(self.master * self.effects_volume)
        sound.play()

    def start_music(self) -> None:
        if self.enabled and self.music_loaded and not pygame.mixer.music.get_busy():
            try:
                pygame.mixer.music.play(-1)
            except pygame.error as error:
                print(f"No se pudo iniciar la música: {error}", file=sys.stderr)
        self.apply_volumes()

    def apply_volumes(self) -> None:
        if self.enabled:
            pygame.mixer.music.set_volume(self.master * self.music_volume)


class Chest:
    def __init__(self, x: float, y: float, kind: str = "chest") -> None:
        self.x, self.y = x, y
        self.radius = 21
        self.kind = kind
        self.max_health = 45.0 if kind == "barrel" else 90.0
        self.health = self.max_health
        self.hit_flash = 0.0


class Game:
    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption("NÁUFRAGO | Supervivencia en la isla")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.accumulator = 0.0
        self.fonts = {
            "title": pygame.font.SysFont("georgia", 82, bold=True),
            "heading": pygame.font.SysFont("georgia", 42),
            "body": pygame.font.SysFont("trebuchetms", 20),
            "small": pygame.font.SysFont("arial", 15),
            "mono": pygame.font.SysFont("consolas", 14, bold=True),
        }
        self.audio = Audio()
        self.profile = ProfileStore()
        self.state_manager = GameStateManager("menu")
        self.previous_state = "menu"
        self.player: Player | None = None
        self.enemies: list[Enemy] = []
        self.shots: list[dict] = []
        self.hostile_shots: list[dict] = []
        self.orbs: list[dict] = []
        self.orb_pool: list[dict] = []
        self.vfx = VFXManager()
        self.particles = self.vfx.particles
        self.chests: list[Chest] = []
        self.hazards: list[dict] = []
        self.boss: Boss | None = None
        self.run_coins = 0
        self.last_run_coins = 0
        self.notice = ""
        self.map_name = "forest"
        self.elapsed = 0.0
        self.wave = 1
        self.wave_time = 0.0
        self.spawn_timer = 0.75
        self.chest_timer = 22.0
        self.attack_timer = 0.3
        self.kills = 0
        self.scenery = self.make_scenery()
        self.shallows = self.make_shallows()
        self.footprints: list[dict] = []
        self.damage_numbers: list[dict] = []
        self.screen_flash = 0.0
        self.pickup_notice = ""
        self.pickup_notice_time = 0.0
        self.hud_health = 1.0
        self.hud_xp = 0.0
        self.choice_rarities: dict[str, tuple[str, tuple[int, int, int]]] = {}
        self.choices: list[tuple] = []
        self.buttons: dict[str, pygame.Rect] = {}
        self.sliders: dict[str, pygame.Rect] = {}
        self.camera = (0, 0)
        self.coastline_points = coastline()
        self.terrain_tiles: OrderedDict[tuple[int, int], pygame.Surface | None] = OrderedDict()
        self.overlay_surfaces: dict[tuple[tuple[int, int], int, tuple[int, int, int]], pygame.Surface] = {}
        self.boss_glows: dict[tuple[int, tuple[int, int, int]], pygame.Surface] = {}
        self.flash_surface = pygame.Surface(self.screen.get_size())
        self.flash_surface.fill((255, 240, 207))
        self.enemy_pool: list[Enemy] = []
        self.projectile_pool: list[dict] = []
        self.defeated_biomes: set[str] = set()
        self.boss_spawned_at: set[str] = set()
        self.sandstorm_timer = 0.0
        self.sandstorm_remaining = 0.0
        self.ice_slow = 0.0
        self.altar: dict | None = None
        self.altar_active = 0.0
        self.altar_cooldown = 45.0
        self.artifacts: set[str] = set()
        self.final_boss_spawned = False
        self.meteor_timer = 5.0
        self.victory = False
        self.running = True
        self.warm_terrain_cache()

    @property
    def screen_state(self) -> str:
        return self.state_manager.state

    @screen_state.setter
    def screen_state(self, value: str) -> None:
        self.state_manager.set(value)

    @staticmethod
    def point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
        x, y = point
        inside = False
        previous = polygon[-1]
        for current in polygon:
            if (current[1] > y) != (previous[1] > y):
                crossing_x = (previous[0] - current[0]) * (y - current[1]) / (previous[1] - current[1]) + current[0]
                if x < crossing_x:
                    inside = not inside
            previous = current
        return inside

    def make_shallows(self) -> list[list[tuple[float, float]]]:
        return [
            [
                (ISLAND_CENTER[0] - 1000, ISLAND_CENTER[1] - 620),
                (ISLAND_CENTER[0] - 570, ISLAND_CENTER[1] - 740),
                (ISLAND_CENTER[0] - 200, ISLAND_CENTER[1] - 695),
                (ISLAND_CENTER[0] - 410, ISLAND_CENTER[1] - 500),
            ],
            [
                (ISLAND_CENTER[0] + 550, ISLAND_CENTER[1] + 520),
                (ISLAND_CENTER[0] + 1060, ISLAND_CENTER[1] + 480),
                (ISLAND_CENTER[0] + 900, ISLAND_CENTER[1] + 700),
                (ISLAND_CENTER[0] + 430, ISLAND_CENTER[1] + 690),
            ],
        ]

    @staticmethod
    def biome_at(x: float, y: float = float(ISLAND_CENTER[1])) -> str:
        return world_biome_at(x, y)

    def make_scenery(self) -> list[dict]:
        rng = random.Random(92741)
        items = []
        biome_kinds = {
            "forest": (("palm", "rock", "bush", "shell", "barrel", "wreck"), (0.34, 0.16, 0.26, 0.12, 0.06, 0.06)),
            "desert": (("cactus", "rock", "ruin", "shell", "barrel"), (0.32, 0.22, 0.25, 0.15, 0.06)),
            "snow": (("pine", "ice_rock", "ice_ruin", "snow_bush"), (0.35, 0.28, 0.2, 0.17)),
            "volcano": (("rock", "torch", "stalactite", "puddle"), (0.36, 0.24, 0.22, 0.14)),
        }
        for _ in range(720):
            x = rng.uniform(70, WORLD_WIDTH - 70)
            y = rng.uniform(70, WORLD_HEIGHT - 70)
            if not world_contains(x, y):
                continue
            weights_by_biome = biome_weights(x, y)
            biome = rng.choices(tuple(biome_kinds), weights=[weights_by_biome[name] for name in biome_kinds])[0]
            kinds, weights = biome_kinds[biome]
            items.append({
                "x": x,
                "y": y,
                "kind": rng.choices(kinds, weights)[0],
                "scale": rng.uniform(0.75, 1.45),
                "rotation": rng.random() * math.tau,
                "phase": rng.random() * math.tau,
                "leaf_timer": 0.0,
            })
        items.append({"x": ISLAND_CENTER[0] - 120, "y": ISLAND_CENTER[1] + 300, "kind": "wreck", "scale": 1.4, "rotation": -0.32, "phase": 0, "leaf_timer": 0})
        for index in range(32):
            items.append({
                "x": rng.uniform(ISLAND_CENTER[0] - 540, ISLAND_CENTER[0] + 540),
                "y": rng.uniform(80, ISLAND_CENTER[1] - 760),
                "kind": "lava_crack" if index % 2 else "ash",
                "scale": rng.uniform(0.8, 1.7),
                "rotation": rng.random() * math.tau,
                "phase": rng.random() * math.tau,
                "leaf_timer": 0.0,
            })
        items.sort(key=lambda item: item["y"])
        self.reactive_bushes = [item for item in items if item["kind"] == "bush"]
        return items

    def start_game(self) -> None:
        self.map_name = "forest"
        self.scenery = self.make_scenery()
        self.player = Player(self.profile, self.map_name)
        self.enemy_pool.extend(self.enemies[:max(0, 180 - len(self.enemy_pool))])
        for projectile in self.shots + self.hostile_shots:
            self.recycle_projectile(projectile)
        self.enemies.clear()
        self.shots.clear()
        self.hostile_shots.clear()
        for orb in self.orbs:
            self.recycle_orb(orb)
        self.orbs.clear()
        self.vfx.clear()
        self.chests.clear()
        self.chests.extend(
            Chest(item["x"], item["y"], kind="barrel")
            for item in self.scenery
            if item["kind"] == "barrel"
        )
        self.hazards.clear()
        self.boss = None
        self.altar = None
        self.altar_active = 0.0
        self.altar_cooldown = 45.0
        self.artifacts.clear()
        self.final_boss_spawned = False
        self.meteor_timer = 5.0
        self.victory = False
        self.elapsed = 0.0
        self.wave = 1
        self.wave_time = 0.0
        self.spawn_timer = 0.75
        self.chest_timer = 22.0
        self.attack_timer = 0.3
        self.kills = 0
        self.run_coins = 0
        self.notice = ""
        self.footprints.clear()
        self.damage_numbers.clear()
        self.pickup_notice = ""
        self.pickup_notice_time = 0.0
        self.hud_health = 1.0
        self.hud_xp = 0.0
        self.defeated_biomes.clear()
        self.boss_spawned_at.clear()
        self.sandstorm_timer = random.uniform(75, 105)
        self.sandstorm_remaining = 0.0
        self.screen_state = "playing"
        self.update_camera()
        self.audio.start_music()

    def spawn_enemy(self) -> None:
        if self.player is None or len(self.enemies) >= MAX_ENEMIES:
            return
        angle = random.random() * math.tau
        radius = random.uniform(470, 680)
        x = clamp(self.player.x + math.cos(angle) * radius, 45, WORLD_WIDTH - 45)
        y = clamp(self.player.y + math.sin(angle) * radius, 45, WORLD_HEIGHT - 45)
        x, y = keep_inside(x, y, padding=40)
        biome = self.biome_at(x, y)
        enemy_pools = {
            "forest": ("crab", "crab", "skeleton", "skeleton", "pirate"),
            "desert": ("sand_snake", "sand_snake", "scorpion", "gull"),
            "snow": ("polar_bear", "polar_bear", "ice_wraith", "ice_wraith"),
            "volcano": ("ash_imp", "ash_imp", "fire_wraith", "fire_wraith"),
        }
        kind = random.choice(enemy_pools[biome])
        elite = self.elapsed > 90 and random.random() < min(0.16, self.elapsed / 5000)
        enemy = self.enemy_pool.pop() if self.enemy_pool else Enemy(kind, x, y, self.wave, biome, self.elapsed)
        enemy.reset(kind, x, y, self.wave, biome, self.elapsed, elite)
        self.enemies.append(enemy)

    def spawn_boss(self, biome: str | None = None) -> None:
        if self.player is None:
            return
        biome = biome or self.biome_at(self.player.x, self.player.y)
        if biome in self.boss_spawned_at:
            return
        if biome != "final":
            self.map_name = biome
        boss_y = self.player.y - 460 if biome == "volcano" else self.player.y - 80
        boss_x, boss_y = keep_inside(self.player.x + 460, boss_y, padding=90)
        self.boss = Boss(biome, self.wave, boss_x, boss_y)
        self.boss_spawned_at.add(biome)
        self.audio.play("level")

    def bank_run_coins(self) -> None:
        if self.player is None or self.player.banked:
            return
        self.last_run_coins = self.run_coins
        if self.run_coins > 0:
            self.profile.earn_coins(self.run_coins)
        else:
            self.profile.save()
        self.player.banked = True
        self.run_coins = 0

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.bank_run_coins()
            self.running = False
        elif event.type == pygame.VIDEORESIZE:
            self.screen = pygame.display.set_mode((max(640, event.w), max(600, event.h)), pygame.RESIZABLE)
            self.overlay_surfaces.clear()
            self.flash_surface = pygame.Surface(self.screen.get_size())
            self.flash_surface.fill((255, 240, 207))
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self.screen_state == "playing":
                self.screen_state = "paused"
            elif self.screen_state == "paused":
                self.screen_state = "playing"
            elif self.screen_state in ("settings", "pause_settings"):
                self.screen_state = self.previous_state
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_e and self.screen_state == "playing":
            self.activate_altar()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.handle_click(event.pos)
        elif event.type == pygame.MOUSEMOTION and pygame.mouse.get_pressed()[0]:
            self.handle_slider(event.pos)

    def handle_click(self, pos: tuple[int, int]) -> None:
        for name, rect in self.sliders.items():
            if rect.inflate(20, 20).collidepoint(pos):
                self.set_slider(name, pos[0])
                return
        for action, rect in self.buttons.items():
            if rect.collidepoint(pos):
                self.activate(action)
                return

    def handle_slider(self, pos: tuple[int, int]) -> None:
        for name, rect in self.sliders.items():
            if pygame.mouse.get_pressed()[0] and abs(pos[1] - rect.centery) < 18:
                self.set_slider(name, pos[0])

    def set_slider(self, name: str, mouse_x: int) -> None:
        rect = self.sliders[name]
        value = clamp((mouse_x - rect.x) / rect.width, 0, 1)
        setattr(self.audio, name, value)
        self.audio.apply_volumes()

    def activate(self, action: str) -> None:
        if action in ("start", "retry"):
            self.start_game()
        elif action == "settings":
            self.previous_state = "menu"
            self.screen_state = "settings"
        elif action == "howto":
            self.screen_state = "howto"
        elif action == "character":
            self.screen_state = "character"
        elif action == "back":
            self.screen_state = self.previous_state
        elif action == "resume":
            self.screen_state = "playing"
        elif action == "pause_settings":
            self.previous_state = "paused"
            self.screen_state = "pause_settings"
        elif action == "menu":
            self.bank_run_coins()
            self.screen_state = "menu"
            self.player = None
            self.enemies.clear()
            self.shots.clear()
            self.hostile_shots.clear()
            for orb in self.orbs:
                self.recycle_orb(orb)
            self.orbs.clear()
            self.chests.clear()
            self.boss = None
        elif action.startswith("gender:"):
            self.profile.data["gender"] = action.split(":", 1)[1]
            self.profile.save()
        elif action.startswith("character:"):
            self.select_character(action.split(":", 1)[1])
        elif action.startswith("weapon:"):
            self.select_weapon(action.split(":", 1)[1])
        elif action.startswith("hat:"):
            self.select_hat(action.split(":", 1)[1])
        elif action.startswith("upgrade:"):
            self.apply_upgrade(action.split(":", 1)[1])

    def select_character(self, character_id: str) -> None:
        character = CHARACTERS.get(character_id)
        if character is None:
            return
        unlocked = self.profile.data["unlocked_characters"]
        if character_id not in unlocked:
            price = character["price"]
            if not self.profile.spend_coins(price):
                self.notice = f"Te faltan {price - self.profile.coins} doblones."
                return
            unlocked.append(character_id)
        self.profile.data["selected_character"] = character_id
        starting_weapon = character["weapon"]
        self.profile.data["selected_weapon"] = starting_weapon
        if starting_weapon not in self.profile.data["unlocked_weapons"]:
            self.profile.data["unlocked_weapons"].append(starting_weapon)
        self.profile.save()
        self.notice = f"Seleccionaste: {character['name']}."

    def select_weapon(self, weapon_id: str) -> None:
        weapon = WEAPONS.get(weapon_id)
        if weapon is None:
            return
        unlocked = self.profile.data["unlocked_weapons"]
        if weapon_id not in unlocked:
            price = weapon["price"]
            if not self.profile.spend_coins(price):
                self.notice = f"Te faltan {price - self.profile.coins} doblones."
                return
            unlocked.append(weapon_id)
        self.profile.data["selected_weapon"] = weapon_id
        self.profile.save()
        self.notice = f"Arma inicial equipada: {weapon['name']}."

    def select_hat(self, hat: str) -> None:
        if hat not in HATS:
            return
        if hat not in self.profile.data["unlocked_hats"]:
            if not self.profile.spend_coins(HATS[hat]["price"]):
                self.notice = f"Te faltan {HATS[hat]['price'] - self.profile.coins} doblones."
                return
            self.profile.data["unlocked_hats"].append(hat)
        self.profile.data["selected_hat"] = hat
        self.notice = f"Equipaste: {HATS[hat]['name']}."
        self.profile.save()

    def apply_upgrade(self, upgrade: str) -> None:
        if self.player is None:
            return
        player = self.player
        rarity = self.choice_rarities.get(upgrade, UPGRADE_RARITIES[0][:2])[0]
        rarity_rank = {name: index for index, (name, _, _) in enumerate(UPGRADE_RARITIES)}[rarity]
        bonus = {
            "común": 1.0,
            "poco común": 1.1,
            "raro": 1.18,
            "épico": 1.4,
            "legendario": 1.8,
        }[rarity]
        if upgrade == "speed":
            player.speed *= 1 + 0.2 * bonus
        elif upgrade == "eye":
            player.attack_range *= 1 + 0.2 * bonus
            player.crit_chance = min(0.8, player.crit_chance + 0.1 * bonus)
        elif upgrade == "damage":
            player.damage *= 1 + 0.2 * bonus
        elif upgrade == "fire_rate":
            player.fire_rate *= 1 + 0.15 * bonus
        elif upgrade == "projectiles":
            player.projectiles += 1 + int(rarity_rank >= 3)
        elif upgrade == "max_health":
            health_gain = 20 * bonus
            player.max_health += health_gain
            player.health = min(player.max_health, player.health + health_gain)
        elif upgrade == "regen":
            player.regen += 1 * bonus
        elif upgrade == "armor":
            player.armor += 5 * bonus
        elif upgrade == "healing":
            player.healing_multiplier += 0.25 * bonus
        elif upgrade == "card_damage":
            player.card_damage_multiplier *= 1 + 0.2 * bonus
        elif upgrade == "card_speed":
            player.card_speed *= 1 + 0.2 * bonus
        elif upgrade == "card_size":
            player.card_size *= 1 + 0.2 * bonus
        elif upgrade == "card_pierce":
            player.card_pierce += 1 + int(rarity_rank >= 3)
        elif upgrade == "card_burn":
            player.card_burn_chance = min(0.75, player.card_burn_chance + 0.18 * bonus)
        elif upgrade in player.weapon_levels and player.weapon_levels[upgrade] < 5:
            player.weapon_levels[upgrade] = min(5, player.weapon_levels[upgrade] + 1 + int(rarity_rank >= 3))
            if rarity == "épico" and upgrade in ("dagger", "shell"):
                player.freeze_chance = min(0.6, player.freeze_chance + 0.22)
            if rarity == "épico" and upgrade in ("bomb", "fire"):
                player.fire_damage_multiplier *= 1.2
                player.area_multiplier *= 1.08
        elif upgrade == "synergy":
            player.projectiles *= 2
            player.max_health *= 0.85
            player.health = min(player.health, player.max_health)
            player.synergy_used = True
        elif upgrade == "bloodlust":
            player.bloodlust = min(5, player.bloodlust + 1 + int(rarity_rank >= 2))
        elif upgrade == "magnet":
            player.magnet_radius *= 1 + 0.3 * bonus
        self.screen_state = "playing"
        if player.xp >= player.xp_to_next:
            self.advance_level()

    def update(self, dt: float) -> None:
        if self.screen_state != "playing" or self.player is None:
            return
        if self.vfx.hit_stop > 0:
            self.vfx.update(dt)
            return
        player = self.player
        self.hud_health += (player.health / player.max_health - self.hud_health) * min(1.0, dt * 12)
        self.hud_xp += (player.xp / player.xp_to_next - self.hud_xp) * min(1.0, dt * 10)
        self.pickup_notice_time = max(0.0, self.pickup_notice_time - dt)
        keys = pygame.key.get_pressed()
        player.invulnerable = max(0, player.invulnerable - dt)
        mx = float(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - float(keys[pygame.K_a] or keys[pygame.K_LEFT])
        my = float(keys[pygame.K_s] or keys[pygame.K_DOWN]) - float(keys[pygame.K_w] or keys[pygame.K_UP])
        input_vector = Vector2(mx, my)
        if input_vector.length_squared() > 1:
            input_vector = input_vector.normalize()
        player.dash_cooldown = max(0.0, player.dash_cooldown - dt)
        player.dash_remaining = max(0.0, player.dash_remaining - dt)
        if (keys[pygame.K_SPACE] or keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]) and player.dash_cooldown <= 0:
            if input_vector.length_squared() > 0:
                player.dash_direction = tuple(input_vector)
            else:
                player.dash_direction = (float(player.facing), 0.0)
            player.dash_remaining = 0.19
            player.dash_cooldown = 3.5
            player.invulnerable = max(player.invulnerable, 0.2)
        if mx:
            player.facing = 1 if mx > 0 else -1
        biome = self.biome_at(player.x, player.y)
        self.map_name = biome
        slow_factor = 0.85 if self.in_shallows(player.x, player.y) else 1.0
        if biome == "snow":
            slow_factor *= 0.9
        if biome == "volcano" and mx == 0 and my == 0:
            slow_factor *= 0.85
        if self.ice_slow > 0:
            slow_factor *= 0.84
            self.ice_slow = max(0, self.ice_slow - dt)
        dash_factor = 3.2 if player.dash_remaining > 0 else 1.0
        move_vector = input_vector
        if player.dash_remaining > 0:
            move_vector = Vector2(player.dash_direction)
        elif biome == "snow":
            velocity = Vector2(player.velocity)
            target_velocity = input_vector * player.speed
            velocity = velocity.lerp(target_velocity, min(1.0, dt * (3.2 if input_vector.length_squared() else 1.1)))
            player.velocity = tuple(velocity)
            move_vector = velocity / max(1.0, player.speed)
        else:
            player.velocity = tuple(input_vector * player.speed)
        movement = move_vector * player.speed * slow_factor * dash_factor * dt
        player.x += movement.x
        player.y += movement.y
        self.keep_player_on_island()
        player.walk_time += dt * 9
        heat_suppressed = biome == "desert" and input_vector.length_squared() == 0
        player.health = min(player.max_health, player.health + player.regen * dt * (0.5 if heat_suppressed else 1))
        self.elapsed += dt
        self.wave_time += dt
        self.attack_timer -= dt
        player.dagger_timer -= dt
        player.bomb_timer -= dt
        player.fire_timer -= dt
        player.shell_angle += dt * (2.7 + player.weapon_levels["shell"] * 0.45)
        for key in list(player.shell_hit_timers):
            player.shell_hit_timers[key] = max(0, player.shell_hit_timers[key] - dt)
            if player.shell_hit_timers[key] == 0:
                del player.shell_hit_timers[key]

        if self.wave_time >= 40:
            self.wave += 1
            self.wave_time -= 40
            for _ in range(min(self.wave + 1, 5)):
                self.spawn_enemy()

        if self.map_name == "desert":
            self.sandstorm_timer -= dt
            if self.sandstorm_timer <= 0:
                self.sandstorm_remaining = 8.0
                self.sandstorm_timer = random.uniform(85, 125)
        self.sandstorm_remaining = max(0, self.sandstorm_remaining - dt)

        milestones = ((300, "forest"), (600, "desert"), (900, "snow"), (1080, "volcano"))
        if self.elapsed >= 1200 and not self.final_boss_spawned and self.boss is None:
            self.spawn_boss("final")
            self.final_boss_spawned = True
        if not self.final_boss_spawned:
            for milestone, biome_boss in milestones:
                if self.boss is None and biome_boss not in self.boss_spawned_at and self.elapsed >= milestone:
                    self.spawn_boss(biome_boss)
                    break
        if self.boss is None and self.map_name == "desert" and player.x > ISLAND_CENTER[0] + 1900:
            self.spawn_boss("desert")
        elif self.boss is None and self.map_name == "snow" and player.x < ISLAND_CENTER[0] - 1900:
            self.spawn_boss("snow")
        elif self.boss is None and self.map_name == "volcano" and player.y < ISLAND_CENTER[1] - 1050:
            self.spawn_boss("volcano")

        if self.boss is None:
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                self.spawn_enemy()
                if self.wave >= 4 and random.random() < 0.18:
                    self.spawn_enemy()
                self.spawn_timer = max(0.52, 2.5 - self.wave * 0.15) * random.uniform(0.72, 1.27)

        self.chest_timer -= dt
        if self.chest_timer <= 0 and sum(chest.kind == "chest" for chest in self.chests) < 2:
            self.spawn_chest()
            self.chest_timer = random.uniform(28, 40)
        self.update_altar(dt)
        if biome == "volcano":
            self.update_meteorites(dt)
        self.update_environment(dt, mx, my)
        self.update_enemies(dt)
        if self.screen_state != "playing":
            return
        self.update_boss(dt)
        if self.screen_state != "playing":
            return
        self.update_hostile_projectiles(dt)
        self.update_map_hazards(dt)
        if self.screen_state != "playing":
            return
        self.update_projectiles(dt)
        if self.screen_state != "playing":
            return
        self.update_bombs(dt)
        if self.screen_state != "playing":
            return
        self.update_shell(dt)
        if self.screen_state != "playing":
            return
        self.update_orbs(dt)
        if self.screen_state != "playing":
            return
        self.update_particles(dt)
        if self.screen_state == "playing" and self.attack_timer <= 0:
            self.fire_at_nearest()
        if self.screen_state == "playing" and player.weapon_levels["dagger"] and player.dagger_timer <= 0:
            self.fire_daggers()
        if self.screen_state == "playing" and player.weapon_levels["bomb"] and player.bomb_timer <= 0:
            self.throw_bomb()
        if self.screen_state == "playing" and player.weapon_levels["fire"] and player.fire_timer <= 0:
            if input_vector.length_squared() > 0:
                self.add_fire_patch(player.x - input_vector.x * 34, player.y - input_vector.y * 34)
            player.fire_timer = max(0.08, 0.24 - player.weapon_levels["fire"] * 0.025)
        self.update_fire_trail(dt)
        self.update_camera()

    def add_fire_patch(self, x: float, y: float) -> None:
        assert self.player is not None
        if len(self.player.fire_trail) >= 60:
            self.player.fire_trail.pop(0)
        self.player.fire_trail.append({
            "x": x,
            "y": y,
            "life": 2.1,
            "radius": 25 + self.player.weapon_levels["fire"] * 3,
            "damage_timer": 0.0,
        })

    def update_fire_trail(self, dt: float) -> None:
        if self.player is None:
            return
        for flame in self.player.fire_trail[:]:
            flame["life"] -= dt
            flame["damage_timer"] -= dt
            if flame["life"] <= 0:
                self.player.fire_trail.remove(flame)
                continue
            if flame["damage_timer"] <= 0:
                for enemy in self.enemies:
                    if math.hypot(enemy.x - flame["x"], enemy.y - flame["y"]) < enemy.radius + flame["radius"]:
                        self.damage_target(
                            enemy,
                            self.player.damage * 0.3 * self.player.area_multiplier * self.player.fire_damage_multiplier,
                        )
                        enemy.slow_timer = max(enemy.slow_timer, 0.4)
                flame["damage_timer"] = 0.45

    def activate_altar(self) -> None:
        if self.player is None or self.altar is None or self.altar_active > 0:
            return
        distance = math.hypot(self.altar["x"] - self.player.x, self.altar["y"] - self.player.y)
        if distance > self.altar["radius"] + 60:
            return
        self.altar_active = 30.0
        self.altar["challenge"] = 30.0
        self.notice = "¡Resiste junto al altar durante 30 segundos!"

    def update_altar(self, dt: float) -> None:
        if self.player is None:
            return
        if self.altar_active > 0 and self.altar is not None:
            distance = math.hypot(self.altar["x"] - self.player.x, self.altar["y"] - self.player.y)
            if distance > self.altar["radius"]:
                self.altar_active = 0
                self.altar_cooldown = 90
                self.altar = None
                self.notice = "El reto del altar se interrumpió."
                return
            self.altar_active = max(0, self.altar_active - dt)
            self.altar["challenge"] = self.altar_active
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                for _ in range(2):
                    self.spawn_enemy()
                self.spawn_timer = 1.0
            if self.altar_active == 0:
                remaining_artifacts = {"reliquia", "brujula", "amuleto"} - self.artifacts
                artifact = random.choice(tuple(remaining_artifacts))
                self.artifacts.add(artifact)
                if artifact == "reliquia":
                    self.player.damage *= 1.12
                elif artifact == "brujula":
                    self.player.magnet_radius *= 1.25
                else:
                    self.player.max_health += 15
                    self.player.health = min(self.player.max_health, self.player.health + 15)
                self.run_coins += 15
                self.altar = None
                self.altar_cooldown = 90
                self.notice = f"Artefacto obtenido: {artifact.title()}."
            return
        if self.altar is None and len(self.artifacts) < 3:
            self.altar_cooldown -= dt
            if self.altar_cooldown <= 0:
                angle = random.random() * math.tau
                altar_x, altar_y = keep_inside(
                    self.player.x + math.cos(angle) * 260,
                    self.player.y + math.sin(angle) * 260,
                    padding=80,
                )
                self.altar = {
                    "x": altar_x,
                    "y": altar_y,
                    "radius": 145,
                    "challenge": 0.0,
                }

    def update_meteorites(self, dt: float) -> None:
        self.meteor_timer -= dt
        if self.meteor_timer > 0 or self.player is None:
            return
        angle = random.random() * math.tau
        x, y = keep_inside(
            self.player.x + math.cos(angle) * random.uniform(100, 330),
            self.player.y + math.sin(angle) * random.uniform(100, 330),
            padding=70,
        )
        self.hazards.append({
            "x": x, "y": y, "radius": 70, "color": (239, 105, 55),
            "timer": 1.25, "life": 1.45, "kind": "meteor",
        })
        self.meteor_timer = random.uniform(5, 9)

    def keep_player_on_island(self) -> None:
        assert self.player is not None
        self.player.x = clamp(self.player.x, self.player.radius, WORLD_WIDTH - self.player.radius)
        self.player.y = clamp(self.player.y, self.player.radius, WORLD_HEIGHT - self.player.radius)
        self.player.x, self.player.y = keep_inside(self.player.x, self.player.y, padding=self.player.radius + 4)

    def in_shallows(self, x: float, y: float) -> bool:
        return any(self.point_in_polygon((x, y), polygon) for polygon in self.shallows)

    def update_environment(self, dt: float, move_x: float, move_y: float) -> None:
        if self.player is None:
            return
        player = self.player
        player.shallow = self.in_shallows(player.x, player.y)
        for chest in self.chests:
            chest.hit_flash = max(0, chest.hit_flash - dt)
        player.footstep_timer -= dt
        if (move_x or move_y) and player.footstep_timer <= 0:
            if not player.shallow:
                self.footprints.append({"x": player.x, "y": player.y, "life": 9.0, "phase": player.walk_time})
                self.footprints = self.footprints[-42:]
            player.footstep_timer = 0.24
        for item in self.reactive_bushes:
            item["leaf_timer"] = max(0, item["leaf_timer"] - dt)
            if item["leaf_timer"] <= 0 and (move_x or move_y):
                dx, dy = item["x"] - player.x, item["y"] - player.y
                if dx * dx + dy * dy < 62 * 62:
                    self.add_particles(item["x"], item["y"], (153, 193, 102), 4, "shard")
                    item["leaf_timer"] = 0.48
        for footprint in self.footprints[:]:
            footprint["life"] -= dt
            if footprint["life"] <= 0:
                self.footprints.remove(footprint)
        for number in self.damage_numbers[:]:
            number["y"] -= number["rise"] * dt
            number["life"] -= dt
            if number["life"] <= 0:
                self.damage_numbers.remove(number)
        self.screen_flash = max(0, self.screen_flash - dt * 2.5)

    def update_enemies(self, dt: float) -> None:
        assert self.player is not None
        for enemy in self.enemies[:]:
            direction = Vector2(self.player.x - enemy.x, self.player.y - enemy.y)
            distance = direction.length() or 1
            enemy.phase += dt * 5
            enemy.hit_flash = max(0, enemy.hit_flash - dt)
            enemy.knockback = max(0.0, enemy.knockback - dt * 90)
            if enemy.burn_timer > 0:
                enemy.burn_timer = max(0.0, enemy.burn_timer - dt)
                enemy.burn_tick -= dt
                if enemy.burn_tick <= 0:
                    enemy.burn_tick = 0.55
                    self.damage_target(enemy, enemy.burn_damage)
                    if enemy not in self.enemies:
                        continue
            if enemy.kind in ("octopus", "ice_wraith", "fire_wraith") and distance > 210:
                enemy.attack_timer -= dt
                if enemy.attack_timer <= 0:
                    self.fire_ink(enemy, ice=enemy.kind in ("ice_wraith", "fire_wraith"))
                    enemy.attack_timer = enemy.reaction * 2.8
            if distance > self.player.radius + enemy.radius + 2:
                target = Vector2(self.player.x, self.player.y)
                if enemy.kind == "gull":
                    target += direction.normalize() * enemy.speed * 0.45
                target_direction = target - Vector2(enemy.x, enemy.y)
                target_distance = target_direction.length() or 1
                slow_factor = 0.85 if self.in_shallows(enemy.x, enemy.y) else 1.0
                if self.biome_at(enemy.x, enemy.y) == "snow":
                    slow_factor *= 0.9
                if enemy.slow_timer > 0:
                    slow_factor *= 0.7
                    enemy.slow_timer = max(0, enemy.slow_timer - dt)
                movement = target_direction / target_distance * enemy.speed * slow_factor * dt
                enemy.x += movement.x
                enemy.y += movement.y
                if enemy.knockback > 0:
                    enemy.x += math.cos(enemy.knockback_angle) * enemy.knockback * dt
                    enemy.y += math.sin(enemy.knockback_angle) * enemy.knockback * dt
                enemy.x, enemy.y = keep_inside(enemy.x, enemy.y, padding=enemy.radius)
            else:
                enemy.attack_timer -= dt
                if enemy.attack_timer <= 0 and self.player.invulnerable <= 0:
                    self.hurt_player(enemy.damage)
                    enemy.attack_timer = 0.95
                    if self.screen_state != "playing":
                        return

    def combat_targets(self) -> list[Enemy | Chest | Boss]:
        targets: list[Enemy | Chest] = [*self.enemies, *self.chests]
        if self.boss is not None:
            targets.append(self.boss)
        return targets

    def fire_at_nearest(self) -> None:
        assert self.player is not None
        target = min(
            self.combat_targets(),
            key=lambda entity: math.hypot(entity.x - self.player.x, entity.y - self.player.y),
            default=None,
        )
        if target is None or math.hypot(target.x - self.player.x, target.y - self.player.y) > self.player.attack_range:
            self.attack_timer = 0.12
            return
        angle = math.atan2(target.y - self.player.y, target.x - self.player.x)
        count = self.player.projectiles
        for index in range(count):
            shot_angle = angle + (index - (count - 1) / 2) * 0.15
            self.launch_projectile(self.shots, {
                "x": self.player.x + math.cos(shot_angle) * 20,
                "y": self.player.y + math.sin(shot_angle) * 20,
                "vx": math.cos(shot_angle) * self.player.card_speed,
                "vy": math.sin(shot_angle) * self.player.card_speed,
                "damage": self.player.damage * self.player.card_damage_multiplier,
                "life": 1.8,
                "pierce": self.player.card_pierce + self.player.pierce_bonus,
                "hit_ids": set(),
                "critical": random.random() < self.player.crit_chance,
                "card": True,
                "size": self.player.card_size,
                "rotation": random.uniform(-0.35, 0.35),
            })
        self.attack_timer = 1 / self.player.fire_rate
        self.audio.play("shot")

    def update_projectiles(self, dt: float) -> None:
        for shot in self.shots[:]:
            if shot.get("card"):
                shot["rotation"] += dt * 13
            previous = (shot["x"], shot["y"])
            position = Vector2(shot["x"], shot["y"])
            position += Vector2(shot["vx"], shot["vy"]) * dt
            shot["x"], shot["y"] = position
            shot["life"] -= dt
            target_hit = None
            for target in self.combat_targets():
                if id(target) in shot["hit_ids"]:
                    continue
                if distance_to_segment(
                    (target.x, target.y),
                    previous,
                    (shot["x"], shot["y"]),
                ) > target.radius + (5 * shot.get("size", 1.0) if shot.get("card") else 5):
                    continue
                damage = shot["damage"] * (2 if shot["critical"] else 1)
                self.damage_target(target, damage, critical=shot["critical"])
                if isinstance(target, Enemy) and shot.get("card") and self.player and random.random() < self.player.card_burn_chance:
                    target.burn_timer = max(target.burn_timer, 3.0)
                    target.burn_tick = min(target.burn_tick or 0.55, 0.55)
                    target.burn_damage = max(target.burn_damage, self.player.damage * 0.22)
                    self.add_particles(target.x, target.y, (255, 129, 54), 7, "ember")
                if (
                    self.player
                    and isinstance(target, Enemy)
                    and shot.get("dagger")
                    and random.random() < self.player.freeze_chance
                ):
                    target.slow_timer = max(target.slow_timer, 1.8)
                shot["hit_ids"].add(id(target))
                shot["pierce"] -= 1
                self.add_particles(shot["x"], shot["y"], (255, 226, 155), 3)
                target_hit = target
                break
            if (target_hit is not None and shot["pierce"] < 0) or shot["life"] <= 0:
                self.shots.remove(shot)
                self.recycle_projectile(shot)

    def damage_target(
        self,
        target: Enemy | Chest | Boss,
        damage: float,
        critical: bool = False,
    ) -> None:
        target.health -= damage
        target.hit_flash = 0.08
        if isinstance(target, Enemy):
            target.knockback = min(18.0, target.knockback + (18 if critical else 7))
            target.knockback_angle = math.atan2(
                target.y - (self.player.y if self.player else target.y),
                target.x - (self.player.x if self.player else target.x),
            )
        self.damage_numbers.append({
            "x": target.x + random.uniform(-10, 10),
            "y": target.y - target.radius,
            "text": str(round(damage)),
            "color": (255, 203, 91) if critical else (250, 244, 219),
            "surface": self.fonts["body" if critical else "small"].render(str(round(damage)), True, (255, 203, 91) if critical else (250, 244, 219)),
            "life": 0.9,
            "rise": 28,
            "critical": critical,
        })
        if len(self.damage_numbers) > 40:
            del self.damage_numbers[:-40]
        if isinstance(target, Enemy):
            if critical:
                self.add_particles(target.x, target.y, (255, 208, 105), 7, "shard")
                self.vfx.request_hit_stop()
            else:
                self.add_particles(target.x, target.y, (252, 231, 185), 3)
            if target.health <= 0:
                self.defeat_enemy(target)
        elif isinstance(target, Chest):
            self.add_particles(target.x, target.y, (216, 173, 105), 3, "shard")
            if target.health <= 0:
                self.open_chest(target)
        else:
            target.hit_flash = 0.08
            self.add_particles(target.x, target.y, (255, 218, 131), 5, "shard")
            if critical:
                self.vfx.request_hit_stop()
            if target.health <= 0:
                self.defeat_boss()

    def fire_daggers(self) -> None:
        assert self.player is not None
        targets = self.combat_targets()
        if not targets:
            self.player.dagger_timer = 0.35
            return
        targets.sort(key=lambda target: math.hypot(target.x - self.player.x, target.y - self.player.y))
        target = targets[0]
        distance = math.hypot(target.x - self.player.x, target.y - self.player.y)
        if distance > self.player.attack_range * 0.8:
            self.player.dagger_timer = 0.35
            return
        level = self.player.weapon_levels["dagger"]
        angle = math.atan2(target.y - self.player.y, target.x - self.player.x)
        count = 1 + (level - 1) // 2
        for index in range(count):
            shot_angle = angle + (index - (count - 1) / 2) * 0.22
            critical = random.random() < min(0.7, self.player.crit_chance + 0.22)
            self.launch_projectile(self.shots, {
                "x": self.player.x + math.cos(shot_angle) * 19,
                "y": self.player.y + math.sin(shot_angle) * 19,
                "vx": math.cos(shot_angle) * (650 + level * 45),
                "vy": math.sin(shot_angle) * (650 + level * 45),
                "damage": self.player.damage * (0.7 + level * 0.18),
                "life": 1.5,
                "pierce": 1 + level // 2 + self.player.pierce_bonus,
                "hit_ids": set(),
                "critical": critical,
                "dagger": True,
            })
        self.player.dagger_timer = max(0.32, 1.25 - level * 0.14)
        self.audio.play("shot")

    def throw_bomb(self) -> None:
        assert self.player is not None
        targets = self.combat_targets()
        if not targets:
            self.player.bomb_timer = 0.5
            return
        target = min(targets, key=lambda item: math.hypot(item.x - self.player.x, item.y - self.player.y))
        distance = math.hypot(target.x - self.player.x, target.y - self.player.y)
        if distance > 420:
            self.player.bomb_timer = 0.5
            return
        level = self.player.weapon_levels["bomb"]
        self.player.bombs.append({
            "x": target.x,
            "y": target.y,
            "fuse": 0.85,
            "radius": 78 + level * 16,
            "damage": (
                self.player.damage * (1.8 + level * 0.55)
                * self.player.area_multiplier * self.player.fire_damage_multiplier
            ),
        })
        self.player.bomb_timer = max(1.8, 5.4 - level * 0.52)

    def update_bombs(self, dt: float) -> None:
        if self.player is None:
            return
        for bomb in self.player.bombs[:]:
            bomb["fuse"] -= dt
            if bomb["fuse"] > 0:
                continue
            radius = bomb["radius"]
            for target in self.combat_targets():
                if math.hypot(target.x - bomb["x"], target.y - bomb["y"]) <= radius + target.radius:
                    self.damage_target(target, bomb["damage"])
                    if self.screen_state != "playing":
                        break
            self.add_particles(bomb["x"], bomb["y"], (255, 178, 75), 30)
            self.screen_flash = max(self.screen_flash, 0.12)
            self.player.bombs.remove(bomb)

    def update_shell(self, dt: float) -> None:
        if self.player is None:
            return
        level = self.player.weapon_levels["shell"]
        if not level:
            return
        count = 1 + (level - 1) // 2
        for index in range(count):
            angle = self.player.shell_angle + math.tau * index / count
            sx = self.player.x + math.cos(angle) * 48
            sy = self.player.y + math.sin(angle) * 48
            for target in self.combat_targets():
                if math.hypot(target.x - sx, target.y - sy) > target.radius + 12:
                    continue
                identity = id(target)
                if self.player.shell_hit_timers.get(identity, 0) > 0:
                    continue
                self.damage_target(target, self.player.damage * (0.45 + level * 0.12))
                self.player.shell_hit_timers[identity] = 0.62
                if isinstance(target, Enemy):
                    target.hit_flash = 0.09
                break

    def spawn_chest(self) -> None:
        for _ in range(30):
            angle = random.random() * math.tau
            radius = random.uniform(130, 610)
            x = self.player.x + math.cos(angle) * radius if self.player else ISLAND_CENTER[0] + math.cos(angle) * radius
            y = self.player.y + math.sin(angle) * radius if self.player else ISLAND_CENTER[1] + math.sin(angle) * radius
            if 30 <= x <= WORLD_WIDTH - 30 and 30 <= y <= WORLD_HEIGHT - 30:
                x, y = keep_inside(x, y, padding=35)
                self.chests.append(Chest(x, y))
                return

    def spawn_orb(self, x: float, y: float, value: int, coin: bool = False) -> None:
        if len(self.orbs) >= MAX_ORBS:
            return
        orb = self.orb_pool.pop() if self.orb_pool else {}
        orb.clear()
        orb.update({
            "x": x,
            "y": y,
            "value": value,
            "phase": random.random() * math.tau,
            "coin": coin,
        })
        self.orbs.append(orb)

    def recycle_orb(self, orb: dict) -> None:
        orb.clear()
        if len(self.orb_pool) < MAX_ORBS:
            self.orb_pool.append(orb)

    def open_chest(self, chest: Chest) -> None:
        if chest not in self.chests:
            return
        self.chests.remove(chest)
        drops = min(5 if chest.kind == "barrel" else 10, MAX_ORBS - len(self.orbs))
        for _ in range(drops):
            angle = random.random() * math.tau
            radius = random.uniform(8, 38)
            self.spawn_orb(
                chest.x + math.cos(angle) * radius,
                chest.y + math.sin(angle) * radius,
                1 if chest.kind == "barrel" else 2,
            )
        if len(self.orbs) < MAX_ORBS and random.random() < (0.35 if chest.kind == "barrel" else 0.58):
            coins = random.randint(1, 4) if chest.kind == "barrel" else random.randint(8, 18)
            self.spawn_orb(chest.x, chest.y - 20, coins, coin=True)
        if random.random() < 0.14 and self.player:
            self.player.health = min(
                self.player.max_health,
                self.player.health + self.player.max_health * 0.3 * self.player.healing_multiplier,
            )
        if self.player:
            self.player.health = min(
                self.player.max_health,
                self.player.health + self.player.bloodlust * self.player.max_health * 0.025 * self.player.healing_multiplier,
            )
        self.add_particles(chest.x, chest.y, (239, 199, 118), 18)
        self.vfx.request_shake(0.7, 0.07)
        self.pickup_notice = "¡COFRE ABIERTO!"
        self.pickup_notice_time = 1.5
        self.screen_flash = max(self.screen_flash, 0.12)
        self.audio.play("level")

    def fire_ink(self, enemy: Enemy, ice: bool = False) -> None:
        if self.player is None:
            return
        angle = math.atan2(self.player.y - enemy.y, self.player.x - enemy.x)
        self.launch_projectile(self.hostile_shots, {
            "x": enemy.x,
            "y": enemy.y,
            "vx": math.cos(angle) * 190,
            "vy": math.sin(angle) * 190,
            "damage": enemy.damage,
            "radius": 9,
            "life": 3.0,
            "color": (106, 219, 236) if ice else (87, 50, 104),
            "ice": ice,
        })

    def update_boss(self, dt: float) -> None:
        boss = self.boss
        if boss is None or self.player is None or self.screen_state != "playing":
            return
        boss.hit_flash = max(0, boss.hit_flash - dt)
        boss.phase = 2 if boss.health <= boss.max_health * 0.5 else 1
        boss.attack_timer -= dt
        boss.telegraph = boss.attack_timer < 0.75 and boss.charge_timer <= 0
        dx, dy = self.player.x - boss.x, self.player.y - boss.y
        distance = math.hypot(dx, dy) or 1
        if boss.charge_timer > 0:
            was_charging = boss.charge_timer > dt
            boss.charge_timer = max(0, boss.charge_timer - dt)
            tx, ty = boss.charge_target
            charge_direction = Vector2(tx - boss.x, ty - boss.y)
            if charge_direction.length_squared():
                charge_direction.scale_to_length(390 * dt)
                boss_position = Vector2(boss.x, boss.y) + charge_direction
                boss.x, boss.y = boss_position
            if was_charging and boss.charge_timer == 0:
                self.screen_flash = max(self.screen_flash, 0.16)
                if math.hypot(tx - self.player.x, ty - self.player.y) < 92:
                    self.hurt_player(24 + self.wave)
        else:
            if distance > boss.radius + self.player.radius + 6:
                movement = Vector2(dx, dy)
                movement.scale_to_length(boss.speed * dt)
                boss_position = Vector2(boss.x, boss.y) + movement
                boss.x, boss.y = boss_position
            if boss.attack_timer <= 0:
                pattern = boss.attack_index % 3
                boss.attack_index += 1
                boss.attack_timer = 2.3 if boss.phase == 2 else 3.4
                if pattern == 0:
                    if boss.map_name == "final":
                        shot_count = 7 if boss.phase == 1 else 13
                        for index in range(shot_count):
                            angle = math.atan2(dy, dx) + (index - (shot_count - 1) / 2) * 0.2
                            self.launch_projectile(self.hostile_shots, {
                                "x": boss.x, "y": boss.y,
                                "vx": math.cos(angle) * 235, "vy": math.sin(angle) * 235,
                                "damage": 17 if boss.phase == 1 else 23,
                                "radius": 10, "life": 4.0, "color": (215, 211, 229),
                            })
                    else:
                        boss.charge_target = (self.player.x, self.player.y)
                        boss.charge_timer = 0.72
                elif pattern == 1:
                    for index in range(5 if boss.phase == 2 else 3):
                        if len(self.enemies) >= MAX_ENEMIES:
                            break
                        angle = math.tau * index / 3
                        kind = (
                            "skeleton" if boss.map_name == "final"
                            else "fire_wraith" if boss.map_name == "volcano"
                            else "ice_wraith" if boss.map_name == "snow"
                            else "sand_snake" if boss.map_name == "desert"
                            else "octopus"
                        )
                        summoned = self.enemy_pool.pop() if self.enemy_pool else Enemy(kind, boss.x, boss.y, self.wave, boss.map_name, self.elapsed)
                        summoned.reset(
                            kind, boss.x + math.cos(angle) * 72,
                            boss.y + math.sin(angle) * 72, self.wave, boss.map_name, self.elapsed,
                        )
                        self.enemies.append(summoned)
                else:
                    base_angle = math.atan2(dy, dx)
                    if boss.map_name == "final":
                        for index in range(3 if boss.phase == 1 else 5):
                            angle = math.tau * index / (3 if boss.phase == 1 else 5)
                            self.hazards.append({
                                "x": self.player.x + math.cos(angle) * 115,
                                "y": self.player.y + math.sin(angle) * 115,
                                "radius": 74,
                                "color": (203, 121, 82),
                                "timer": 0.95,
                                "life": 1.2,
                                "kind": "meteor",
                            })
                    if boss.map_name == "snow":
                        self.hazards.append({
                            "x": self.player.x,
                            "y": self.player.y,
                            "radius": 105,
                            "color": (108, 210, 232),
                            "timer": 0.0,
                            "life": 3.0,
                            "slow": True,
                        })
                    elif boss.map_name == "volcano":
                        self.hazards.append({
                            "x": self.player.x, "y": self.player.y, "radius": 125,
                            "color": (239, 105, 55), "timer": 0.7, "life": 1.0,
                            "kind": "meteor",
                        })
                    shot_count = 13 if boss.phase == 2 else 9
                    for index in range(shot_count):
                        angle = base_angle + (index - (shot_count - 1) / 2) * 0.16
                        self.launch_projectile(self.hostile_shots, {
                            "x": boss.x,
                            "y": boss.y,
                            "vx": math.cos(angle) * 205,
                            "vy": math.sin(angle) * 205,
                            "damage": 13 + self.wave + (5 if boss.phase == 2 else 0),
                            "radius": 8,
                            "life": 4.0,
                            "color": (112, 214, 238) if boss.map_name == "snow" else (231, 155, 84) if boss.map_name == "desert" else (237, 118, 103),
                            "ice": boss.map_name == "snow",
                        })
        boss.x, boss.y = keep_inside(boss.x, boss.y, padding=boss.radius)
        boss.contact_timer = max(0, boss.contact_timer - dt)
        if distance <= boss.radius + self.player.radius + 7 and boss.contact_timer <= 0:
            self.hurt_player(22 + self.wave)
            boss.contact_timer = 0.8

    def update_hostile_projectiles(self, dt: float) -> None:
        if self.player is None:
            return
        for shot in self.hostile_shots[:]:
            position = Vector2(shot["x"], shot["y"])
            position += Vector2(shot["vx"], shot["vy"]) * dt
            shot["x"], shot["y"] = position
            shot["life"] -= dt
            if math.hypot(shot["x"] - self.player.x, shot["y"] - self.player.y) < shot["radius"] + self.player.radius:
                self.hurt_player(shot["damage"])
                if shot.get("ice"):
                    self.ice_slow = 1.4
                self.hostile_shots.remove(shot)
                self.recycle_projectile(shot)
            elif shot["life"] <= 0:
                self.hostile_shots.remove(shot)
                self.recycle_projectile(shot)

    def update_map_hazards(self, dt: float) -> None:
        if self.player is None:
            return
        for hazard in self.hazards[:]:
            if "life" in hazard:
                hazard["life"] -= dt
                if hazard["life"] <= 0:
                    self.hazards.remove(hazard)
                    continue
            hazard["timer"] = max(0, hazard["timer"] - dt)
            if hazard.get("kind") == "meteor" and hazard["timer"] <= 0:
                if math.hypot(hazard["x"] - self.player.x, hazard["y"] - self.player.y) < hazard["radius"] + self.player.radius:
                    self.hurt_player(22)
                hazard["kind"] = "impact"
                hazard["life"] = min(hazard.get("life", 0.2), 0.2)
                continue
            if hazard.get("kind") == "impact":
                continue
            if hazard.get("slow") and math.hypot(
                hazard["x"] - self.player.x, hazard["y"] - self.player.y,
            ) < hazard["radius"] + self.player.radius:
                self.ice_slow = max(self.ice_slow, 0.15)
            if hazard["timer"] <= 0 and math.hypot(
                hazard["x"] - self.player.x, hazard["y"] - self.player.y,
            ) < hazard["radius"] + self.player.radius:
                self.hurt_player(7)
                hazard["timer"] = 1.0

    def hurt_player(self, damage: float) -> None:
        if self.player is None or self.player.invulnerable > 0:
            return
        damage = max(1.0, damage * 100 / (100 + self.player.armor))
        self.player.health = max(0, self.player.health - damage)
        self.player.invulnerable = 0.56
        self.screen_flash = max(self.screen_flash, 0.16)
        self.vfx.request_shake(2.2, 0.12)
        self.damage_numbers.append({
            "x": self.player.x,
            "y": self.player.y - 28,
            "text": f"-{round(damage)}",
            "color": (246, 115, 93),
            "surface": self.fonts["small"].render(f"-{round(damage)}", True, (246, 115, 93)),
            "life": 0.9,
            "rise": 34,
            "critical": False,
        })
        if len(self.damage_numbers) > 40:
            del self.damage_numbers[:-40]
        self.audio.play("damage")
        self.add_particles(self.player.x, self.player.y, (240, 128, 102), 8)
        if self.player.character_id == "sailor":
            for enemy in self.enemies:
                dx, dy = enemy.x - self.player.x, enemy.y - self.player.y
                distance = math.hypot(dx, dy)
                if 0 < distance < 150:
                    enemy.x += dx / distance * 75
                    enemy.y += dy / distance * 75
        if self.player.health <= 0:
            self.end_game()

    def defeat_boss(self) -> None:
        if self.boss is None:
            return
        boss = self.boss
        self.boss = None
        self.kills += 1
        self.run_coins += 35
        self.add_particles(boss.x, boss.y, (255, 219, 131), 20)
        self.vfx.request_shake(2.4, 0.16)
        if self.player:
            self.player.health = min(
                self.player.max_health,
                self.player.health + self.player.bloodlust * self.player.max_health * 0.05 * self.player.healing_multiplier,
            )
        self.defeated_biomes.add(boss.map_name)
        self.screen_flash = max(self.screen_flash, 0.24)
        self.audio.play("level")
        if boss.map_name == "final":
            self.victory = True
            self.bank_run_coins()
            self.screen_state = "victory"
            self.vfx.shake_time = 0.0

    def defeat_enemy(self, enemy: Enemy) -> None:
        if enemy not in self.enemies:
            return
        self.enemies.remove(enemy)
        if len(self.enemy_pool) < 180:
            self.enemy_pool.append(enemy)
        self.kills += 1
        self.run_coins += 1
        self.add_particles(enemy.x, enemy.y, enemy.color, 12, "shard")
        if enemy.kind == "skeleton":
            self.hazards.append({
                "x": enemy.x,
                "y": enemy.y,
                "radius": 54,
                "color": (197, 89, 60),
                "timer": 0.0,
                "life": 5.0,
            })
        elif enemy.kind == "scorpion":
            self.hazards.append({
                "x": enemy.x, "y": enemy.y, "radius": 62,
                "color": (123, 174, 79), "timer": 0.3, "life": 4.0,
            })
        if len(self.orbs) < MAX_ORBS and random.random() < 0.72:
            self.spawn_orb(enemy.x, enemy.y, enemy.xp)
        self.audio.play("enemy")

    def update_orbs(self, dt: float) -> None:
        assert self.player is not None
        for orb in self.orbs[:]:
            orb["phase"] += dt * 4
            direction = Vector2(self.player.x - orb["x"], self.player.y - orb["y"])
            distance = direction.length() or 1
            if distance < self.player.magnet_radius:
                speed = 390 if distance < 25 else 165
                movement = direction / distance * speed * dt
                orb["x"] += movement.x
                orb["y"] += movement.y
            if distance < self.player.radius + 11:
                self.orbs.remove(orb)
                if orb.get("coin"):
                    self.run_coins += orb["value"]
                    self.add_particles(orb["x"], orb["y"], (246, 202, 91), 8, "ember")
                    self.pickup_notice = f"+{orb['value']} DOBLONES"
                else:
                    self.gain_experience(orb["value"])
                    self.add_particles(orb["x"], orb["y"], (250, 231, 151), 5, "shard")
                    self.pickup_notice = f"+{orb['value']} EXPERIENCIA"
                self.pickup_notice_time = 1.05
                self.recycle_orb(orb)
                if self.screen_state == "levelup":
                    break

    def gain_experience(self, amount: int) -> None:
        assert self.player is not None
        self.player.xp += amount
        if self.screen_state != "levelup" and self.player.xp >= self.player.xp_to_next:
            self.advance_level()

    def available_upgrades(self) -> list[tuple]:
        if self.player is None:
            return UPGRADES
        available = []
        for upgrade in UPGRADES:
            key, title, detail, icon = upgrade
            if key == "synergy" and self.player.synergy_used:
                continue
            if key == "card_burn" and self.player.card_burn_chance >= 0.75:
                continue
            if key == "card_pierce" and self.player.card_pierce >= 5:
                continue
            if key in self.player.weapon_levels:
                level = self.player.weapon_levels[key]
                if level >= 5:
                    continue
                detail = detail.format(level=level + 1)
            elif key == "bloodlust" and self.player.bloodlust >= 5:
                continue
            available.append((key, title, detail, icon))
        return available

    def advance_level(self) -> None:
        assert self.player is not None
        player = self.player
        player.xp -= player.xp_to_next
        player.level += 1
        player.xp_to_next = round(player.xp_to_next * 1.3 + 3)
        self.open_level_up()

    def open_level_up(self) -> None:
        choices = self.available_upgrades()
        if not choices:
            self.screen_state = "playing"
            return
        self.choices = random.sample(choices, min(3, len(choices)))
        self.choice_rarities = {
            choice[0]: ("legendario", UPGRADE_RARITIES[-1][1]) if choice[0] == "synergy" else choose_rarity()
            for choice in self.choices
        }
        self.screen_state = "levelup"
        self.audio.play("level")

    def add_particles(
        self,
        x: float,
        y: float,
        color: tuple[int, int, int],
        count: int,
        kind: str = "spark",
    ) -> None:
        self.vfx.burst(x, y, color, count, kind)

    def launch_projectile(self, destination: list[dict], values: dict) -> None:
        if len(self.shots) + len(self.hostile_shots) >= MAX_PROJECTILES:
            return
        projectile = self.projectile_pool.pop() if self.projectile_pool else {}
        projectile.clear()
        projectile.update(values)
        destination.append(projectile)

    def recycle_projectile(self, projectile: dict) -> None:
        projectile.clear()
        if len(self.projectile_pool) < 120:
            self.projectile_pool.append(projectile)

    def update_particles(self, dt: float) -> None:
        self.vfx.update(dt)

    def end_game(self) -> None:
        self.bank_run_coins()
        self.screen_state = "gameover"
        self.vfx.shake_time = 0.0
        self.audio.play("game_over")

    def update_camera(self) -> None:
        if self.player is None:
            return
        width, height = self.screen.get_size()
        camera_x = self.player.x - width / 2
        camera_y = self.player.y - height / 2
        if width >= WORLD_WIDTH:
            camera_x = (WORLD_WIDTH - width) / 2
        else:
            camera_x = clamp(camera_x, 0, WORLD_WIDTH - width)
        if height >= WORLD_HEIGHT:
            camera_y = (WORLD_HEIGHT - height) / 2
        else:
            camera_y = clamp(camera_y, 0, WORLD_HEIGHT - height)
        self.camera = (
            int(camera_x),
            int(camera_y),
        )

    def run(self) -> None:
        try:
            while self.running:
                frame_time = min(self.clock.tick(FPS) / 1000, FIXED_DT * 5)
                for event in pygame.event.get():
                    self.handle_event(event)
                self.accumulator += frame_time
                while self.accumulator >= FIXED_DT:
                    self.update(FIXED_DT)
                    self.accumulator -= FIXED_DT
                self.draw()
                pygame.display.flip()
        except KeyboardInterrupt:
            self.bank_run_coins()
            self.running = False
        finally:
            pygame.quit()

    def draw(self) -> None:
        self.buttons.clear()
        self.sliders.clear()
        self.draw_world()
        if self.screen_state == "playing":
            self.draw_hud()
        elif self.screen_state == "menu":
            self.draw_menu()
        elif self.screen_state == "character":
            self.draw_character()
        elif self.screen_state == "howto":
            self.draw_howto()
        elif self.screen_state in ("settings", "pause_settings"):
            self.draw_settings()
        elif self.screen_state == "paused":
            self.draw_pause()
        elif self.screen_state == "levelup":
            self.draw_levelup()
        elif self.screen_state == "gameover":
            self.draw_gameover()
        elif self.screen_state == "victory":
            self.draw_victory()

    def draw_world(self) -> None:
        width, height = self.screen.get_size()
        camera_x, camera_y = self.camera if self.player else (
            ISLAND_CENTER[0] - width // 2,
            ISLAND_CENTER[1] - height // 2,
        )
        shake_x, shake_y = self.vfx.camera_offset()
        camera_x += shake_x
        camera_y += shake_y
        self.draw_continuous_terrain(camera_x, camera_y)
        self.draw_shallows(camera_x, camera_y)
        self.draw_footprints(camera_x, camera_y)
        self.draw_map_hazards(camera_x, camera_y)
        visible_scenery = []
        for item in self.scenery:
            x, y = int(item["x"] - camera_x), int(item["y"] - camera_y)
            if -80 <= x <= width + 80 and -100 <= y <= height + 100:
                visible_scenery.append((item, x, y))
        player_screen_y = self.player.y - camera_y if self.player else height / 2
        split = 0
        while split < len(visible_scenery) and visible_scenery[split][0]["y"] < player_screen_y:
            item, x, y = visible_scenery[split]
            self.draw_scenery(item, x, y)
            split += 1
        self.draw_entities(camera_x, camera_y)
        for item, x, y in visible_scenery[split:]:
            self.draw_scenery(item, x, y)
        if self.sandstorm_remaining > 0 and self.player and self.biome_at(self.player.x, self.player.y) == "desert":
            self.screen.fill((16, 9, 0), special_flags=pygame.BLEND_RGB_ADD)
        if self.screen_flash > 0:
            if self.flash_surface.get_size() != self.screen.get_size():
                self.flash_surface = pygame.Surface(self.screen.get_size())
                self.flash_surface.fill((255, 240, 207))
            self.flash_surface.set_alpha(int(90 * min(1.0, self.screen_flash)))
            self.screen.blit(self.flash_surface, (0, 0))
        self.vfx.draw(self.screen, (camera_x, camera_y))
        self.draw_damage_numbers(camera_x, camera_y)

    def draw_continuous_terrain(self, camera_x: int, camera_y: int) -> None:
        width, height = self.screen.get_size()
        self.screen.fill((17, 76, 91))
        tile = 48
        start_x = max(0, camera_x // tile * tile)
        start_y = max(0, camera_y // tile * tile)
        end_x = min(WORLD_WIDTH, camera_x + width + tile)
        end_y = min(WORLD_HEIGHT, camera_y + height + tile)
        for world_x in range(start_x, end_x, tile):
            for world_y in range(start_y, end_y, tile):
                tile_surface = self.get_terrain_tile(world_x, world_y, tile)
                if tile_surface is not None:
                    self.screen.blit(tile_surface, (world_x - camera_x, world_y - camera_y))
        coast = [
            (round(x - camera_x), round(y - camera_y))
            for x, y in self.coastline_points
        ]
        pygame.draw.lines(self.screen, BIOMES["forest"]["accent"], True, coast, 14)
        pygame.draw.lines(self.screen, (44, 133, 143), True, coast, 8)
        pygame.draw.lines(self.screen, (177, 224, 204), True, coast, 2)
        phase = pygame.time.get_ticks() // 90
        for index in range(0, len(coast), 8):
            x, y = coast[(index + phase) % len(coast)]
            pygame.draw.circle(self.screen, (220, 241, 216), (x, y), 2)

    def get_terrain_tile(self, world_x: int, world_y: int, tile_size: int) -> pygame.Surface | None:
        key = (world_x // tile_size, world_y // tile_size)
        cached = self.terrain_tiles.get(key)
        if key in self.terrain_tiles:
            self.terrain_tiles.move_to_end(key)
            return cached

        center_x = world_x + tile_size / 2
        center_y = world_y + tile_size / 2
        radius = min(WORLD_WIDTH, WORLD_HEIGHT) * 0.497
        normalized_distance = math.hypot(center_x - ISLAND_CENTER[0], center_y - ISLAND_CENTER[1]) / radius
        tile_margin = math.sqrt(2) * tile_size / (2 * radius)
        fully_inside = normalized_distance < 0.976 - tile_margin
        possibly_inside = normalized_distance <= 1.024 + tile_margin
        if not possibly_inside:
            cached = None
        else:
            color = self.terrain_color(center_x, center_y)
            cached = pygame.Surface((tile_size + 1, tile_size + 1), pygame.SRCALPHA)
            if fully_inside:
                cached.fill((*color, 255))
            else:
                coast_tile = clip_polygon_to_rect(
                    self.coastline_points,
                    world_x,
                    world_y,
                    world_x + tile_size,
                    world_y + tile_size,
                )
                if len(coast_tile) >= 3:
                    local_points = [(round(x - world_x), round(y - world_y)) for x, y in coast_tile]
                    pygame.draw.polygon(cached, (*color, 255), local_points)
                if not cached.get_bounding_rect():
                    cached = None
        if cached is not None and fully_inside and (key[0] * 31 + key[1] * 13) % 23 == 0:
            detail_color = tuple(min(255, channel + 7) for channel in color)
            px = 6 + (key[0] * 7) % 30
            py = 6 + (key[1] * 11) % 30
            pygame.draw.line(cached, (*detail_color, 255), (px, py), (px + 4, py + 1), 1)
        self.terrain_tiles[key] = cached
        if len(self.terrain_tiles) > 800:
            self.terrain_tiles.popitem(last=False)
        return cached

    def warm_terrain_cache(self) -> None:
        width, height = self.screen.get_size()
        tile = 48
        camera_x = ISLAND_CENTER[0] - width // 2
        camera_y = ISLAND_CENTER[1] - height // 2
        start_x = max(0, camera_x // tile * tile)
        start_y = max(0, camera_y // tile * tile)
        for world_x in range(start_x, min(WORLD_WIDTH, camera_x + width + tile), tile):
            for world_y in range(start_y, min(WORLD_HEIGHT, camera_y + height + tile), tile):
                self.get_terrain_tile(world_x, world_y, tile)

    @staticmethod
    def terrain_color(x: float, y: float = float(ISLAND_CENTER[1])) -> tuple[int, int, int]:
        weights = biome_weights(x, y)
        return tuple(
            round(sum(BIOMES[name]["ground"][channel] * weight for name, weight in weights.items()))
            for channel in range(3)
        )

    def draw_shallows(self, camera_x: int, camera_y: int) -> None:
        for polygon in self.shallows:
            points = [(int(x - camera_x), int(y - camera_y)) for x, y in polygon]
            if max(x for x, _ in points) < 0 or min(x for x, _ in points) > self.screen.get_width():
                continue
            if max(y for _, y in points) < 0 or min(y for _, y in points) > self.screen.get_height():
                continue
            pygame.draw.polygon(self.screen, (77, 149, 165), points)
            pygame.draw.lines(self.screen, (128, 213, 204), True, points, 2)

    def draw_footprints(self, camera_x: int, camera_y: int) -> None:
        for footprint in self.footprints:
            x, y = int(footprint["x"] - camera_x), int(footprint["y"] - camera_y)
            strength = min(0.34, footprint["life"] / 9 * 0.34)
            base = self.terrain_color(footprint["x"])
            mark = tuple(round(channel * (1 - strength) + 43 * strength) for channel in base)
            offset = int(math.sin(footprint["phase"] * 0.04) * 2)
            pygame.draw.ellipse(self.screen, mark, (x - 5, y - 4 + offset, 4, 7))
            pygame.draw.ellipse(self.screen, mark, (x + 1, y - 4 - offset, 4, 7))

    def draw_damage_numbers(self, camera_x: int, camera_y: int) -> None:
        width, height = self.screen.get_size()
        for number in self.damage_numbers:
            x, y = int(number["x"] - camera_x), int(number["y"] - camera_y)
            image = number["surface"]
            if not (-image.get_width() <= x <= width + image.get_width() and -image.get_height() <= y <= height + image.get_height()):
                continue
            image.set_alpha(int(255 * min(1, number["life"] / 0.2)))
            rect = image.get_rect(center=(x, y))
            self.screen.blit(image, rect)

    def draw_map_hazards(self, camera_x: int, camera_y: int) -> None:
        if not self.hazards:
            return
        for hazard in self.hazards:
            x, y = int(hazard["x"] - camera_x), int(hazard["y"] - camera_y)
            color = hazard["color"] if "life" not in hazard else (236, 133, 77)
            pygame.draw.circle(self.screen, color, (x, y), hazard["radius"], 2)
            pygame.draw.circle(self.screen, color, (x, y), max(2, hazard["radius"] - 8), 1)
            if hazard.get("kind") == "meteor":
                self.text("¡METEORITO!", (x, y - hazard["radius"] - 18), self.fonts["mono"], color, center=True)

    def draw_scenery(self, item: dict, x: int, y: int) -> None:
        scale = item["scale"]
        phase = item["phase"] + self.elapsed * (1.5 if item["kind"] == "palm" else 1.0)
        if item["kind"] == "palm":
            sway = math.sin(phase * 0.7) * 4
            pygame.draw.ellipse(
                self.screen, (59, 81, 48),
                pygame.Rect(int(x - 28 * scale), int(y + 6 * scale), int(60 * scale), int(20 * scale)),
            )
            pygame.draw.line(
                self.screen, (112, 79, 49),
                (x, int(y + 12 * scale)), (int(x + 3 * scale + sway), int(y - 27 * scale)),
                max(3, int(9 * scale)),
            )
            for index in range(7):
                angle = index * math.tau / 7
                end = (
                    int(x + sway + math.cos(angle) * 36 * scale),
                    int(y - 30 * scale + math.sin(angle) * 21 * scale),
                )
                pygame.draw.line(
                    self.screen, (48, 105 + (index % 2) * 13, 61),
                    (int(x + 3 * scale + sway), int(y - 29 * scale)), end, max(3, int(7 * scale)),
                )
        elif item["kind"] == "rock":
            pygame.draw.ellipse(
                self.screen, (106, 113, 100),
                pygame.Rect(int(x - 22 * scale), int(y - 13 * scale), int(45 * scale), int(29 * scale)),
            )
            pygame.draw.ellipse(
                self.screen, (159, 163, 139),
                pygame.Rect(int(x - 13 * scale), int(y - 12 * scale), int(19 * scale), int(9 * scale)),
            )
        elif item["kind"] == "bush":
            for dx, dy, radius, color in ((-12, 2, 15, (79, 119, 65)), (2, -7, 18, (66, 105, 57)), (15, 2, 13, (91, 132, 70))):
                pygame.draw.circle(self.screen, color, (int(x + dx * scale), int(y + dy * scale)), int(radius * scale))
            glint = int((math.sin(phase * 2) + 1) * 1.5)
            pygame.draw.polygon(self.screen, (164, 191, 101), ((x - 3, y - 13), (x + 3, y - 15 - glint), (x + 1, y - 8)))
        elif item["kind"] == "cactus":
            pygame.draw.line(self.screen, (48, 117, 68), (x, y + 18), (x, y - 25), 10)
            pygame.draw.line(self.screen, (48, 117, 68), (x - 9, y + 2), (x - 9, y - 12), 7)
            pygame.draw.line(self.screen, (48, 117, 68), (x - 9, y - 12), (x - 1, y - 12), 7)
            pygame.draw.line(self.screen, (48, 117, 68), (x + 8, y + 5), (x + 8, y - 7), 7)
            pygame.draw.line(self.screen, (48, 117, 68), (x + 1, y - 7), (x + 8, y - 7), 7)
            for offset in (-4, 4):
                pygame.draw.line(self.screen, (195, 203, 137), (x + offset, y - 15), (x + offset + 3, y - 12), 1)
        elif item["kind"] == "pine":
            pygame.draw.line(self.screen, (93, 77, 62), (x, y + 14), (x, y - 25), 5)
            for level in range(3):
                yy = y - 7 - level * 13
                pygame.draw.polygon(self.screen, (60, 114, 118), ((x - 18 + level * 4, yy + 12), (x, yy - 12), (x + 18 - level * 4, yy + 12)))
                pygame.draw.line(self.screen, (207, 231, 222), (x - 8, yy + 4), (x, yy - 8), 2)
        elif item["kind"] == "ice_rock":
            pygame.draw.polygon(self.screen, (102, 150, 164), ((x - 23, y + 12), (x - 17, y - 12), (x - 5, y - 19), (x + 18, y - 9), (x + 24, y + 12)))
            pygame.draw.line(self.screen, (215, 236, 226), (x - 8, y - 11), (x + 8, y - 14), 3)
        elif item["kind"] in ("ruin", "ice_ruin"):
            stone = (127, 112, 80) if item["kind"] == "ruin" else (112, 158, 169)
            pygame.draw.polygon(self.screen, stone, ((x - 25, y + 12), (x - 20, y - 14), (x - 10, y - 18), (x - 6, y + 12)))
            pygame.draw.polygon(self.screen, tuple(max(0, c - 14) for c in stone), ((x + 5, y + 12), (x + 7, y - 18), (x + 19, y - 14), (x + 24, y + 12)))
            pygame.draw.line(self.screen, (211, 202, 163) if item["kind"] == "ruin" else (188, 229, 231), (x - 25, y - 15), (x + 24, y - 15), 5)
        elif item["kind"] == "snow_bush":
            for dx, dy, radius in ((-10, 2, 12), (2, -6, 15), (13, 2, 11)):
                pygame.draw.circle(self.screen, (76, 127, 128), (x + dx, y + dy), radius)
                pygame.draw.arc(self.screen, (219, 238, 228), (x + dx - radius, y + dy - radius, radius * 2, radius * 2), 3.2, 5.9, 2)
        elif item["kind"] == "wreck":
            pygame.draw.line(self.screen, (119, 82, 53), (x - 75, y), (x + 75, y + 14), 24)
            pygame.draw.line(self.screen, (183, 133, 79), (x - 48, y - 10), (x - 43, y + 12), 4)
            pygame.draw.line(self.screen, (183, 133, 79), (x, y - 4), (x + 2, y + 18), 4)
            pygame.draw.line(self.screen, (220, 210, 170), (x - 22, y - 12), (x - 8, y - 96), 4)
            pygame.draw.polygon(self.screen, (186, 176, 139), ((x - 8, y - 90), (x - 52, y - 20), (x - 13, y - 18)))
            pygame.draw.line(self.screen, (87, 57, 39), (x - 68, y - 5), (x + 58, y + 8), 2)
        elif item["kind"] == "shell":
            pygame.draw.ellipse(self.screen, (95, 135, 127), (x - 11, y - 4, 22, 13))
            pygame.draw.arc(self.screen, (238, 215, 163), (x - 10, y - 12, 20, 22), 0, math.pi, 3)
            for offset in (-5, 0, 5):
                pygame.draw.line(self.screen, (233, 218, 179), (x + offset, y - 8), (x + offset, y + 3), 1)
        elif item["kind"] == "coral":
            pulse = int((math.sin(phase * 2) + 1) * 2)
            pygame.draw.circle(self.screen, (84, 190, 170), (x, y), 25 + pulse, 1)
            coral = (58, 198, 179) if self.map_name == "forest" else (191, 113, 91)
            for branch in (-1, 0, 1):
                pygame.draw.line(self.screen, coral, (x, y + 11), (x + branch * 12, y - 15 - (1 - abs(branch)) * 11), 5)
                pygame.draw.circle(self.screen, (163, 245, 217), (x + branch * 12, y - 15 - (1 - abs(branch)) * 11), 3)
        elif item["kind"] == "ruin":
            pygame.draw.polygon(self.screen, (92, 157, 145), ((x - 25, y + 12), (x - 20, y - 14), (x - 10, y - 18), (x - 6, y + 12)))
            pygame.draw.polygon(self.screen, (75, 128, 125), ((x + 5, y + 12), (x + 7, y - 18), (x + 19, y - 14), (x + 24, y + 12)))
            pygame.draw.line(self.screen, (115, 204, 185), (x - 25, y - 15), (x + 24, y - 15), 5)
            shine = int((math.sin(phase * 2) + 1) * 20)
            pygame.draw.circle(self.screen, (125, 235, 210), (x, y - 2), 5 + shine // 10)
        elif item["kind"] == "torch":
            pygame.draw.line(self.screen, (98, 61, 39), (x, y + 18), (x, y - 14), 7)
            flicker = math.sin(pygame.time.get_ticks() * 0.018 + phase) * 3
            pygame.draw.polygon(self.screen, (245, 116, 49), ((x - 7, y - 12), (x + flicker, y - 30), (x + 8, y - 12)))
            pygame.draw.polygon(self.screen, (255, 214, 105), ((x - 3, y - 12), (x + flicker, y - 25), (x + 4, y - 12)))
            pygame.draw.circle(self.screen, (255, 170, 80), (x, y - 10), 30, 1)
        elif item["kind"] == "stalactite":
            pygame.draw.polygon(self.screen, (73, 74, 68), ((x - 16, y - 22), (x + 15, y - 19), (x + 2, y + 17)))
            pygame.draw.line(self.screen, (121, 120, 103), (x - 9, y - 18), (x + 1, y + 8), 2)
            shadow_points = ((x - 30, y + 8), (x + 18, y + 1), (x + 76, y + 24), (x + 5, y + 16))
            pygame.draw.polygon(self.screen, (60, 62, 57), shadow_points)
        elif item["kind"] == "puddle":
            ripple = int((math.sin(phase * 1.7) + 1) * 2)
            pygame.draw.ellipse(self.screen, (43, 80, 91), (x - 28, y - 9, 56, 19))
            pygame.draw.ellipse(self.screen, (89, 144, 147), (x - 20, y - 6, 38, 8))
            pygame.draw.arc(self.screen, (185, 226, 211), (x - 13, y - 5, 25, 8 + ripple), 0.1, 2.9, 2)
            pygame.draw.line(self.screen, (219, 212, 174), (x - 8, y - 2), (x + 4, y - 3), 1)
        elif item["kind"] == "lava_crack":
            length = int(28 * scale)
            points = ((x - length, y - 7), (x - 5, y - 2), (x + 2, y + 8), (x + length, y + 5))
            pygame.draw.lines(self.screen, (50, 43, 43), False, points, 9)
            pygame.draw.lines(self.screen, (226, 92, 42), False, points, 4)
            pygame.draw.lines(self.screen, (255, 184, 75), False, points, 1)
        elif item["kind"] == "ash":
            pulse = int((math.sin(phase * 2) + 1) * 2)
            pygame.draw.circle(self.screen, (139, 105, 91), (x, y), 4 + pulse)
        elif item["kind"] == "barrel":
            return

    def draw_entities(self, camera_x: int, camera_y: int) -> None:
        width, height = self.screen.get_size()

        def on_screen(x: float, y: float, margin: float = 48) -> bool:
            sx, sy = x - camera_x, y - camera_y
            return -margin <= sx <= width + margin and -margin <= sy <= height + margin

        if self.player:
            for flame in self.player.fire_trail:
                if not on_screen(flame["x"], flame["y"], flame["radius"] + 8):
                    continue
                fx, fy = int(flame["x"] - camera_x), int(flame["y"] - camera_y)
                pygame.draw.circle(self.screen, (171, 70, 42), (fx, fy), flame["radius"] + 3)
                pygame.draw.circle(self.screen, (245, 139, 60), (fx, fy), flame["radius"] - 3)
                pygame.draw.circle(self.screen, (255, 208, 115), (fx, fy), max(4, flame["radius"] // 3))
        if self.altar is not None and on_screen(self.altar["x"], self.altar["y"], self.altar["radius"]):
            ax, ay = int(self.altar["x"] - camera_x), int(self.altar["y"] - camera_y)
            pygame.draw.circle(self.screen, (206, 145, 72), (ax, ay), self.altar["radius"], 2)
            pygame.draw.polygon(self.screen, (124, 72, 48), ((ax, ay - 22), (ax + 17, ay), (ax, ay + 22), (ax - 17, ay)))
            pygame.draw.circle(self.screen, (255, 210, 113), (ax, ay), 6)
            if self.altar_active > 0:
                self.draw_bar(ax - 48, ay - 40, 96, 7, self.altar_active / 30, (239, 199, 118))
        for orb in self.orbs:
            if not on_screen(orb["x"], orb["y"], 12):
                continue
            x, y = int(orb["x"] - camera_x), int(orb["y"] - camera_y)
            color = (239, 192, 94) if orb.get("coin") else (246, 216, 120)
            if orb.get("coin"):
                pygame.draw.polygon(self.screen, color, ((x, y - 9), (x + 7, y - 5), (x + 7, y + 5), (x, y + 9), (x - 7, y + 5), (x - 7, y - 5)))
                pygame.draw.circle(self.screen, (255, 241, 185), (x, y), 3, 1)
            else:
                pygame.draw.polygon(self.screen, color, ((x, y - 8), (x + 7, y - 1), (x + 3, y + 7), (x - 4, y + 7), (x - 7, y - 1)))
                pygame.draw.line(self.screen, (255, 251, 208), (x - 2, y - 3), (x + 1, y + 3), 2)
        for shot in self.shots:
            if not on_screen(shot["x"], shot["y"], 14):
                continue
            pos = (int(shot["x"] - camera_x), int(shot["y"] - camera_y))
            tip = (pos[0] - int(shot["vx"] * 0.018), pos[1] - int(shot["vy"] * 0.018))
            if shot.get("card"):
                angle = math.atan2(shot["vy"], shot["vx"]) + shot["rotation"]
                half_width = 7 * shot.get("size", 1.0)
                half_height = 11 * shot.get("size", 1.0)
                corners = []
                for local_x, local_y in ((-half_width, -half_height), (half_width, -half_height), (half_width, half_height), (-half_width, half_height)):
                    corners.append((
                        round(pos[0] + local_x * math.cos(angle) - local_y * math.sin(angle)),
                        round(pos[1] + local_x * math.sin(angle) + local_y * math.cos(angle)),
                    ))
                pygame.draw.polygon(self.screen, (247, 239, 211), corners)
                pygame.draw.polygon(self.screen, (151, 64, 61), corners, 2)
                pygame.draw.circle(self.screen, (185, 62, 60), pos, max(2, round(3 * shot.get("size", 1.0))))
                pygame.draw.line(self.screen, (255, 232, 166), tip, pos, 1)
            else:
                pygame.draw.line(self.screen, (217, 225, 215) if shot.get("dagger") else (255, 204, 113), tip, pos, 3 if shot.get("dagger") else 2)
                pygame.draw.circle(self.screen, (255, 249, 213), pos, 3 if shot.get("dagger") else 2)
        if self.player:
            for bomb in self.player.bombs:
                if not on_screen(bomb["x"], bomb["y"], 14):
                    continue
                pos = (int(bomb["x"] - camera_x), int(bomb["y"] - camera_y))
                pygame.draw.polygon(self.screen, (56, 44, 36), ((pos[0] - 9, pos[1] - 4), (pos[0] - 4, pos[1] - 10), (pos[0] + 6, pos[1] - 8), (pos[0] + 10, pos[1] + 1), (pos[0] + 5, pos[1] + 9), (pos[0] - 7, pos[1] + 8)))
                pygame.draw.line(self.screen, (239, 145, 75), (pos[0] + 4, pos[1] - 7), (pos[0] + 10, pos[1] - 13), 2)
                pygame.draw.circle(self.screen, (255, 215, 117), (pos[0] + 10, pos[1] - 13), 2)
            level = self.player.weapon_levels["shell"]
            if level:
                count = 1 + (level - 1) // 2
                for index in range(count):
                    angle = self.player.shell_angle + math.tau * index / count
                    pos = (
                        int(self.player.x - camera_x + math.cos(angle) * 48),
                        int(self.player.y - camera_y + math.sin(angle) * 48),
                    )
                    pygame.draw.circle(self.screen, (198, 230, 215), pos, 10)
                    pygame.draw.circle(self.screen, (75, 151, 152), pos, 6)
        for shot in self.hostile_shots:
            if not on_screen(shot["x"], shot["y"], shot["radius"] + 5):
                continue
            pos = (int(shot["x"] - camera_x), int(shot["y"] - camera_y))
            pygame.draw.circle(self.screen, shot["color"], pos, shot["radius"] + 2)
            pygame.draw.circle(self.screen, (242, 207, 166), pos, max(2, shot["radius"] // 2))
        for chest in self.chests:
            if not on_screen(chest.x, chest.y, 48):
                continue
            self.draw_chest(chest, int(chest.x - camera_x), int(chest.y - camera_y))
        for enemy in self.enemies:
            if not on_screen(enemy.x, enemy.y, enemy.radius + 12):
                continue
            self.draw_enemy(enemy, int(enemy.x - camera_x), int(enemy.y - camera_y))
        if self.boss and on_screen(self.boss.x, self.boss.y, self.boss.radius + 80):
            self.draw_boss_telegraph(self.boss, camera_x, camera_y)
            self.draw_boss(self.boss, int(self.boss.x - camera_x), int(self.boss.y - camera_y))
        if self.player:
            self.draw_player(int(self.player.x - camera_x), int(self.player.y - camera_y))

    def draw_enemy(self, enemy: Enemy, x: int, y: int) -> None:
        r = enemy.radius
        color = (255, 242, 199) if enemy.hit_flash else enemy.color
        if enemy.elite:
            pygame.draw.circle(self.screen, (246, 204, 76), (x, y), r + 8, 2)
        if enemy.burn_timer > 0:
            pygame.draw.circle(self.screen, (255, 111, 49), (x, y), r + 5, 2)
        pygame.draw.ellipse(self.screen, (57, 66, 48), (x - r, y + r // 2, r * 2, r))
        if enemy.kind == "crab":
            claw = int(math.sin(enemy.phase * 2.3) * 5)
            for side in (-1, 1):
                for index in range(3):
                    pygame.draw.line(self.screen, (163, 73, 62), (x + side * 7, y + 3), (x + side * (15 + index * 2), y - 5 + index * 7), 3)
                pygame.draw.line(self.screen, (199, 80, 64), (x + side * 12, y + claw), (x + side * 23, y - 5 + claw), 4)
                pygame.draw.line(self.screen, (199, 80, 64), (x + side * 23, y - 5 + claw), (x + side * 28, y - 10 + claw), 3)
                pygame.draw.line(self.screen, (199, 80, 64), (x + side * 23, y - 5 + claw), (x + side * 29, y + claw), 3)
            pygame.draw.ellipse(self.screen, color, (x - 15, y - 9, 30, 22))
            for side in (-1, 1):
                pygame.draw.circle(self.screen, (238, 207, 151), (x + side * 6, y - 10), 3)
                pygame.draw.circle(self.screen, (40, 43, 38), (x + side * 6, y - 10), 1)
        elif enemy.kind == "pirate":
            walk = int(math.sin(enemy.phase * 2) * 4)
            pygame.draw.line(self.screen, (206, 195, 163), (x - 5, y + 8), (x - 9 + walk, y + 19), 4)
            pygame.draw.line(self.screen, (206, 195, 163), (x + 5, y + 8), (x + 9 - walk, y + 19), 4)
            pygame.draw.line(self.screen, (157, 111, 75), (x - 8, y + 20), (x - 14 + walk, y + 21), 4)
            pygame.draw.line(self.screen, (157, 111, 75), (x + 8, y + 20), (x + 14 - walk, y + 21), 4)
            pygame.draw.ellipse(self.screen, color, (x - 12, y - 12, 24, 32))
            pygame.draw.line(self.screen, (217, 204, 168), (x + 9, y - 1), (x + 17, y + 9), 3)
            pygame.draw.line(self.screen, (171, 181, 176), (x + 17, y + 9), (x + 22, y + 15), 2)
            pygame.draw.line(self.screen, (153, 106, 67), (x + 5, y - 2), (x + 13, y + 5), 3)
            pygame.draw.circle(self.screen, (236, 216, 170), (x, y - 9), 9)
            pygame.draw.polygon(self.screen, (48, 45, 40), ((x - 13, y - 12), (x, y - 25), (x + 13, y - 12)))
            pygame.draw.rect(self.screen, (204, 81, 68), (x - 12, y - 15, 24, 4))
            pygame.draw.line(self.screen, (106, 76, 54), (x - 6, y - 3), (x + 6, y - 3), 2)
            pygame.draw.circle(self.screen, (45, 40, 37), (x, y - 9), 2)
        elif enemy.kind == "gull":
            flap = int(math.sin(enemy.phase * 2) * 9)
            pygame.draw.ellipse(self.screen, color, (x - 12, y - 5, 24, 18))
            pygame.draw.polygon(self.screen, (235, 230, 207), ((x - 4, y), (x - 26, y - 16 - flap), (x - 10, y + 2)))
            pygame.draw.polygon(self.screen, (235, 230, 207), ((x + 4, y), (x + 26, y - 16 - flap), (x + 10, y + 2)))
            pygame.draw.polygon(self.screen, (217, 143, 67), ((x + 8, y - 3), (x + 19, y), (x + 8, y + 3)))
            pygame.draw.circle(self.screen, (228, 218, 194), (x, y - 8), 7)
            pygame.draw.line(self.screen, (174, 63, 53), (x - 8, y - 11), (x + 8, y - 11), 3)
            pygame.draw.circle(self.screen, (41, 42, 38), (x + 3, y - 8), 3)
        elif enemy.kind == "octopus":
            for index in range(6):
                angle = math.tau * index / 6 + enemy.phase * 0.2
                end = (int(x + math.cos(angle) * (r + 12)), int(y + math.sin(angle) * (r + 12)))
                pygame.draw.line(self.screen, (111, 62, 105), (x, y + 5), end, 6)
            pygame.draw.circle(self.screen, color, (x, y), r)
            for dx in (-7, 7):
                pygame.draw.circle(self.screen, (239, 219, 164), (x + dx, y - 4), 4)
                pygame.draw.circle(self.screen, (45, 37, 53), (x + dx, y - 4), 2)
        elif enemy.kind == "skeleton":
            pygame.draw.circle(self.screen, color, (x, y - 8), 10)
            pygame.draw.circle(self.screen, (43, 43, 37), (x - 4, y - 9), 2)
            pygame.draw.circle(self.screen, (43, 43, 37), (x + 4, y - 9), 2)
            pygame.draw.line(self.screen, (226, 217, 183), (x - 5, y + 5), (x + 5, y + 5), 5)
            pygame.draw.line(self.screen, (226, 217, 183), (x, y + 1), (x, y + 16), 4)
            for side in (-1, 1):
                pygame.draw.line(self.screen, (226, 217, 183), (x, y + 6), (x + side * 13, y + 12), 3)
                pygame.draw.line(self.screen, (226, 217, 183), (x + side * 5, y + 14), (x + side * 10, y + 21), 3)
        elif enemy.kind == "sea":
            snake_points = []
            for segment in range(7):
                snake_points.append((
                    x - 29 + segment * 9,
                    y + int(math.sin(enemy.phase * 1.8 - segment * 0.58) * 8),
                ))
            pygame.draw.lines(self.screen, (54, 94, 90), False, snake_points, 17)
            pygame.draw.lines(self.screen, color, False, snake_points, 12)
            head_x, head_y = snake_points[-1]
            pygame.draw.polygon(self.screen, (191, 112, 118), ((head_x + 6, head_y), (head_x + 19, head_y + 4), (head_x + 7, head_y + 7)))
            pygame.draw.circle(self.screen, (246, 218, 142), (head_x + 1, head_y - 5), 3)
            pygame.draw.circle(self.screen, (50, 42, 62), (head_x + 2, head_y - 5), 1)
        elif enemy.kind == "sand_snake":
            points = [(x - 28 + index * 9, y + int(math.sin(enemy.phase * 1.7 - index * 0.6) * 8)) for index in range(7)]
            pygame.draw.lines(self.screen, (122, 89, 51), False, points, 16)
            pygame.draw.lines(self.screen, color, False, points, 11)
            pygame.draw.circle(self.screen, (246, 211, 126), points[-1], 3)
            pygame.draw.polygon(self.screen, (180, 67, 54), ((points[-1][0] + 4, points[-1][1]), (points[-1][0] + 13, points[-1][1] + 4), (points[-1][0] + 4, points[-1][1] + 7)))
        elif enemy.kind == "scorpion":
            pygame.draw.ellipse(self.screen, color, (x - 20, y - 8, 40, 25))
            for side in (-1, 1):
                pygame.draw.line(self.screen, (106, 70, 45), (x + side * 12, y + 5), (x + side * 28, y + 15), 4)
                pygame.draw.line(self.screen, (106, 70, 45), (x + side * 28, y + 15), (x + side * 34, y + 5), 4)
                pygame.draw.line(self.screen, color, (x + side * 14, y - 1), (x + side * 28, y - 11), 5)
                pygame.draw.circle(self.screen, color, (x + side * 31, y - 13), 7)
            pygame.draw.lines(self.screen, color, False, ((x, y - 6), (x + 12, y - 23), (x + 8, y - 35)), 5)
            pygame.draw.polygon(self.screen, (77, 53, 40), ((x + 3, y - 36), (x + 13, y - 33), (x + 9, y - 26)))
        elif enemy.kind == "polar_bear":
            pygame.draw.ellipse(self.screen, color, (x - 24, y - 19, 48, 38))
            pygame.draw.circle(self.screen, (232, 236, 218), (x + 18, y - 11), 15)
            for side in (-1, 1):
                pygame.draw.circle(self.screen, (206, 220, 213), (x + 12 + side * 12, y - 22), 6)
                pygame.draw.line(self.screen, (202, 216, 208), (x + side * 13, y + 7), (x + side * 15, y + 20), 8)
            pygame.draw.circle(self.screen, (42, 58, 63), (x + 28, y - 9), 3)
        elif enemy.kind == "ice_wraith":
            pygame.draw.polygon(self.screen, color, ((x, y - 22), (x + 19, y - 4), (x + 15, y + 17), (x, y + 24), (x - 15, y + 17), (x - 19, y - 4)))
            pygame.draw.polygon(self.screen, (204, 241, 237), ((x, y - 28), (x + 7, y - 9), (x, y - 3), (x - 7, y - 9)))
            pygame.draw.ellipse(self.screen, (31, 77, 98), (x - 9, y - 4, 6, 4))
            pygame.draw.ellipse(self.screen, (31, 77, 98), (x + 3, y - 4, 6, 4))
        elif enemy.kind in ("ash_imp", "fire_wraith"):
            flame = int(math.sin(enemy.phase * 2) * 4)
            pygame.draw.polygon(self.screen, (101, 42, 42), ((x - r, y + 10), (x - r // 2, y - 8), (x, y + flame), (x + r // 2, y - 15), (x + r, y + 12)))
            pygame.draw.polygon(self.screen, color, ((x - r + 4, y + 9), (x - 5, y - 11), (x + r - 4, y + 9)))
            pygame.draw.circle(self.screen, (255, 220, 131), (x - 5, y - 2), 3)
            pygame.draw.circle(self.screen, (255, 220, 131), (x + 5, y - 2), 3)
        else:
            pygame.draw.circle(self.screen, color, (x, y), r)
            for side in (-1, 1):
                pygame.draw.ellipse(self.screen, (81, 74, 125), (x + side * 12 - 6, y, 16, 25))
                pygame.draw.circle(self.screen, (236, 211, 138), (x + side * 8, y - 5), 5)
                pygame.draw.circle(self.screen, (56, 45, 75), (x + side * 8, y - 5), 2)
        if enemy.health < enemy.max_health:
            bar = pygame.Rect(x - r, y - r - 12, r * 2, 4)
            pygame.draw.rect(self.screen, (39, 42, 35), bar)
            pygame.draw.rect(self.screen, (237, 146, 114), (bar.x, bar.y, int(bar.width * enemy.health / enemy.max_health), bar.height))

    def draw_player(self, x: int, y: int) -> None:
        assert self.player is not None
        player = self.player
        pressed = pygame.key.get_pressed()
        moving = pressed[pygame.K_w] or pressed[pygame.K_a] or pressed[pygame.K_s] or pressed[pygame.K_d] or any(
            pressed[key]
            for key in (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT)
        )
        bob = math.sin(player.walk_time) * (3 if moving else 1.5)
        step = int(math.sin(player.walk_time) * 5) if moving else 0
        y = int(y + bob)
        if player.invulnerable and int(player.invulnerable * 18) % 2 == 0:
            return
        pygame.draw.ellipse(self.screen, (55, 69, 46), (x - 18, y + 9, 36, 16))
        pygame.draw.line(self.screen, (93, 70, 51), (x - 4, y + 10), (x - 6 - step, y + 24), 6)
        pygame.draw.line(self.screen, (93, 70, 51), (x + 4, y + 10), (x + 6 + step, y + 24), 6)
        pygame.draw.line(self.screen, (183, 135, 81), (x - 6 - step, y + 24), (x - 13 - step, y + 24), 4)
        pygame.draw.line(self.screen, (183, 135, 81), (x + 6 + step, y + 24), (x + 13 + step, y + 24), 4)
        pygame.draw.ellipse(self.screen, (181, 119, 67), (x - 10, y + 1, 15, 20))
        skin = (226, 184, 145) if player.gender == "woman" else (216, 175, 124)
        pygame.draw.circle(self.screen, skin, (x, y - 7), 10 if player.gender == "man" else 9)
        pygame.draw.line(self.screen, skin, (x - 9, y + 2), (x - 13, y + 12 + step), 5)
        pygame.draw.line(self.screen, skin, (x + 8, y + 2), (x + 12, y + 11 - step), 5)
        pygame.draw.arc(self.screen, (79, 60, 45), (x - 10, y - 19, 20, 17), math.pi, math.tau, 7)
        character_coats = {
            "captain": (207, 110, 79),
            "corsair": (68, 149, 142),
            "sailor": (165, 143, 101),
        }
        coat = character_coats[player.character_id]
        pygame.draw.polygon(self.screen, coat, ((x - 11, y + 1), (x, y - 3), (x + 11, y + 1), (x + 8, y + 16), (x - 8, y + 16)))
        pygame.draw.line(self.screen, (231, 197, 126), (x - 8, y + 6), (x + 8, y + 6), 3)
        pygame.draw.line(self.screen, (247, 221, 172), (x, y + 1), (x, y + 14), 2)
        pygame.draw.circle(self.screen, (78, 62, 47), (x, y + 9), 1)
        pygame.draw.polygon(self.screen, (220, 194, 138), ((x - 10, y + 2), (x - 16, y + 7), (x - 10, y + 9)))
        pygame.draw.circle(self.screen, (45, 64, 53), (x + player.facing * 4, y - 7), 2)
        self.draw_hat(player.hat, x + player.facing, y - 16, player.facing)

    def draw_hat(self, hat: str, x: int, y: int, facing: int) -> None:
        if hat == "none":
            return
        colors = {
            "wool": (180, 91, 75),
            "pirate": (46, 43, 40),
            "straw": (211, 174, 95),
            "top": (48, 46, 43),
        }
        color = colors.get(hat, (211, 174, 95))
        if hat == "wool":
            pygame.draw.circle(self.screen, color, (x, y - 2), 9)
            pygame.draw.rect(self.screen, color, (x - 8, y - 2, 16, 5))
            pygame.draw.circle(self.screen, (239, 199, 118), (x, y - 11), 3)
        elif hat == "pirate":
            pygame.draw.polygon(self.screen, color, ((x - 14, y), (x - 10, y - 9), (x, y - 13), (x + 10, y - 9), (x + 14, y)))
            pygame.draw.rect(self.screen, (183, 70, 58), (x - 13, y - 1, 26, 3))
            pygame.draw.circle(self.screen, (240, 218, 167), (x + facing * 3, y - 7), 2)
        elif hat == "straw":
            pygame.draw.ellipse(self.screen, color, (x - 14, y - 3, 28, 7))
            pygame.draw.ellipse(self.screen, (226, 191, 113), (x - 7, y - 11, 14, 10))
            pygame.draw.line(self.screen, (167, 110, 58), (x - 12, y), (x + 12, y), 2)
        else:
            pygame.draw.rect(self.screen, color, (x - 6, y - 15, 12, 13))
            pygame.draw.rect(self.screen, color, (x - 11, y - 3, 22, 4))
            pygame.draw.rect(self.screen, (173, 75, 66), (x - 6, y - 5, 12, 2))

    def draw_chest(self, chest: Chest, x: int, y: int) -> None:
        pygame.draw.ellipse(self.screen, (57, 54, 38), (x - 25, y + 8, 50, 16))
        if chest.kind == "barrel":
            pygame.draw.ellipse(self.screen, (112, 72, 42), (x - 17, y - 15, 34, 34))
            pygame.draw.ellipse(self.screen, (158, 102, 55), (x - 14, y - 14, 28, 8))
            pygame.draw.ellipse(self.screen, (76, 52, 35), (x - 14, y + 8, 28, 8))
            for offset in (-9, 0, 9):
                pygame.draw.line(self.screen, (92, 63, 39), (x + offset, y - 12), (x + offset, y + 14), 3)
            for offset in (-8, 6):
                pygame.draw.ellipse(self.screen, (192, 148, 86), (x - 20, y + offset, 40, 4))
        else:
            wood = (255, 238, 194) if chest.hit_flash > 0 else (121, 76, 42)
            pygame.draw.polygon(self.screen, wood, ((x - 20, y - 3), (x - 17, y - 12), (x + 17, y - 12), (x + 20, y - 3)))
            pygame.draw.rect(self.screen, wood, (x - 20, y - 4, 40, 22), border_radius=4)
            pygame.draw.rect(self.screen, (172, 118, 61), (x - 20, y - 9, 40, 10), border_radius=5)
            pygame.draw.rect(self.screen, (220, 184, 99), (x - 3, y - 5, 6, 17))
            pygame.draw.rect(self.screen, (52, 43, 31), (x - 21, y - 13, 42, 3))
            pygame.draw.line(self.screen, (202, 156, 89), (x - 14, y + 1), (x - 14, y + 14), 2)
            pygame.draw.line(self.screen, (202, 156, 89), (x + 14, y + 1), (x + 14, y + 14), 2)
        if chest.health < chest.max_health:
            self.draw_bar(x - 21, y - 22, 42, 4, chest.health / chest.max_health, (238, 150, 75))

    def draw_boss(self, boss: Boss, x: int, y: int) -> None:
        r = boss.radius
        color = (255, 235, 195) if boss.hit_flash else boss.color
        pulse = int((math.sin(pygame.time.get_ticks() * 0.008) + 1) * 8)
        pygame.draw.ellipse(self.screen, (45, 32, 44), (x - r - pulse, y + r // 2, r * 2 + pulse * 2, r))
        glow_key = (r, boss.color)
        aura = self.boss_glows.get(glow_key)
        if aura is None:
            aura = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
            pygame.draw.ellipse(aura, (*boss.color, 28), (r // 2, r // 2, r * 3, r * 3))
            self.boss_glows[glow_key] = aura
        aura.set_alpha(170 + pulse * 3)
        self.screen.blit(aura, (x - r * 2, y - r * 2))
        if boss.map_name == "final":
            pygame.draw.ellipse(self.screen, (25, 28, 44), (x - r, y - r // 2, r * 2, r * 2))
            pygame.draw.polygon(self.screen, color, ((x - 62, y + 24), (x - 54, y - 48), (x - 31, y - 67), (x + 33, y - 65), (x + 59, y - 34), (x + 53, y + 31)))
            pygame.draw.arc(self.screen, (212, 211, 222), (x - 32, y - 56, 64, 32), math.pi, math.tau, 8)
            pygame.draw.rect(self.screen, (177, 54, 52), (x - 38, y - 38, 76, 8), border_radius=3)
            pygame.draw.circle(self.screen, (255, 84, 72), (x - 18, y - 15), 6)
            pygame.draw.circle(self.screen, (255, 84, 72), (x + 18, y - 15), 6)
            pygame.draw.line(self.screen, (222, 218, 200), (x + 41, y - 5), (x + 71, y + 28), 5)
            pygame.draw.polygon(self.screen, (199, 205, 209), ((x + 71, y + 28), (x + 79, y + 38), (x + 66, y + 34)))
        elif boss.map_name == "desert":
            pygame.draw.polygon(self.screen, color, ((x - 48, y + 34), (x - 55, y - 20), (x - 27, y - 48), (x + 13, y - 51), (x + 52, y - 15), (x + 42, y + 35)))
            pygame.draw.lines(self.screen, (116, 75, 47), False, ((x - 28, y - 16), (x - 9, y - 2), (x - 21, y + 15)), 4)
            pygame.draw.lines(self.screen, (116, 75, 47), False, ((x + 15, y - 26), (x + 3, y - 8), (x + 25, y + 3)), 4)
            pygame.draw.circle(self.screen, (255, 214, 133), (x - 18, y - 14), 7)
            pygame.draw.circle(self.screen, (255, 214, 133), (x + 19, y - 14), 7)
        elif boss.map_name == "snow":
            pygame.draw.polygon(self.screen, (188, 226, 230), ((x - 50, y + 32), (x - 36, y - 29), (x - 10, y - 46), (x + 17, y - 43), (x + 53, y + 3), (x + 36, y + 38)))
            for side in (-1, 1):
                pygame.draw.polygon(self.screen, (234, 248, 239), ((x + side * 20, y - 23), (x + side * 34, y - 4), (x + side * 22, y - 8)))
                pygame.draw.circle(self.screen, (47, 89, 118), (x + side * 16, y - 9), 5)
            pygame.draw.arc(self.screen, (81, 152, 184), (x - 23, y + 1, 46, 28), 0.1, 3.0, 4)
        else:
            pygame.draw.ellipse(self.screen, color, (x - r, y - r // 2, r * 2, r))
            for side in (-1, 1):
                phase = pygame.time.get_ticks() * 0.003 + side
                end_x = x + side * (r + 28)
                end_y = y + int(math.sin(phase) * 13)
                pygame.draw.lines(self.screen, (81, 58, 122), False, ((x + side * 34, y + 15), (x + side * 50, y + 5), (end_x, end_y)), 10)
                pygame.draw.circle(self.screen, (173, 114, 193), (end_x, end_y), 7)
                pygame.draw.circle(self.screen, (237, 199, 126), (x + side * 22, y - 12), 10)
                pygame.draw.circle(self.screen, (48, 39, 34), (x + side * 22, y - 12), 4)
            eye_pulse = 1 if math.sin(pygame.time.get_ticks() * 0.003) > 0.96 else 0
            pygame.draw.ellipse(self.screen, (246, 67, 66), (x - 26, y - 15, 18, 18 - eye_pulse * 10))
            pygame.draw.ellipse(self.screen, (246, 67, 66), (x + 8, y - 15, 18, 18 - eye_pulse * 10))
            pygame.draw.circle(self.screen, (45, 19, 44), (x - 17, y - 6), 4)
            pygame.draw.circle(self.screen, (45, 19, 44), (x + 17, y - 6), 4)
        self.text(boss.name, (x, y - r - 34), self.fonts["small"], (255, 239, 199), center=True)
        self.draw_bar(x - r, y - r - 25, r * 2, 9, boss.health / boss.max_health, (210, 71, 63))

    def draw_boss_telegraph(self, boss: Boss, camera_x: int, camera_y: int) -> None:
        if not boss.telegraph and boss.charge_timer <= 0:
            return
        if boss.charge_timer > 0:
            target_x, target_y = boss.charge_target
        elif self.player:
            target_x, target_y = self.player.x, self.player.y
        else:
            return
        x, y = int(target_x - camera_x), int(target_y - camera_y)
        pulse = int((math.sin(pygame.time.get_ticks() * 0.025) + 1) * 2)
        warning_color = (104, 205, 232) if boss.map_name == "snow" else (239, 116, 61) if boss.map_name in ("volcano", "final") else (221, 158, 74) if boss.map_name == "desert" else (223, 82, 76)
        pygame.draw.ellipse(self.screen, warning_color, (x - 95, y - 95, 190, 190), 3 + pulse)
        pygame.draw.ellipse(self.screen, warning_color, (x - 72, y - 72, 144, 144), 1)
        pygame.draw.line(self.screen, warning_color, (x - 8, y), (x + 8, y), 2)
        pygame.draw.line(self.screen, warning_color, (x, y - 8), (x, y + 8), 2)

    def draw_hud(self) -> None:
        assert self.player is not None
        player = self.player
        card = pygame.Rect(22, 20, min(415, self.screen.get_width() // 2), 68)
        pygame.draw.rect(self.screen, (9, 31, 32), card, border_radius=8)
        pygame.draw.rect(self.screen, (116, 111, 76), card, 1, border_radius=8)
        pygame.draw.circle(self.screen, (239, 199, 118), (card.x + 27, card.centery), 19, 1)
        self.text("N", (card.x + 27, card.centery), self.fonts["body"], COLORS["gold"], center=True)
        self.draw_bar(card.x + 55, card.y + 19, card.width - 160, 9, self.hud_health, (223, 103, 83))
        self.draw_bar(card.x + 55, card.y + 42, card.width - 123, 8, self.hud_xp, (239, 199, 118))
        self.text(f"{math.ceil(player.health)}/{math.ceil(player.max_health)}", (card.right - 91, card.y + 14), self.fonts["small"])
        self.text(f"NIV. {player.level}", (card.right - 69, card.y + 38), self.fonts["mono"], COLORS["gold"])

        run_card = pygame.Rect(self.screen.get_width() - 176, 20, 128, 68)
        pygame.draw.rect(self.screen, (9, 31, 32), run_card, border_radius=8)
        self.text(f"OLEADA {self.wave}", (run_card.centerx, run_card.y + 21), self.fonts["mono"], COLORS["gold"], center=True)
        self.text(format_time(self.elapsed), (run_card.centerx, run_card.y + 47), self.fonts["body"], center=True)
        self.draw_button("pause", pygame.Rect(self.screen.get_width() - 42, 29, 34, 42), "||", small=True)
        map_title = BIOMES[self.map_name]["title"].upper()
        title_width = 400 if self.boss else 360
        title_height = 49 if self.boss else 35
        title_panel = pygame.Rect((self.screen.get_width() - title_width) // 2, 17, title_width, title_height)
        pygame.draw.rect(self.screen, (9, 31, 32), title_panel, border_radius=7)
        pygame.draw.rect(self.screen, (116, 111, 76), title_panel, 1, border_radius=7)
        if self.boss:
            self.text(self.boss.name.upper(), (self.screen.get_width() // 2, 29), self.fonts["mono"], COLORS["gold"], center=True)
            self.draw_bar(
                self.screen.get_width() // 2 - 180, 48, 360, 10,
                self.boss.health / self.boss.max_health, (207, 72, 62),
            )
        else:
            self.text(f"{map_title}  ·  SUPERVIVE Y EXPLORA", (self.screen.get_width() // 2, 34), self.fonts["small"], COLORS["gold"], center=True)
        dash_label = "DASH LISTO" if self.player.dash_cooldown <= 0 else f"DASH {self.player.dash_cooldown:.1f}s"
        self.text(f"WASD · ESPACIO {dash_label} · E ALTAR · ESC PAUSA", (22, self.screen.get_height() - 26), self.fonts["mono"], COLORS["ink"])
        self.text(f"ENEMIGOS: {len(self.enemies)}", (self.screen.get_width() - 22, self.screen.get_height() - 26), self.fonts["mono"], COLORS["ink"], anchor="topright")
        self.text(f"DOBLONES: {self.run_coins}", (22, self.screen.get_height() - 51), self.fonts["mono"], COLORS["gold"])
        dash_ratio = 1.0 if player.dash_cooldown <= 0 else 1 - player.dash_cooldown / 3.5
        self.draw_bar(23, self.screen.get_height() - 63, 100, 4, dash_ratio, (102, 206, 174))
        if self.pickup_notice_time > 0:
            self.text(
                self.pickup_notice,
                (self.screen.get_width() // 2, self.screen.get_height() - 132),
                self.fonts["mono"],
                COLORS["gold"],
                center=True,
            )
        self.draw_active_weapons()
        if self.altar and self.altar_active <= 0:
            if math.hypot(self.altar["x"] - player.x, self.altar["y"] - player.y) < self.altar["radius"] + 60:
                self.text("PULSA E PARA ACTIVAR EL ALTAR", (self.screen.get_width() // 2, self.screen.get_height() - 68), self.fonts["mono"], COLORS["gold"], center=True)
        if self.notice:
            self.text(self.notice, (self.screen.get_width() // 2, self.screen.get_height() - 100), self.fonts["small"], COLORS["gold"], center=True)
        self.draw_biome_compass()

    def draw_active_weapons(self) -> None:
        assert self.player is not None
        weapons = [("pistol", "PIST"), ("dagger", "DAG"), ("bomb", "BOMB"), ("shell", "CON"), ("fire", "RON")]
        active = [(key, label) for key, label in weapons if key == "pistol" or self.player.weapon_levels[key] > 0]
        y = self.screen.get_height() - 104
        for index, (key, label) in enumerate(active):
            rect = pygame.Rect(22 + index * 60, y, 54, 36)
            pygame.draw.rect(self.screen, (9, 31, 32), rect, border_radius=5)
            pygame.draw.rect(self.screen, (116, 111, 76), rect, 1, border_radius=5)
            self.text(label, (rect.centerx, rect.y + 9), self.fonts["small"], COLORS["ink"], center=True)
            level = 1 if key == "pistol" else self.player.weapon_levels[key]
            self.text(f"NIV {level}", (rect.centerx, rect.y + 25), self.fonts["mono"], COLORS["gold"], center=True)

    def draw_biome_compass(self) -> None:
        assert self.player is not None
        rect = pygame.Rect(self.screen.get_width() - 298, 103, 250, 57)
        pygame.draw.rect(self.screen, (9, 31, 32), rect, border_radius=7)
        pygame.draw.rect(self.screen, (116, 111, 76), rect, 1, border_radius=7)
        track = pygame.Rect(rect.x + 18, rect.y + 12, rect.width - 36, 9)
        pygame.draw.rect(self.screen, BIOMES["snow"]["ground"], (track.x, track.y, track.width // 3, track.height), border_radius=4)
        pygame.draw.rect(self.screen, BIOMES["forest"]["ground"], (track.x + track.width // 3, track.y, track.width // 3, track.height))
        pygame.draw.rect(self.screen, BIOMES["desert"]["ground"], (track.x + 2 * track.width // 3, track.y, track.width - 2 * track.width // 3, track.height), border_radius=4)
        marker_x = track.x + int((self.player.x / WORLD_WIDTH) * track.width)
        pygame.draw.circle(self.screen, COLORS["ink"], (marker_x, track.centery), 5)
        pygame.draw.circle(self.screen, COLORS["gold"], (marker_x, track.centery), 3)
        biome = self.biome_at(self.player.x, self.player.y)
        self.text("O TUNDRA  ·  N VOLCAN  ·  E DESIERTO", (rect.centerx, rect.y + 30), self.fonts["small"], COLORS["muted"], center=True)
        self.text(f"BIOMA: {BIOMES[biome]['title'].upper()}", (rect.centerx, rect.y + 47), self.fonts["mono"], COLORS["gold"], center=True)

    def draw_bar(self, x: int, y: int, width: int, height: int, fraction: float, color: tuple[int, int, int]) -> None:
        pygame.draw.rect(self.screen, (36, 43, 37), (x, y, width, height), border_radius=5)
        pygame.draw.rect(self.screen, color, (x, y, int(width * clamp(fraction, 0, 1)), height), border_radius=5)

    def draw_overlay(
        self,
        alpha: int = 165,
        max_width: int = 570,
        max_height: int = 570,
    ) -> pygame.Rect:
        self.screen.blit(self.get_overlay_surface(alpha, (5, 23, 27)), (0, 0))
        width, height = self.screen.get_size()
        panel = pygame.Rect(0, 0, min(max_width, width - 40), min(max_height, height - 40))
        panel.center = (width // 2, height // 2)
        pygame.draw.rect(self.screen, (12, 34, 35), panel, border_radius=8)
        pygame.draw.rect(self.screen, (98, 104, 77), panel, 1, border_radius=8)
        return panel

    def get_overlay_surface(self, alpha: int, color: tuple[int, int, int]) -> pygame.Surface:
        size = self.screen.get_size()
        key = (size, alpha, color)
        overlay = self.overlay_surfaces.get(key)
        if overlay is None:
            overlay = pygame.Surface(size, pygame.SRCALPHA)
            overlay.fill((*color, alpha))
            self.overlay_surfaces[key] = overlay
        return overlay

    def draw_menu(self) -> None:
        self.screen.blit(self.get_overlay_surface(142, (5, 22, 24)), (0, 0))
        left = max(40, int(self.screen.get_width() * 0.1))
        height = self.screen.get_height()
        menu_width = min(350, max(270, int(self.screen.get_width() * 0.31)))
        self.text("UNA AVENTURA DE SUPERVIVENCIA", (left, height * 0.13), self.fonts["mono"], (127, 231, 205))
        title_rect = self.text("NÁUFRAGO", (left - 3, height * 0.20), self.fonts["title"], (255, 238, 190))
        pygame.draw.line(
            self.screen,
            (245, 158, 91),
            (title_rect.left + 5, title_rect.bottom + 5),
            (title_rect.left + min(title_rect.width - 8, 210), title_rect.bottom + 5),
            4,
        )
        self.text("Una isla. Un náufrago. Ninguna tregua.", (left + 3, height * 0.39), self.fonts["body"], (231, 224, 199))
        self.text("SOBREVIVE A LA MAREA", (left + 3, height * 0.44), self.fonts["mono"], (244, 190, 112))
        button_y = max(int(height * 0.51), height - 286)
        entries = (
            ("start", "JUGAR", True),
            ("character", "PERSONAJES / TIENDA", False),
            ("settings", "CONFIGURACIÓN", False),
            ("howto", "CÓMO JUGAR", False),
        )
        for index, (action, label, primary) in enumerate(entries):
            rect = pygame.Rect(left, button_y + index * 51, menu_width, 45)
            self.draw_button(action, rect, label, primary=primary)
        self.draw_menu_illustration(
            pygame.Rect(
                max(left + menu_width + 48, self.screen.get_width() * 0.57),
                int(height * 0.15),
                min(440, self.screen.get_width() - max(left + menu_width + 70, int(self.screen.get_width() * 0.57)) - 38),
                int(height * 0.66),
            )
        )
        selected = CHARACTERS[self.profile.data["selected_character"]]["name"].upper()
        profile_label = f"DOBLONES  {self.profile.coins}   ·   {selected}"
        pygame.draw.line(self.screen, (116, 155, 124), (left, height - 47), (left + menu_width, height - 47), 1)
        coin_x, coin_y = left + 8, height - 25
        pygame.draw.circle(self.screen, (244, 190, 112), (coin_x, coin_y), 8, 2)
        pygame.draw.line(self.screen, (244, 190, 112), (coin_x - 3, coin_y), (coin_x + 3, coin_y), 2)
        self.text(profile_label, (left + 24, height - 28), self.fonts["mono"], COLORS["gold"])

    def draw_menu_illustration(self, rect: pygame.Rect) -> None:
        if rect.width < 190 or rect.height < 190:
            return
        pygame.draw.rect(self.screen, (10, 42, 45), rect, border_radius=18)
        pygame.draw.rect(self.screen, (69, 146, 128), rect, 2, border_radius=18)
        inner = rect.inflate(-12, -12)
        pygame.draw.rect(self.screen, (19, 69, 70), inner, border_radius=14)
        for band in range(4):
            y = rect.y + rect.height * 0.59 + band * 17
            pygame.draw.arc(
                self.screen,
                (56 + band * 8, 153 + band * 8, 146 + band * 6),
                (rect.x + 23 + band * 6, int(y), rect.width - 46 - band * 12, 72),
                math.pi,
                math.tau,
                2,
            )

        island_y = rect.y + int(rect.height * 0.58)
        pygame.draw.ellipse(self.screen, (31, 50, 43), (rect.x + 44, island_y - 31, rect.width - 88, 78))
        pygame.draw.ellipse(self.screen, (178, 151, 91), (rect.x + 58, island_y - 40, rect.width - 116, 65))
        pygame.draw.ellipse(self.screen, (94, 139, 74), (rect.x + 92, island_y - 38, rect.width - 184, 51))
        palm_x = rect.centerx - 18
        palm_y = island_y - 26
        pygame.draw.line(self.screen, (104, 70, 45), (palm_x, palm_y + 24), (palm_x + 5, palm_y - 32), 8)
        for angle in (-2.8, -2.15, -1.55, -0.9, -0.25):
            end = (int(palm_x + 37 * math.cos(angle)), int(palm_y - 31 + 22 * math.sin(angle)))
            pygame.draw.line(self.screen, (55, 112, 65), (palm_x + 5, palm_y - 32), end, 7)
            pygame.draw.line(self.screen, (103, 164, 82), (palm_x + 5, palm_y - 32), end, 2)
        wreck_x = rect.x + int(rect.width * 0.28)
        wreck_y = island_y - 4
        pygame.draw.polygon(self.screen, (110, 65, 42), ((wreck_x - 27, wreck_y), (wreck_x + 24, wreck_y + 3), (wreck_x + 12, wreck_y + 17), (wreck_x - 17, wreck_y + 14)))
        pygame.draw.line(self.screen, (204, 174, 120), (wreck_x, wreck_y), (wreck_x + 4, wreck_y - 37), 3)
        pygame.draw.polygon(self.screen, (232, 221, 184), ((wreck_x + 3, wreck_y - 34), (wreck_x - 12, wreck_y - 6), (wreck_x + 3, wreck_y - 8)))
        pygame.draw.circle(self.screen, (255, 192, 105), (rect.right - 37, rect.y + 36), 16)
        pygame.draw.circle(self.screen, (255, 231, 176), (rect.right - 37, rect.y + 36), 21, 1)
        for angle in range(0, 360, 45):
            dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            pygame.draw.line(
                self.screen,
                (255, 216, 148),
                (rect.right - 37 + int(dx * 24), rect.y + 36 + int(dy * 24)),
                (rect.right - 37 + int(dx * 29), rect.y + 36 + int(dy * 29)),
                2,
            )
        for index, (label, accent) in enumerate((
            ("4 BIOMAS POR EXPLORAR", (115, 225, 197)),
            ("ARMAS Y MEJORAS", (255, 205, 125)),
            ("JEFES Y TESOROS", (242, 139, 111)),
        )):
            badge = pygame.Rect(rect.x + 28, rect.y + 82 + index * 34, min(204, rect.width - 70), 25)
            pygame.draw.rect(self.screen, (12, 48, 51), badge, border_radius=8)
            pygame.draw.rect(self.screen, accent, badge, 1, border_radius=8)
            pygame.draw.circle(self.screen, accent, (badge.x + 12, badge.centery), 3)
            self.text(label, (badge.x + 24, badge.centery), self.fonts["mono"], (232, 239, 214), center=False)
        self.text("BITÁCORA DE SUPERVIVENCIA", (rect.centerx, rect.y + 27), self.fonts["mono"], (255, 234, 186), center=True)
        self.text("EXPLORA  ·  RESISTE  ·  SOBREVIVE", (rect.centerx, rect.bottom - 29), self.fonts["small"], (197, 225, 192), center=True)

    def draw_character(self) -> None:
        panel = self.draw_overlay(178, max_width=1050, max_height=570)
        x, y = panel.x + 35, panel.y + 24
        self.text("ARMARIO DEL NÁUFRAGO", (x, y), self.fonts["mono"], COLORS["gold"])
        self.text("Personaje", (x, y + 35), self.fonts["heading"])
        self.text(f"DOBLONES  {self.profile.coins}", (panel.right - 225, y + 12), self.fonts["mono"], COLORS["gold"])

        gender_y = y + 91
        self.text("APARIENCIA", (x, gender_y), self.fonts["mono"], COLORS["muted"])
        for gender, label, offset in (("man", "HOMBRE", 0), ("woman", "MUJER", 156)):
            selected = self.profile.data["gender"] == gender
            self.draw_button(
                f"gender:{gender}",
                pygame.Rect(x + offset, gender_y + 25, 142, 39),
                label,
                primary=selected,
            )

        preview_x, preview_y = panel.right - 104, y + 70 + int(math.sin(pygame.time.get_ticks() * 0.003) * 3)
        character_color = {
            "captain": (207, 110, 79),
            "corsair": (68, 149, 142),
            "sailor": (165, 143, 101),
        }[self.profile.data["selected_character"]]
        pygame.draw.ellipse(self.screen, (42, 56, 42), (preview_x - 26, preview_y + 25, 52, 19))
        pygame.draw.polygon(self.screen, character_color, ((preview_x - 16, preview_y), (preview_x, preview_y - 8), (preview_x + 16, preview_y), (preview_x + 12, preview_y + 28), (preview_x - 12, preview_y + 28)))
        preview_skin = (226, 184, 145) if self.profile.data["gender"] == "woman" else (216, 175, 124)
        pygame.draw.circle(self.screen, preview_skin, (preview_x, preview_y - 14), 13)
        pygame.draw.arc(self.screen, (79, 60, 45), (preview_x - 13, preview_y - 27, 26, 22), math.pi, math.tau, 8)
        self.draw_hat(self.profile.data["selected_hat"], preview_x, preview_y - 33, 1)
        self.text("ELIGE TU AVENTURERO", (x, y + 164), self.fonts["mono"], COLORS["muted"])
        character_gap = 12
        character_width = min(275, (panel.width - 78) // len(CHARACTERS))
        character_y = y + 185
        for index, (character_id, character) in enumerate(CHARACTERS.items()):
            rect = pygame.Rect(x + index * (character_width + character_gap), character_y, character_width, 70)
            selected = self.profile.data["selected_character"] == character_id
            unlocked = character_id in self.profile.data["unlocked_characters"]
            self.buttons[f"character:{character_id}"] = rect
            pygame.draw.rect(self.screen, (37, 68, 55) if selected else (24, 47, 43), rect, border_radius=5)
            pygame.draw.rect(self.screen, COLORS["gold"] if selected else (76, 92, 75), rect, 2 if selected else 1, border_radius=5)
            self.text(character["name"], (rect.x + 10, rect.y + 9), self.fonts["body"], COLORS["ink"])
            self.text(character["description"], (rect.x + 10, rect.y + 36), self.fonts["small"], COLORS["muted"])
            status = "SELECCIONADO" if selected else "USAR" if unlocked else f"DESBLOQUEAR · {character['price']} D"
            self.text(status, (rect.right - 8, rect.y + 58), self.fonts["mono"], COLORS["gold"], anchor="topright")

        self.text("ARMA INICIAL", (x, y + 261), self.fonts["mono"], COLORS["muted"])
        weapon_y = y + 282
        weapon_width = min(185, (panel.width - 90) // len(WEAPONS))
        weapon_gap = 10
        for index, (weapon_id, weapon) in enumerate(WEAPONS.items()):
            rect = pygame.Rect(x + index * (weapon_width + weapon_gap), weapon_y, weapon_width, 54)
            selected = self.profile.data["selected_weapon"] == weapon_id
            unlocked = weapon_id in self.profile.data["unlocked_weapons"]
            self.buttons[f"weapon:{weapon_id}"] = rect
            pygame.draw.rect(self.screen, (37, 68, 55) if selected else (24, 47, 43), rect, border_radius=5)
            pygame.draw.rect(self.screen, COLORS["gold"] if selected else (76, 92, 75), rect, 2 if selected else 1, border_radius=5)
            self.wrap_text(
                weapon["name"],
                pygame.Rect(rect.x + 4, rect.y + 4, rect.width - 8, 30),
                self.fonts["small"],
                COLORS["ink"],
                center=True,
            )
            status = "EQUIPADA" if selected else "USAR" if unlocked else f"{weapon['price']} DOBLONES"
            self.text(status, (rect.centerx, rect.bottom - 10), self.fonts["mono"], COLORS["gold"], center=True)

        self.text("SOMBREROS", (x, y + 340), self.fonts["mono"], COLORS["muted"])
        hat_y = y + 361
        card_width = min(190, (panel.width - 82) // 5)
        gap = 10
        for index, hat in enumerate(HAT_ORDER):
            rect = pygame.Rect(x + index * (card_width + gap), hat_y, card_width, 111)
            selected = self.profile.data["selected_hat"] == hat
            color = (37, 68, 55) if selected else (24, 47, 43)
            pygame.draw.rect(self.screen, color, rect, border_radius=5)
            pygame.draw.rect(self.screen, COLORS["gold"] if selected else (76, 92, 75), rect, 1, border_radius=5)
            self.draw_hat(hat, rect.centerx, rect.y + 37, 1)
            self.text(HATS[hat]["name"], (rect.centerx, rect.y + 68), self.fonts["small"], center=True)
            unlocked = hat in self.profile.data["unlocked_hats"]
            label = "EQUIPADO" if selected else "USAR" if unlocked else f"COMPRAR · {HATS[hat]['price']}"
            self.text(label, (rect.centerx, rect.y + 91), self.fonts["mono"], COLORS["gold"], center=True)
            self.buttons[f"hat:{hat}"] = rect

        if self.notice:
            self.text(self.notice, (panel.centerx, panel.bottom - 34), self.fonts["small"], COLORS["gold"], center=True)
        self.draw_button("back", pygame.Rect(panel.right - 150, panel.bottom - 51, 112, 34), "VOLVER", primary=False)

    def draw_talent_icon(
        self,
        icon: str,
        center: tuple[int, int],
        color: tuple[int, int, int],
    ) -> None:
        x, y = center
        if icon == "heart":
            pygame.draw.polygon(self.screen, color, ((x, y + 10), (x - 15, y - 2), (x - 15, y - 9), (x - 8, y - 14), (x, y - 8), (x + 8, y - 14), (x + 15, y - 9), (x + 15, y - 2)))
            pygame.draw.line(self.screen, (255, 224, 177), (x - 7, y - 5), (x - 2, y - 9), 2)
        elif icon == "boot":
            pygame.draw.polygon(self.screen, color, ((x - 13, y - 11), (x - 4, y - 13), (x, y - 2), (x + 13, y + 2), (x + 13, y + 9), (x - 14, y + 9), (x - 16, y + 4)))
            pygame.draw.line(self.screen, (232, 234, 203), (x - 6, y - 5), (x + 2, y - 1), 2)
            pygame.draw.line(self.screen, color, (x - 17, y - 13), (x - 22, y - 17), 2)
            pygame.draw.line(self.screen, color, (x - 19, y - 7), (x - 25, y - 7), 2)
        elif icon == "potion":
            pygame.draw.rect(self.screen, (174, 211, 142), (x - 6, y - 14, 12, 5), border_radius=2)
            pygame.draw.polygon(self.screen, color, ((x - 5, y - 9), (x + 5, y - 9), (x + 12, y + 8), (x + 8, y + 13), (x - 8, y + 13), (x - 12, y + 8)))
            pygame.draw.line(self.screen, (213, 239, 170), (x - 4, y + 5), (x + 4, y + 5), 2)
            pygame.draw.circle(self.screen, (225, 239, 183), (x + 15, y - 11), 2)
            pygame.draw.circle(self.screen, (225, 239, 183), (x + 18, y - 16), 1)
        elif icon == "swords":
            pygame.draw.line(self.screen, color, (x - 11, y - 13), (x + 9, y + 8), 4)
            pygame.draw.line(self.screen, (238, 226, 188), (x - 13, y - 15), (x + 7, y + 6), 1)
            pygame.draw.line(self.screen, color, (x + 11, y - 13), (x - 9, y + 8), 4)
            pygame.draw.line(self.screen, (238, 226, 188), (x + 13, y - 15), (x - 7, y + 6), 1)
            pygame.draw.line(self.screen, (133, 83, 53), (x - 13, y + 5), (x - 5, y + 13), 3)
            pygame.draw.line(self.screen, (133, 83, 53), (x + 13, y + 5), (x + 5, y + 13), 3)
        else:
            pygame.draw.arc(self.screen, color, (x - 14, y - 13, 28, 27), -1.2, 1.2, 5)
            pygame.draw.line(self.screen, color, (x - 15, y - 10), (x - 15, y + 10), 5)
            for dx, dy in ((14, -10), (18, 0), (14, 10)):
                pygame.draw.polygon(self.screen, (239, 199, 118), ((x + dx, y + dy), (x + dx + 4, y + dy - 3), (x + dx + 4, y + dy + 3)))

    def draw_howto(self) -> None:
        panel = self.draw_overlay()
        x, y = panel.x + 40, panel.y + 34
        self.text("GUÍA DE CAMPO", (x, y), self.fonts["mono"], COLORS["gold"])
        self.text("Cómo jugar", (x, y + 42), self.fonts["heading"])
        instructions = [
            ("Muévete", "Usa WASD o las flechas para explorar la isla."),
            ("Esquiva", "Pulsa ESPACIO o SHIFT para hacer un dash; recarga en 3,5 segundos."),
            ("Sobrevive", "Tu personaje ataca automáticamente al enemigo más cercano."),
            ("Crece", "Derrota enemigos para ganar experiencia y subir de nivel."),
            ("Elige una mejora", "Cada nivel te permite escoger una mejora."),
            ("Explora", "Bosque, desierto, tundra y volcán tienen eventos y jefes propios."),
            ("Desafía", "Activa altares con E y derrota a Barbanegra al minuto 20."),
        ]
        for index, (title, detail) in enumerate(instructions):
            yy = y + 117 + index * 48
            self.text(title, (x, yy), self.fonts["body"], COLORS["gold"])
            self.text(detail, (x, yy + 21), self.fonts["small"], COLORS["muted"])
        self.draw_button("back", pygame.Rect(panel.centerx - 100, panel.bottom - 66, 200, 43), "VOLVER")

    def draw_settings(self) -> None:
        panel = self.draw_overlay()
        x, y = panel.x + 40, panel.y + 40
        self.text("AJUSTES DE SUPERVIVENCIA", (x, y), self.fonts["mono"], COLORS["gold"])
        self.text("Configuración", (x, y + 42), self.fonts["heading"])
        rows = [
            ("master", "Volumen general", "Todos los sonidos"),
            ("effects_volume", "Efectos", "Disparos, daño y hallazgos"),
            ("music_volume", "Música", "Ambiente de la isla"),
        ]
        for index, (name, label, detail) in enumerate(rows):
            yy = y + 132 + index * 85
            self.text(label, (x, yy), self.fonts["body"])
            self.text(detail, (x, yy + 25), self.fonts["small"], COLORS["muted"])
            rect = pygame.Rect(panel.right - 190, yy + 8, 135, 12)
            pygame.draw.rect(self.screen, (54, 67, 56), rect, border_radius=5)
            value = getattr(self.audio, name)
            pygame.draw.rect(self.screen, COLORS["gold"], (rect.x, rect.y, int(rect.width * value), rect.height), border_radius=5)
            pygame.draw.circle(self.screen, (255, 235, 180), (int(rect.x + rect.width * value), rect.centery), 8)
            self.sliders[name] = rect
            self.text(f"{round(value * 100)}%", (rect.right + 12, rect.y - 4), self.fonts["small"], COLORS["gold"])
        self.draw_button("back", pygame.Rect(panel.centerx - 100, panel.bottom - 66, 200, 43), "VOLVER")

    def draw_pause(self) -> None:
        panel = self.draw_overlay(185)
        self.text("RESPIRA, NÁUFRAGO", (panel.centerx, panel.y + 77), self.fonts["mono"], COLORS["gold"], center=True)
        self.text("En pausa", (panel.centerx, panel.y + 125), self.fonts["heading"], center=True)
        self.text("La isla espera. Por ahora.", (panel.centerx, panel.y + 177), self.fonts["small"], COLORS["muted"], center=True)
        self.draw_button("resume", pygame.Rect(panel.centerx - 145, panel.y + 220, 290, 48), "CONTINUAR")
        self.draw_button("pause_settings", pygame.Rect(panel.centerx - 145, panel.y + 278, 290, 45), "CONFIGURACIÓN", primary=False)
        self.draw_button("menu", pygame.Rect(panel.centerx - 145, panel.y + 333, 290, 45), "VOLVER AL MENÚ", primary=False)

    def draw_levelup(self) -> None:
        panel = self.draw_overlay(205, max_width=650, max_height=590)
        pygame.draw.line(self.screen, (76, 156, 132), (panel.x + 38, panel.y + 39), (panel.right - 38, panel.y + 39), 1)
        self.text("HALLAZGO DE SUPERVIVENCIA", (panel.centerx, panel.y + 25), self.fonts["mono"], (113, 225, 197), center=True)
        for x in (panel.centerx - 144, panel.centerx + 144):
            pygame.draw.polygon(self.screen, (113, 225, 197), ((x, panel.y + 20), (x + 5, panel.y + 25), (x, panel.y + 30), (x - 5, panel.y + 25)))
        self.text("¡Subiste de nivel!", (panel.centerx, panel.y + 69), self.fonts["heading"], (255, 239, 199), center=True)
        self.text("Elige una carta y haz tuya la isla.", (panel.centerx, panel.y + 108), self.fonts["small"], (195, 214, 193), center=True)
        card_width = min(155, (panel.width - 56) // 3)
        gap = 12
        total = card_width * 3 + gap * 2
        start_x = panel.centerx - total // 2
        card_y = panel.y + 132
        card_height = min(340, panel.height - 196)
        body_colors = {
            "común": (35, 49, 55),
            "poco común": (30, 55, 43),
            "raro": (25, 48, 69),
            "épico": (48, 34, 67),
            "legendario": (68, 49, 23),
        }
        for index, upgrade in enumerate(self.choices):
            key, title, detail, icon = upgrade
            rect = pygame.Rect(start_x + index * (card_width + gap), card_y, card_width, card_height)
            rarity, rarity_color = self.choice_rarities.get(key, UPGRADE_RARITIES[0][:2])
            hover = rect.collidepoint(pygame.mouse.get_pos())
            lift = 8 if hover else 0
            card = rect.move(0, -lift)
            body = body_colors.get(rarity, body_colors["común"])
            pygame.draw.rect(self.screen, (5, 17, 23), card.move(0, 5), border_radius=12)
            pygame.draw.rect(self.screen, body, card, border_radius=12)
            header_rect = pygame.Rect(card.x + 2, card.y + 2, card.width - 4, 33)
            pygame.draw.rect(self.screen, rarity_color, header_rect, border_top_left_radius=10, border_top_right_radius=10)
            pygame.draw.rect(self.screen, rarity_color, card, 2 if hover else 1, border_radius=12)
            pygame.draw.line(self.screen, tuple(min(255, c + 45) for c in rarity_color), (card.x + 13, card.y + 39), (card.right - 13, card.y + 39), 1)
            if hover:
                pygame.draw.rect(self.screen, tuple(min(255, c + 35) for c in rarity_color), card.inflate(9, 9), 1, border_radius=14)
            pygame.draw.circle(self.screen, tuple(max(0, c // 3) for c in rarity_color), (card.centerx, card.y + 91), 39)
            pygame.draw.circle(self.screen, rarity_color, (card.centerx, card.y + 91), 33, 1)
            rarity_label = rarity.upper().replace("Ú", "U").replace("É", "E")
            self.text(rarity_label, (card.centerx, card.y + 19), self.fonts["mono"], body, center=True)
            self.draw_upgrade_icon(key, card.centerx, card.y + 91, rarity_color, pygame.time.get_ticks() * 0.001)
            self.wrap_text(
                title,
                pygame.Rect(card.x + 12, card.y + 142, card.width - 24, 48),
                self.fonts["body"],
                (255, 245, 218),
                center=True,
            )
            pygame.draw.line(self.screen, tuple(max(0, c // 2) for c in rarity_color), (card.x + 17, card.y + 196), (card.right - 17, card.y + 196), 1)
            self.wrap_text(
                detail.replace("·", " / ").translate(str.maketrans(
                    "áéíóúÁÉÍÓÚñÑ",
                    "aeiouAEIOUnN",
                )),
                pygame.Rect(card.x + 12, card.y + 204, card.width - 24, 54),
                self.fonts["small"],
                (207, 218, 210),
                center=True,
            )
            if rarity == "legendario":
                for spark in range(3):
                    sx = card.x + 12 + (pygame.time.get_ticks() // 18 + spark * 47) % max(1, card.width - 24)
                    sy = card.y + 49 + (spark * 27) % 88
                    pygame.draw.circle(self.screen, (255, 236, 160), (sx, sy), 2)
            cue_y = card.bottom - 22
            pygame.draw.line(self.screen, tuple(max(0, c // 2) for c in rarity_color), (card.x + 17, cue_y - 10), (card.right - 17, cue_y - 10), 1)
            self.text("ELEGIR", (card.centerx, cue_y + 1), self.fonts["mono"], rarity_color, center=True)
            self.buttons[f"upgrade:{key}"] = card
        self.text(
            "ELIGE UNA CARTA PARA CONTINUAR",
            (panel.centerx, panel.bottom - 25),
            self.fonts["mono"],
            (169, 197, 177),
            center=True,
        )

    def draw_upgrade_icon(
        self,
        key: str,
        x: int,
        y: int,
        color: tuple[int, int, int],
        time: float,
    ) -> None:
        pulse = math.sin(time * 4) * 2
        if key in ("projectiles", "card_damage", "card_speed", "card_size", "card_pierce", "card_burn"):
            pygame.draw.rect(self.screen, (245, 237, 210), (x - 19, y - 27, 38, 54), border_radius=4)
            pygame.draw.rect(self.screen, color, (x - 19, y - 27, 38, 54), 2, border_radius=4)
            pygame.draw.circle(self.screen, (190, 61, 59) if key == "card_burn" else color, (x, y), 7)
            pygame.draw.circle(self.screen, color, (x - 11, y - 19), 2)
            pygame.draw.circle(self.screen, color, (x + 11, y + 19), 2)
            if key == "card_burn":
                pygame.draw.polygon(self.screen, (255, 134, 54), ((x - 4, y + 9), (x, y - 3), (x + 4, y + 2), (x + 8, y - 8), (x + 7, y + 10)))
        elif key in ("max_health", "regen", "healing"):
            self.draw_talent_icon("heart", (x, y), color)
            if key != "max_health":
                pygame.draw.line(self.screen, (241, 248, 217), (x - 17, y), (x + 17, y), 3)
                pygame.draw.line(self.screen, (241, 248, 217), (x, y - 17), (x, y + 17), 3)
        elif key == "armor":
            pygame.draw.polygon(self.screen, color, ((x, y - 29), (x + 25, y - 17), (x + 20, y + 11), (x, y + 29), (x - 20, y + 11), (x - 25, y - 17)))
            pygame.draw.lines(self.screen, (245, 237, 210), True, ((x, y - 18), (x + 15, y - 10), (x + 12, y + 7), (x, y + 20), (x - 12, y + 7), (x - 15, y - 10)), 2)
        elif key in ("dagger", "damage"):
            pygame.draw.polygon(self.screen, color, ((x - 28, y + 24), (x + 18, y - 25), (x + 8, y + 1)))
            pygame.draw.line(self.screen, (244, 235, 204), (x - 21, y + 19), (x + 15, y - 20), 2)
            pygame.draw.line(self.screen, (127, 86, 52), (x - 15, y + 17), (x - 28, y + 30), 5)
            pygame.draw.ellipse(self.screen, (239, 199, 118), (x - 8, y - 6, 16, 12), 2)
        elif key == "bomb":
            pygame.draw.polygon(self.screen, (88, 57, 43), ((x - 18, y - 4), (x - 12, y - 19), (x + 11, y - 19), (x + 18, y - 4), (x + 14, y + 20), (x - 14, y + 20)))
            pygame.draw.arc(self.screen, (168, 120, 74), (x - 20, y - 10, 40, 42), 0, math.pi, 3)
            pygame.draw.line(self.screen, (211, 162, 97), (x + 3, y - 18), (x + 16, y - 28), 4)
            pygame.draw.polygon(self.screen, (255, 135, 63), ((x + 15, y - 28), (x + 25, y - 34 - int(abs(pulse))), (x + 24, y - 21)))
        elif key in ("shell", "projectiles"):
            pygame.draw.arc(self.screen, color, (x - 24, y - 24, 48, 48), 0.2, math.pi * 1.8, 7)
            pygame.draw.lines(self.screen, (230, 238, 208), False, ((x - 18, y + 9), (x - 7, y + 1), (x + 1, y - 9), (x + 10, y - 18)), 3)
            pygame.draw.circle(self.screen, color, (x + 17, y - 16), 8)
        elif key == "speed":
            pygame.draw.polygon(self.screen, color, ((x - 26, y - 11), (x - 7, y - 11), (x + 2, y + 2), (x + 20, y + 7), (x + 23, y + 18), (x - 17, y + 18), (x - 25, y + 8)))
            for offset in (-17, -8):
                pygame.draw.line(self.screen, (212, 231, 231), (x + offset, y - 17), (x + offset + 14, y - 17), 2)
        elif key in ("eye", "magnet"):
            pygame.draw.arc(self.screen, color, (x - 29, y - 17, 58, 36), 0, math.pi * 2, 4)
            pygame.draw.circle(self.screen, color, (x, y), 11)
            pygame.draw.circle(self.screen, (239, 199, 118), (x, y), 4)
            for angle in range(0, 360, 45):
                dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
                pygame.draw.line(self.screen, color, (x + dx * 22, y + dy * 22), (x + dx * 29, y + dy * 29), 2)
        else:
            self.draw_talent_icon("heart", (x, y), color)
            pygame.draw.line(self.screen, (244, 230, 193), (x - 20, y - 25), (x + 22, y + 21), 3)
            pygame.draw.line(self.screen, (244, 230, 193), (x + 20, y - 24), (x - 22, y + 21), 3)

    def draw_gameover(self) -> None:
        panel = self.draw_overlay(205)
        assert self.player is not None
        self.text("LA ISLA RECLAMA LO SUYO", (panel.centerx, panel.y + 49), self.fonts["mono"], COLORS["gold"], center=True)
        self.text("Fin del viaje", (panel.centerx, panel.y + 88), self.fonts["heading"], center=True)
        stats = (
            ("TIEMPO SOBREVIVIDO", format_time(self.elapsed)),
            ("OLEADA ALCANZADA", str(self.wave)),
            ("NIVEL", str(self.player.level)),
            ("ENEMIGOS DERROTADOS", str(self.kills)),
        )
        for index, (label, value) in enumerate(stats):
            col, row = index % 2, index // 2
            rect = pygame.Rect(panel.x + 34 + col * (panel.width // 2), panel.y + 154 + row * 69, panel.width // 2 - 50, 56)
            pygame.draw.rect(self.screen, (24, 46, 42), rect, border_radius=4)
            self.text(label, (rect.centerx, rect.y + 8), self.fonts["small"], COLORS["muted"], center=True)
            self.text(value, (rect.centerx, rect.y + 30), self.fonts["body"], COLORS["gold"], center=True)
        self.draw_button("retry", pygame.Rect(panel.centerx - 140, panel.y + 307, 280, 43), "REINTENTAR")
        self.draw_button("menu", pygame.Rect(panel.centerx - 140, panel.y + 359, 280, 43), "VOLVER AL MENÚ", primary=False)

    def draw_victory(self) -> None:
        panel = self.draw_overlay(205)
        assert self.player is not None
        self.text("EL MAR RECUERDA TU NOMBRE", (panel.centerx, panel.y + 62), self.fonts["mono"], COLORS["gold"], center=True)
        self.text("¡VICTORIA!", (panel.centerx, panel.y + 111), self.fonts["heading"], COLORS["ink"], center=True)
        self.text("Barbanegra ha caído. La travesía continúa.", (panel.centerx, panel.y + 169), self.fonts["body"], COLORS["muted"], center=True)
        self.text(
            f"TIEMPO {format_time(self.elapsed)}   ·   OLEADA {self.wave}   ·   NIVEL {self.player.level}",
            (panel.centerx, panel.y + 220), self.fonts["mono"], COLORS["gold"], center=True,
        )
        self.text(f"DOBLONES ASEGURADOS: {self.last_run_coins}", (panel.centerx, panel.y + 261), self.fonts["body"], COLORS["ink"], center=True)
        self.draw_button("retry", pygame.Rect(panel.centerx - 140, panel.y + 315, 280, 43), "NUEVA PARTIDA")
        self.draw_button("menu", pygame.Rect(panel.centerx - 140, panel.y + 367, 280, 43), "VOLVER AL MENÚ", primary=False)

    def draw_button(self, action: str, rect: pygame.Rect, label: str, primary: bool = True, small: bool = False) -> None:
        hovered = rect.collidepoint(pygame.mouse.get_pos())
        fill = (255, 210, 121) if hovered else (239, 178, 88) if primary else (31, 88, 79) if hovered else (16, 52, 52)
        border = (255, 237, 185) if primary else (104, 190, 158) if hovered else (76, 126, 111)
        pygame.draw.rect(self.screen, (7, 22, 27), rect.move(0, 4), border_radius=9)
        pygame.draw.rect(self.screen, fill, rect, border_radius=9)
        pygame.draw.rect(self.screen, border, rect, 2 if hovered or primary else 1, border_radius=9)
        pygame.draw.line(self.screen, tuple(min(255, channel + 22) for channel in fill), (rect.x + 12, rect.y + 3), (rect.right - 12, rect.y + 3), 1)
        if primary and rect.width >= 140:
            x, y = rect.x + 23, rect.centery
            pygame.draw.polygon(self.screen, (115, 67, 37), ((x - 4, y - 7), (x + 7, y), (x - 4, y + 7)))
            text_center = (rect.centerx + 7, rect.centery)
            color = (48, 48, 38)
        else:
            if not primary and rect.width >= 150:
                pygame.draw.circle(self.screen, border, (rect.x + 20, rect.centery), 3 if hovered else 2)
                text_center = (rect.centerx + 4, rect.centery)
            else:
                text_center = rect.center
            color = (255, 244, 216)
        self.text(label, text_center, self.fonts["small"] if small else self.fonts["mono"], color, center=True)
        self.buttons[action] = rect

    def text(
        self,
        value: str,
        position: tuple[float, float],
        font: pygame.font.Font,
        color: tuple[int, int, int] = COLORS["ink"],
        center: bool = False,
        anchor: str | None = None,
    ) -> pygame.Rect:
        image = font.render(value, True, color)
        rect = image.get_rect()
        if center:
            rect.center = (int(position[0]), int(position[1]))
        elif anchor == "topright":
            rect.topright = (int(position[0]), int(position[1]))
        else:
            rect.topleft = (int(position[0]), int(position[1]))
        self.screen.blit(image, rect)
        return rect

    def wrap_text(
        self,
        value: str,
        rect: pygame.Rect,
        font: pygame.font.Font,
        color: tuple[int, int, int],
        center: bool = False,
    ) -> None:
        words = value.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if font.size(candidate)[0] > rect.width and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        for index, line in enumerate(lines[:3]):
            position = (
                (rect.centerx, rect.y + index * (font.get_linesize() + 2))
                if center else (rect.x, rect.y + index * (font.get_linesize() + 2))
            )
            self.text(line, position, font, color, center=center)


if __name__ == "__main__":
    Game().run()
