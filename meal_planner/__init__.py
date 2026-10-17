"""
Weekly meal planner for the price finder, served as a Flask blueprint at /meals/.

Usage:

    from meal_planner import meal_bp, price_provider
    price_provider.register(my_search)        # search(store, query) -> list[dict], see pricing.py
    app.register_blueprint(meal_bp)
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, render_template, request

from . import custom
from .planner import APPLIANCES, DAYS, DIETS, MEALS, SOURCES, Planner, detect_appliances
from .pricing import STORES, PriceProvider

HERE = os.path.dirname(os.path.abspath(__file__))
# Ingredients and built-in recipes, shipped with the code
DATA = os.path.join(HERE, "data")
# Price cache, current plan, imported and own recipes, kept across updates (e.g. the Docker volume)
STATE = os.environ.get("MEAL_PLANNER_DATA", DATA)
os.makedirs(STATE, exist_ok=True)
PLAN_FILE = os.path.join(STATE, "current_plan.json")

price_provider = PriceProvider(os.path.join(STATE, "price_cache.json"),
                               ttl_hours=float(os.environ.get("MEAL_PLANNER_PRICE_TTL_H", 24)))
planner = Planner(DATA, STATE, price_provider)
_lock = threading.Lock()

meal_bp = Blueprint("meal_planner", __name__, url_prefix="/meals",
                    template_folder=os.path.join(HERE, "templates"))


def _load_plan():
    try:
        with open(PLAN_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save_plan(plan):
    tmp = PLAN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False)
    os.replace(tmp, PLAN_FILE)


def _err(msg, code=400):
    return jsonify({"error": msg}), code


@meal_bp.get("/")
def page():
    return render_template("meal_planner.html")


@meal_bp.get("/api/meta")
def meta():
    ings = sorted(({"id": k, "name": v["name"], "unit": v["unit"], "pantry": v.get("pantry", False)}
                   for k, v in planner.ingredients.items() if not v.get("auto")), key=lambda x: x["name"])
    imported = sum(1 for r in planner.recipes.values() if r["imported"])
    own = sum(1 for r in planner.recipes.values() if r["custom"])
    counts = {"builtin": len(planner.recipes) - imported - own, "imported": imported, "custom": own}
    return jsonify({"stores": STORES, "diets": DIETS, "meals": MEALS, "days": DAYS, "sources": SOURCES,
                    "source_counts": counts, "types": custom.TYPES, "appliances": APPLIANCES,
                    "ingredients": ings, "recipe_count": len(planner.recipes),
                    "connected": price_provider.search_fn is not None})


@meal_bp.get("/api/plan")
def get_plan():
    return jsonify(_load_plan())


@meal_bp.post("/api/plan")
def new_plan():
    try:
        with _lock:
            plan = planner.generate(request.get_json(force=True) or {})
            _save_plan(plan)
    except ValueError as e:
        return _err(str(e))
    return jsonify(plan)


@meal_bp.post("/api/swap")
def swap():
    body = request.get_json(force=True) or {}
    with _lock:
        plan = _load_plan()
        if not plan:
            return _err("Δεν υπάρχει πλάνο.")
        try:
            plan = planner.swap(plan, int(body["day"]), body["meal"])
        except (KeyError, ValueError) as e:
            return _err(str(e))
        _save_plan(plan)
    return jsonify(plan)


@meal_bp.get("/api/alternatives")
def alternatives():
    """The recipes that can replace a meal (?day=0..6&meal=...), best first."""
    plan = _load_plan()
    if not plan:
        return _err("Δεν υπάρχει πλάνο.")
    day = request.args.get("day", type=int)
    try:
        return jsonify(planner.alternatives(plan, day, request.args.get("meal", "")))
    except ValueError as e:
        return _err(str(e))


@meal_bp.post("/api/choose")
def choose():
    """Put the chosen recipe ({day, meal, recipe_id}) in a meal."""
    body = request.get_json(force=True) or {}
    with _lock:
        plan = _load_plan()
        if not plan:
            return _err("Δεν υπάρχει πλάνο.")
        try:
            plan = planner.choose(plan, int(body["day"]), body["meal"], body["recipe_id"])
        except (KeyError, TypeError, ValueError) as e:
            return _err(str(e))
        _save_plan(plan)
    return jsonify(plan)


@meal_bp.get("/api/recipe/<rid>")
def recipe(rid):
    if rid not in planner.recipes:
        return _err("Άγνωστη συνταγή", 404)
    portions = max(1, min(24, request.args.get("portions", 2, type=int)))
    return jsonify(planner.recipe_view(rid, portions))


@meal_bp.post("/api/refresh-prices")
def refresh_prices():
    """Clear the price cache and reprice the current plan."""
    with _lock:
        price_provider.clear()
        plan = _load_plan()
        if plan:
            s = plan["settings"]
            ids = sorted({i["id"] for g in plan["shopping"] for i in g["items"]})
            price_provider.warm(planner.ingredients, ids, planner.stores(s), force=True)
            plan = planner.reprice(plan)
            _save_plan(plan)
    return jsonify(plan)


@meal_bp.post("/api/reload-recipes")
def reload_recipes():
    try:
        planner.reload()
    except (ValueError, OSError) as e:
        return _err(str(e))
    return jsonify({"recipes": len(planner.recipes), "ingredients": len(planner.ingredients)})


# ---- the user's own recipes ------------------------------------------
def _plan_cooks(rid):
    """The current plan and the cooks of it that use recipe rid."""
    plan = _load_plan()
    return plan, [c for c in (plan or {}).get("cooks", []) if c["recipe_id"] == rid]


@meal_bp.get("/api/custom")
def custom_list():
    return jsonify(sorted(custom.recipes(STATE), key=lambda r: r["name"]))


@meal_bp.post("/api/custom")
def custom_save():
    """Create or update an own recipe (format in custom.save)."""
    body = request.get_json(force=True) or {}
    with _lock:
        plan, cooks = _plan_cooks(body.get("id"))
        if any((c["kind"] == "breakfast") != (body.get("meal") == "breakfast") for c in cooks):
            return _err("Η συνταγή είναι στο πλάνο ως άλλο γεύμα. Άλλαξέ τη εκεί με ↻ και μετά άλλαξε το γεύμα της.")
        try:
            recipe = custom.save(STATE, planner, body)
        except ValueError as e:
            return _err(str(e))
        planner.reload()
        if cooks:  # the plan costs the edited recipe
            _save_plan(planner.reprice(plan))
    return jsonify(recipe)


@meal_bp.post("/api/custom/<rid>/delete")
def custom_delete(rid):
    with _lock:
        if _plan_cooks(rid)[1]:
            return _err("Η συνταγή είναι στο πλάνο της εβδομάδας. Άλλαξέ τη με ↻ και μετά διάγραψέ τη.")
        try:
            custom.delete(STATE, rid)
        except ValueError as e:
            return _err(str(e))
        planner.reload()
    return jsonify({"ok": True})


@meal_bp.post("/api/custom/parse")
def custom_parse():
    """A draft recipe from pasted text, to check and correct in the form."""
    body = request.get_json(force=True) or {}
    return jsonify(custom.parse(str(body.get("text") or "")[:20000], planner.ingredients))


@meal_bp.post("/api/custom/appliances")
def custom_appliances():
    """The appliances found in the steps of a recipe ({text}), to tick them in the form."""
    body = request.get_json(force=True) or {}
    return jsonify(detect_appliances(str(body.get("text") or "")[:20000]))


@meal_bp.get("/api/products")
def products():
    """Products for a new ingredient (?q=...&store=ab|sklavenitis|mymarket|all), to pick the right one."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return _err("Γράψε τι να ψάξω.")
    store = request.args.get("store", "all")
    stores = [store] if store in STORES else list(STORES)
    with ThreadPoolExecutor(len(stores)) as ex:
        found = [p for ps in ex.map(lambda s: price_provider.products(s, q), stores) for p in ps[:30]]
    return jsonify({"products": found, "type": custom.guess_type(q)})
