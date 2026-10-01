from __future__ import annotations


GAME_STATES = {
    "menu",
    "character",
    "howto",
    "settings",
    "pause_settings",
    "playing",
    "paused",
    "levelup",
    "gameover",
    "victory",
}


class GameStateManager:
    def __init__(self, initial: str = "menu") -> None:
        self._state = "menu"
        self.set(initial)

    @property
    def state(self) -> str:
        return self._state

    def set(self, state: str) -> None:
        if state not in GAME_STATES:
            raise ValueError(f"Estado de juego desconocido: {state}")
        self._state = state
