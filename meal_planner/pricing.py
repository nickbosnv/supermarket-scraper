"""
Prices for the meal planner from the price finder's scrapers, with a cache.

The registered search function has the signature:

    search(store: str, query: str) -> list[dict]

where store is "ab", "sklavenitis" or "mymarket", and each dict is
    {"name": str, "price": float, "size": float, "size_unit": "g|kg|ml|l|pcs|τεμ", "url": str (optional)}

"price" is the price of the package and "size" its contents.
"""
import json
import logging
import math
import os
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

STORES = {"ab": "ΑΒ Βασιλόπουλος", "sklavenitis": "Σκλαβενίτης", "mymarket": "My Market"}

_UNITS = {
    "g": ("g", 1), "gr": ("g", 1), "γρ": ("g", 1), "kg": ("g", 1000), "κιλο": ("g", 1000),
    "ml": ("ml", 1), "l": ("ml", 1000), "lt": ("ml", 1000), "λιτρο": ("ml", 1000),
    "pcs": ("pcs", 1), "pc": ("pcs", 1), "τεμ": ("pcs", 1), "τεμαχιο": ("pcs", 1), "τμχ": ("pcs", 1),
}


def norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("ς", "σ")


def normalize_size(size, unit):
    u = norm(unit).strip().rstrip(".")
    if u not in _UNITS:
        return None
    base, mul = _UNITS[u]
    try:
        v = float(size) * mul
    except (TypeError, ValueError):
        return None
    return (base, v) if v > 0 else None


class PriceProvider:
    def __init__(self, cache_path, ttl_hours=24, workers=6):
        self.search_fn = None
        self.cache_path = cache_path
        self.ttl = ttl_hours * 3600
        self.workers = workers
        self.lock = threading.Lock()
        self.cache = self._load()

    # ---- setup -------------------------------------------------------
    def register(self, fn):
        """Set the search(store, query) function of the price finder."""
        self.search_fn = fn

    def _load(self):
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save(self):
        with self.lock:
            data = json.dumps(self.cache, ensure_ascii=False)
        tmp = self.cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, self.cache_path)

    def clear(self):
        with self.lock:
            self.cache = {}
        self.save()

    # ---- lookups -----------------------------------------------------
    def options(self, store, ing_id, ing, force=False):
        key = f"{store}:{ing_id}"
        with self.lock:
            hit = self.cache.get(key)
        if hit and not force and time.time() - hit["t"] < self.ttl:
            return hit["opts"]
        if not self.search_fn:
            return []
        # A list of queries when the stores name the product differently (e.g. ντομάτες / τομάτες)
        queries = ing["query"] if isinstance(ing["query"], list) else [ing["query"]]
        try:
            raw = [r for q in queries for r in self.search_fn(store, q) or []]
        except Exception as e:  # a broken scraper must not fail the plan
            log.warning("search %s/%s failed: %s", store, ing["query"], e)
            return hit["opts"] if hit else []
        match = [norm(m) for m in ing.get("match", [])]
        excl = [norm(x) for x in ing.get("exclude", [])]
        opts = []
        for p in map(_product, raw):
            nn = norm(p["name"]) if p else ""
            if not p or p["unit"] != ing["unit"]:
                continue
            if match and not any(m in nn for m in match):
                continue
            if any(x in nn for x in excl):
                continue
            opts.append({k: p[k] for k in ("name", "price", "size", "url")})
        with self.lock:
            self.cache[key] = {"t": time.time(), "opts": opts}
        return opts

    def products(self, store, query):
        """Products of one store for a search, with sizes in g, ml or pcs (not cached)."""
        if not self.search_fn:
            return []
        try:
            raw = self.search_fn(store, query) or []
        except Exception as e:
            log.warning("search %s/%s failed: %s", store, query, e)
            return []
        return [{**p, "store": store} for p in map(_product, raw) if p]

    def warm(self, ingredients, ing_ids, stores, force=False):
        jobs = [(s, i) for s in stores for i in ing_ids]
        with ThreadPoolExecutor(self.workers) as ex:
            list(ex.map(lambda j: self.options(j[0], j[1], ingredients[j[1]], force), jobs))
        self.save()

    def cost(self, ing_id, ing, need, stores):
        """
        Cheapest way to buy the quantity `need` (in the unit of the ingredient). Packages are bigger than
        needed most of the time: "leftover" is what is left, for another time.
        In the store of the product the user picked for an ingredient ("product"), only that product is bought.
        """
        pick = ing.get("product") or {}
        best = None
        for s in stores:
            opts = self.options(s, ing_id, ing)
            if pick.get("store") == s:
                opts = [o for o in opts if norm(o["name"]) == norm(pick["name"])] or opts
            for o in opts:
                packs = max(1, math.ceil(need / o["size"] - 1e-9))
                c = packs * o["price"]
                if best is None or c < best["cost"]:
                    best = {
                        "store": s, "product": o["name"], "url": o.get("url"), "packs": packs,
                        "pack_size": o["size"], "pack_price": o["price"], "cost": round(c, 2),
                        "leftover": round(packs * o["size"] - need, 1), "estimated": False,
                    }
        if best:
            return best
        per = ing["fallback_price"] / (1000 if ing["unit"] in ("g", "ml") else 1)
        return {"store": None, "product": None, "url": None, "packs": None, "pack_size": None,
                "pack_price": None, "cost": round(need * per, 2), "leftover": 0, "estimated": True}


def _product(r):
    """A search result as {name, price, size, unit} with the size in g, ml or pcs, or None."""
    n = normalize_size(r.get("size"), r.get("size_unit"))
    try:
        price = float(r["price"])
    except (KeyError, TypeError, ValueError):
        return None
    if not n:
        return None
    return {"name": r.get("name", ""), "price": price, "size": n[1], "unit": n[0], "url": r.get("url")}
