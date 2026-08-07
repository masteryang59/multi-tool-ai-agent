"""Builds the demo database: a made-up outdoor-gear chain, Trailhead Outfitters.

The data is random but seeded, so the same seed and date always give the same database. Sales follow
the seasons and each store's climate (rain gear sells in Seattle in autumn, parkas in Minneapolis in
winter), and the Seattle store is nearly out of rain gear, so "is it going to rain, and do we have
enough jackets?" has an interesting answer.
"""

import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE stores (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    region TEXT NOT NULL,
    country TEXT NOT NULL,
    opened_on TEXT NOT NULL
);
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price REAL NOT NULL,
    cost REAL NOT NULL
);
CREATE TABLE inventory (
    store_id INTEGER NOT NULL REFERENCES stores(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    reorder_level INTEGER NOT NULL,
    PRIMARY KEY (store_id, product_id)
);
CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    home_store_id INTEGER REFERENCES stores(id),
    joined_on TEXT NOT NULL
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    store_id INTEGER NOT NULL REFERENCES stores(id),
    ordered_at TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('in_store', 'online')),
    status TEXT NOT NULL CHECK (status IN ('completed', 'returned', 'cancelled'))
);
CREATE TABLE order_items (
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX orders_store_date ON orders(store_id, ordered_at);
CREATE INDEX order_items_order ON order_items(order_id);
"""

NOTES = (
    "Money is USD. orders.ordered_at is ISO 8601 store-local time (use date(ordered_at)). "
    "Sales and revenue count only orders with status = 'completed'; revenue = SUM(order_items.quantity * "
    "order_items.unit_price). inventory.quantity is current stock; stock is low when quantity <= reorder_level. "
    "Categories: Rain gear, Insulation, Footwear, Camping, Packs, Accessories."
)

# id, name, city, region, climate
STORES = [
    (1, "Trailhead Seattle", "Seattle", "Washington", "wet"),
    (2, "Trailhead Portland", "Portland", "Oregon", "wet"),
    (3, "Trailhead Denver", "Denver", "Colorado", "cold"),
    (4, "Trailhead Minneapolis", "Minneapolis", "Minnesota", "cold"),
    (5, "Trailhead Boston", "Boston", "Massachusetts", "mixed"),
    (6, "Trailhead Austin", "Austin", "Texas", "hot"),
]

# sku, name, category, price, season (wet / cold / summer / any)
PRODUCTS = [
    ("RG-101", "Cascade 2.5L Rain Shell", "Rain gear", 149.0, "wet"),
    ("RG-102", "Drizzle Packable Jacket", "Rain gear", 89.0, "wet"),
    ("RG-103", "Stormline Pro Jacket", "Rain gear", 229.0, "wet"),
    ("RG-110", "Cascade Rain Pants", "Rain gear", 99.0, "wet"),
    ("RG-120", "Compact Travel Umbrella", "Rain gear", 29.0, "wet"),
    ("IN-201", "Summit Down Parka", "Insulation", 279.0, "cold"),
    ("IN-202", "Ridge Synthetic Puffer", "Insulation", 159.0, "cold"),
    ("IN-210", "Merino Base Layer Top", "Insulation", 75.0, "cold"),
    ("FW-301", "Trailrunner GTX Shoe", "Footwear", 139.0, "wet"),
    ("FW-302", "Basecamp Waterproof Boot", "Footwear", 189.0, "cold"),
    ("FW-310", "Riverbed Sandal", "Footwear", 59.0, "summer"),
    ("CA-401", "Alpine 2P Tent", "Camping", 329.0, "summer"),
    ("CA-402", "Meadow 4P Family Tent", "Camping", 399.0, "summer"),
    ("CA-410", "Nightfall 20F Sleeping Bag", "Camping", 199.0, "any"),
    ("CA-411", "Summer 45F Sleeping Bag", "Camping", 99.0, "summer"),
    ("PK-501", "Daytripper 22L Pack", "Packs", 79.0, "any"),
    ("PK-502", "Traverse 55L Pack", "Packs", 219.0, "summer"),
    ("AC-601", "Merino Beanie", "Accessories", 32.0, "cold"),
    ("AC-602", "Insulated Gloves", "Accessories", 45.0, "cold"),
    ("AC-610", "SPF 50 Sunscreen", "Accessories", 14.0, "summer"),
    ("AC-611", "Steel Water Bottle 1L", "Accessories", 34.0, "any"),
    ("AC-612", "Headlamp 400lm", "Accessories", 49.0, "any"),
]

FIRST_NAMES = (
    "Ava Ben Chloe Dev Elena Finn Grace Hiro Isla Jonah Kira Liam Maya Noah Olive Priya Quinn Rosa Sam Theo "
    "Uma Victor Wren Xavier Yara Zane Amir Bea Carlos Dana Emil Fatima Gus Hana Ivan Jade Kofi Lena Marco Nia"
).split()
LAST_NAMES = (
    "Abbott Baker Chen Diaz Evans Fischer Garcia Hughes Ito Jensen Kowalski Lopez Moreau Nakamura Okafor "
    "Patel Quinlan Rossi Silva Tanaka Ueda Varga Walsh Xu Young Zimmer"
).split()

# Seattle is nearly sold out of rain gear: (store_id, sku) -> stock
LOW_STOCK = {(1, "RG-101"): 3, (1, "RG-102"): 6, (1, "RG-103"): 2, (1, "RG-110"): 4, (1, "RG-120"): 9, (2, "RG-103"): 5}


def season_weight(season: str, climate: str, month: int) -> float:
    winter = month in (11, 12, 1, 2)
    wet_months = month in (10, 11, 12, 1, 2, 3, 4)
    summer = month in (5, 6, 7, 8, 9)
    weight = 1.0
    if season == "wet":
        weight = {"wet": 3.0, "mixed": 1.2, "cold": 1.0, "hot": 0.6}[climate] if wet_months else 0.4
        if climate == "hot" and not wet_months:
            weight = 0.25
    elif season == "cold":
        weight = (3.5 if climate == "cold" else 1.5) if winter else 0.3
        if climate == "hot":
            weight *= 0.3
    elif season == "summer":
        weight = (2.5 if climate == "hot" else 2.0) if summer else 0.4
    return weight


def build(path: Path, *, today: date | None = None, seed: int = 7, days: int = 365) -> Path:
    today = today or date.today()
    rng = random.Random(seed)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)

    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)
    for store_id, name, city, region, _ in STORES:
        opened = date(2012 + store_id * 2, rng.randint(1, 12), rng.randint(1, 28))
        conn.execute("INSERT INTO stores VALUES (?, ?, ?, ?, 'US', ?)", (store_id, name, city, region, opened.isoformat()))

    product_ids = {}
    for i, (sku, name, category, price, _) in enumerate(PRODUCTS, start=1):
        product_ids[sku] = i
        conn.execute(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)",
            (i, sku, name, category, price, round(price * rng.uniform(0.42, 0.55), 2)),
        )

    for store_id, *_ in STORES:
        for sku, *_ in PRODUCTS:
            reorder = 8 if sku.startswith(("RG", "IN")) else 5
            quantity = LOW_STOCK.get((store_id, sku), rng.randint(12, 60))
            conn.execute("INSERT INTO inventory VALUES (?, ?, ?, ?)", (store_id, product_ids[sku], quantity, reorder))

    customers = []
    used_emails = set()
    for cid in range(1, 401):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        email = f"{first}.{last}".lower()
        while email in used_emails:
            email = f"{first}.{last}{rng.randint(2, 99)}".lower()
        used_emails.add(email)
        home = rng.choice(STORES)[0]
        joined = today - timedelta(days=rng.randint(30, 1500))
        customers.append((cid, home))
        conn.execute(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
            (cid, f"{first} {last}", f"{email}@example.com", home, joined.isoformat()),
        )

    locals_by_store = {store_id: [c for c, home in customers if home == store_id] for store_id, *_ in STORES}
    order_id = 0
    store_traffic = {1: 1.3, 2: 1.0, 3: 1.1, 4: 0.8, 5: 1.0, 6: 0.9}
    for day_offset in range(days, 0, -1):
        day = today - timedelta(days=day_offset)
        weekend_boost = 1.5 if day.weekday() >= 5 else 1.0
        for store_id, _, _, _, climate in STORES:
            weights = [season_weight(p[4], climate, day.month) for p in PRODUCTS]
            n_orders = _poisson(rng, 1.6 * store_traffic[store_id] * weekend_boost)
            for _ in range(n_orders):
                order_id += 1
                customer = rng.choice(locals_by_store[store_id]) if rng.random() < 0.85 else rng.choice(customers)[0]
                at = datetime(day.year, day.month, day.day, rng.randint(9, 20), rng.randint(0, 59))
                channel = "online" if rng.random() < 0.35 else "in_store"
                roll = rng.random()
                status = "cancelled" if roll < 0.02 else "returned" if roll < 0.05 else "completed"
                conn.execute(
                    "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
                    (order_id, customer, store_id, at.isoformat(timespec="minutes"), channel, status),
                )
                picked = set()
                for _ in range(rng.choices((1, 2, 3), (0.6, 0.3, 0.1))[0]):
                    sku, _, _, price, _ = rng.choices(PRODUCTS, weights)[0]
                    if sku in picked:
                        continue
                    picked.add(sku)
                    discount = rng.choice((1.0, 1.0, 1.0, 1.0, 0.9, 0.8))
                    conn.execute(
                        "INSERT INTO order_items VALUES (?, ?, ?, ?)",
                        (order_id, product_ids[sku], 1 if price > 60 else rng.randint(1, 3), round(price * discount, 2)),
                    )

    conn.executemany(
        "INSERT INTO meta VALUES (?, ?)",
        [("notes", NOTES), ("generated_on", today.isoformat()), ("seed", str(seed))],
    )
    conn.commit()
    conn.close()
    tmp.replace(path)
    return path


def _poisson(rng: random.Random, lam: float) -> int:
    # Knuth's method; fine for the small rates used here.
    limit, k, p = pow(2.718281828459045, -lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def ensure(path: Path) -> Path:
    path = Path(path)
    if not path.exists():
        build(path)
    return path

def sync_records(data=None):
    if data is None:
        return None
    return data

def sync_records(data=None):
    if data is None:
        return None
    return data

def serialize_data(data=None):
    if data is None:
        return None
    return data