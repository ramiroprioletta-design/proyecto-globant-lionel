from __future__ import annotations

WIDTH, HEIGHT = 1280, 720
WORLD_WIDTH, WORLD_HEIGHT = 6400, 6400
ISLAND_CENTER = (WORLD_WIDTH // 2, WORLD_HEIGHT // 2)
FPS = 60
FIXED_DT = 1 / FPS
MAX_ENEMIES = 180
MAX_PROJECTILES = 240
MAX_PARTICLES = 60
MAX_ORBS = 240

BIOMES = {
    "forest": {
        "title": "Bosque costero",
        "center": ISLAND_CENTER[0],
        "ground": (100, 137, 77),
        "accent": (221, 194, 131),
        "water": (14, 78, 87),
        "boss": "Kraken de la Orilla",
        "boss_color": (119, 79, 149),
    },
    "desert": {
        "title": "Desierto de Calaveras",
        "center": ISLAND_CENTER[0] + 1500,
        "ground": (207, 171, 103),
        "accent": (232, 207, 148),
        "water": (14, 78, 87),
        "boss": "Gólem de Arena y Roca",
        "boss_color": (194, 120, 66),
    },
    "snow": {
        "title": "Tundra helada",
        "center": ISLAND_CENTER[0] - 1500,
        "ground": (166, 195, 200),
        "accent": (217, 229, 221),
        "water": (38, 78, 101),
        "boss": "Gran Kraken Helado",
        "boss_color": (89, 158, 192),
    },
    "volcano": {
        "title": "Volcán Sombrío",
        "center": ISLAND_CENTER[0],
        "ground": (76, 64, 64),
        "accent": (207, 98, 54),
        "water": (14, 58, 68),
        "boss": "Titán de Ceniza",
        "boss_color": (190, 76, 54),
    },
}

COLORS = {
    "ink": (247, 240, 215),
    "muted": (184, 197, 177),
    "gold": (239, 199, 118),
    "deep": (12, 34, 35),
    "panel": (12, 34, 35),
    "sand": (220, 193, 126),
    "grass": (91, 127, 69),
}

UPGRADES = [
    ("speed", "Paso ligero", "+20% velocidad de movimiento", ">"),
    ("eye", "Buen ojo", "+20% alcance · +10% crítico", "O"),
    ("projectiles", "Mano de naipes", "+1 carta por lanzamiento", ">>"),
    ("max_health", "Corazón de hierro", "+20 vida máxima y curación", "+"),
    ("regen", "Sangre caliente", "+1 vida regenerada por segundo", "H"),
    ("armor", "Chaqueta reforzada", "Reduce el daño recibido", "A"),
    ("healing", "Hierbas de la costa", "+25% vida recuperada", "H+"),
    ("card_damage", "Filo de plata", "+20% daño de las cartas", "C+"),
    ("card_speed", "Reparto veloz", "+20% velocidad de las cartas", "C>"),
    ("card_size", "Naipes enormes", "+20% tamaño y alcance de impacto", "C#"),
    ("card_pierce", "As perforante", "Las cartas atraviesan +1 enemigo", "C!"),
    ("card_burn", "As de brasas", "Las cartas pueden prender fuego", "C*"),
    ("dagger", "Dagas ágiles", "Desbloquea o mejora dagas · nivel {level}", "D"),
    ("bomb", "Carga explosiva", "Desbloquea o mejora bombas · nivel {level}", "*"),
    ("shell", "Escudo de mar", "Desbloquea o mejora la concha · nivel {level}", "S"),
    ("fire", "Llama de ron", "Prende una estela de fuego · nivel {level}", "F"),
    ("synergy", "Sinergia legendaria", "Duplica proyectiles · -15% vida máxima", "L"),
    ("bloodlust", "Sed de sangre", "Recupera vida al abrir cofres y vencer jefes", "+"),
    ("magnet", "Magnetismo", "Aumenta el radio de atracción de orbes y monedas", "M"),
    ("damage", "Golpe certero", "+20% daño de tus armas", "!"),
    ("fire_rate", "Mano rápida", "+15% velocidad de ataque", "~"),
]

HAT_ORDER = ("none", "wool", "pirate", "straw", "top")
