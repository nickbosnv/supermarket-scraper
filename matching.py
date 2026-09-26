"""
Find the same product in the different supermarkets.

Each store names its products its own way, e.g. for the same DETTOL product:
    AB           "Απολυμαντικό Ρούχων 2,5lt" (brand in a separate field)
    Sklavenitis  "DETTOL Αντιβακτηριδιακό Απολυμαντικό Υγρό Ρούχων 2,5lt"
    My Market    "Dettol Απολυμαντικό Για Τα Ρούχα 2,5lt"
Products are taken to be the same if they have the same brand and size and similar names.
Words are compared in Latin letters, since stores write e.g. both "Πάπρικα" and "Paprika".
"""
from collections import Counter, defaultdict
from itertools import combinations
from typing import Dict, List, Optional, Set, Tuple

from supermarket_scraper import (
    MAX_EXTRA_LETTERS,
    MIN_STEM_LENGTH,
    _SIZE_RE,
    _latin,
    _stem,
    _words,
    product_quantity,
)

# Words that do not tell products apart ("Απολυμαντικό Για Τα Ρούχα" is "Απολυμαντικό Ρούχων")
FILLER_WORDS = {'με', 'σε', 'για', 'απο', 'και', 'ο', 'η', 'το', 'οι', 'τα', 'του', 'τησ', 'των',
                'τον', 'την', 'τη', 'στο', 'στη', 'στα', 'στον', 'στην'}

# Starts of words that always mean a different variant of a product, e.g. "Χωρίς λακτόζη",
# "Ελαφρύ", "Decaffeinated". Words with these starts are shortened to them, so that
# "Decaf" and "Decafeine" are the same word.
VARIANT_PREFIXES = ('χωρι', 'ελαφρ', 'πληρ', 'light', 'zero', 'decaf', 'βιολογ', 'bio')
ALWAYS_VARIANT_WORDS = {_latin(prefix) for prefix in VARIANT_PREFIXES}

# Share of name words two products must have in common to be the same product
MIN_NAME_SIMILARITY = 0.5
# Sizes are equal if they differ by at most this fraction (rounding, e.g. "1,5lt" vs "1500ml")
SIZE_TOLERANCE = 0.01
# Product choices returned per search
MAX_GROUPS = 10


def _same_word(a: str, b: str) -> bool:
    if a == b:
        return True
    shorter, longer = sorted((a, b), key=len)
    return (len(shorter) >= MIN_STEM_LENGTH and longer.startswith(shorter)
            and len(longer) - len(shorter) <= MAX_EXTRA_LETTERS)


def _name_word(word: str) -> str:
    return _latin(next((prefix for prefix in VARIANT_PREFIXES if word.startswith(prefix)), _stem(word)))


def _brand_words(product: Dict) -> Set[str]:
    return {_latin(word) for word in _words(product.get('brand') or '')}


def name_words(product: Dict) -> List[str]:
    """Stemmed words in Latin letters of a product name, without its brand, size, numbers and filler words."""
    brand = _brand_words(product)
    name = _SIZE_RE.sub(' ', product['name'])
    return [_name_word(word) for word in _words(name)
            if _latin(word) not in brand and word not in FILLER_WORDS and not word.isdigit()]


def name_similarity(a: List[str], b: List[str]) -> float:
    """Share of the words of both names that are also in the other name (0 to 1)."""
    if not a and not b:
        return 1.0
    common = (sum(any(_same_word(word, other) for other in b) for word in a)
              + sum(any(_same_word(word, other) for other in a) for word in b))
    return common / (len(a) + len(b))


def _extra_words(a: List[str], b: List[str]) -> Set[str]:
    """Words of name a that are not in name b."""
    return {word for word in a if not any(_same_word(word, other) for other in b)}


def _missing_words(a: List[str], b: List[str]) -> Set[str]:
    """Words of each name that are not in the other one."""
    return _extra_words(a, b) | _extra_words(b, a)


def _brand_and_name(product: Dict) -> Tuple[Set[str], Set[str]]:
    return _brand_words(product), {_latin(word) for word in _words(product['name'])}


def same_brand(a: Dict, b: Dict) -> bool:
    """
    Brands match if they share a word. If one product has no brand, the brand of
    the other must be in its name (My Market often leaves the brand out).
    """
    return _same_brand(_brand_and_name(a), _brand_and_name(b))


def _same_brand(a: Tuple[Set[str], Set[str]], b: Tuple[Set[str], Set[str]]) -> bool:
    (brand_a, name_a), (brand_b, name_b) = a, b
    if brand_a and brand_b:
        return bool(brand_a & brand_b)
    if brand_a:
        return bool(brand_a & name_b)
    if brand_b:
        return bool(brand_b & name_a)
    return True


def same_size(a: Optional[Tuple[float, str]], b: Optional[Tuple[float, str]]) -> bool:
    # Products without a size (e.g. loose fruit priced per kg) only match each other
    if a is None or b is None:
        return a is None and b is None
    return a[1] == b[1] and abs(a[0] - b[0]) <= SIZE_TOLERANCE * max(a[0], b[0])


def variant_words(results: Dict[str, List[Dict]]) -> Set[str]:
    """
    Words that tell apart variants of a product, e.g. "Λεβάντα" or "Άρωμα".

    These are the words that differ between products of the same brand and size with
    similar names in one store, in at least two stores. Words that differ in one store
    only are often just that store's way of naming (e.g. AB "Υγρό Απολυμαντικό ...
    Αντιβακτηριδιακό"). Products with different names (e.g. a liquid soap and a
    cleaner of the same size) are not compared, as all their words would count.

    Stores are not consistent in their own naming either, so words that are only in one
    name of the single products of a brand and size of two stores are not variant words:
    these products are the same (Sklavenitis "Αντιβακτηριδιακό Απολυμαντικό Υγρό Ρούχων
    2,5lt", AB "Απολυμαντικό Ρούχων 2,5lt").
    """
    names_of = defaultdict(lambda: defaultdict(list))
    for store, products in results.items():
        for product in products:
            names_of[_brand_and_size(product)][store].append(name_words(product))

    stores_of_word = defaultdict(set)
    naming_words = set()
    for names_in_store in names_of.values():
        for store, names in names_in_store.items():
            for a, b in combinations(names, 2):
                if name_similarity(a, b) >= MIN_NAME_SIMILARITY:
                    for word in _missing_words(a, b):
                        stores_of_word[word].add(store)

        single_products = [names[0] for names in names_in_store.values() if len(names) == 1]
        for a, b in combinations(single_products, 2):
            # Only if one name has more words: two names with different words are different flavours
            if name_similarity(a, b) >= MIN_NAME_SIMILARITY and not (_extra_words(a, b) and _extra_words(b, a)):
                naming_words |= _missing_words(a, b)

    variants = {word for word, stores in stores_of_word.items() if len(stores) > 1}
    return (variants - naming_words) | ALWAYS_VARIANT_WORDS


def _brand_and_size(product: Dict) -> Tuple:
    quantity = product_quantity(product)
    return frozenset(_brand_words(product)), quantity and (round(quantity[0], 3), quantity[1])


def group_products(results: Dict[str, List[Dict]]) -> List[Dict]:
    """
    Group the products of all stores into product choices, most likely first.

    Each group holds at most one product per store: the pairs of products with the most
    similar names are grouped first, and a product only joins a group if it matches every
    product already in it. Products whose names differ in a variant word (e.g. one has
    "Λεβάντα" and the other has not) never match.

    The most likely choices are the ones sold in the most stores, then the cheapest per
    unit (in the most common unit, as in sort_by_value).

    Args:
        results: Relevant products per store, as returned by search_all_supermarkets

    Returns:
        Up to MAX_GROUPS dicts with a 'label' and 'products' ({store: index in results[store]}).
    """
    stores = list(results)
    items = [(store, index) for store, products in results.items() for index in range(len(products))]
    product = {item: results[item[0]][item[1]] for item in items}
    words = {item: name_words(product[item]) for item in items}
    quantity = {item: product_quantity(product[item]) for item in items}
    brand_and_name = {item: _brand_and_name(product[item]) for item in items}
    variants = variant_words(results)

    # Products of the same store are never the same product
    pairs = ((a, b) for store_a, store_b in combinations(stores, 2)
             for a in items if a[0] == store_a for b in items if b[0] == store_b)
    similarity = {}
    for a, b in pairs:
        if not same_size(quantity[a], quantity[b]) or not _same_brand(brand_and_name[a], brand_and_name[b]):
            continue
        score = name_similarity(words[a], words[b])
        if score >= MIN_NAME_SIMILARITY and not _missing_words(words[a], words[b]) & variants:
            similarity[a, b] = similarity[b, a] = score

    group_of = {item: [item] for item in items}
    for a, b in sorted((pair for pair in similarity if pair[0] < pair[1]), key=similarity.get, reverse=True):
        group_a, group_b = group_of[a], group_of[b]
        if group_a is group_b or {store for store, _ in group_a} & {store for store, _ in group_b}:
            continue
        if all((x, y) in similarity for x in group_a for y in group_b):
            merged = group_a + group_b
            for item in merged:
                group_of[item] = merged

    groups = [sorted(group, key=lambda item: stores.index(item[0]))
              for group in {id(group): group for group in group_of.values()}.values()]
    unit_counts = Counter(product[item]['unit_price_calc']['unit'] for item in items)

    def cheapest(group):
        return min((product[item]['unit_price_calc'] for item in group), key=lambda price: price['value'])

    groups.sort(key=lambda group: (
        -len(group),
        -unit_counts[cheapest(group)['unit']],
        cheapest(group)['unit'],
        cheapest(group)['value'],
    ))

    return [
        {'label': _label(product[group[0]]), 'products': dict(group)}
        for group in groups[:MAX_GROUPS]
    ]


def _label(product: Dict) -> str:
    """Product name with the brand in front, if the name does not have it."""
    brand = product.get('brand') or ''
    if brand and not set(_words(brand)) <= set(_words(product['name'])):
        return f"{brand} {product['name']}"
    return product['name']
