"""Stockroom — a minimal check-in / check-out inventory app.

FastAPI + Jinja2 templates + SQLite. Run from this folder with:

    uvicorn main:app --reload
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, timedelta
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from db import BASE_DIR, get_db, init_db

TODAY = date.today


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Stockroom", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# --------------------------------------------------------------------------- #
# Template helpers
# --------------------------------------------------------------------------- #


def _datefmt(value, fmt: str = "%d %b %Y") -> str:
    if not value:
        return "—"
    try:
        return date.fromisoformat(str(value)[:10]).strftime(fmt)
    except ValueError:
        return str(value)


def _initials(name: str) -> str:
    parts = [part for part in str(name or "").split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _signed(value) -> str:
    number = int(value or 0)
    return "0" if number == 0 else f"{number:+d}"


def _unit_label(value, unit: str = "") -> str:
    count = abs(int(value or 0))
    if not unit:
        return f"{count:,}"
    if unit == "pcs":
        return f"{count:,} pcs"
    if unit == "pair":
        return f"{count:,} {'pair' if count == 1 else 'pairs'}"
    return f"{count:,} {unit}{'' if count == 1 else 's'}"


def _unit_name(value, unit: str = "") -> str:
    count = abs(int(value or 0))
    if not unit:
        return ""
    if unit == "pcs":
        return "pcs"
    if unit == "pair":
        return "pair" if count == 1 else "pairs"
    return f"{unit}{'' if count == 1 else 's'}"


templates.env.filters["datefmt"] = _datefmt
templates.env.filters["num"] = lambda value: f"{int(value or 0):,}"
templates.env.filters["signed"] = _signed
templates.env.filters["unit_label"] = _unit_label
templates.env.filters["unit_name"] = _unit_name
templates.env.filters["initials"] = _initials


def shell(
    request: Request,
    db: sqlite3.Connection,
    active: str,
    title: str,
    eyebrow: str = "",
    subtitle: str = "",
) -> dict:
    """Common context for every page, including the sidebar counters."""
    low_stock = db.execute(
        "SELECT COUNT(*) FROM items WHERE current_stock <= reorder_level"
    ).fetchone()[0]
    open_issues = db.execute(
        """SELECT COUNT(*) FROM issues i
           WHERE EXISTS (SELECT 1 FROM issue_items ii
                         WHERE ii.issue_id = i.id
                           AND ii.quantity_issued > ii.quantity_returned)"""
    ).fetchone()[0]
    outstanding = db.execute(
        "SELECT COALESCE(SUM(quantity_issued - quantity_returned), 0) FROM issue_items"
    ).fetchone()[0]

    return {
        "request": request,
        "active": active,
        "page_title": title,
        "eyebrow": eyebrow,
        "subtitle": subtitle,
        "today": TODAY().isoformat(),
        "nav_low": low_stock,
        "nav_open_issues": open_issues,
        "nav_outstanding": outstanding,
        "notice": request.query_params.get("msg"),
        "error": request.query_params.get("error"),
    }


def render(request: Request, template: str, context: dict, status_code: int = 200):
    return templates.TemplateResponse(
        request=request,
        name=template,
        context=context,
        status_code=status_code,
    )


def redirect(path: str, *, msg: str | None = None, error: str | None = None):
    params = {key: value for key, value in (("msg", msg), ("error", error)) if value}
    if params:
        path += ("&" if "?" in path else "?") + urlencode(params)
    return RedirectResponse(path, status_code=303)


def as_int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def as_date(value, default: date | None = None) -> date:
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return default or TODAY()


def get_item_or_404(db: sqlite3.Connection, item_id: int) -> dict:
    row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="That item could not be found.")
    return dict(row)


def get_issue_or_404(db: sqlite3.Connection, issue_id: int) -> dict:
    row = db.execute(
        """SELECT iss.*, p.name AS person, p.phone, p.active AS person_active
           FROM issues iss JOIN issued_to p ON p.id = iss.issued_to_id
           WHERE iss.id = ?""",
        (issue_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="That issue could not be found.")
    return dict(row)


def issue_lines(db: sqlite3.Connection, issue_id: int) -> list[dict]:
    rows = db.execute(
        """SELECT ii.*, i.name AS item_name, i.unit, i.current_stock
           FROM issue_items ii JOIN items i ON i.id = ii.item_id
           WHERE ii.issue_id = ? ORDER BY ii.id""",
        (issue_id,),
    ).fetchall()
    lines = []
    for row in rows:
        line = dict(row)
        line["outstanding"] = line["quantity_issued"] - line["quantity_returned"]
        lines.append(line)
    return lines


def issue_form_context(
    request: Request,
    db: sqlite3.Connection,
    *,
    values: dict | None = None,
    rows: list[dict] | None = None,
    error: str | None = None,
) -> dict:
    ctx = shell(
        request,
        db,
        "issue",
        "Issue stock",
        "Check-out",
        "Pick who is receiving the items, then add what they are taking.",
    )
    people = db.execute(
        "SELECT * FROM issued_to WHERE active = 1 ORDER BY name COLLATE NOCASE"
    ).fetchall()
    items = db.execute(
        "SELECT * FROM items ORDER BY name COLLATE NOCASE"
    ).fetchall()
    if values is None:
        selected = request.query_params.get("person", "")
        values = {"issued_to_id": selected, "date": TODAY().isoformat()}
    if rows is None:
        rows = [{"item_id": "", "quantity": "1", "metres": "", "serials": ""}]
    ctx.update(
        people=people,
        items=items,
        values=values,
        rows=rows,
        error=error or ctx["error"],
    )
    return ctx


def stock_in_context(
    request: Request,
    db: sqlite3.Connection,
    *,
    values: dict | None = None,
    error: str | None = None,
) -> dict:
    ctx = shell(
        request,
        db,
        "stock_in",
        "Receive stock",
        "Check-in",
        "Log a new delivery so stock on hand stays accurate.",
    )
    items = db.execute("SELECT * FROM items ORDER BY name COLLATE NOCASE").fetchall()
    deliveries = db.execute(
        """SELECT si.*, i.name AS item_name, i.unit, i.category, i.metres_per_drum,
                  i.tracks_serial
           FROM stock_in si JOIN items i ON i.id = si.item_id
           ORDER BY si.date DESC, si.id DESC LIMIT 15"""
    ).fetchall()
    ctx.update(
        items=items,
        deliveries=deliveries,
        values=values
        or {
            "item_id": request.query_params.get("item", ""),
            "quantity": "",
            "source": "",
            "date": TODAY().isoformat(),
            "metres": "",
            "serial_numbers": "",
        },
        error=error or ctx["error"],
    )
    return ctx


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #


@app.get("/")
async def dashboard(request: Request):
    with get_db() as db:
        ctx = shell(
            request,
            db,
            "dashboard",
            "Dashboard",
            "Overview",
            "A live view of stock on hand and what is currently checked out.",
        )
        items = [dict(row) for row in db.execute(
            """SELECT * FROM items
               ORDER BY CASE
                   WHEN current_stock <= 0 THEN 0
                   WHEN current_stock <= reorder_level THEN 1
                   ELSE 2 END,
                   name COLLATE NOCASE"""
        ).fetchall()]
        for item in items:
            target = max(item["reorder_level"] * 3, item["current_stock"], 1)
            item["stock_pct"] = min(100, round(item["current_stock"] / target * 100))

        recent = db.execute(
            """SELECT * FROM (
                   SELECT si.date AS date, 'in' AS kind, si.quantity AS qty,
                          i.name AS item, i.unit AS unit,
                          COALESCE(NULLIF(si.source, ''), 'Delivery') AS detail
                   FROM stock_in si JOIN items i ON i.id = si.item_id
                   UNION ALL
                   SELECT iss.date, 'out', -ii.quantity_issued,
                          i.name, i.unit, p.name
                   FROM issue_items ii
                   JOIN issues iss ON iss.id = ii.issue_id
                   JOIN items i ON i.id = ii.item_id
                   JOIN issued_to p ON p.id = iss.issued_to_id
                   UNION ALL
                   SELECT ii.returned_at, 'return', ii.quantity_returned,
                          i.name, i.unit, p.name
                   FROM issue_items ii
                   JOIN issues iss ON iss.id = ii.issue_id
                   JOIN items i ON i.id = ii.item_id
                   JOIN issued_to p ON p.id = iss.issued_to_id
                   WHERE ii.returned_at IS NOT NULL AND ii.quantity_returned > 0
                   UNION ALL
                   SELECT sa.date, 'adjust', sa.quantity_change,
                          i.name, i.unit, COALESCE(NULLIF(sa.reason, ''), 'Manual adjustment')
                   FROM stock_adjustments sa JOIN items i ON i.id = sa.item_id
               )
               ORDER BY date DESC
               LIMIT 8"""
        ).fetchall()

        stats = {
            "item_count": len(items),
            "drums": sum(item["current_stock"] for item in items if item["unit"] == "drum"),
            "cable_types": sum(1 for item in items if item["unit"] == "drum"),
            "low": sum(1 for item in items if item["current_stock"] <= item["reorder_level"]),
            "outstanding": ctx["nav_outstanding"],
            "open_issues": ctx["nav_open_issues"],
            "people": db.execute(
                "SELECT COUNT(*) FROM issued_to WHERE active = 1"
            ).fetchone()[0],
            "categories": len({item["category"] for item in items}),
        }
        ctx.update(items=items, stats=stats, recent=recent)
    return render(request, "dashboard.html", ctx)


# --------------------------------------------------------------------------- #
# Items
# --------------------------------------------------------------------------- #


@app.get("/items")
async def items_page(request: Request, q: str = "", category: str = ""):
    with get_db() as db:
        ctx = shell(
            request,
            db,
            "items",
            "Items",
            "Catalogue",
            "Add or edit items and drill into the stock history of any one item.",
        )
        clauses, params = [], []
        q = q.strip()
        category = category.strip()
        if q:
            clauses.append("(name LIKE ? OR category LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        if category:
            clauses.append("category = ?")
            params.append(category)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        items = db.execute(
            f"""SELECT * FROM items {where}
                ORDER BY name COLLATE NOCASE""",
            params,
        ).fetchall()
        categories = [
            row["category"]
            for row in db.execute(
                "SELECT DISTINCT category FROM items ORDER BY category COLLATE NOCASE"
            ).fetchall()
        ]
        ctx.update(items=items, categories=categories, q=q, category=category)
    return render(request, "items.html", ctx)


@app.get("/items/new")
async def item_new_page(request: Request):
    with get_db() as db:
        ctx = shell(
            request,
            db,
            "items",
            "Add item",
            "Catalogue",
            "Create a catalogue item, with an optional opening stock entry.",
        )
        ctx.update(
            item=None,
            values={
                "name": "",
                "category": "",
                "unit": "",
                "opening_stock": "0",
                "reorder_level": "0",
                "metres_per_drum": "0",
                "tracks_serial": 0,
            },
        )
    return render(request, "item_form.html", ctx)


@app.post("/items/new")
async def item_new(request: Request):
    form = await request.form()
    values = {
        "name": str(form.get("name", "")).strip(),
        "category": str(form.get("category", "")).strip() or "General",
        "unit": str(form.get("unit", "")).strip() or "pcs",
        "opening_stock": str(form.get("opening_stock", "0")).strip() or "0",
        "reorder_level": str(form.get("reorder_level", "0")).strip() or "0",
        "metres_per_drum": str(form.get("metres_per_drum", "0")).strip() or "0",
        "tracks_serial": 1 if form.get("tracks_serial") else 0,
    }
    opening = as_int(values["opening_stock"], -1)
    reorder = as_int(values["reorder_level"], -1)
    metres = as_int(values["metres_per_drum"], -1)
    error = None
    if not values["name"]:
        error = "Give the item a name."
    elif len(values["name"]) > 100:
        error = "Keep the item name under 100 characters."
    elif opening < 0 or reorder < 0 or metres < 0:
        error = "Opening stock, reorder level and metres must be whole numbers of zero or more."
    elif len(values["category"]) > 50 or len(values["unit"]) > 30:
        error = "Category or unit is too long."

    with get_db() as db:
        if error:
            ctx = shell(
                request,
                db,
                "items",
                "Add item",
                "Catalogue",
                "Create a catalogue item, with an optional opening stock entry.",
            )
            ctx.update(item=None, values=values, error=error)
            return render(request, "item_form.html", ctx, status_code=400)

        item_id = db.execute(
            """INSERT INTO items
               (name, category, unit, current_stock, reorder_level,
                metres_per_drum, tracks_serial)
               VALUES (?, ?, ?, 0, ?, ?, ?)""",
            (
                values["name"],
                values["category"],
                values["unit"],
                reorder,
                metres,
                values["tracks_serial"],
            ),
        ).lastrowid
        if opening:
            total_metres = opening * metres if metres else None
            db.execute(
                """INSERT INTO stock_in
                   (item_id, quantity, source, date, metres)
                   VALUES (?, ?, ?, ?, ?)""",
                (item_id, opening, "Opening balance", TODAY().isoformat(), total_metres),
            )
            db.execute(
                "UPDATE items SET current_stock = current_stock + ? WHERE id = ?",
                (opening, item_id),
            )
    return redirect(f"/items/{item_id}", msg=f"{values['name']} was added to the catalogue.")


@app.get("/items/{item_id}/edit")
async def item_edit_page(request: Request, item_id: int):
    with get_db() as db:
        item = get_item_or_404(db, item_id)
        ctx = shell(
            request,
            db,
            "items",
            "Edit item",
            "Catalogue",
            f"Update the details for {item['name']}.",
        )
        ctx.update(item=item, values=dict(item))
    return render(request, "item_form.html", ctx)


@app.post("/items/{item_id}/edit")
async def item_edit(request: Request, item_id: int):
    form = await request.form()
    values = {
        "name": str(form.get("name", "")).strip(),
        "category": str(form.get("category", "")).strip() or "General",
        "unit": str(form.get("unit", "")).strip() or "pcs",
        "reorder_level": str(form.get("reorder_level", "0")).strip() or "0",
        "metres_per_drum": str(form.get("metres_per_drum", "0")).strip() or "0",
        "tracks_serial": 1 if form.get("tracks_serial") else 0,
    }
    reorder = as_int(values["reorder_level"], -1)
    metres = as_int(values["metres_per_drum"], -1)
    error = None
    if not values["name"]:
        error = "Give the item a name."
    elif len(values["name"]) > 100:
        error = "Keep the item name under 100 characters."
    elif reorder < 0 or metres < 0:
        error = "Reorder level and metres must be whole numbers of zero or more."

    with get_db() as db:
        item = get_item_or_404(db, item_id)
        if error:
            ctx = shell(
                request,
                db,
                "items",
                "Edit item",
                "Catalogue",
                f"Update the details for {item['name']}.",
            )
            ctx.update(item=item, values={**item, **values}, error=error)
            return render(request, "item_form.html", ctx, status_code=400)

        db.execute(
            """UPDATE items
               SET name = ?, category = ?, unit = ?, reorder_level = ?,
                   metres_per_drum = ?, tracks_serial = ?
               WHERE id = ?""",
            (
                values["name"],
                values["category"],
                values["unit"],
                reorder,
                metres,
                values["tracks_serial"],
                item_id,
            ),
        )
    return redirect(f"/items/{item_id}", msg="Item details updated.")


@app.get("/items/{item_id}")
async def item_detail(request: Request, item_id: int):
    with get_db() as db:
        item = get_item_or_404(db, item_id)
        target = max(item["reorder_level"] * 3, item["current_stock"], 1)
        item["stock_pct"] = min(100, round(item["current_stock"] / target * 100))
        item["metres_on_hand"] = (
            item["current_stock"] * item["metres_per_drum"]
            if item["metres_per_drum"]
            else 0
        )
        ctx = shell(
            request,
            db,
            "items",
            item["name"],
            "Item history",
            f"{item['category']} · tracked in {item['unit']}",
        )
        movements = db.execute(
            """SELECT * FROM (
                   SELECT si.date AS date, 'in' AS kind, si.quantity AS delta,
                          COALESCE(NULLIF(si.source, ''), 'Delivery') AS detail,
                          'Stock in' AS label, si.id AS ref_id,
                          si.metres AS metres, si.serial_numbers AS serial_numbers
                   FROM stock_in si WHERE si.item_id = ?
                   UNION ALL
                   SELECT iss.date, 'out', -ii.quantity_issued,
                          'Issue #' || iss.id || ' · ' || p.name, 'Issued', ii.id,
                          ii.metres, ii.serial_numbers
                   FROM issue_items ii
                   JOIN issues iss ON iss.id = ii.issue_id
                   JOIN issued_to p ON p.id = iss.issued_to_id
                   WHERE ii.item_id = ?
                   UNION ALL
                   SELECT ii.returned_at, 'return', ii.quantity_returned,
                          'Issue #' || iss.id || ' · ' || p.name, 'Returned', ii.id,
                          NULL, ''
                   FROM issue_items ii
                   JOIN issues iss ON iss.id = ii.issue_id
                   JOIN issued_to p ON p.id = iss.issued_to_id
                   WHERE ii.item_id = ? AND ii.returned_at IS NOT NULL
                     AND ii.quantity_returned > 0
                   UNION ALL
                   SELECT sa.date, 'adjust', sa.quantity_change,
                          COALESCE(NULLIF(sa.reason, ''), 'Manual adjustment'), 'Adjustment', sa.id,
                          NULL, ''
                   FROM stock_adjustments sa WHERE sa.item_id = ?
               )
               ORDER BY date ASC, ref_id ASC, kind ASC""",
            (item_id, item_id, item_id, item_id),
        ).fetchall()

        history, balance = [], 0
        for movement in movements:
            balance += movement["delta"]
            history.append({**dict(movement), "balance": balance})
        history.reverse()

        totals = {
            "received": db.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM stock_in WHERE item_id = ?",
                (item_id,),
            ).fetchone()[0],
            "issued": db.execute(
                "SELECT COALESCE(SUM(quantity_issued), 0) FROM issue_items WHERE item_id = ?",
                (item_id,),
            ).fetchone()[0],
            "returned": db.execute(
                "SELECT COALESCE(SUM(quantity_returned), 0) FROM issue_items WHERE item_id = ?",
                (item_id,),
            ).fetchone()[0],
        }
        totals["outstanding"] = totals["issued"] - totals["returned"]

        ctx.update(item=item, history=history, totals=totals)
    return render(request, "item_detail.html", ctx)


@app.post("/items/{item_id}/adjust")
async def item_adjust(request: Request, item_id: int):
    form = await request.form()
    change = as_int(form.get("quantity_change"), 0)
    reason = str(form.get("reason", "")).strip()
    adjust_date = as_date(form.get("date"), TODAY())

    with get_db() as db:
        item = get_item_or_404(db, item_id)
        if change == 0:
            return redirect(
                f"/items/{item_id}",
                error="Enter a non-zero stock change (use - to reduce stock).",
            )
        if not reason:
            return redirect(f"/items/{item_id}", error="Give a reason for the adjustment.")
        if item["current_stock"] + change < 0:
            return redirect(
                f"/items/{item_id}",
                error="That adjustment would push stock below zero.",
            )
        db.execute(
            """INSERT INTO stock_adjustments (item_id, quantity_change, reason, date)
               VALUES (?, ?, ?, ?)""",
            (item_id, change, reason, adjust_date.isoformat()),
        )
        db.execute(
            "UPDATE items SET current_stock = current_stock + ? WHERE id = ?",
            (change, item_id),
        )
    return redirect(
        f"/items/{item_id}",
        msg=f"Stock adjusted by {change:+d} {item['unit']}.",
    )


# --------------------------------------------------------------------------- #
# Receive stock
# --------------------------------------------------------------------------- #


@app.get("/stock-in")
async def stock_in_page(request: Request):
    with get_db() as db:
        ctx = stock_in_context(request, db)
    return render(request, "stock_in.html", ctx)


@app.post("/stock-in")
async def stock_in_create(request: Request):
    form = await request.form()
    values = {
        "item_id": str(form.get("item_id", "")).strip(),
        "quantity": str(form.get("quantity", "")).strip(),
        "source": str(form.get("source", "")).strip(),
        "date": str(form.get("date", "")).strip() or TODAY().isoformat(),
        "metres": str(form.get("metres", "")).strip(),
        "serial_numbers": str(form.get("serial_numbers", "")).strip(),
    }
    quantity = as_int(values["quantity"], 0)
    metres = as_int(values["metres"], 0) if values["metres"] else None

    with get_db() as db:
        item = db.execute(
            "SELECT * FROM items WHERE id = ?", (as_int(values["item_id"]),)
        ).fetchone()
        error = None
        if item is None:
            error = "Pick an item to receive."
        elif quantity <= 0:
            error = "Enter a quantity greater than zero."
        elif metres is not None and metres < 0:
            error = "Metres must be zero or more."
        elif len(values["serial_numbers"]) > 500:
            error = "Keep serial numbers under 500 characters."
        elif not values["source"]:
            values["source"] = "Supplier delivery"
        if error:
            ctx = stock_in_context(request, db, values=values, error=error)
            return render(request, "stock_in.html", ctx, status_code=400)

        db.execute(
            """INSERT INTO stock_in
               (item_id, quantity, source, date, metres, serial_numbers)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                item["id"],
                quantity,
                values["source"],
                as_date(values["date"]).isoformat(),
                metres or None,
                values["serial_numbers"],
            ),
        )
        db.execute(
            "UPDATE items SET current_stock = current_stock + ? WHERE id = ?",
            (quantity, item["id"]),
        )
    message = f"Received {_unit_label(quantity, item['unit'])} of {item['name']}"
    if metres:
        message += f" ({metres:,} m)"
    message += "."
    return redirect("/stock-in", msg=message)


# --------------------------------------------------------------------------- #
# Issues & returns
# --------------------------------------------------------------------------- #


@app.get("/issues/new")
async def issue_new_page(request: Request):
    with get_db() as db:
        ctx = issue_form_context(request, db)
    return render(request, "issue_form.html", ctx)


@app.post("/issues/new")
async def issue_new(request: Request):
    form = await request.form()
    person_raw = str(form.get("issued_to_id", "")).strip()
    date_raw = str(form.get("date", "")).strip()
    raw_items = form.getlist("item_id")
    raw_quantities = form.getlist("quantity")
    raw_metres = form.getlist("metres")
    raw_serials = form.getlist("serials")

    rows = []
    for index, item_raw in enumerate(raw_items):
        rows.append(
            {
                "item_id": str(item_raw).strip(),
                "quantity": str(raw_quantities[index]).strip()
                if index < len(raw_quantities)
                else "",
                "metres": str(raw_metres[index]).strip()
                if index < len(raw_metres)
                else "",
                "serials": str(raw_serials[index]).strip()
                if index < len(raw_serials)
                else "",
            }
        )
    if not rows:
        rows = [{"item_id": "", "quantity": "1", "metres": "", "serials": ""}]
    values = {
        "issued_to_id": person_raw,
        "date": date_raw or TODAY().isoformat(),
    }

    with get_db() as db:
        person = db.execute(
            "SELECT * FROM issued_to WHERE id = ?", (as_int(person_raw),)
        ).fetchone()
        item_rows = db.execute("SELECT * FROM items").fetchall()
        items_by_id = {row["id"]: dict(row) for row in item_rows}

        error = None
        if person is None:
            error = "Pick the person receiving the items."
        elif not person["active"]:
            error = "That person is inactive. Reactivate them before issuing stock."
        else:
            lines: list[dict] = []
            seen: set[int] = set()
            for index, row in enumerate(rows, start=1):
                if not row["item_id"]:
                    continue
                item_id = as_int(row["item_id"], 0)
                quantity = as_int(row["quantity"], 0)
                metres = as_int(row["metres"], 0) if row["metres"] else None
                if item_id not in items_by_id:
                    error = f"Choose a valid item on line {index}."
                    break
                if quantity <= 0:
                    error = f"Enter a quantity greater than zero on line {index}."
                    break
                if metres is not None and metres < 0:
                    error = f"Metres on line {index} must be zero or more."
                    break
                if len(row["serials"]) > 500:
                    error = f"Keep serial numbers on line {index} under 500 characters."
                    break
                if item_id in seen:
                    error = f"{items_by_id[item_id]['name']} appears more than once. Combine it into one line."
                    break
                seen.add(item_id)
                lines.append(
                    {
                        "item_id": item_id,
                        "quantity": quantity,
                        "metres": metres,
                        "serials": row["serials"],
                    }
                )

            if error is None and not lines:
                error = "Add at least one item to the issue."
            if error is None:
                for line in lines:
                    item = items_by_id[line["item_id"]]
                    if line["quantity"] > item["current_stock"]:
                        error = (
                            f"Only {item['current_stock']} {item['unit']} of "
                            f"{item['name']} are in stock."
                        )
                        break

        if error:
            ctx = issue_form_context(
                request, db, values=values, rows=rows, error=error
            )
            return render(request, "issue_form.html", ctx, status_code=400)

        issue_id = db.execute(
            "INSERT INTO issues (issued_to_id, date) VALUES (?, ?)",
            (person["id"], as_date(values["date"]).isoformat()),
        ).lastrowid
        for line in lines:
            db.execute(
                """INSERT INTO issue_items
                   (issue_id, item_id, quantity_issued, quantity_returned,
                    metres, serial_numbers)
                   VALUES (?, ?, ?, 0, ?, ?)""",
                (
                    issue_id,
                    line["item_id"],
                    line["quantity"],
                    line["metres"] or None,
                    line["serials"],
                ),
            )
            db.execute(
                "UPDATE items SET current_stock = current_stock - ? WHERE id = ?",
                (line["quantity"], line["item_id"]),
            )
    return redirect(
        f"/issues/{issue_id}",
        msg=f"Issue #{issue_id} recorded for {person['name']}.",
    )


@app.get("/issues/{issue_id}")
async def issue_detail(request: Request, issue_id: int):
    with get_db() as db:
        issue = get_issue_or_404(db, issue_id)
        lines = issue_lines(db, issue_id)
        ctx = shell(
            request,
            db,
            "returns",
            f"Issue #{issue_id}",
            "Check-out record",
            f"{issue['person']} · issued {_datefmt(issue['date'])}",
        )
        totals = {
            "issued": sum(line["quantity_issued"] for line in lines),
            "returned": sum(line["quantity_returned"] for line in lines),
            "outstanding": sum(line["outstanding"] for line in lines),
        }
        ctx.update(
            issue=issue,
            lines=lines,
            totals=totals,
            complete=totals["outstanding"] == 0,
        )
    return render(request, "issue_detail.html", ctx)


@app.post("/issues/{issue_id}/return")
async def record_return(request: Request, issue_id: int):
    form = await request.form()
    return_date = as_date(form.get("date"), TODAY())

    with get_db() as db:
        get_issue_or_404(db, issue_id)
        lines = issue_lines(db, issue_id)
        actions: list[dict] = []
        error = None

        for line in lines:
            quantity = as_int(form.get(f"return_{line['id']}"), 0)
            if quantity <= 0:
                continue
            if quantity > line["outstanding"]:
                error = (
                    f"Only {line['outstanding']} {line['unit']} of "
                    f"{line['item_name']} are still out."
                )
                break
            actions.append({"line": line, "quantity": quantity})

        if error is None and not actions:
            error = "Enter at least one quantity greater than zero to return."
        if error:
            return redirect(f"/issues/{issue_id}", error=error)

        total = 0
        for action in actions:
            line, quantity = action["line"], action["quantity"]
            db.execute(
                """UPDATE issue_items
                   SET quantity_returned = quantity_returned + ?, returned_at = ?
                   WHERE id = ?""",
                (quantity, return_date.isoformat(), line["id"]),
            )
            db.execute(
                "UPDATE items SET current_stock = current_stock + ? WHERE id = ?",
                (quantity, line["item_id"]),
            )
            total += quantity
    return redirect(
        f"/issues/{issue_id}",
        msg=f"Recorded {total} returned unit{'' if total == 1 else 's'} on issue #{issue_id}.",
    )


@app.get("/returns")
async def returns_page(request: Request, scope: str = "open"):
    with get_db() as db:
        ctx = shell(
            request,
            db,
            "returns",
            "Returns",
            "Check-in",
            "Pick a past issue to record returned quantities and add them back to stock.",
        )
        having = "HAVING SUM(ii.quantity_issued - ii.quantity_returned) > 0" if scope != "all" else ""
        issues = db.execute(
            f"""SELECT iss.id, iss.date, p.name AS person, p.id AS person_id,
                       COUNT(ii.id) AS line_count,
                       SUM(ii.quantity_issued) AS issued,
                       SUM(ii.quantity_returned) AS returned,
                       SUM(ii.quantity_issued - ii.quantity_returned) AS outstanding,
                       GROUP_CONCAT(
                           CASE WHEN ii.quantity_issued > ii.quantity_returned
                                THEN i.name || ' ×' || (ii.quantity_issued - ii.quantity_returned)
                           END, ', '
                       ) AS outstanding_summary
                FROM issues iss
                JOIN issued_to p ON p.id = iss.issued_to_id
                JOIN issue_items ii ON ii.issue_id = iss.id
                JOIN items i ON i.id = ii.item_id
                GROUP BY iss.id
                {having}
                ORDER BY iss.date DESC, iss.id DESC"""
        ).fetchall()
        stats = {
            "open": db.execute(
                """SELECT COUNT(*) FROM issues i WHERE EXISTS (
                       SELECT 1 FROM issue_items ii WHERE ii.issue_id = i.id
                         AND ii.quantity_issued > ii.quantity_returned)"""
            ).fetchone()[0],
            "units": ctx["nav_outstanding"],
            "people": db.execute(
                """SELECT COUNT(DISTINCT iss.issued_to_id)
                   FROM issues iss JOIN issue_items ii ON ii.issue_id = iss.id
                   WHERE ii.quantity_issued > ii.quantity_returned"""
            ).fetchone()[0],
            "closed": db.execute(
                """SELECT COUNT(*) FROM issues i WHERE NOT EXISTS (
                       SELECT 1 FROM issue_items ii WHERE ii.issue_id = i.id
                         AND ii.quantity_issued > ii.quantity_returned)"""
            ).fetchone()[0],
        }
        ctx.update(issues=issues, stats=stats, scope=scope)
    return render(request, "returns.html", ctx)


# --------------------------------------------------------------------------- #
# People (issued to)
# --------------------------------------------------------------------------- #


@app.get("/people")
async def people_page(request: Request):
    with get_db() as db:
        ctx = shell(
            request,
            db,
            "people",
            "Issued to",
            "People",
            "Everyone who can be issued stock, and what each person still has out.",
        )
        people_rows = db.execute(
            """SELECT p.*,
                      (SELECT COUNT(*) FROM issues iss WHERE iss.issued_to_id = p.id) AS issue_count,
                      (SELECT COUNT(DISTINCT iss.id) FROM issues iss
                       JOIN issue_items ii ON ii.issue_id = iss.id
                       WHERE iss.issued_to_id = p.id
                         AND ii.quantity_issued > ii.quantity_returned) AS open_issue_count,
                      COALESCE((SELECT SUM(ii.quantity_issued - ii.quantity_returned)
                                FROM issue_items ii
                                JOIN issues iss ON iss.id = ii.issue_id
                                WHERE iss.issued_to_id = p.id), 0) AS outstanding
               FROM issued_to p
               ORDER BY p.active DESC, p.name COLLATE NOCASE"""
        ).fetchall()
        outstanding_rows = db.execute(
            """SELECT iss.issued_to_id AS person_id, i.name AS item_name, i.unit,
                      SUM(ii.quantity_issued - ii.quantity_returned) AS quantity
               FROM issue_items ii
               JOIN issues iss ON iss.id = ii.issue_id
               JOIN items i ON i.id = ii.item_id
               WHERE ii.quantity_issued > ii.quantity_returned
               GROUP BY iss.issued_to_id, i.id
               ORDER BY i.name COLLATE NOCASE"""
        ).fetchall()
        by_person: dict[int, list[dict]] = defaultdict(list)
        for row in outstanding_rows:
            by_person[row["person_id"]].append(dict(row))
        people = []
        for row in people_rows:
            person = dict(row)
            person["outstanding_items"] = by_person.get(person["id"], [])
            people.append(person)
        ctx.update(
            people=people,
            active_count=sum(1 for person in people if person["active"]),
            inactive_count=sum(1 for person in people if not person["active"]),
        )
    return render(request, "people.html", ctx)


@app.post("/people")
async def person_create(request: Request):
    form = await request.form()
    name = str(form.get("name", "")).strip()
    phone = str(form.get("phone", "")).strip()
    if not name:
        return redirect("/people", error="Enter a name for the person.")
    if len(name) > 100:
        return redirect("/people", error="Keep the name under 100 characters.")
    with get_db() as db:
        db.execute(
            "INSERT INTO issued_to (name, phone, active) VALUES (?, ?, 1)",
            (name, phone),
        )
    return redirect("/people", msg=f"{name} can now be issued stock.")


@app.post("/people/{person_id}/toggle")
async def person_toggle(request: Request, person_id: int):
    with get_db() as db:
        person = db.execute(
            "SELECT * FROM issued_to WHERE id = ?", (person_id,)
        ).fetchone()
        if person is None:
            raise HTTPException(status_code=404, detail="That person could not be found.")
        new_active = 0 if person["active"] else 1
        db.execute(
            "UPDATE issued_to SET active = ? WHERE id = ?", (new_active, person_id)
        )
        outstanding = db.execute(
            """SELECT COALESCE(SUM(ii.quantity_issued - ii.quantity_returned), 0)
               FROM issue_items ii JOIN issues iss ON iss.id = ii.issue_id
               WHERE iss.issued_to_id = ?""",
            (person_id,),
        ).fetchone()[0]
    if new_active:
        return redirect("/people", msg=f"{person['name']} is active again.")
    note = f"{person['name']} is now inactive."
    if outstanding:
        note += f" They still have {outstanding} unit(s) out."
    return redirect("/people", msg=note)


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #


def report_range(start_raw: str, end_raw: str) -> tuple[date, date]:
    end = as_date(end_raw, TODAY())
    start = as_date(start_raw, end - timedelta(days=29))
    if start > end:
        start, end = end, start
    return start, end


@app.get("/reports")
async def reports_page(request: Request, start: str = "", end: str = ""):
    start_date, end_date = report_range(start, end)
    start_iso, end_iso = start_date.isoformat(), end_date.isoformat()

    with get_db() as db:
        ctx = shell(
            request,
            db,
            "reports",
            "Reports",
            "Insights",
            "Stock in and out over a date range, plus a per-person issuance summary.",
        )
        summary = {
            "stock_in": db.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM stock_in WHERE date BETWEEN ? AND ?",
                (start_iso, end_iso),
            ).fetchone()[0],
            "stock_out": db.execute(
                """SELECT COALESCE(SUM(ii.quantity_issued), 0)
                   FROM issue_items ii JOIN issues iss ON iss.id = ii.issue_id
                   WHERE iss.date BETWEEN ? AND ?""",
                (start_iso, end_iso),
            ).fetchone()[0],
            "returns": db.execute(
                """SELECT COALESCE(SUM(quantity_returned), 0) FROM issue_items
                   WHERE returned_at BETWEEN ? AND ?""",
                (start_iso, end_iso),
            ).fetchone()[0],
            "adjustments": db.execute(
                """SELECT COALESCE(SUM(quantity_change), 0) FROM stock_adjustments
                   WHERE date BETWEEN ? AND ?""",
                (start_iso, end_iso),
            ).fetchone()[0],
        }
        summary["net"] = (
            summary["stock_in"]
            - summary["stock_out"]
            + summary["returns"]
            + summary["adjustments"]
        )

        movements = db.execute(
            """SELECT * FROM (
                   SELECT si.date AS date, 'in' AS kind, i.id AS item_id,
                          i.name AS item, i.unit AS unit, si.quantity AS qty,
                          COALESCE(NULLIF(si.source, ''), 'Delivery') AS reference
                   FROM stock_in si JOIN items i ON i.id = si.item_id
                   UNION ALL
                   SELECT iss.date, 'out', i.id, i.name, i.unit, -ii.quantity_issued,
                          'Issue #' || iss.id || ' · ' || p.name
                   FROM issue_items ii
                   JOIN issues iss ON iss.id = ii.issue_id
                   JOIN items i ON i.id = ii.item_id
                   JOIN issued_to p ON p.id = iss.issued_to_id
                   UNION ALL
                   SELECT ii.returned_at, 'return', i.id, i.name, i.unit, ii.quantity_returned,
                          'Issue #' || iss.id || ' · ' || p.name
                   FROM issue_items ii
                   JOIN issues iss ON iss.id = ii.issue_id
                   JOIN items i ON i.id = ii.item_id
                   JOIN issued_to p ON p.id = iss.issued_to_id
                   WHERE ii.returned_at IS NOT NULL AND ii.quantity_returned > 0
                   UNION ALL
                   SELECT sa.date, 'adjust', i.id, i.name, i.unit, sa.quantity_change,
                          COALESCE(NULLIF(sa.reason, ''), 'Manual adjustment')
                   FROM stock_adjustments sa JOIN items i ON i.id = sa.item_id
               )
               WHERE date BETWEEN ? AND ?
               ORDER BY date DESC, kind ASC""",
            (start_iso, end_iso),
        ).fetchall()

        per_person = db.execute(
            """SELECT p.id, p.name, COUNT(DISTINCT iss.id) AS issue_count,
                      SUM(ii.quantity_issued) AS issued,
                      SUM(ii.quantity_returned) AS returned,
                      SUM(ii.quantity_issued - ii.quantity_returned) AS outstanding
               FROM issues iss
               JOIN issued_to p ON p.id = iss.issued_to_id
               JOIN issue_items ii ON ii.issue_id = iss.id
               WHERE iss.date BETWEEN ? AND ?
               GROUP BY p.id, p.name
               ORDER BY issued DESC, p.name COLLATE NOCASE""",
            (start_iso, end_iso),
        ).fetchall()

        ctx.update(
            summary=summary,
            movements=movements,
            per_person=per_person,
            start=start_iso,
            end=end_iso,
        )
    return render(request, "reports.html", ctx)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        with get_db() as db:
            ctx = shell(
                request,
                db,
                "",
                "Page not found",
                "404",
                "The page you were looking for does not exist.",
            )
        ctx["message"] = exc.detail
        return render(request, "404.html", ctx, status_code=404)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
