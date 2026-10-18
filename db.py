"""SQLite schema, connection helper, and fibre-catalogue demo seed."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "stockroom.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    category        TEXT    NOT NULL DEFAULT 'General',
    unit            TEXT    NOT NULL DEFAULT 'pcs',
    current_stock   INTEGER NOT NULL DEFAULT 0,
    reorder_level   INTEGER NOT NULL DEFAULT 0,
    metres_per_drum INTEGER NOT NULL DEFAULT 0,
    tracks_serial   INTEGER NOT NULL DEFAULT 0 CHECK (tracks_serial IN (0, 1))
);

CREATE TABLE IF NOT EXISTS issued_to (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name   TEXT    NOT NULL,
    phone  TEXT    NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS stock_in (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id        INTEGER NOT NULL REFERENCES items(id),
    quantity       INTEGER NOT NULL CHECK (quantity > 0),
    source         TEXT    NOT NULL DEFAULT '',
    date           TEXT    NOT NULL,
    metres         INTEGER,
    serial_numbers TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS issues (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    issued_to_id INTEGER NOT NULL REFERENCES issued_to(id),
    date         TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS issue_items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id          INTEGER NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    item_id           INTEGER NOT NULL REFERENCES items(id),
    quantity_issued   INTEGER NOT NULL CHECK (quantity_issued > 0),
    quantity_returned INTEGER NOT NULL DEFAULT 0 CHECK (quantity_returned >= 0),
    returned_at       TEXT,
    metres            INTEGER,
    serial_numbers    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS stock_adjustments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES items(id),
    quantity_change INTEGER NOT NULL CHECK (quantity_change <> 0),
    reason          TEXT    NOT NULL DEFAULT '',
    date            TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stock_in_item ON stock_in(item_id);
CREATE INDEX IF NOT EXISTS idx_stock_in_date ON stock_in(date);
CREATE INDEX IF NOT EXISTS idx_issues_date ON issues(date);
CREATE INDEX IF NOT EXISTS idx_issue_items_issue ON issue_items(issue_id);
CREATE INDEX IF NOT EXISTS idx_issue_items_item ON issue_items(item_id);
CREATE INDEX IF NOT EXISTS idx_adjustments_date ON stock_adjustments(date);
"""


@contextmanager
def get_db():
    """Open a connection, commit on success, roll back on error, always close."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as db:
        db.executescript(SCHEMA)
        _migrate(db)
        if db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
            _seed_demo(db)


def _migrate(db) -> None:
    """Keep older databases compatible with the fibre-specific columns."""
    columns = {
        table: {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        for table in ("items", "stock_in", "issue_items")
    }
    additions = [
        ("items", "metres_per_drum", "metres_per_drum INTEGER NOT NULL DEFAULT 0"),
        ("items", "tracks_serial", "tracks_serial INTEGER NOT NULL DEFAULT 0"),
        ("stock_in", "metres", "metres INTEGER"),
        ("stock_in", "serial_numbers", "serial_numbers TEXT NOT NULL DEFAULT ''"),
        ("issue_items", "metres", "metres INTEGER"),
        ("issue_items", "serial_numbers", "serial_numbers TEXT NOT NULL DEFAULT ''"),
    ]
    for table, column, ddl in additions:
        if column not in columns[table]:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _change_stock(db, item_id: int, change: int) -> None:
    db.execute(
        "UPDATE items SET current_stock = current_stock + ? WHERE id = ?",
        (change, item_id),
    )


def _seed_demo(db) -> None:
    """Seed a fibre-materials catalogue with stock, issues, returns and tools."""

    items = [
        # name, category, unit, opening, reorder, metres per drum, serial tracking
        ("1-Core Aerial Drop Cable", "Fibre Cable", "drum", 6, 3, 1000, 0),
        ("12-Core ADSS Fibre Cable", "Fibre Cable", "drum", 4, 2, 2000, 0),
        ("24-Core ADSS Fibre Cable", "Fibre Cable", "drum", 3, 1, 2000, 0),
        ("48-Core ADSS Fibre Cable", "Fibre Cable", "drum", 2, 1, 2000, 0),
        ("Inline Splice Closure, 24-Port", "Outside Plant", "pcs", 8, 3, 0, 0),
        ("ODF / Distribution Box, 12-Port", "Outside Plant", "pcs", 10, 4, 0, 0),
        ("Drop Cable Anchor Clamp", "Outside Plant", "pcs", 250, 80, 0, 0),
        ("Tension Clamp — Small", "Outside Plant", "pcs", 120, 40, 0, 0),
        ("Tension Clamp — Big", "Outside Plant", "pcs", 80, 30, 0, 0),
        ("Universal Pole Bracket (UPB)", "Outside Plant", "pcs", 150, 50, 0, 0),
        ("J Hook", "Outside Plant", "pcs", 200, 60, 0, 0),
        ("Buckle Clip", "Outside Plant", "pcs", 300, 100, 0, 0),
        ("UV Cable Ties, 300mm", "Outside Plant", "pack", 15, 5, 0, 0),
        ("Warning Tape", "Outside Plant", "roll", 6, 3, 0, 0),
        ("Cable Labels", "Outside Plant", "pack", 8, 4, 0, 0),
        ("SC/APC Fast Connector", "Passive Components", "pcs", 80, 30, 0, 0),
        ("SC/APC Pigtail", "Passive Components", "pcs", 80, 30, 0, 0),
        ("SC/APC Patch Cord, 3m", "Passive Components", "pcs", 40, 15, 0, 0),
        ("LC/UPC Patch Cord, 3m", "Passive Components", "pcs", 30, 10, 0, 0),
        ("PLC Splitter 1×8, SC/APC", "Passive Components", "pcs", 15, 6, 0, 0),
        ("PLC Splitter 1×16, SC/APC", "Passive Components", "pcs", 8, 4, 0, 0),
        ("Splice Protection Sleeves (100/pack)", "Passive Components", "pack", 12, 5, 0, 0),
        ("GPON ONT, Single-Port", "Active Equipment", "pcs", 25, 10, 0, 1),
        ("GPON ONT with WiFi", "Active Equipment", "pcs", 20, 10, 0, 1),
        ("GPON OLT, 8-Port", "Active Equipment", "pcs", 2, 1, 0, 1),
        ("GPON SFP Module", "Active Equipment", "pcs", 12, 5, 0, 1),
        ("8-Port Gigabit Switch", "Active Equipment", "pcs", 4, 2, 0, 1),
        ("Customer WiFi Router", "Active Equipment", "pcs", 15, 6, 0, 1),
        ("Mini UPS, 12V", "Active Equipment", "pcs", 8, 4, 0, 1),
        ("Fusion Splicer", "Tools & Test", "pcs", 2, 1, 0, 1),
        ("OTDR", "Tools & Test", "pcs", 2, 1, 0, 1),
        ("Optical Power Meter", "Tools & Test", "pcs", 3, 2, 0, 1),
        ("Visual Fault Locator (VFL)", "Tools & Test", "pcs", 3, 2, 0, 1),
        ("Fibre Cleaver", "Tools & Test", "pcs", 4, 2, 0, 0),
        ("Fibre Stripper", "Tools & Test", "pcs", 4, 2, 0, 0),
        ("Cordless Drill", "Tools & Test", "pcs", 3, 1, 0, 1),
        ("Safety Harness", "Safety", "pcs", 6, 2, 0, 0),
        ("Isopropyl Alcohol 99%", "Consumables", "bottle", 8, 4, 0, 0),
        ("Lint-Free Wipes", "Consumables", "pack", 12, 5, 0, 0),
        ("Fibre Cleaning Swabs", "Consumables", "pack", 12, 5, 0, 0),
        ("Electrical Tape", "Consumables", "roll", 15, 6, 0, 0),
        ("Heat-Shrink Tubing", "Consumables", "pack", 6, 3, 0, 0),
        ("Silicone Sealant", "Consumables", "tube", 8, 3, 0, 0),
        ("20mm Conduit", "Consumables", "length", 30, 10, 0, 0),
        ("Wall Anchors & Screws", "Consumables", "pack", 10, 4, 0, 0),
        ("Safety Helmet", "Safety", "pcs", 8, 3, 0, 0),
        ("Reflective Vest", "Safety", "pcs", 8, 3, 0, 0),
        ("Safety Gloves", "Safety", "pair", 12, 5, 0, 0),
        ("First Aid Kit", "Safety", "kit", 2, 1, 0, 0),
    ]

    item_ids: dict[str, int] = {}
    for name, category, unit, opening, reorder, metres, serial in items:
        item_id = db.execute(
            """INSERT INTO items
               (name, category, unit, current_stock, reorder_level, metres_per_drum, tracks_serial)
               VALUES (?, ?, ?, 0, ?, ?, ?)""",
            (name, category, unit, reorder, metres, serial),
        ).lastrowid
        item_ids[name] = item_id
        if opening:
            total_metres = opening * metres if metres else None
            db.execute(
                """INSERT INTO stock_in
                   (item_id, quantity, source, date, metres, serial_numbers)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (item_id, opening, "Opening balance", _days_ago(45), total_metres, ""),
            )
            _change_stock(db, item_id, opening)

    people = [
        ("Amina Yusuf", "+254 712 000 111", 1),
        ("Brian Otieno", "+254 733 000 222", 1),
        ("Grace Wanjiku", "+254 700 000 333", 1),
        ("Daniel Mwangi", "+254 722 000 444", 0),
    ]
    person_ids: dict[str, int] = {}
    for name, phone, active in people:
        person_ids[name] = db.execute(
            "INSERT INTO issued_to (name, phone, active) VALUES (?, ?, ?)",
            (name, phone, active),
        ).lastrowid

    deliveries = [
        # item, qty, source, days ago, metres, serials
        ("48-Core ADSS Fibre Cable", 2, "FibreLine Supplies", 20, 4000, ""),
        ("12-Core ADSS Fibre Cable", 3, "OptiCore Ltd", 16, 4500, ""),
        ("1-Core Aerial Drop Cable", 4, "OptiCore Ltd", 14, 4000, ""),
        ("SC/APC Fast Connector", 100, "OptiCore Ltd", 18, None, ""),
        ("GPON ONT with WiFi", 15, "MetroLink Systems", 12, None, "ONTW-2311 – ONTW-2325"),
        ("Inline Splice Closure, 24-Port", 5, "FibreLine Supplies", 19, None, ""),
        ("Tension Clamp — Small", 100, "FibreLine Supplies", 22, None, ""),
        ("OTDR", 1, "MetroLink Systems", 12, None, "OTDR-9130"),
        ("Safety Helmet", 4, "SafeSite Kenya", 10, None, ""),
    ]
    for name, quantity, source, days, metres, serials in deliveries:
        db.execute(
            """INSERT INTO stock_in
               (item_id, quantity, source, date, metres, serial_numbers)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (item_ids[name], quantity, source, _days_ago(days), metres, serials),
        )
        _change_stock(db, item_ids[name], quantity)

    issue_plan = [
        (
            "Amina Yusuf",
            26,
            [
                ("12-Core ADSS Fibre Cable", 1, 1800, ""),
                ("Tension Clamp — Small", 20, None, ""),
                ("J Hook", 40, None, ""),
            ],
        ),
        (
            "Brian Otieno",
            24,
            [
                ("48-Core ADSS Fibre Cable", 1, 2000, ""),
                ("Inline Splice Closure, 24-Port", 2, None, ""),
                ("OTDR", 1, None, "OTDR-8842"),
                ("Safety Harness", 2, None, ""),
                ("Safety Helmet", 1, None, ""),
            ],
        ),
        (
            "Grace Wanjiku",
            21,
            [
                ("1-Core Aerial Drop Cable", 2, 2000, ""),
                ("Drop Cable Anchor Clamp", 30, None, ""),
                ("Buckle Clip", 60, None, ""),
            ],
        ),
        (
            "Amina Yusuf",
            18,
            [
                ("24-Core ADSS Fibre Cable", 1, 2000, ""),
                ("SC/APC Pigtail", 20, None, ""),
                ("Splice Protection Sleeves (100/pack)", 2, None, ""),
            ],
        ),
        (
            "Brian Otieno",
            15,
            [
                ("PLC Splitter 1×8, SC/APC", 4, None, ""),
                ("GPON ONT with WiFi", 6, None, "ONTW-2311, ONTW-2312, ONTW-2313, ONTW-2314, ONTW-2315, ONTW-2316"),
                ("SC/APC Patch Cord, 3m", 8, None, ""),
            ],
        ),
        (
            "Grace Wanjiku",
            12,
            [
                ("12-Core ADSS Fibre Cable", 1, 1500, ""),
                ("Tension Clamp — Big", 15, None, ""),
                ("Universal Pole Bracket (UPB)", 20, None, ""),
                ("J Hook", 60, None, ""),
                ("Lint-Free Wipes", 2, None, ""),
            ],
        ),
        (
            "Amina Yusuf",
            9,
            [
                ("48-Core ADSS Fibre Cable", 1, 2000, ""),
                ("Optical Power Meter", 1, None, "OPM-2207"),
                ("Isopropyl Alcohol 99%", 1, None, ""),
            ],
        ),
        (
            "Brian Otieno",
            7,
            [
                ("1-Core Aerial Drop Cable", 2, 2000, ""),
                ("Buckle Clip", 100, None, ""),
                ("Drop Cable Anchor Clamp", 40, None, ""),
                ("Electrical Tape", 3, None, ""),
            ],
        ),
        (
            "Grace Wanjiku",
            5,
            [
                ("GPON ONT, Single-Port", 4, None, "ONT-5510, ONT-5511, ONT-5512, ONT-5513"),
                ("SC/APC Patch Cord, 3m", 5, None, ""),
            ],
        ),
        (
            "Amina Yusuf",
            3,
            [
                ("48-Core ADSS Fibre Cable", 1, 2000, ""),
                ("Inline Splice Closure, 24-Port", 2, None, ""),
                ("Heat-Shrink Tubing", 1, None, ""),
            ],
        ),
        (
            "Brian Otieno",
            2,
            [
                ("12-Core ADSS Fibre Cable", 1, 1500, ""),
                ("J Hook", 80, None, ""),
                ("Buckle Clip", 100, None, ""),
            ],
        ),
        (
            "Grace Wanjiku",
            1,
            [
                ("Safety Gloves", 2, None, ""),
                ("Reflective Vest", 2, None, ""),
                ("Safety Helmet", 1, None, ""),
            ],
        ),
    ]

    created: list[tuple[int, dict[str, int]]] = []
    for person, days, lines in issue_plan:
        issue_id = db.execute(
            "INSERT INTO issues (issued_to_id, date) VALUES (?, ?)",
            (person_ids[person], _days_ago(days)),
        ).lastrowid
        line_ids: dict[str, int] = {}
        for name, quantity, metres, serials in lines:
            line_id = db.execute(
                """INSERT INTO issue_items
                   (issue_id, item_id, quantity_issued, quantity_returned, metres, serial_numbers)
                   VALUES (?, ?, ?, 0, ?, ?)""",
                (issue_id, item_ids[name], quantity, metres, serials),
            ).lastrowid
            line_ids[name] = line_id
            _change_stock(db, item_ids[name], -quantity)
        created.append((issue_id, line_ids))

    # Partial returns against past issues.
    returns = [
        (0, "Tension Clamp — Small", 5, 12),
        (1, "Inline Splice Closure, 24-Port", 1, 10),
        (1, "OTDR", 1, 5),
        (1, "Safety Harness", 1, 8),
        (2, "1-Core Aerial Drop Cable", 1, 7),
        (4, "GPON ONT with WiFi", 2, 6),
        (4, "SC/APC Patch Cord, 3m", 2, 6),
        (8, "GPON ONT, Single-Port", 1, 2),
    ]
    for issue_index, name, quantity, days in returns:
        _, line_ids = created[issue_index]
        db.execute(
            """UPDATE issue_items
               SET quantity_returned = quantity_returned + ?, returned_at = ?
               WHERE id = ?""",
            (quantity, _days_ago(days), line_ids[name]),
        )
        _change_stock(db, item_ids[name], quantity)

    adjustments = [
        ("Safety Gloves", -1, "Damaged pair discarded", 4),
        ("SC/APC Fast Connector", 5, "Physical count correction", 6),
    ]
    for name, change, reason, days in adjustments:
        db.execute(
            """INSERT INTO stock_adjustments (item_id, quantity_change, reason, date)
               VALUES (?, ?, ?, ?)""",
            (item_ids[name], change, reason, _days_ago(days)),
        )
        _change_stock(db, item_ids[name], change)
