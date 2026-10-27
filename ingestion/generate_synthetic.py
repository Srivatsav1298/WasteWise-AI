"""Deterministic, documented synthetic source data for the local demo.

Why synthetic
-------------
The platform is demoed end to end without customer data. The generator is seeded,
so every run produces byte-identical files and therefore identical mart output.

What the data models
--------------------
- 3 cafes, 8 ingredients in 4 categories, 8 products mapped to ingredients.
- 45 trading days of point-of-sale units with weekday seasonality, a gentle
  upward trend and demand lift around external events.
- Daily inventory snapshots for every ingredient at every cafe.
- Waste events whose reason mix and volume follow the demand signal, so
  overproduction clusters on event days and spoilage clusters on slow days.
- Two deliberate defects to exercise the pipeline: a duplicated sale line and a
  duplicated inventory snapshot (late corrections, resolved by silver dedup).
"""
from __future__ import annotations

import random
from csv import DictWriter
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SEED = 20260921

LOCATIONS = [
    {"location_id": "oslo_central", "location_name": "Fjord & Bean Central", "city": "Oslo"},
    {"location_id": "oslo_deck", "location_name": "Fjord & Bean Bar", "city": "Oslo"},
    {"location_id": "bergen_kai", "location_name": "Fjord & Bean Bergen", "city": "Bergen"},
]

INGREDIENTS = [
    {"ingredient_id": "salmon", "ingredient_name": "Salmon", "category": "Protein", "unit": "kg", "pack_size": "6", "unit_cost": "390"},
    {"ingredient_id": "chicken", "ingredient_name": "Chicken", "category": "Protein", "unit": "kg", "pack_size": "5", "unit_cost": "275"},
    {"ingredient_id": "bread", "ingredient_name": "Sourdough bread", "category": "Bakery", "unit": "loaf", "pack_size": "10", "unit_cost": "12.5"},
    {"ingredient_id": "avocado", "ingredient_name": "Avocado", "category": "Produce", "unit": "kg", "pack_size": "6", "unit_cost": "210"},
    {"ingredient_id": "berries", "ingredient_name": "Berries", "category": "Produce", "unit": "kg", "pack_size": "6", "unit_cost": "240"},
    {"ingredient_id": "tomato", "ingredient_name": "Tomato", "category": "Produce", "unit": "kg", "pack_size": "8", "unit_cost": "96"},
    {"ingredient_id": "milk", "ingredient_name": "Milk", "category": "Dairy", "unit": "L", "pack_size": "12", "unit_cost": "14"},
    {"ingredient_id": "cream", "ingredient_name": "Cream", "category": "Dairy", "unit": "kg", "pack_size": "6", "unit_cost": "195"},
]

PRODUCTS = [
    {"product_id": "salmon_open", "product_name": "Salmon open sandwich", "category": "Food", "ingredient_id": "salmon", "qty_per_unit": "0.12", "unit": "kg"},
    {"product_id": "chicken_wrap", "product_name": "Chicken wrap", "category": "Food", "ingredient_id": "chicken", "qty_per_unit": "0.14", "unit": "kg"},
    {"product_id": "berry_bowl", "product_name": "Berry breakfast bowl", "category": "Food", "ingredient_id": "berries", "qty_per_unit": "0.09", "unit": "kg"},
    {"product_id": "avocado_toast", "product_name": "Avocado toast", "category": "Food", "ingredient_id": "avocado", "qty_per_unit": "0.08", "unit": "kg"},
    {"product_id": "tomato_soup", "product_name": "Tomato soup", "category": "Food", "ingredient_id": "tomato", "qty_per_unit": "0.18", "unit": "kg"},
    {"product_id": "sourdough_loaf", "product_name": "Sourdough loaf", "category": "Bakery", "ingredient_id": "bread", "qty_per_unit": "1", "unit": "loaf"},
    {"product_id": "flat_white", "product_name": "Flat white & latte", "category": "Beverage", "ingredient_id": "milk", "qty_per_unit": "0.15", "unit": "L"},
    {"product_id": "creme_brulee", "product_name": "Creme brulee", "category": "Dessert", "ingredient_id": "cream", "qty_per_unit": "0.06", "unit": "kg"},
]

# Products each location sells, and the relative demand of that product.
LOCATION_MENU = {
    "oslo_central": {"salmon_open": 26, "chicken_wrap": 22, "berry_bowl": 18, "avocado_toast": 14, "tomato_soup": 12, "sourdough_loaf": 9, "flat_white": 46, "creme_brulee": 7},
    "oslo_deck": {"salmon_open": 14, "chicken_wrap": 11, "berry_bowl": 12, "avocado_toast": 10, "tomato_soup": 8, "sourdough_loaf": 7, "flat_white": 38, "creme_brulee": 5},
    "bergen_kai": {"salmon_open": 18, "chicken_wrap": 13, "berry_bowl": 10, "avocado_toast": 9, "tomato_soup": 11, "sourdough_loaf": 6, "flat_white": 28, "creme_brulee": 4},
}

WEEKDAY_FACTOR = {0: 0.86, 1: 0.92, 2: 0.97, 3: 1.02, 4: 1.18, 5: 1.24, 6: 1.09}

EVENTS = [
    {"event_id": "evt-oslo-summit", "city": "Oslo", "event_date": "2026-09-12", "event_name": "Oslo Food & Hospitality Summit", "event_type": "Conference", "venue": "Oslo Spektrum", "expected_attendance": "1400", "attendance_quality": "Published delegates", "source_url": "https://www.visitoslo.com/"},
    {"event_id": "evt-bergen-seafood", "city": "Bergen", "event_date": "2026-09-26", "event_name": "Bergen Seafood Weekend", "event_type": "Festival", "venue": "Bergen Grieghallen", "expected_attendance": "5200", "attendance_quality": "Organiser estimate", "source_url": "https://www.visitoslo.com/"},
    {"event_id": "evt-coffee-expo", "city": "Oslo", "event_date": "2026-10-03", "event_name": "Nordic Coffee Expo", "event_type": "Conference", "venue": "Oslo Nordsalen", "expected_attendance": "900", "attendance_quality": "Published delegates", "source_url": "https://www.visitoslo.com/"},
    {"event_id": "evt-eda", "city": "Oslo", "event_date": "2026-11-04", "event_name": "EDA Annual Conference", "event_type": "Conference", "venue": "Radisson Blu Scandinavia", "expected_attendance": "260", "attendance_quality": "Published delegates", "source_url": "https://www.visitoslo.com/no/moter-og-kongresser/kongresskalender"},
    {"event_id": "evt-jcole", "city": "Oslo", "event_date": "2026-11-12", "event_name": "J. Cole: The Fall-Off Tour", "event_type": "Concert", "venue": "Unity Arena", "expected_attendance": "25000", "attendance_quality": "Venue capacity", "source_url": "https://www.visitoslo.com/misc/unity-arena"},
]

START = date(2026, 9, 1)
DAYS = 45

REASONS = [
    ("spoilage", 0.42, (0.4, 1.9)),
    ("overproduction", 0.26, (1.2, 4.4)),
    ("trim", 0.17, (0.15, 0.65)),
    ("expired", 0.1, (0.35, 1.2)),
    ("damaged", 0.05, (0.2, 0.9)),
]

PRODUCT_INGREDIENT = {p["product_id"]: p["ingredient_id"] for p in PRODUCTS}
INGREDIENT_UNIT = {i["ingredient_id"]: i["unit"] for i in INGREDIENTS}


def write(name: str, rows: List[Dict], fields: List[str]) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    with (RAW / name).open("w", newline="") as handle:
        writer = DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _event_lift(day: date) -> float:
    """Demand multiplier from events in the same city window (documented heuristic)."""
    lift = 1.0
    for event in EVENTS:
        event_date = date.fromisoformat(event["event_date"])
        delta = abs((day - event_date).days)
        if delta <= 2:
            lift += {0: 0.55, 1: 0.35, 2: 0.2}[delta]
    return lift


def _event_city(event_date: date) -> set:
    cities = set()
    for event in EVENTS:
        if abs((event_date - date.fromisoformat(event["event_date"])).days) <= 2:
            cities.add("Bergen" if "bergen" in event["event_id"] else "Oslo")
    return cities


def main() -> None:
    random.seed(SEED)
    sales: List[Dict] = []
    inventory: List[Dict] = []
    waste: List[Dict] = []

    for offset in range(DAYS):
        day = START + timedelta(days=offset)
        trend = 1 + 0.004 * offset
        cities = _event_city(day)
        for location in LOCATIONS:
            menu = LOCATION_MENU[location["location_id"]]
            city_lift = 1.35 if location["city"] in cities else 1.0
            for product_id, base in menu.items():
                factor = WEEKDAY_FACTOR[day.weekday()] * trend * _event_lift(day) * city_lift
                units = max(0, round(base * factor + random.uniform(-1.5, 1.5)))
                sales.append({
                    "sale_id": f"s-{offset}-{location['location_id']}-{product_id}",
                    "location_id": location["location_id"],
                    "sale_date": day.isoformat(),
                    "product_id": product_id,
                    "units_sold": units,
                })

            for ingredient in INGREDIENTS:
                used = any(PRODUCT_INGREDIENT[p] == ingredient["ingredient_id"] for p in menu)
                if not used:
                    continue
                base_stock = 14 if ingredient["category"] == "Produce" else 20
                stock = max(0, round(base_stock * (0.6 + 0.4 * random.random()) + random.uniform(-2, 4)))
                inventory.append({
                    "snapshot_date": day.isoformat(),
                    "location_id": location["location_id"],
                    "ingredient_id": ingredient["ingredient_id"],
                    "quantity_on_hand": stock,
                })

            # Waste: more overproduction on busy days, spoilage on slow days.
            menu_ingredients = sorted({PRODUCT_INGREDIENT[p] for p in menu})
            event_pressure = random.random() < 0.35 and len(cities) > 0
            for ingredient_id in menu_ingredients:
                if random.random() > (0.34 if event_pressure else 0.22):
                    continue
                roll = random.random()
                cumulative = 0.0
                reason, low, high = REASONS[-1]
                for candidate, weight, bounds in REASONS:
                    cumulative += weight
                    if roll <= cumulative:
                        reason, low, high = candidate, bounds[0], bounds[1]
                        break
                if reason == "overproduction":
                    low, high = low * (1.6 if event_pressure else 1.0), high * (1.8 if event_pressure else 1.0)
                quantity = round(random.uniform(low, high), 2)
                waste.append({
                    "waste_id": f"w-{offset}-{location['location_id']}-{ingredient_id}-{len(waste)}",
                    "location_id": location["location_id"],
                    "waste_date": day.isoformat(),
                    "ingredient_id": ingredient_id,
                    "quantity": quantity,
                    "reason": reason,
                })

    # Deliberate defects: late corrections delivered as duplicate rows.
    # Silver dedup on the natural key resolves them; the trust report records it.
    sales.append(dict(sales[0], units_sold=int(sales[0]["units_sold"]) + 3))
    inventory.append(dict(inventory[0], quantity_on_hand=int(inventory[0]["quantity_on_hand"]) + 2))

    write("locations.csv", LOCATIONS, list(LOCATIONS[0].keys()))
    write("products.csv", PRODUCTS, list(PRODUCTS[0].keys()))
    write("ingredients.csv", INGREDIENTS, list(INGREDIENTS[0].keys()))
    write("sales.csv", sales, list(sales[0].keys()))
    write("inventory_snapshots.csv", inventory, list(inventory[0].keys()))
    write("waste_events.csv", waste, list(waste[0].keys()))
    write("events.csv", EVENTS, list(EVENTS[0].keys()))
    print(
        f"Generated {len(sales)} sales, {len(inventory)} inventory snapshots, "
        f"{len(waste)} waste events, {len(EVENTS)} events across {len(LOCATIONS)} locations"
    )


if __name__ == "__main__":
    main()
