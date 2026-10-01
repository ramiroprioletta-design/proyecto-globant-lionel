from __future__ import annotations

import json
import sys
from pathlib import Path


HATS = {
    "none": {"name": "Sin sombrero", "price": 0},
    "wool": {"name": "Gorro de lana", "price": 20},
    "pirate": {"name": "Boina pirata", "price": 35},
    "straw": {"name": "Sombrero de paja", "price": 45},
    "top": {"name": "Sombrero de copa", "price": 70},
}


class ProfileStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path.home() / ".naufrago" / "profile.json"
        self.data = self._load()

    @staticmethod
    def defaults() -> dict:
        return {
            "version": 3,
            "coins": 0,
            "gender": "man",
            "unlocked_hats": ["none"],
            "selected_hat": "none",
            "unlocked_characters": ["captain"],
            "selected_character": "captain",
            "unlocked_weapons": ["pistol"],
            "selected_weapon": "pistol",
        }

    def _load(self) -> dict:
        if not self.path.exists():
            return self.defaults()
        try:
            with self.path.open("r", encoding="utf-8") as save_file:
                raw = json.load(save_file)
        except (OSError, json.JSONDecodeError) as error:
            print(f"No se pudo leer el perfil ({self.path}): {error}. Se usará un perfil nuevo.", file=sys.stderr)
            return self.defaults()
        if not isinstance(raw, dict):
            print(f"El perfil {self.path} no tiene un formato válido. Se usará un perfil nuevo.", file=sys.stderr)
            return self.defaults()
        return self._sanitize(raw)

    def _sanitize(self, raw: dict) -> dict:
        data = self.defaults()
        if isinstance(raw.get("coins"), int):
            data["coins"] = max(0, raw["coins"])
        if raw.get("gender") in ("man", "woman"):
            data["gender"] = raw["gender"]
        unlocked_hats = raw.get("unlocked_hats")
        if isinstance(unlocked_hats, list):
            data["unlocked_hats"] = sorted(
                {"none"} | {hat for hat in unlocked_hats if isinstance(hat, str) and hat in HATS}
            )
        selected_hat = raw.get("selected_hat")
        if selected_hat in data["unlocked_hats"]:
            data["selected_hat"] = selected_hat
        unlocked_characters = raw.get("unlocked_characters")
        if isinstance(unlocked_characters, list):
            data["unlocked_characters"] = sorted(
                {"captain"} | {
                    character
                    for character in unlocked_characters
                    if character in ("captain", "corsair", "sailor")
                }
            )
        selected_character = raw.get("selected_character")
        if selected_character in data["unlocked_characters"]:
            data["selected_character"] = selected_character
        unlocked_weapons = raw.get("unlocked_weapons")
        if isinstance(unlocked_weapons, list):
            data["unlocked_weapons"] = sorted(
                {"pistol"} | {
                    weapon
                    for weapon in unlocked_weapons
                    if weapon in ("pistol", "dagger", "bomb", "shell", "fire")
                }
            )
        selected_weapon = raw.get("selected_weapon")
        if selected_weapon in data["unlocked_weapons"]:
            data["selected_weapon"] = selected_weapon
        return data

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as save_file:
                json.dump(self.data, save_file, ensure_ascii=False, indent=2)
            temporary.replace(self.path)
        except OSError as error:
            raise RuntimeError(f"No se pudo guardar el progreso en {self.path}: {error}") from error

    @property
    def coins(self) -> int:
        return self.data["coins"]

    def earn_coins(self, amount: int) -> None:
        self.data["coins"] += max(0, amount)
        self.save()

    def spend_coins(self, amount: int) -> bool:
        if amount < 0 or self.coins < amount:
            return False
        self.data["coins"] -= amount
        self.save()
        return True
