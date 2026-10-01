import json
import tempfile
import unittest
from pathlib import Path

from profile import ProfileStore


class ProfileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "profile.json"
        self.profile = ProfileStore(self.path)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_new_profile_has_only_cosmetics_and_unlockable_loadouts(self) -> None:
        self.assertEqual(self.profile.data["unlocked_hats"], ["none"])
        self.assertEqual(self.profile.data["unlocked_characters"], ["captain"])
        self.assertEqual(self.profile.data["selected_character"], "captain")
        self.assertEqual(self.profile.data["unlocked_weapons"], ["pistol"])
        self.assertEqual(self.profile.data["selected_weapon"], "pistol")
        self.assertNotIn("health_talent", self.profile.data)
        self.assertNotIn("selected_map", self.profile.data)
        self.assertNotIn("global_level", self.profile.data)

    def test_coins_and_cosmetics_persist(self) -> None:
        self.profile.earn_coins(50)
        self.assertTrue(self.profile.spend_coins(20))
        self.profile.data["selected_hat"] = "straw"
        self.profile.data["unlocked_hats"].append("straw")
        self.profile.save()

        loaded = ProfileStore(self.path)
        self.assertEqual(loaded.coins, 30)
        self.assertEqual(loaded.data["unlocked_hats"], ["none", "straw"])
        self.assertEqual(loaded.data["selected_hat"], "straw")

    def test_legacy_gameplay_upgrades_and_map_progress_are_ignored(self) -> None:
        self.path.write_text(json.dumps({
            "coins": 10,
            "health_talent": 5,
            "damage_talent": 4,
            "selected_map": "pirate_cave",
            "unlocked_maps": ["desert_island", "pirate_cave"],
        }), encoding="utf-8")

        migrated = ProfileStore(self.path)
        self.assertEqual(migrated.data["coins"], 10)
        self.assertNotIn("health_talent", migrated.data)
        self.assertNotIn("selected_map", migrated.data)
        self.assertEqual(migrated.data["unlocked_hats"], ["none"])
        self.assertEqual(migrated.data["unlocked_characters"], ["captain"])
        self.assertEqual(migrated.data["unlocked_weapons"], ["pistol"])

    def test_only_known_unlocked_characters_and_weapons_are_restored(self) -> None:
        self.path.write_text(json.dumps({
            "unlocked_characters": ["captain", "corsair", "unknown"],
            "selected_character": "corsair",
            "unlocked_weapons": ["pistol", "dagger", "unknown"],
            "selected_weapon": "dagger",
        }), encoding="utf-8")
        loaded = ProfileStore(self.path)

        self.assertEqual(loaded.data["selected_character"], "corsair")
        self.assertIn("corsair", loaded.data["unlocked_characters"])
        self.assertEqual(loaded.data["selected_weapon"], "dagger")
        self.assertNotIn("unknown", loaded.data["unlocked_weapons"])


if __name__ == "__main__":
    unittest.main()
