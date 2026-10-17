"""
The user's own recipes, written or pasted on the page.

Kept in MEAL_PLANNER_DATA:
    recipes_custom.json      (the recipes, loaded by the planner like the imported ones)
    ingredients_custom.json  (ingredients the user added by picking a product, reused in later recipes)

Each recipe keeps the rows of the form ("lines": text, ingredient id, amount), so that it can be edited.
Rows without an ingredient (e.g. "αλάτι, πιπέρι") are shown but not costed.
"""
import json
import os
import re

from .import_akis import ANIMAL, FISH, MEAT, category_for, map_ingredient, map_unit, parse_qty, slugify, to_amount
from .planner import APPLIANCES, CUSTOM_RECIPES, detect_appliances
from .pricing import norm, normalize_size

CUSTOM_INGREDIENTS = "ingredients_custom.json"
TYPES = {"plant": "Φυτικό", "dairy": "Γαλακτοκομικό", "egg": "Αυγά", "meat": "Κρέας", "fish": "Ψάρι"}
UNITS = ("g", "ml", "pcs")


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def recipes(state_dir):
    return _read(os.path.join(state_dir, CUSTOM_RECIPES), [])


def guess_type(name):
    """Plant, dairy, egg, meat or fish from the name of a product."""
    n = norm(name)
    if FISH.search(n):
        return "fish"
    if MEAT.search(n):
        return "meat"
    if re.search(r"\bαυγ", n):
        return "egg"
    return "dairy" if ANIMAL.search(n) else "plant"


def _new_ingredient(raw):
    """An ingredient from a product the user picked: {name, query, type, product: {store, name, price, size, unit}}."""
    name = str(raw.get("name") or "").strip()
    p = raw.get("product") or {}
    if not name or p.get("unit") not in UNITS:
        raise ValueError("Λείπει το όνομα ή το προϊόν του νέου υλικού.")
    try:
        price, size = float(p["price"]), float(p["size"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"Λάθος τιμή για το υλικό «{name}».")
    if size <= 0:
        raise ValueError(f"Λάθος μέγεθος για το υλικό «{name}».")
    per = price / size * (1000 if p["unit"] in ("g", "ml") else 1)  # €/kg, €/l or €/piece
    return {
        "name": name[:1].upper() + name[1:], "query": str(raw.get("query") or name).strip(), "unit": p["unit"],
        "fallback_price": round(per, 2), "aisle": "Δικά μου υλικά",
        "type": raw.get("type") if raw.get("type") in TYPES else guess_type(p.get("name", name)),
        "custom": True, "product": {"store": p.get("store"), "name": p.get("name", "")},
    }


def _unique(base, taken):
    rid, n = base, 2
    while rid in taken:
        rid, n = f"{base}_{n}", n + 1
    return rid


def save(state_dir, planner, body):
    """
    Create or update (body["id"]) a recipe:
    {name, meal: "breakfast"|"main", servings, time, steps: [str], appliances: [id] (null: found in the steps),
     lines: [{text, ingredient: id|null, amount, new: {name, query, type, product} (an ingredient to add)}]}
    """
    name = str(body.get("name") or "").strip()
    if not name:
        raise ValueError("Δώσε όνομα στη συνταγή.")
    try:
        servings = max(1, min(24, int(body.get("servings") or 4)))
        time = max(1, min(600, int(body.get("time") or 30)))
    except (TypeError, ValueError):
        raise ValueError("Οι μερίδες και ο χρόνος πρέπει να είναι αριθμοί.")
    meal = ["breakfast"] if body.get("meal") == "breakfast" else ["lunch", "dinner"]

    ing_path = os.path.join(state_dir, CUSTOM_INGREDIENTS)
    own = _read(ing_path, {})
    known = {**planner.ingredients, **own}
    lines, amounts = [], {}
    for row in body.get("lines") or []:
        text = str(row.get("text") or "").strip()
        iid = row.get("ingredient")
        if row.get("new"):
            ing = _new_ingredient(row["new"])
            # The same product again (e.g. in a second recipe) reuses the ingredient
            iid = next((k for k, v in own.items() if v.get("product") == ing["product"] and v["name"] == ing["name"]),
                       None) or _unique("my_" + (slugify(ing["name"]) or "item"), known)
            own[iid] = known[iid] = ing
        if iid and iid not in known:
            raise ValueError(f"Άγνωστο υλικό: {iid}")
        try:
            amount = float(row.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0
        if iid and amount <= 0:
            raise ValueError(f"Βάλε ποσότητα για «{text or known[iid]['name']}».")
        if not text and not iid:
            continue
        if iid:
            amounts[iid] = amounts.get(iid, 0) + amount
            text = text or known[iid]["name"]
        lines.append({"text": text, "ingredient": iid or None, "amount": round(amount, 1) if iid else None})
    if not amounts:
        raise ValueError("Η συνταγή χρειάζεται τουλάχιστον ένα υλικό με ποσότητα.")
    steps = [s.strip() for s in body.get("steps") or [] if str(s).strip()]
    appliances = body.get("appliances")
    appliances = detect_appliances(" ".join([name] + steps)) if appliances is None else         [a for a in APPLIANCES if a in appliances]

    all_recipes = recipes(state_dir)
    rid = body.get("id")
    if rid and not any(r["id"] == rid for r in all_recipes):
        raise ValueError("Η συνταγή δεν βρέθηκε.")
    if not rid:
        rid = _unique("my_" + (slugify(name) or "recipe"), set(planner.recipes))
    recipe = {
        "id": rid, "name": name, "meal": meal,
        "category": category_for(meal, amounts, norm(" ".join([name] + [l["text"] for l in lines]))),
        "servings": servings, "time": time, "ingredients": {k: round(v, 1) for k, v in amounts.items()},
        "display": [l["text"] for l in lines], "lines": lines, "steps": steps, "appliances": appliances,
    }
    if body.get("id"):
        all_recipes = [recipe if r["id"] == rid else r for r in all_recipes]
    else:
        all_recipes.append(recipe)
    _write(ing_path, own)
    _write(os.path.join(state_dir, CUSTOM_RECIPES), all_recipes)
    return recipe


def delete(state_dir, rid):
    rs = recipes(state_dir)
    if not any(r["id"] == rid for r in rs):
        raise ValueError("Η συνταγή δεν βρέθηκε.")
    _write(os.path.join(state_dir, CUSTOM_RECIPES), [r for r in rs if r["id"] != rid])


# ---- pasted text -----------------------------------------------------
_ING_HEAD = re.compile(r"^(υλικα|συστατικα|χρειαζομαστε|τι χρειαζεσαι)\b")
_STEP_HEAD = re.compile(r"^(εκτελεση|οδηγιες|παρασκευη|βηματα|τροποσ|διαδικασια|μεθοδοσ)\b")
_QTY = r"\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?(?:\s+\d+/\d+)?|[½¼¾]"
_LEAD = re.compile(rf"^((?:{_QTY})(?:\s*[-–]\s*(?:{_QTY}))?)\s*(.*)$")
# Sizes and containers are not part of the name: "κουτί philadelphia 200g" is searched as "philadelphia"
_SIZE = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?\s*(?:g|gr|kg|ml|l|lt|γρ\w*|κιλ\w*|λ[ιί]τρ\w*)\.?(?!\w)", re.I)
# Matched on the text without accents
_CONTAINER = re.compile(r"^(?:κουτ|βαζ|πακετ|συσκευασ|κονσερβ|μπουκαλ|σακουλ)\w*\s+")
_TRAIL = re.compile(rf"^(.*?)[\s:,-]+((?:{_QTY}))\s*([^\d\s]*\.?)\s*$")


def _clean(line):
    return re.sub(r"^\s*(?:[-•*·▪●–]|\d+[.)])\s+", "", line).strip()


def _amount(qty_s, unit_s, title, ingredients):
    """(ingredient id or None, amount) for a parsed ingredient line."""
    _, iid = map_ingredient(title)
    if not iid or iid not in ingredients:
        return None, None
    unit = map_unit(unit_s) if unit_s else ("pcs", 1)
    qty = parse_qty(qty_s) if qty_s else None
    amount = to_amount(qty, unit, iid, ingredients[iid]) if unit and qty else None
    return iid, round(amount, 1) if amount else None


def _hint(text, qty_s, unit_s):
    """
    The quantity of a line for an ingredient that is not known yet, {unit, amount} or None:
    "1 κουτί philadelphia 200g" -> 200 g, "500 ml κρέμα" -> 500 ml, "2 αβοκάντο" -> 2 pcs.
    """
    size = _SIZE.search(text)
    if size:
        m = re.match(r"([\d.,]+)\s*(\w+)", size.group())
        n = normalize_size(m.group(1).replace(",", "."), {"γρ": "g", "κι": "kg", "λι": "l", "λί": "l"}.get(
            m.group(2)[:2].lower(), m.group(2)))
        if n:
            return {"unit": n[0], "amount": n[1]}
    qty = parse_qty(qty_s) if qty_s else None
    unit = map_unit(unit_s) if unit_s else ("pcs", 1)
    if qty and unit and unit[0] in UNITS:
        return {"unit": unit[0], "amount": qty * unit[1]}
    return None


def parse_line(line, ingredients):
    """An ingredient line as {text, ingredient, amount, title}: "200 γρ. φέτα", "2 ντομάτες", "φέτα 200γρ"."""
    text = _clean(line)
    qty_s = unit_s = ""
    title = text
    m = _LEAD.match(text)
    if m:
        # "200γρ. φέτα", "2 κ.σ. ελαιόλαδο", "2 ντομάτες" (no unit), "1 σκόρδο" (not "σκ(ελίδα)" + nothing)
        qty_s, title = m.group(1), m.group(2)
        um = re.match(r"^(\S+)\s+(\S.*)$", title)
        if um and map_unit(um.group(1)):
            unit_s, title = um.group(1), um.group(2)
    else:
        m = _TRAIL.match(text)
        if m and m.group(1):
            title, qty_s, unit_s = m.group(1), m.group(2), m.group(3)
    title = _SIZE.sub("", re.sub(r"\(.*?\)", " ", title))
    title = re.sub(r"\s+", " ", title).strip(" ,.-")
    c = _CONTAINER.match(norm(title))
    if c and c.end() < len(title):  # norm() keeps the length of precomposed Greek letters
        title = title[c.end():]
    known, mapped = map_ingredient(title)
    iid, amount = _amount(qty_s, unit_s, title, ingredients)
    return {"text": text, "title": title, "ingredient": iid, "amount": amount, "hint": _hint(text, qty_s, unit_s),
            # "αλάτι", "νερό": a known item that is not costed
            "free": known and mapped is None}


def parse(text, ingredients):
    """A draft recipe from pasted text: {name, servings, time, lines, steps, appliances}."""
    raw = [l.strip() for l in (text or "").replace("\r", "").split("\n")]
    raw = [l for l in raw if l]
    draft = {"name": "", "servings": None, "time": None, "lines": [], "steps": [], "appliances": detect_appliances(text)}
    mode = None
    for i, line in enumerate(raw):
        n = norm(line).strip(" :")
        if _ING_HEAD.match(n):
            mode = "ing"
            continue
        if _STEP_HEAD.match(n):
            mode = "step"
            continue
        sv = re.search(r"(\d+)\s*(μεριδ|ατομ)", n)
        tm = re.search(r"(\d+)\s*(λεπτ|')", n)
        if (sv or tm) and len(n) < 40 and mode != "step":
            if sv:
                draft["servings"] = int(sv.group(1))
            if tm:
                draft["time"] = int(tm.group(1))
            continue
        if not draft["name"] and mode is None:
            draft["name"] = _clean(line)
            continue
        if mode is None:
            # No headings: short lines with a quantity are ingredients, the rest steps
            mode_here = "ing" if (_LEAD.match(_clean(line)) and len(line) < 60) or len(line) < 30 else "step"
        else:
            mode_here = mode
        if mode_here == "ing":
            draft["lines"].append(parse_line(line, ingredients))
        else:
            draft["steps"].append(_clean(line))
    return draft
