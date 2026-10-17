"""
Greek ingredient lines: ingredient names, units and quantities for the meal planner.
"""
import re
from fractions import Fraction

from .pricing import norm

# Ingredient names -> ids in ingredients.json
# Checked in order, so the most specific come first. Compared without accents.
# None = pantry item or spice that is not costed.
ALIASES = [
    (r"^νερο|ζεστο νερο|κρυο νερο|παγακ", None),
    (r"^αλατι|ανθο αλατιου|^πιπερι(?!α|ε)|πιπερι καγιεν|μπουκοβο|παπρικα|κυμινο|καρι\b|κουρκουμα|μοσχοκαρφ|μπαχαρι|τζιντζερ σε σκονη|σκονη σκορδου|σκονη κρεμμυδιου|θυμαρι|δεντρολιβαν|βασιλικ|δυοσμ|κολιανδρ|σχοινοπρασ|εστραγκον|φασκομηλ|μαντζουραν|κυβο|ζωμο|μπεικιν|σοδα|μαγια|βανιλ|κορν φλαουρ|ξυσμα|μουσταρδ|κετσαπ|μαγιονεζ|σογια|μπαλσαμικ|ταμπασκο|worcester|τσιλι|μπουκιστ", None),
    (r"ελαιολαδο|ηλιελαιο|σπορελαιο|^λαδι", "olive_oil"),
    (r"ριγαν", "oregano"), (r"κανελ", "cinnamon"), (r"μοσχοκαρυδ", "nutmeg"), (r"δαφν", "bay_leaf"),
    (r"ζαχαρ", "sugar"), (r"ξυδι|ξιδι", "vinegar"),
    (r"γαλοπουλ", "turkey"), (r"κιμα", "minced"), (r"μπεικον|bacon|πανσετ", "bacon"), (r"αρν", "lamb"),
    (r"γαριδ", "shrimp"), (r"γλυκοπατατ", "sweet_potato"), (r"κρασ", "white_wine"),
    (r"κρεμα γαλακτ|κρεμα μαγειρικ", "cream"), (r"μοτσαρελ", "mozzarella"),
    (r"στηθ.* κοτοπουλ|φιλετο κοτοπουλ|κοτοπουλο φιλετο|στηθος", "chicken_breast"),
    (r"κοτοπουλ|μπουτακ|κοτομπουκ", "chicken_thigh"),
    (r"μπριζολ.* χοιριν|χοιριν.* μπριζολ", "pork_chop"),
    (r"χοιριν", "pork_leg"), (r"μοσχαρ", "beef"), (r"λουκανικ", "sausage"),
    (r"μπακαλιαρ", "cod"), (r"σολομ(?!.*καπνιστ)", "salmon"), (r"\bτονο", "tuna"),
    (r"φακε|φακη", "lentils"), (r"ρεβιθ", "chickpeas"), (r"γιγαντ", "gigantes"),
    (r"φασολακ|φρεσκα φασολ", "green_beans"), (r"φασολ", "beans"),
    (r"ρυζι", "rice"), (r"κριθαρακ", "orzo"), (r"νο ?2|παστιτσ", "pasta_pastitsio"),
    (r"σπαγγετ|μακαρονι|λιγκουιν|ταλιατελ", "spaghetti"), (r"πενες|πεννε|βιδακ|φαρφαλ|ριγκατον", "penne"),
    (r"φυλλο κρουστ|φυλλα κρουστ", "phyllo"), (r"αλευρ", "flour"),
    (r"πελτ", "tomato_paste"),
    (r"ψιλοκομμεν.* ντοματ|ντοματ.* κονσερβ|κονκασε|τριμμεν.* ντοματ|ντοματ.* τριμμεν|πασσατα|passata|ντοματακια κονσερβ", "tomato_canned"),
    (r"ντοματ", "tomato"),
    (r"φρεσκ.* κρεμμυδ|κρεμμυδακ", "spring_onion"), (r"κρεμμυδ", "onion"),
    (r"σκορδ", "garlic"),
    (r"(?<!γλυκο)πατατ", "potato"), (r"καροτ", "carrot"), (r"κολοκυθ", "zucchini"),
    (r"πιπερι(α|ε|ι)", "peppers"), (r"μελιτζαν", "eggplant"), (r"σπανακ", "spinach"),
    (r"αρακα", "peas"), (r"αγγουρ", "cucumber"), (r"μαρουλ|iceberg", "lettuce"),
    (r"λαχανο(?! βρυξ)", "cabbage"), (r"λεμον", "lemon"), (r"μπαναν", "banana"),
    (r"\bμηλ(α|ο|ου)\b", "apple"), (r"πορτοκαλ", "orange"), (r"μανιταρ", "mushrooms"),
    (r"μαιντανο", "parsley"), (r"ανηθο|ανιθο", "dill"), (r"ελιε|ελιες", "olives"),
    (r"γιαουρτ", "yogurt"), (r"φετα\b", "feta"), (r"γραβιερ|κεφαλοτυρ|κεφαλογραβ|παρμεζαν|πεκορινο", "graviera"),
    (r"τυρι.*τοστ|γκουντα|ενταμ|τυρι σε φετες", "cheese_toast"),
    (r"(?<!φυστικο)βουτυρ(?!ογαλ)", "butter"), (r"^γαλα|φρεσκο γαλα|πληρες γαλα|ελαφρυ γαλα", "milk"),
    (r"αυγ|κροκο|ασπραδ", "egg"), (r"μελι\b", "honey"), (r"μαρμελαδ", "jam"),
    (r"βρωμ", "oats"), (r"καρυδ(?!ας)", "walnuts"), (r"ταχιν", "tahini"),
    (r"ψωμι του τοστ|ψωμι τοστ|φετες ψωμι τοστ", "bread_toast"),
    (r"αραβικ.* πιτ|πιτες για σουβλακι|πιτα για σουβλακι|πιτες σουβλακ", "pita"),
    (r"ψωμ|φρυγανι", "bread_village"),
]
ALIASES = [(re.compile(norm(p)), i) for p, i in ALIASES]

# Weight of one piece (g), for ingredients counted in g when the recipe gives pieces
PIECE_G = {
    "onion": 150, "tomato": 150, "potato": 200, "carrot": 100, "zucchini": 200, "peppers": 150,
    "eggplant": 300, "lemon": 120, "banana": 120, "apple": 180, "orange": 200, "garlic": 5,
    "chicken_breast": 250, "chicken_thigh": 200, "pork_chop": 250, "sausage": 100, "cod": 150,
    "salmon": 180, "spring_onion": 1, "bread_village": 40, "bread_toast": 30, "cheese_toast": 20,
    "turkey": 15, "tuna": 160, "cabbage": 1200, "mushrooms": 20, "feta": 30, "graviera": 20,
}

# Recipe units -> (unit, multiplier). "pcs" = pieces.
UNIT_MAP = [
    (r"^(γρ|γραμ|gr|g)\b", ("g", 1)), (r"^(κιλ|kg)", ("g", 1000)),
    (r"^(ml|μλ)", ("ml", 1)), (r"^λιτρ|^lt|^l\b", ("ml", 1000)),
    (r"^κ\.?σ", ("spoon", 15)), (r"^κ\.?γ", ("spoon", 5)), (r"^φλιτζ|^κουπ", ("spoon", 240)),
    (r"^ποτηρ", ("spoon", 200)), (r"^πρεζ", ("spoon", 0.5)),
    (r"^σκ", ("pcs", 1)), (r"^κεφαλ", ("head", 1)), (r"^ματσ", ("bunch", 1)),
    (r"^φετ", ("slice", 1)), (r"^(τεμ|τμχ)", ("pcs", 1)), (r"^κλ|^κλωναρ|^στικ|^φυλλ", ("skip", 0)),
    (r"^κονσερβ", ("can", 1)), (r"^συσκευασ|^πακετ", ("pack", 1)),
]
UNIT_MAP = [(re.compile(norm(p)), v) for p, v in UNIT_MAP]

def _words(pat):
    """Match at the start of a word, so that e.g. «μυδι» does not match «κρεμμύδια»."""
    return re.compile(r"\b(?:" + norm(pat) + ")")


MEAT = _words("κρεα|κιμα|κοτοπουλ|κοτα|χοιριν|μοσχαρ|αρνι|αρνισ|κατσικ|μπεικον|προσουτ|ζαμπον|σαλαμ|λουκαν|γαλοπουλ|παπια|κουνελ|συκωτ|μπουτ")
FISH = _words("ψαρ|σολομ|τονο|μπακαλιαρ|γαριδ|καλαμαρ|χταπ|μυδ|σουπι|γαυρ|σαρδελ|τσιπουρ|λαβρακ|αντζουγ|θαλασσιν")
ANIMAL = _words("γαλα|τυρ|φετα\\b|γιαουρτ|βουτυρ|αυγ|κροκ|κρεμα γαλακτ|μελι\\b|παρμεζαν|μοτσαρελ|ρικοτα|ανθοτυρ|μυζηθρ|cheddar|κεφαλοτυρ|γραβιερ")


def parse_qty(s):
    s = (s or "").strip().replace(",", ".").replace("½", " 1/2").replace("¼", " 1/4").replace("¾", " 3/4")
    s = re.split(r"\s*[-–]\s*", s)[0]  # "2-3" → 2
    total = 0.0
    for part in s.split():
        try:
            total += float(Fraction(part))
        except (ValueError, ZeroDivisionError):
            return None
    return total or None


def map_unit(u):
    nu = norm(u).strip()
    if not nu:
        return ("pcs", 1)
    for rx, v in UNIT_MAP:
        if rx.search(nu):
            return v
    return None


def map_ingredient(title):
    nt = norm(title).strip()
    for rx, iid in ALIASES:
        if rx.search(nt):
            return True, iid
    return False, None


def slugify(s):
    tr = str.maketrans(dict(zip("αβγδεζηθικλμνξοπρστυφχψω",
                                ["a", "v", "g", "d", "e", "z", "i", "th", "i", "k", "l", "m", "n", "x", "o",
                                 "p", "r", "s", "t", "y", "f", "ch", "ps", "o"])))
    s = norm(s).translate(tr)
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:40]


def to_amount(qty, unit, iid, ing):
    """Convert a recipe quantity to the unit of the ingredient. None = not costed."""
    kind, mul = unit
    target = ing["unit"]
    if kind == "skip" or qty is None:
        return None
    if kind in ("g", "ml"):
        v = qty * mul
        if target in ("g", "ml"):
            return v
        return max(1, round(v / PIECE_G.get(iid, 100)))  # g -> pieces
    if kind == "spoon":
        v = qty * mul  # ≈ g/ml
        return v if target in ("g", "ml") else None
    if kind == "slice":
        w = {"bread_village": 30, "bread_toast": 30, "cheese_toast": 20, "turkey": 15, "lemon": 15,
             "tomato": 30, "bacon": 15, "graviera": 20, "feta": 30}.get(iid, 20)
        return qty if target == "pcs" else qty * w
    if kind == "head":  # head of garlic / cabbage
        return qty * (50 if iid == "garlic" else PIECE_G.get(iid, 500)) if target == "g" else qty
    if kind == "bunch":
        return qty if target == "pcs" else qty * 50
    if kind == "can":
        return qty * 400 if target == "g" else qty
    if kind == "pack":
        return qty * 500 if target in ("g", "ml") else qty
    # pieces
    if target == "pcs":
        return qty
    return qty * PIECE_G.get(iid, 100)


def category_for(meal, amounts, text):
    if meal == ["breakfast"]:
        return "breakfast_eggs" if "egg" in amounts else "breakfast_sweet"
    ids = set(amounts)
    if FISH.search(text):
        return "fish"
    if ids & {"chicken_breast", "chicken_thigh"} or "κοτοπουλ" in text:
        return "chicken"
    if ids & {"pork_chop", "pork_leg", "sausage"} or "χοιριν" in text:
        return "pork"
    if MEAT.search(text):
        return "beef"
    if ids & {"lentils", "chickpeas", "beans", "gigantes"}:
        return "legumes"
    if "egg" in ids and len(ids) <= 4:
        return "eggs"
    return "ladera"
