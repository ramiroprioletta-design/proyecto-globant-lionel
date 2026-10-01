from __future__ import annotations

import math

from settings import ISLAND_CENTER, WORLD_HEIGHT, WORLD_WIDTH


BIOME_CENTERS = {
    "forest": (ISLAND_CENTER[0], ISLAND_CENTER[1], 1300.0, 2400.0),
    "desert": (ISLAND_CENTER[0] + 2050, ISLAND_CENTER[1] + 80, 2400.0, 1700.0),
    "snow": (ISLAND_CENTER[0] - 2050, ISLAND_CENTER[1] + 80, 2400.0, 1700.0),
    "volcano": (ISLAND_CENTER[0], ISLAND_CENTER[1] - 1600, 1750.0, 1800.0),
}


def biome_weights(x: float, y: float) -> dict[str, float]:
    scores = {}
    for index, (name, (center_x, center_y, radius_x, radius_y)) in enumerate(BIOME_CENTERS.items()):
        distance = math.hypot((x - center_x) / radius_x, (y - center_y) / radius_y)
        phase = index * 2.1
        irregularity = (
            0.055 * math.sin(x / 410 + math.sin(y / 670) + phase)
            + 0.035 * math.sin(y / 370 - x / 900 + phase)
            + 0.02 * math.sin((x + y) / 210 - phase)
        )
        scores[name] = 1 - distance + irregularity

    highest = max(scores.values())
    weights = {name: math.exp((score - highest) / 0.12) for name, score in scores.items()}
    total = sum(weights.values())
    return {name: weight / total for name, weight in weights.items()}


def edge_radius(angle: float) -> float:
    return (
        1.0
        + 0.012 * math.sin(angle * 7 + 0.4)
        + 0.008 * math.sin(angle * 13 - 1.1)
        + 0.004 * math.sin(angle * 23 + 0.7)
    )


def world_contains(x: float, y: float) -> bool:
    radius_x = radius_y = min(WORLD_WIDTH, WORLD_HEIGHT) * 0.497
    nx = (x - ISLAND_CENTER[0]) / radius_x
    ny = (y - ISLAND_CENTER[1]) / radius_y
    angle = math.atan2(ny, nx)
    return math.hypot(nx, ny) <= edge_radius(angle)


def keep_inside(x: float, y: float, padding: float = 0.0) -> tuple[float, float]:
    radius_x = radius_y = min(WORLD_WIDTH, WORLD_HEIGHT) * 0.497
    nx = (x - ISLAND_CENTER[0]) / radius_x
    ny = (y - ISLAND_CENTER[1]) / radius_y
    angle = math.atan2(ny, nx)
    distance = math.hypot(nx, ny)
    safe_edge = max(0.0, edge_radius(angle) - padding / min(radius_x, radius_y))
    if distance <= safe_edge or distance == 0:
        return x, y
    scale = safe_edge / distance
    return ISLAND_CENTER[0] + nx * scale * radius_x, ISLAND_CENTER[1] + ny * scale * radius_y


def coastline(samples: int = 512) -> list[tuple[float, float]]:
    radius_x = radius_y = min(WORLD_WIDTH, WORLD_HEIGHT) * 0.497
    points = []
    for index in range(samples):
        angle = math.tau * index / samples
        radius = edge_radius(angle)
        points.append((
            ISLAND_CENTER[0] + math.cos(angle) * radius_x * radius,
            ISLAND_CENTER[1] + math.sin(angle) * radius_y * radius,
        ))
    return points


def clip_polygon_to_rect(
    points: list[tuple[float, float]],
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> list[tuple[float, float]]:
    polygon = points
    for axis, boundary, keep_greater in (
        (0, left, True),
        (0, right, False),
        (1, top, True),
        (1, bottom, False),
    ):
        if not polygon:
            break
        clipped = []
        previous = polygon[-1]
        previous_inside = previous[axis] >= boundary if keep_greater else previous[axis] <= boundary
        for current in polygon:
            current_inside = current[axis] >= boundary if keep_greater else current[axis] <= boundary
            if current_inside != previous_inside:
                delta = current[axis] - previous[axis]
                amount = (boundary - previous[axis]) / delta
                intersection = (
                    previous[0] + amount * (current[0] - previous[0]),
                    previous[1] + amount * (current[1] - previous[1]),
                )
                clipped.append(intersection)
            if current_inside:
                clipped.append(current)
            previous = current
            previous_inside = current_inside
        polygon = clipped
    return polygon


def biome_at(x: float, y: float = float(ISLAND_CENTER[1])) -> str:
    weights = biome_weights(x, y)
    return max(weights, key=weights.get)
