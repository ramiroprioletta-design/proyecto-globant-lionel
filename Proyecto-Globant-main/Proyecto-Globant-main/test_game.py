import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from main import BIOMES, ISLAND_CENTER, MAX_PARTICLES, WORLD_HEIGHT, WORLD_WIDTH, Boss, Chest, Enemy, Game
from profile import ProfileStore
from world import coastline, world_contains
from vfx import VFXManager


class GameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.game = Game()
        self.game.profile = ProfileStore(Path(self.directory.name) / "profile.json")

    def tearDown(self) -> None:
        pygame.display.quit()
        self.directory.cleanup()

    def test_cosmetics_do_not_change_fixed_starting_stats(self) -> None:
        self.game.profile.data["coins"] = 100
        self.game.profile.save()
        self.game.activate("gender:woman")
        self.game.activate("hat:straw")
        self.game.start_game()

        self.assertEqual(self.game.profile.coins, 55)
        self.assertEqual(self.game.player.max_health, 100)
        self.assertEqual(self.game.player.speed, 230)
        self.assertEqual(self.game.player.damage, 23)
        self.assertNotIn("talent:health_talent", self.game.buttons)

    def test_main_menu_draws_before_a_game_starts(self) -> None:
        self.assertEqual(self.game.screen_state, "menu")
        self.game.draw()
        self.assertIn((self.game.screen.get_size(), 142, (5, 22, 24)), self.game.overlay_surfaces)
        self.assertIn("start", self.game.buttons)
        self.assertIn("character", self.game.buttons)
        self.assertIsNotNone(self.game.flash_surface)

    def test_single_world_has_gradual_biomes_and_hard_bounds(self) -> None:
        self.game.start_game()
        self.assertEqual((self.game.player.x, self.game.player.y), ISLAND_CENTER)
        self.assertEqual(self.game.biome_at(ISLAND_CENTER[0]), "forest")
        self.assertEqual(self.game.biome_at(100), "snow")
        self.assertEqual(self.game.biome_at(WORLD_WIDTH - 100), "desert")
        snow = self.game.terrain_color(ISLAND_CENTER[0] - 1800)
        forest = self.game.terrain_color(ISLAND_CENTER[0])
        desert = self.game.terrain_color(ISLAND_CENTER[0] + 1800)
        self.assertNotEqual(snow, forest)
        self.assertNotEqual(desert, forest)

        self.game.player.x = -200
        self.game.player.y = WORLD_HEIGHT + 200
        self.game.keep_player_on_island()
        self.assertGreaterEqual(self.game.player.x, self.game.player.radius)
        self.assertLessEqual(self.game.player.y, WORLD_HEIGHT - self.game.player.radius)
        self.assertTrue(world_contains(*ISLAND_CENTER))
        self.assertFalse(world_contains(0, 0))
        self.assertEqual(len(coastline()), 128)

    def test_spawns_are_exclusive_to_the_current_biome(self) -> None:
        self.game.start_game()
        assert self.game.player is not None
        for x, biome, expected in (
            (ISLAND_CENTER[0], "forest", {"crab", "skeleton", "pirate"}),
            (ISLAND_CENTER[0] + 2200, "desert", {"sand_snake", "scorpion", "gull"}),
            (ISLAND_CENTER[0] - 2200, "snow", {"polar_bear", "ice_wraith"}),
        ):
            self.game.enemies.clear()
            self.game.player.x = x
            for _ in range(16):
                self.game.spawn_enemy()
            self.assertTrue({enemy.kind for enemy in self.game.enemies} <= expected, biome)
            self.assertTrue(self.game.enemies)

    def test_enemy_health_and_damage_scale_with_survival_time(self) -> None:
        early = Enemy("crab", 0, 0, 1, "forest", 0)
        late = Enemy("crab", 0, 0, 1, "forest", 900)
        self.assertGreater(late.max_health, early.max_health)
        self.assertGreater(late.damage, early.damage)
        self.assertGreater(late.speed, early.speed)

    def test_auto_attack_defeats_enemy_and_awards_experience(self) -> None:
        self.game.start_game()
        assert self.game.player is not None
        enemy = Enemy("crab", self.game.player.x + 35, self.game.player.y, 1, "forest")
        enemy.health = 1
        self.game.enemies.append(enemy)
        self.game.attack_timer = 0
        with patch("main.random.random", return_value=0.0):
            for _ in range(4):
                self.game.update(0.04)

        self.assertEqual(self.game.kills, 1)
        self.assertNotIn(enemy, self.game.enemies)
        self.assertIn(enemy, self.game.enemy_pool)
        self.assertTrue(self.game.orbs or self.game.player.xp > 0)

    def test_chest_rewards_and_in_run_weapon_upgrades(self) -> None:
        self.game.start_game()
        assert self.game.player is not None
        chest = Chest(self.game.player.x + 30, self.game.player.y)
        self.game.chests.append(chest)
        self.game.damage_target(chest, chest.max_health + 1)

        self.assertNotIn(chest, self.game.chests)
        self.assertGreaterEqual(len(self.game.orbs), 10)
        self.game.player.weapon_levels.update(dagger=1, bomb=1, shell=1)
        self.game.enemies.append(Enemy("skeleton", self.game.player.x + 80, self.game.player.y, 1, "forest"))
        self.game.throw_bomb()
        self.assertEqual(len(self.game.player.bombs), 1)
        self.game.draw()

    def test_level_up_pauses_and_pause_freezes_simulation(self) -> None:
        self.game.start_game()
        assert self.game.player is not None
        self.game.player.xp = self.game.player.xp_to_next - 1
        self.game.gain_experience(1)
        self.assertEqual(self.game.screen_state, "levelup")
        self.assertEqual(len(self.game.choices), 3)
        self.game.draw()
        self.assertTrue(all(f"upgrade:{choice[0]}" in self.game.buttons for choice in self.game.choices))
        self.game.apply_upgrade(self.game.choices[0][0])
        self.assertEqual(self.game.screen_state, "playing")
        self.game.screen_state = "paused"
        elapsed = self.game.elapsed
        self.game.update(1.0)
        self.assertEqual(self.game.elapsed, elapsed)
        self.game.draw()

    def test_boss_milestone_and_second_phase_patterns(self) -> None:
        self.game.start_game()
        self.game.elapsed = 299.99
        self.game.update(0.02)
        self.assertIsInstance(self.game.boss, Boss)
        assert self.game.boss is not None
        self.assertEqual(self.game.boss.name, BIOMES["forest"]["boss"])
        self.game.boss.health = self.game.boss.max_health / 2
        self.game.boss.attack_timer = 0
        self.game.boss.attack_index = 2
        self.game.hostile_shots.clear()
        self.game.update_boss(0.01)
        self.assertEqual(self.game.boss.phase, 2)
        self.assertGreaterEqual(len(self.game.hostile_shots), 13)

    def test_boss_victory_continues_the_world_and_banks_cosmetic_currency(self) -> None:
        self.game.start_game()
        assert self.game.player is not None
        self.game.spawn_boss("forest")
        assert self.game.boss is not None
        self.game.boss.health = 1
        self.game.shots.append({
            "x": self.game.boss.x,
            "y": self.game.boss.y,
            "vx": 0,
            "vy": 0,
            "damage": 5,
            "life": 1,
            "pierce": 0,
            "hit_ids": set(),
            "critical": False,
        })
        self.game.update_projectiles(0.01)

        self.assertEqual(self.game.screen_state, "playing")
        self.assertIn("forest", self.game.defeated_biomes)
        self.assertEqual(self.game.run_coins, 35)
        self.game.activate("menu")
        self.assertEqual(self.game.profile.coins, 35)

    def test_dash_works_and_obeys_three_and_a_half_second_cooldown(self) -> None:
        class Keys:
            def __getitem__(self, key: int) -> bool:
                return key == pygame.K_SPACE

        self.game.start_game()
        assert self.game.player is not None
        start_x = self.game.player.x
        with patch("main.pygame.key.get_pressed", return_value=Keys()):
            self.game.update(0.05)
            self.assertGreater(self.game.player.x, start_x + 20)
            self.assertAlmostEqual(self.game.player.dash_cooldown, 3.5)
            self.game.update(0.05)
            self.assertAlmostEqual(self.game.player.dash_cooldown, 3.45)

    def test_walking_updates_footsteps_and_crosses_into_desert(self) -> None:
        class Keys:
            def __getitem__(self, key: int) -> bool:
                return key == pygame.K_d

        self.game.start_game()
        assert self.game.player is not None
        self.game.player.x = ISLAND_CENTER[0] + 680
        with patch("main.pygame.key.get_pressed", return_value=Keys()):
            for _ in range(8):
                self.game.update(0.1)

        self.assertGreater(self.game.player.x, ISLAND_CENTER[0] + 700)
        self.assertEqual(self.game.map_name, "desert")
        self.assertTrue(self.game.footprints)

    def test_deep_biome_exploration_summons_its_regional_boss(self) -> None:
        self.game.start_game()
        assert self.game.player is not None
        self.game.player.x = ISLAND_CENTER[0] + 2050
        self.game.update(0.01)
        self.assertIsNotNone(self.game.boss)
        self.assertEqual(self.game.boss.name, BIOMES["desert"]["boss"])

    def test_snow_boss_attack_leaves_a_freezing_area(self) -> None:
        self.game.start_game()
        assert self.game.player is not None
        self.game.boss = Boss("snow", 3, self.game.player.x + 450, self.game.player.y)
        self.game.boss.attack_index = 2
        self.game.boss.attack_timer = 0
        self.game.update_boss(0.01)
        self.assertTrue(any(hazard.get("slow") for hazard in self.game.hazards))
        self.assertTrue(any(shot.get("ice") for shot in self.game.hostile_shots))

    def test_particle_cap_and_projectile_pool(self) -> None:
        self.game.add_particles(0, 0, (255, 255, 255), 80)
        self.assertEqual(len(self.game.particles), MAX_PARTICLES)
        shot = {"x": 1, "life": 1}
        self.game.launch_projectile(self.game.shots, shot)
        projectile = self.game.shots.pop()
        self.game.recycle_projectile(projectile)
        self.game.launch_projectile(self.game.shots, {"x": 2, "life": 1})
        self.assertIs(self.game.shots[0], projectile)

    def test_vfx_particles_are_bounded_recycled_and_drawable(self) -> None:
        effects = VFXManager()
        effects.burst(20, 30, (255, 210, 120), 100, "shard")
        self.assertEqual(len(effects.particles), MAX_PARTICLES)
        effects.update(1.0)
        self.assertEqual(effects.particles, [])
        self.assertEqual(len(effects.pool), MAX_PARTICLES)
        effects.burst(20, 30, (255, 210, 120), 1)
        self.assertEqual(len(effects.particles), 1)
        effects.draw(pygame.Surface((80, 60)), (0, 0))
        effects.request_shake(8)
        self.assertLessEqual(max(map(abs, effects.camera_offset())), 3)

    def test_critical_hit_feedback_and_hit_stop_pause_simulation(self) -> None:
        self.game.start_game()
        assert self.game.player is not None
        enemy = Enemy("crab", self.game.player.x + 100, self.game.player.y, 1, "forest")
        self.game.enemies.append(enemy)
        self.game.damage_target(enemy, 10, critical=True)
        self.assertTrue(self.game.damage_numbers[-1]["critical"])
        self.assertGreater(self.game.vfx.hit_stop, 0)
        elapsed = self.game.elapsed
        self.game.update(0.02)
        self.assertEqual(self.game.elapsed, elapsed)
        self.assertLess(self.game.vfx.hit_stop, 0.045)

    def test_character_unlocks_are_persistent_but_only_change_run_loadout(self) -> None:
        self.game.profile.earn_coins(100)
        self.game.select_character("corsair")
        self.game.start_game()

        assert self.game.player is not None
        self.assertEqual(self.game.player.max_health, 75)
        self.assertEqual(self.game.player.speed, 276)
        self.assertEqual(self.game.player.crit_chance, 0.2)
        self.assertEqual(self.game.player.weapon_levels["dagger"], 1)
        self.assertEqual(self.game.profile.coins, 10)

    def test_weapon_unlock_is_saved_and_equipped_as_next_run_starting_weapon(self) -> None:
        self.game.profile.earn_coins(40)
        self.game.select_weapon("dagger")
        self.game.start_game()

        assert self.game.player is not None
        self.assertEqual(self.game.player.weapon_levels["dagger"], 1)
        self.assertEqual(self.game.profile.coins, 5)
        self.assertEqual(self.game.profile.data["selected_weapon"], "dagger")

    def test_volcano_biome_spawns_its_own_enemy_family(self) -> None:
        self.game.start_game()
        self.game.player.y = 100
        self.assertEqual(self.game.biome_at(self.game.player.x, self.game.player.y), "volcano")
        for _ in range(20):
            self.game.spawn_enemy()

        self.assertTrue(self.game.enemies)
        self.assertTrue({enemy.kind for enemy in self.game.enemies} <= {"ash_imp", "fire_wraith"})

    def test_final_boss_at_twenty_minutes_can_complete_the_run(self) -> None:
        self.game.start_game()
        self.game.elapsed = 1199.99
        self.game.update(0.02)
        self.assertIsNotNone(self.game.boss)
        assert self.game.boss is not None
        self.assertEqual(self.game.boss.map_name, "final")
        self.game.run_coins = 15
        self.game.damage_target(self.game.boss, self.game.boss.max_health + 1)

        self.assertEqual(self.game.screen_state, "victory")
        self.assertEqual(self.game.profile.coins, 50)
        self.assertTrue(self.game.player.banked)
        self.game.draw()
        self.assertIn("menu", self.game.buttons)

    def test_altar_challenge_awards_one_run_artifact(self) -> None:
        self.game.start_game()
        assert self.game.player is not None
        self.game.altar = {
            "x": self.game.player.x,
            "y": self.game.player.y,
            "radius": 145,
            "challenge": 0,
        }
        self.game.activate_altar()
        self.assertEqual(self.game.altar_active, 30)
        self.game.update_altar(30)

        self.assertEqual(len(self.game.artifacts), 1)
        self.assertEqual(self.game.run_coins, 15)
        self.assertIsNone(self.game.altar)

    def test_meteor_telegraph_deals_one_impact_not_repeated_damage(self) -> None:
        self.game.start_game()
        assert self.game.player is not None
        self.game.hazards.append({
            "x": self.game.player.x,
            "y": self.game.player.y,
            "radius": 70,
            "color": (239, 105, 55),
            "timer": 0.01,
            "life": 1.0,
            "kind": "meteor",
        })
        health = self.game.player.health
        self.game.update_map_hazards(0.02)
        self.assertEqual(self.game.player.health, health - 22)
        self.game.player.invulnerable = 0
        self.game.update_map_hazards(0.05)
        self.assertEqual(self.game.player.health, health - 22)

    def test_fire_trail_damages_nearby_enemy(self) -> None:
        self.game.start_game()
        assert self.game.player is not None
        enemy = Enemy("crab", self.game.player.x + 10, self.game.player.y, 1, "forest")
        self.game.enemies.append(enemy)
        self.game.player.weapon_levels["fire"] = 1
        self.game.add_fire_patch(enemy.x, enemy.y)
        health = enemy.health
        self.game.update_fire_trail(0.01)

        self.assertLess(enemy.health, health)

    def test_epic_card_changes_its_mechanical_upgrade_strength(self) -> None:
        self.game.start_game()
        assert self.game.player is not None
        original_speed = self.game.player.speed
        self.game.choice_rarities["speed"] = ("épico", (183, 111, 242))
        self.game.apply_upgrade("speed")

        self.assertAlmostEqual(self.game.player.speed, original_speed * 1.28)

    def test_state_manager_rejects_unknown_states(self) -> None:
        with self.assertRaises(ValueError):
            self.game.screen_state = "not-a-state"

    def test_ctrl_c_closes_game_and_banks_run_coins_without_traceback(self) -> None:
        self.game.start_game()
        self.game.run_coins = 7
        with (
            patch.object(self.game, "clock", Mock(tick=Mock(side_effect=KeyboardInterrupt))),
            patch("main.pygame.quit") as quit_game,
        ):
            self.game.run()

        self.assertFalse(self.game.running)
        self.assertEqual(self.game.profile.coins, 7)
        quit_game.assert_called_once()

    def test_rendering_shows_biome_hud_and_cosmetics_without_talents(self) -> None:
        self.game.start_game()
        assert self.game.player is not None
        self.game.enemies.extend(
            Enemy(kind, self.game.player.x + 90 + index * 35, self.game.player.y, 3, biome)
            for index, (kind, biome) in enumerate((
                ("sand_snake", "desert"), ("scorpion", "desert"),
                ("polar_bear", "snow"), ("ice_wraith", "snow"),
                ("gull", "desert"),
            ))
        )
        self.game.boss = Boss("snow", 4)
        self.game.draw()
        self.assertIn("forest", self.game.biome_at(self.game.player.x))
        self.game.activate("character")
        self.game.draw()
        self.assertFalse(any(action.startswith("talent:") for action in self.game.buttons))
        self.game.activate("howto")
        self.game.draw()
        self.game.end_game()
        self.game.draw()


if __name__ == "__main__":
    unittest.main()
