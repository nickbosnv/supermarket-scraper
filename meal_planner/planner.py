"""Builds a weekly meal plan within a budget."""
import glob
import json
import logging
import math
import os
import random
import re
from collections import Counter, defaultdict
from datetime import datetime

from .pricing import STORES, norm

DAYS = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
MEALS = {"breakfast": "Πρωινό", "lunch": "Μεσημεριανό", "dinner": "Βραδινό"}
DIETS = {"all": "Όλα", "vegetarian": "Χορτοφαγικό", "fasting": "Νηστίσιμο"}
SOURCES = {"all": "Όλες", "builtin": "Μόνο ενσωματωμένες", "imported": "Μόνο εισαγόμενες",
           "custom": "Μόνο δικές μου"}
# The user's own recipes, written from the page (custom.py)
CUSTOM_RECIPES = "recipes_custom.json"
log = logging.getLogger(__name__)
SAMPLES = 300
MEAL_ORDER = {"breakfast": 0, "lunch": 1, "dinner": 2}
# Main protein group, for variety: not the same group twice in a row, not more than 2 times a week.
GROUPS = {
    "chicken": "chicken", "soup_chicken": "chicken", "pasta_chicken": "chicken",
    "pasta_meat": "beef", "meat_oven": "beef", "beef": "beef", "soup_meat": "beef",
    "pork": "pork", "fish": "fish", "pasta_fish": "fish", "legumes": "legumes",
    "ladera": "veg", "veg_fried": "veg", "pie": "veg", "salad": "veg", "eggs": "eggs",
}

# Kitchen appliances a recipe may need, found in its name and steps (without accents).
# The hob is taken for granted. "σε σχάρα ή τηγάνι" is a choice, so grills are only the named appliances.
APPLIANCES = {
    "oven": "Φούρνος", "blender": "Μπλέντερ", "mixer": "Μίξερ", "processor": "Multi / κοπτικό",
    "air_fryer": "Air fryer", "pressure_cooker": "Χύτρα ταχύτητας", "toaster": "Τοστιέρα",
    "grill": "Γκριλιέρα / ψηστιέρα", "microwave": "Φούρνος μικροκυμάτων", "waffle": "Βαφλιέρα / κρεπιέρα",
    "slow_cooker": "Slow cooker", "thermomix": "Thermomix",
}
_APPLIANCE_RX = {k: re.compile(p) for k, p in {
    "oven": r"φουρν(?!\w*\s+μικροκυμ)|ταψ|πυρεξ",
    "blender": r"μπλεντερ|blender",
    "mixer": r"μιξερ|mixer|κουζινομηχαν",
    "processor": r"multi|μουλτι|κοπτικο|food processor",
    "air_fryer": r"air ?fryer|φριτεζα αερ",
    "pressure_cooker": r"χυτρα ταχυτ|βαλβιδα",
    "toaster": r"τοστιερ",
    "grill": r"γκριλιερ|ψηστιερ|καρβουν",
    "microwave": r"μικροκυμ",
    "waffle": r"βαφλιερ|κρεπιερ",
    "slow_cooker": r"slow ?cooker|αργου μαγειρ",
    "thermomix": r"thermomix|θερμομιξ",
}.items()}
_DEGREES = re.compile(r"\d\s*(?:°|βαθμ)")


def detect_appliances(text):
    """The appliances a recipe text needs, in the order of APPLIANCES."""
    t = norm(text)
    found = {k for k, rx in _APPLIANCE_RX.items() if rx.search(t)}
    # A baking temperature is the oven's, unless the recipe is for the air fryer
    if "air_fryer" not in found and _DEGREES.search(t):
        found.add("oven")
    return [k for k in APPLIANCES if k in found]


DEFAULTS = {
    "persons": 2, "budget": 60.0, "store": "sklavenitis", "diet": "all",
    "meals": ["breakfast", "lunch", "dinner"], "exclude": [], "leftovers": True,
    "include_pantry": False, "source": "all", "appliances": list(APPLIANCES),
}


class Planner:
    def __init__(self, data_dir, state_dir, provider):
        """data_dir has the built-in ingredients and recipes, state_dir the imported and the user's own."""
        self.data_dir = data_dir
        self.state_dir = state_dir
        self.provider = provider
        self.reload()

    def reload(self):
        ings = {}
        for path in [os.path.join(self.data_dir, "ingredients.json")] + \
                sorted(glob.glob(os.path.join(self.state_dir, "ingredients_*.json"))):
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    ings.update({k: v for k, v in json.load(f).items() if not k.startswith("_")})
        recipes = {}
        builtin = os.path.join(self.data_dir, "recipes.json")
        files = [builtin] + sorted(glob.glob(os.path.join(self.state_dir, "recipes_*.json")))
        for path in files:
            with open(path, encoding="utf-8") as f:
                for r in json.load(f):
                    missing = [i for i in r["ingredients"] if i not in ings]
                    if missing:
                        if path == builtin:
                            raise ValueError(f"Συνταγή {r['id']}: άγνωστα υλικά {missing}")
                        log.warning("Skipping recipe %s: unknown ingredients %s", r["id"], missing)
                        continue
                    r["custom"] = os.path.basename(path) == CUSTOM_RECIPES
                    r["imported"] = path != builtin and not r["custom"]
                    if "appliances" not in r:  # own recipes say which they need
                        r["appliances"] = detect_appliances(" ".join([r["name"]] + r["steps"]))
                    recipes[r["id"]] = r
        self.ingredients, self.recipes = ings, recipes

    # ---- settings / eligibility -------------------------------------
    def clean_settings(self, raw):
        s = dict(DEFAULTS)
        s.update({k: v for k, v in (raw or {}).items() if k in DEFAULTS})
        s["persons"] = max(1, min(12, int(s["persons"])))
        s["budget"] = max(0.0, float(s["budget"]))
        if s["store"] not in STORES and s["store"] != "cheapest":
            s["store"] = DEFAULTS["store"]
        if s["diet"] not in DIETS:
            s["diet"] = "all"
        s["meals"] = [m for m in MEALS if m in s["meals"]] or ["dinner"]
        s["exclude"] = [i for i in s["exclude"] if i in self.ingredients]
        s["appliances"] = [a for a in APPLIANCES if a in s["appliances"]]
        s["leftovers"] = bool(s["leftovers"])
        s["include_pantry"] = bool(s["include_pantry"])
        if s["source"] not in SOURCES:
            s["source"] = "all"
        return s

    def stores(self, s):
        return list(STORES) if s["store"] == "cheapest" else [s["store"]]

    def _ok(self, r, s):
        origin = "custom" if r["custom"] else "imported" if r["imported"] else "builtin"
        if s["source"] != "all" and s["source"] != origin:
            return False
        types = {self.ingredients[i]["type"] for i in r["ingredients"]}
        diet = r.get("diet") or {}
        if s["diet"] == "vegetarian" and (types & {"meat", "fish"} or diet.get("vegetarian") is False):
            return False
        if s["diet"] == "fasting" and (types - {"plant"} or diet.get("vegan") is False):
            return False
        if set(r["appliances"]) - set(s["appliances"]):
            return False
        return not set(r["ingredients"]) & set(s["exclude"])

    def eligible(self, s, meal):
        kind = "breakfast" if meal == "breakfast" else "main"
        return [r["id"] for r in self.recipes.values()
                if self._ok(r, s) and (("breakfast" in r["meal"]) == (kind == "breakfast"))]

    # ---- structure ---------------------------------------------------
    def _skeleton(self, s):
        """List of cooks, each one covering 1+ slots (day, meal)."""
        cooks = []
        if "breakfast" in s["meals"]:
            cooks += [{"kind": "breakfast", "slots": [[d, "breakfast"]]} for d in range(7)]
        lunch, dinner = "lunch" in s["meals"], "dinner" in s["meals"]
        if s["leftovers"] and lunch and dinner:
            # Dinner is cooked twice over and becomes the next day's lunch.
            cooks.append({"kind": "main", "slots": [[0, "lunch"]]})
            for d in range(7):
                slots = [[d, "dinner"]] + ([[d + 1, "lunch"]] if d < 6 else [])
                cooks.append({"kind": "main", "slots": slots})
        else:
            for d in range(7):
                for m in ("lunch", "dinner"):
                    if m in s["meals"]:
                        cooks.append({"kind": "main", "slots": [[d, m]]})
        return cooks

    def _fill(self, cooks, s, rng, pools):
        for kind in ("breakfast", "main"):
            idx = [i for i, c in enumerate(cooks) if c["kind"] == kind]
            pool = pools[kind]
            picks = rng.sample(pool, len(idx)) if len(pool) >= len(idx) else \
                [rng.choice(pool) for _ in idx]
            for i, rid in zip(idx, picks):
                cooks[i]["recipe_id"] = rid
        return cooks

    def _variety_penalty(self, cooks):
        mains = sorted((c for c in cooks if c["kind"] == "main"),
                       key=lambda c: (c["slots"][0][0], MEAL_ORDER[c["slots"][0][1]]))
        cats = [self.recipes[c["recipe_id"]]["category"] for c in mains]
        groups = [GROUPS.get(c, c) for c in cats]
        pen = sum(3 for a, b in zip(groups, groups[1:]) if a == b)
        pen += sum(2 * (n - 2) for n in Counter(groups).values() if n > 2)
        bcats = [self.recipes[c["recipe_id"]]["category"] for c in cooks if c["kind"] == "breakfast"]
        pen += sum(1 for a, b in zip(bcats, bcats[1:]) if a == b)
        ids = Counter(c["recipe_id"] for c in cooks)
        pen += sum(5 * (n - 1) for n in ids.values() if n > 1)
        return pen

    # ---- shopping ----------------------------------------------------
    def shopping(self, cooks, s):
        need = defaultdict(float)
        for c in cooks:
            r = self.recipes[c["recipe_id"]]
            factor = s["persons"] * len(c["slots"]) / r["servings"]
            for iid, q in r["ingredients"].items():
                if self.ingredients[iid].get("pantry") and not s["include_pantry"]:
                    continue
                need[iid] += q * factor
        stores = self.stores(s)
        items, total, est = [], 0.0, 0
        for iid, q in need.items():
            ing = self.ingredients[iid]
            if ing["unit"] == "pcs":
                q = math.ceil(q - 1e-9)
            c = self.provider.cost(iid, ing, q, stores)
            total += c["cost"]
            est += c["estimated"]
            items.append({"id": iid, "name": ing["name"], "aisle": ing["aisle"],
                          "need": round(q, 1), "unit": ing["unit"], **c})
        return {"items": items, "total": round(total, 2), "estimated": est}

    # ---- public API --------------------------------------------------
    def generate(self, raw_settings, seed=None):
        s = self.clean_settings(raw_settings)
        rng = random.Random(seed)
        pools = {"breakfast": self.eligible(s, "breakfast"), "main": self.eligible(s, "lunch")}
        skel = self._skeleton(s)
        for kind in {c["kind"] for c in skel}:
            if not pools[kind]:
                what = "πρωινά" if kind == "breakfast" else "κυρίως γεύματα"
                raise ValueError(f"Δεν βρέθηκαν {what} με αυτά τα φίλτρα (διατροφή/πηγή/εξαιρέσεις/συσκευές).")
        self._warm(pools["breakfast"] + pools["main"], s)

        results = []
        for _ in range(SAMPLES):
            cooks = self._fill([dict(c) for c in skel], s, rng, pools)
            shop = self.shopping(cooks, s)
            results.append((self._objective(cooks, shop, s), cooks, shop))
        results.sort(key=lambda r: r[0])
        # Local search on the best 3, then a random pick among them for variety.
        improved = [self._improve(r[1], s, rng, pools) for r in results[:3]]
        improved.sort(key=lambda r: r[0])
        ok = [r for r in improved if r[2]["total"] <= s["budget"]]
        pick = rng.choice(ok) if ok else improved[0]
        return self._build(s, pick[1], pick[2])

    def _warm(self, recipe_ids, s):
        """Search the prices of the costed ingredients of these recipes that are not cached yet."""
        used = {i for rid in recipe_ids for i in self.recipes[rid]["ingredients"]}
        if not s["include_pantry"]:
            used = {i for i in used if not self.ingredients[i].get("pantry")}
        self.provider.warm(self.ingredients, sorted(used), self.stores(s))

    def _objective(self, cooks, shop, s):
        # Package leftovers are not a cost: they are kept for another time
        over = max(0.0, shop["total"] - s["budget"])
        return over * 10 + self._variety_penalty(cooks)

    def _improve(self, cooks, s, rng, pools, passes=3, tries=10):
        cooks = [dict(c) for c in cooks]
        shop = self.shopping(cooks, s)
        best = self._objective(cooks, shop, s)
        for _ in range(passes):
            changed = False
            for c in rng.sample(cooks, len(cooks)):
                pool = pools[c["kind"]]
                old = c["recipe_id"]
                for rid in rng.sample(pool, min(tries, len(pool))):
                    if rid == old:
                        continue
                    c["recipe_id"] = rid
                    sh = self.shopping(cooks, s)
                    obj = self._objective(cooks, sh, s)
                    if obj < best - 1e-6:
                        best, shop, old, changed = obj, sh, rid, True
                c["recipe_id"] = old
            if not changed:
                break
        return best, cooks, shop

    def _target(self, plan, day, meal):
        """The cook that covers a meal (day, meal)."""
        target = next((c for c in plan["cooks"] if [day, meal] in c["slots"]), None)
        if not target:
            raise ValueError("Δεν υπάρχει γεύμα σε αυτή τη θέση.")
        return target

    def _with_recipe(self, cooks, target, rid, s):
        """
        Shopping list and score if target cooks rid: within the budget first, by more variety and then
        cheaper, then over the budget, cheapest first.
        """
        old = target["recipe_id"]
        target["recipe_id"] = rid
        shop = self.shopping(cooks, s)
        over = shop["total"] > s["budget"]
        score = (over, shop["total"]) if over else (over, self._variety_penalty(cooks), shop["total"])
        target["recipe_id"] = old
        return score, shop

    def swap(self, plan, day, meal, seed=None):
        """Another recipe for a meal: the best of 12 random ones that are not in the plan yet."""
        s = plan["settings"]
        rng = random.Random(seed)
        cooks = plan["cooks"]
        target = self._target(plan, day, meal)
        pool = self.eligible(s, meal)
        in_use = {c["recipe_id"] for c in cooks}
        cands = [r for r in pool if r not in in_use] or [r for r in pool if r != target["recipe_id"]]
        if not cands:
            raise ValueError("Δεν υπάρχει εναλλακτική συνταγή.")
        rng.shuffle(cands)
        cands = cands[:12]
        self._warm(cands, s)
        score, shop, rid = min(((*self._with_recipe(cooks, target, rid, s), rid) for rid in cands),
                               key=lambda o: o[0])
        target["recipe_id"] = rid
        return self._build(s, cooks, shop, plan.get("generated_at"))

    def alternatives(self, plan, day, meal):
        """
        Every recipe that fits a meal, with the plan total if it is chosen, best first
        (within the budget, then more variety and cheaper).
        """
        s, cooks = plan["settings"], plan["cooks"]
        target = self._target(plan, day, meal)
        pool = self.eligible(s, meal)
        self._warm(pool, s)
        in_use = {c["recipe_id"] for c in cooks}
        options = []
        for rid in pool:
            score, shop = self._with_recipe(cooks, target, rid, s)
            r = self.recipes[rid]
            options.append((score, r["name"], {
                "id": rid, "name": r["name"], "time": r["time"], "imported": r["imported"], "custom": r["custom"],
                "current": rid == target["recipe_id"], "in_plan": rid in in_use and rid != target["recipe_id"],
                "total": shop["total"], "within_budget": shop["total"] <= s["budget"],
                "ingredients": [self.ingredients[i]["name"] for i in r["ingredients"]
                                if not self.ingredients[i].get("pantry")],
            }))
        options.sort(key=lambda o: o[:2])
        return {"slots": target["slots"], "total": plan["total"], "budget": s["budget"],
                "options": [o[2] for o in options]}

    def choose(self, plan, day, meal, rid):
        """Put recipe rid in a meal (and in the next day's lunch, if it is cooked for both)."""
        s = plan["settings"]
        target = self._target(plan, day, meal)
        if rid not in self.eligible(s, meal):
            raise ValueError("Αυτή η συνταγή δεν ταιριάζει σε αυτό το γεύμα με τις ρυθμίσεις του πλάνου.")
        self._warm([rid], s)
        target["recipe_id"] = rid
        return self._build(s, plan["cooks"], self.shopping(plan["cooks"], s), plan.get("generated_at"))

    def reprice(self, plan):
        return self._build(plan["settings"], plan["cooks"],
                           self.shopping(plan["cooks"], plan["settings"]), plan.get("generated_at"))

    def _build(self, s, cooks, shop, generated_at=None):
        for i, c in enumerate(cooks):
            c["id"] = i
        days = [{"name": DAYS[d], "meals": {}} for d in range(7)]
        for c in cooks:
            r = self.recipes[c["recipe_id"]]
            for n, (d, m) in enumerate(c["slots"]):
                days[d]["meals"][m] = {
                    "cook": c["id"], "recipe_id": r["id"], "name": r["name"], "time": r["time"],
                    "leftover": n > 0, "cook_portions": s["persons"] * len(c["slots"]) if n == 0 else None,
                }
        groups = defaultdict(list)
        for it in sorted(shop["items"], key=lambda x: x["name"]):
            groups[it["aisle"]].append(it)
        by_store = defaultdict(float)
        for it in shop["items"]:
            by_store[it["store"] or "estimate"] += it["cost"]
        return {
            "settings": s, "cooks": cooks, "days": days,
            "shopping": [{"aisle": a, "items": groups[a]} for a in sorted(groups)],
            "total": shop["total"], "estimated": shop["estimated"],
            "by_store": {k: round(v, 2) for k, v in by_store.items()},
            "within_budget": shop["total"] <= s["budget"],
            "generated_at": generated_at or datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def recipe_view(self, rid, persons):
        r = self.recipes[rid]
        f = persons / r["servings"]
        ings = []
        for iid, q in r["ingredients"].items():
            ing = self.ingredients[iid]
            qty = q * f
            ings.append({"name": ing["name"], "qty": _fmt(qty, ing["unit"]), "pantry": ing.get("pantry", False)})
        out = {"id": rid, "name": r["name"], "time": r["time"], "persons": persons,
               "ingredients": ings, "steps": r["steps"], "source": r.get("source"),
               "source_name": r.get("source_name"), "appliances": [APPLIANCES[a] for a in r["appliances"]]}
        if r.get("display"):  # imported or own recipe: show the ingredient lines as written
            out["original"] = {"servings": r["servings"], "lines": r["display"], "custom": r["custom"]}
        return out


def _fmt(q, unit):
    if unit == "pcs":
        return f"{max(1, round(q))} τεμ"
    if q >= 1000:
        return f"{q / 1000:.2f}".rstrip("0").rstrip(".") + (" kg" if unit == "g" else " l")
    q = round(q) if q >= 10 else round(q, 1)
    return f"{q:g} {unit}"
