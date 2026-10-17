import json
import logging
import math
import re
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache, partial
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import lxml.html
import requests
from lxml.cssselect import CSSSelector
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10

# Every result page of a store is read, so that all matching products are compared.
# MAX_PAGES only protects against runaway searches (e.g. "γάλα" is 31 pages on My Market).
MAX_PAGES = 50
# Result pages requested at the same time per store (the 3 stores are searched in parallel)
PAGE_WORKERS = 4
# The largest page size the AB API accepts
AB_PAGE_SIZE = 50

AB_BASE_URL = 'https://www.ab.gr'
AB_API_URL = 'https://www.ab.gr/api/v1/'
SKLAVENITIS_BASE_URL = 'https://www.sklavenitis.gr'
SKLAVENITIS_SEARCH_URL = 'https://www.sklavenitis.gr/apotelesmata-anazitisis/'
MYMARKET_BASE_URL = 'https://www.mymarket.gr'
MYMARKET_SEARCH_URL = 'https://www.mymarket.gr/search'

# GraphQL query used by the ab.gr search page, reduced to the fields we need
AB_SEARCH_QUERY = (
    'query GetProductSearch($lang:String $searchQuery:String $pageSize:Int $pageNumber:Int)'
    '{productSearch:productSearchV2(lang:$lang searchQuery:$searchQuery pageSize:$pageSize pageNumber:$pageNumber)'
    '{products{code name manufacturerName url categories{name}'
    ' price{value discountedPriceFormatted supplementaryPriceLabel1 supplementaryPriceLabel2}}'
    ' pagination{totalPages}}}'
)

# Size unit aliases (Greek and Latin) -> (canonical unit, multiplier to kg / L / piece / wash)
UNIT_ALIASES = {
    'ml': ('L', 0.001),
    'l': ('L', 1),
    'lt': ('L', 1),
    'λτ': ('L', 1),
    'λιτ': ('L', 1),
    'g': ('kg', 0.001),
    'gr': ('kg', 0.001),
    'γρ': ('kg', 0.001),
    'kg': ('kg', 1),
    'κιλ': ('kg', 1),
    'τεμ': ('unit', 1),
    'τμχ': ('unit', 1),
    'pcs': ('unit', 1),
    'κάψουλες': ('unit', 1),
    'καψουλες': ('unit', 1),
    'μεζ': ('wash', 1),
    'μεζούρες': ('wash', 1),
    'μεζουρες': ('wash', 1),
    'πλύσεις': ('wash', 1),
    'πλυσεις': ('wash', 1),
}

# Longest aliases first so that e.g. "ml" is not matched as "l"
_SIZE_RE = re.compile(
    r'(?:(\d+)\s*[x×]\s*)?(\d+(?:[.,]\d+)?)\s*('
    + '|'.join(sorted(map(re.escape, UNIT_ALIASES), key=len, reverse=True))
    + r')(?![a-zα-ω])',
    re.IGNORECASE,
)

# Unit keywords in the unit price labels shown by the stores, matched without accents
# (e.g. "10,98 €/ κιλ", "1,00 € /λίτρο", "0,07€ Τιμή μεζούρας", "0,07 € /πλύση")
UNIT_LABEL_KEYWORDS = {
    'κιλ': 'kg',
    'λιτ': 'L',
    'τεμ': 'unit',
    'μεζ': 'wash',
    'πλυσ': 'wash',
}

# Relevance filtering. The stores return everything that loosely matches a search (e.g. "γάλα"
# also finds "Μεγάλα" and "Σοκολάτα Γάλακτος"), so product names are compared word by word.
# All words below are normalized as in _words(): lowercase, no accents, final ς as σ.

# Words after which a product name describes an ingredient or flavour rather than the product,
# e.g. "Τυρόπιτα με φέτα", "Γιαούρτι γεύση μπανάνα"
DESCRIPTOR_WORDS = {'με', 'σε', 'για', 'απο', 'χωρισ', 'γευση', 'αρωμα'}

# Endings removed from search terms, so that e.g. "μπανάνες" also matches "Μπανάνα"
WORD_ENDINGS = ('εσ', 'ασ', 'οσ', 'ησ', 'ου', 'ων', 'οι', 'ια', 'es', 'α', 'ε', 'η', 'ι', 'ο', 'υ', 'ω', 'σ', 's')
MIN_STEM_LENGTH = 4

# A product word matches a search term if it starts with it and has at most this many extra
# letters, e.g. "φέτα" matches "φέτας" but "γάλα" does not match "γάλακτος"
MAX_EXTRA_LETTERS = 3

# A search word in the other alphabet ("πάπρικα" for "Paprika") matches a product word that
# starts with it in Latin letters and has at most this many extra letters. Fewer than
# MAX_EXTRA_LETTERS, so that e.g. "γάλα" does not match "Galaxy"
MAX_EXTRA_LETTERS_OTHER_ALPHABET = 1

# Latin letters that look like Greek ones. Stores mix them up, e.g. "Kάψουλες" with a Latin K
_LATIN_TO_GREEK = str.maketrans('abehikmnoptxyz', 'αβεηικμνορτχυζ')
_GREEK_TO_LATIN = str.maketrans('αβεηικμνορτχυζ', 'abehikmnoptxyz')

# Greek to Latin letters as the stores write them in Greeklish, e.g. "Πάπρικα" -> "paprika",
# "Μπανάνα" -> "banana", "Λεβάντα" -> "levanta". First letter pairs at the start of a word,
# then other letter pairs, then single letters.
_GREEK_FIRST_LETTER_PAIRS = re.compile(r'^(μπ|ντ|γκ)')
_GREEK_FIRST_LETTERS = {'μπ': 'b', 'ντ': 'd', 'γκ': 'g'}
_GREEK_LETTER_PAIRS = (('ου', 'u'), ('γγ', 'ng'), ('γκ', 'g'),
                       ('αι', 'e'), ('ει', 'i'), ('οι', 'i'), ('αυ', 'av'), ('ευ', 'ev'))
_GREEK_LETTERS = str.maketrans({
    'α': 'a', 'β': 'v', 'γ': 'g', 'δ': 'd', 'ε': 'e', 'ζ': 'z', 'η': 'i', 'θ': 'th', 'ι': 'i',
    'κ': 'k', 'λ': 'l', 'μ': 'm', 'ν': 'n', 'ξ': 'ks', 'ο': 'o', 'π': 'p', 'ρ': 'r', 'σ': 's',
    'τ': 't', 'υ': 'i', 'φ': 'f', 'χ': 'h', 'ψ': 'ps', 'ω': 'o',
})
# Latin spellings of the same sounds, e.g. "Snack" and "Σνακ" both become "snak"
_LATIN_SPELLINGS = (('ou', 'u'), ('ph', 'f'), ('ch', 'h'), ('ck', 'k'), ('c', 'k'), ('q', 'k'),
                    ('x', 'ks'), ('y', 'i'), ('w', 'v'))
_DOUBLE_LETTER_RE = re.compile(r'(.)\1')

_WORD_RE = re.compile(r'[^\W_]+')

# Both stores serve UTF-8; without this, pages without a charset tag would be read as Latin-1
_HTML_PARSER = lxml.html.HTMLParser(encoding='utf-8')


def _strip_accents(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')


def _words(text: str) -> List[str]:
    """Split text into normalized words: lowercase, no accents, final ς as σ, one alphabet per word."""
    words = []
    for word in _WORD_RE.findall(_strip_accents(text.lower()).replace('ς', 'σ')):
        greek = sum('α' <= c <= 'ω' for c in word)
        latin = sum('a' <= c <= 'z' for c in word)
        words.append(word.translate(_LATIN_TO_GREEK if greek >= latin else _GREEK_TO_LATIN))
    return words


def _stem(word: str) -> str:
    for ending in WORD_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= MIN_STEM_LENGTH:
            return word[:-len(ending)]
    return word


@lru_cache(maxsize=None)
def _latin(word: str) -> str:
    """A normalized word (see _words) in Latin letters, spelled the same way for both alphabets."""
    word = _GREEK_FIRST_LETTER_PAIRS.sub(lambda match: _GREEK_FIRST_LETTERS[match.group()], word)
    for greek, latin in _GREEK_LETTER_PAIRS:
        word = word.replace(greek, latin)
    word = word.translate(_GREEK_LETTERS)
    for spelling, sound in _LATIN_SPELLINGS:
        word = word.replace(spelling, sound)
    return _DOUBLE_LETTER_RE.sub(r'\1', word)


def _is_greek(word: str) -> bool:
    return any('α' <= c <= 'ω' for c in word)


def _matches_term(word: str, term: str) -> bool:
    if word.startswith(term) and len(word) - len(term) <= MAX_EXTRA_LETTERS:
        return True
    if _is_greek(word) == _is_greek(term):
        return False
    word, term = _latin(word), _latin(term)
    return word.startswith(term) and len(word) - len(term) <= MAX_EXTRA_LETTERS_OTHER_ALPHABET


def _contains_term(words: List[str], term: str) -> bool:
    return any(_matches_term(word, term) for word in words)


def relevance(search: str, product: Dict) -> int:
    """
    How well a product matches a search.

    Returns:
        2 if every search word is in the brand or in the name before any descriptor word
          (e.g. "Τυρί Φέτα ΠΟΠ 400g" for "φέτα"), or if every search word is in the brand
          or the name and the name before any descriptor has one of the words that are not
          in the brand (e.g. "Dettol Απολυμαντικό Για Τα Ρούχα" for "dettol απολυμαντικό ρούχων"),
        1 if every search word is somewhere in the name (e.g. "Τυρόπιτα με Φέτα"),
        0 otherwise (e.g. "Μορταδέλα Φέτες").
    """
    terms = [_stem(word) for word in _words(search)]
    brand = _words(product.get('brand') or '')
    name = _words(product['name'])
    main_part = next((name[:i] for i, word in enumerate(name) if i > 0 and word in DESCRIPTOR_WORDS), name)

    if all(_contains_term(main_part + brand, term) for term in terms):
        return 2
    if not all(_contains_term(name + brand, term) for term in terms):
        return 0
    if any(_contains_term(main_part, term) for term in terms if not _contains_term(brand, term)):
        return 2
    return 1


def is_named_after(search: str, product: Dict) -> bool:
    """
    True if the product name starts with a search word, after any brand words
    (e.g. "Φέτα Ηπείρου ΠΟΠ 400g" or "ΚΑΡΑΛΗΣ Φέτα ΠΟΠ" for "φέτα", but not "Τυροπιτάκια Φέτα 1kg").
    """
    brand = set(_words(product.get('brand') or ''))
    name = _words(product['name'])
    first = next((word for word in name if word not in brand), None)
    return first is not None and any(_contains_term([first], _stem(term)) for term in _words(search))


def _in_main_categories(search: str, products: List[Dict]) -> List[Dict]:
    """
    Keep the products in the store categories that match the search.

    Names alone cannot tell "Τυροπιτάκια Μυζήθρα Φέτα 1kg" from "Βαρελίσια Φέτα ΠΟΠ", but the
    store files the first under frozen pies and the second under feta. A category matches if
    its name contains the search (e.g. "Γάλατα Αγελάδος φρέσκα") or if it has a product
    named after the search (e.g. "Φέτα Ηπείρου ΠΟΠ"). Brand names are not expected in category
    names, e.g. "Απολυμαντικά ρούχων" matches "dettol απολυμαντικό ρούχων" for a DETTOL product.
    All products are kept if no category matches.
    """
    terms = [_stem(word) for word in _words(search)]

    def category_has_search(product: Dict) -> bool:
        brand = _words(product.get('brand') or '')
        category = _words(product['category'])
        return all(_contains_term(category, term) for term in terms if not _contains_term(brand, term))

    main_categories = {
        p['category'] for p in products
        if p.get('category') and (is_named_after(search, p) or category_has_search(p))
    }
    if not main_categories:
        return products
    return [p for p in products if p.get('category') in main_categories]


def filter_relevant(search: str, results: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
    """
    Keep only the products that best match the search, in every store.

    The same relevance level is used for all stores, so that a store that only has e.g. pies
    "με φέτα" shows nothing instead of pies, while the other stores show feta.
    Within each store, products outside the categories of the search are then removed.
    """
    scores = {key: [relevance(search, product) for product in products] for key, products in results.items()}
    best = max((score for store_scores in scores.values() for score in store_scores), default=0)

    return {
        key: _in_main_categories(search, [p for p, score in zip(products, scores[key]) if best and score == best])
        for key, products in results.items()
    }


def parse_price(text: str) -> Optional[float]:
    """
    Parse a price string in Greek or international format.

    Handles "2,49 €", "€2.49" and "1.234,56". Returns None if no number is found.
    """
    match = re.search(r'\d[\d.,]*', text)
    if not match:
        return None

    number = match.group().rstrip('.,')
    if ',' in number:
        # Greek format: dot is the thousands separator, comma is the decimal separator
        number = number.replace('.', '').replace(',', '.')
    elif number.count('.') > 1:
        number = number.replace('.', '')

    try:
        return float(number)
    except ValueError:
        return None


def parse_unit_price_label(text: Optional[str]) -> Optional[Dict]:
    """
    Parse a unit price label as shown by a store, e.g. "12,63 € /κιλό" or "0,76€ Τιμή τεμαχίου".

    Returns:
        Dict with 'value' and 'unit' (same format as calculate_unit_price), or None
        if the label has no price or no known unit (e.g. "57,63€ Τελ. τιμή").
    """
    if not text:
        return None

    value = parse_price(text)
    if value is None:
        return None

    normalized = _strip_accents(text.lower())
    for keyword, unit in UNIT_LABEL_KEYWORDS.items():
        if keyword in normalized:
            return {'value': value, 'unit': f'€/{unit}'}

    return None


def extract_size(text: str) -> str:
    """Return the size part of a product name (e.g. "400gr", "6x330ml"), or '' if there is none."""
    match = _SIZE_RE.search(text or '')
    return match.group(0) if match else ''


def parse_quantity(text: Optional[str]) -> Optional[Tuple[float, str]]:
    """
    Total quantity in a size string, in kg, L, units or washes.

    E.g. "6x330ml" -> (1.98, 'L'), "1,5 λιτ" -> (1.5, 'L'). Returns None if there is no size.
    """
    match = _SIZE_RE.search(text or '')
    if not match:
        return None

    count = int(match.group(1) or 1)
    quantity = float(match.group(2).replace(',', '.'))
    unit, multiplier = UNIT_ALIASES[match.group(3).lower()]
    total = count * quantity * multiplier
    return (total, unit) if total > 0 else None


def product_quantity(product: Dict) -> Optional[Tuple[float, str]]:
    """Total quantity of a product, from its name or else from the store's size field."""
    return parse_quantity(product['name']) or parse_quantity(product.get('size'))


def calculate_unit_price(price: float, size: str) -> Dict:
    """
    Calculate unit price from total price and size.

    Converts all prices to standardized units (€/kg, €/L, €/unit or €/wash).
    Multipacks such as "6x330ml" are taken into account.

    Args:
        price (float): Product price in euros
        size (str): Size string (e.g., "500ml", "250 γρ", "1,5L", "6x330ml", "20 τεμ")

    Returns:
        Dict: Contains 'value' (unit price) and 'unit' (label string).
        If the size cannot be parsed, the full price is returned with unit '€/unit'.
    """
    quantity = parse_quantity(size)
    if quantity:
        total, unit = quantity
        return {'value': round(price / total, 2), 'unit': f'€/{unit}'}

    return {'value': price, 'unit': '€/unit'}


def unit_price(product: Dict) -> Dict:
    """
    Unit price of a product, in the format of calculate_unit_price.

    Calculated from the price and the size when the size is known, so that all stores are
    compared the same way: store labels can be out of date (My Market showed 20,48 €/kg for
    Pringles 165gr at 2,54 €, the price per kg before a discount). Otherwise the store's own
    unit price is used (e.g. loose fruit priced per kg), or else the full price per unit.
    """
    quantity = product_quantity(product)
    if quantity:
        total, unit = quantity
        return {'value': round(product['price'] / total, 2), 'unit': f'€/{unit}'}

    return product.get('unit_price_calc') or calculate_unit_price(product['price'], '')


def sort_by_value(products: List[Dict]) -> List[Dict]:
    """
    Sort products by best value (lowest unit price first).

    Unit prices in different units (€/kg vs €/L vs €/unit) are not comparable,
    so products are grouped by unit, with the most common unit in the results first.
    """
    unit_counts = Counter(p['unit_price_calc']['unit'] for p in products)
    return sorted(
        products,
        key=lambda p: (
            -unit_counts[p['unit_price_calc']['unit']],
            p['unit_price_calc']['unit'],
            p['unit_price_calc']['value'],
        ),
    )


def _parse_html(html: bytes) -> Optional[lxml.html.HtmlElement]:
    """
    Parse a store page, or return None if it is empty.

    lxml is used instead of BeautifulSoup because it is about 5 times faster, which matters
    when every result page is read (My Market returns 31 pages for "γάλα").
    """
    if not html or not html.strip():
        return None
    return lxml.html.document_fromstring(html, parser=_HTML_PARSER)


@lru_cache(maxsize=None)
def _css(selector: str) -> CSSSelector:
    """Compile a CSS selector once; compiling it for every product is slower than the lookup."""
    return CSSSelector(selector)


def _first(element: lxml.html.HtmlElement, selector: str) -> Optional[lxml.html.HtmlElement]:
    found = _css(selector)(element)
    return found[0] if found else None


def _text(element: Optional[lxml.html.HtmlElement]) -> str:
    """Text of an element with whitespace collapsed, or '' if there is no element."""
    return ' '.join(element.text_content().split()) if element is not None else ''


def _json_attr(element: lxml.html.HtmlElement, name: str):
    """Parse a JSON-valued HTML attribute; returns None if missing or invalid."""
    try:
        return json.loads(element.get(name))
    except (TypeError, ValueError):
        return None


def _page_count(total_products: int, page_size: int) -> int:
    return math.ceil(total_products / page_size) if page_size else 1


def _ab_product_search(data) -> Dict:
    return ((data or {}).get('data') or {}).get('productSearch') or {}


def ab_page_count(data) -> int:
    """Number of result pages in an ab.gr GraphQL product search response."""
    return (_ab_product_search(data).get('pagination') or {}).get('totalPages') or 1


def sklavenitis_page_count(html: str) -> int:
    """Number of result pages, from the "24 από τα 226 προϊόντα" counter below the results."""
    match = re.search(r'(\d+)\s*από τα\s*([\d.]+)\s*προϊόντα', html)
    if not match:
        return 1
    return _page_count(int(match.group(2).replace('.', '')), int(match.group(1)))


def mymarket_page_count(html: str, page_size: int) -> int:
    """Number of result pages, from the "1.062 προϊόντα" total on the filters button."""
    match = re.search(r'findastic#hideFilters[^>]*>\s*([\d.]+)\s*προϊόντα', html)
    if not match:
        return 1
    return _page_count(int(match.group(1).replace('.', '')), page_size)


def parse_ab_response(data) -> List[Dict]:
    """Extract products from an ab.gr GraphQL product search response."""
    items = _ab_product_search(data).get('products') or []

    products = []
    for item in items:
        price_info = item.get('price') or {}
        # discountedPriceFormatted is the price the customer pays; value is the fallback
        price = parse_price(price_info.get('discountedPriceFormatted') or '') or price_info.get('value')
        if not item.get('name') or not price:
            continue

        products.append({
            'name': item['name'],
            'brand': item.get('manufacturerName') or '',
            'price': float(price),
            'size': price_info.get('supplementaryPriceLabel2') or '',
            'url': urljoin(AB_BASE_URL, item.get('url') or ''),
            'category': ((item.get('categories') or [{}])[0] or {}).get('name') or '',
            'unit_price_calc': parse_unit_price_label(price_info.get('supplementaryPriceLabel1')),
            'supermarket': 'AB Vasilopoulos',
        })

    return products


def parse_sklavenitis_html(html: bytes) -> List[Dict]:
    """Extract products from a sklavenitis.gr search results page."""
    doc = _parse_html(html)
    if doc is None:
        return []

    products = []
    for item in _css('.productList div.product')(doc):
        link = _first(item, '.product__title a')
        # The visible text is the price per package; data-price is sometimes the price per kg
        main_price_text = _text(_first(item, '.main-price .price'))
        price = parse_price(main_price_text)
        if link is None or price is None:
            continue

        analytics = _json_attr(item, 'data-plugin-analyticsimpressions') or {}
        analytics_items = analytics.get('Call', {}).get('ecommerce', {}).get('items') or [{}]
        name = _text(link)

        products.append({
            'name': name,
            'brand': analytics_items[0].get('item_brand') or '',
            'price': price,
            'size': extract_size(name),
            'url': urljoin(SKLAVENITIS_BASE_URL, link.get('href') or ''),
            'category': analytics_items[0].get('item_category') or '',
            # Loose products (e.g. fruit) have an empty .priceKil and are priced per kg directly
            'unit_price_calc': (
                parse_unit_price_label(_text(_first(item, '.priceKil')))
                or parse_unit_price_label(main_price_text)
            ),
            'supermarket': 'Sklavenitis',
        })

    return products


def mymarket_category(analytics: Dict) -> str:
    """
    All category levels of a mymarket.gr product, e.g. "Γάλα / Γαλακτοκομικά & Είδη Ψυγείου / Φρέσκο".

    The levels are sorted because their order varies: "Φρούτα & Λαχανικά" is category
    for some bananas and category3 for others.
    """
    levels = {analytics.get(key) for key in ('category', 'category2', 'category3')}
    return ' / '.join(sorted(level for level in levels if level))


def parse_mymarket_html(html: bytes) -> List[Dict]:
    """Extract products from a mymarket.gr search results page."""
    doc = _parse_html(html)
    if doc is None:
        return []

    products = []
    for item in _css('article.product--teaser')(doc):
        link = _first(item, 'h3 a')
        whole = _text(_first(item, '.teaser-display-price-whole'))
        fraction = _text(_first(item, '.teaser-display-price-fraction')) or '00'

        if link is None or not whole:
            continue
        price = parse_price(f'{whole},{fraction}')
        if price is None:
            continue

        analytics = _json_attr(item, 'data-google-analytics-item-value') or {}
        name = _text(link)

        products.append({
            'name': name,
            'brand': analytics.get('brand') or '',
            'price': price,
            'size': extract_size(name),
            'url': urljoin(MYMARKET_BASE_URL, link.get('href') or ''),
            'category': mymarket_category(analytics),
            'unit_price_calc': parse_unit_price_label(_text(_first(item, '.measure-label-wrapper'))),
            'supermarket': 'My Market',
        })

    return products


class SupermarketScraper:
    """
    Web scraper for Greek supermarket chains.
    Handles searching and price extraction from AB Vasilopoulos, Sklavenitis, and My Market.

    Each search method reads every result page of the store and returns a list of product dicts
    with keys: name, brand, price, size, url, category, unit_price_calc, supermarket.
    unit_price_calc is the unit price shown by the store, or None if the store shows none.
    """

    def __init__(self, max_pages: Optional[int] = None):
        # Result pages read per search, MAX_PAGES if not set
        self.max_pages = max_pages
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        # The stores sometimes drop connections when many pages are requested at once.
        # All requests are searches, so retrying is safe for POST (AB GraphQL) too.
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=None)
        self.session.mount('https://', HTTPAdapter(max_retries=retry, pool_maxsize=PAGE_WORKERS))

    def _request(self, supermarket: str, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        try:
            response = self.session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            logger.warning("Error searching %s: %s", supermarket, e)
            return None

    def _search_all_pages(self, fetch_page: Callable[[int], Tuple[List[Dict], int]], first_page: int) -> List[Dict]:
        """
        Collect the products from every result page of a store.

        fetch_page(page) returns the products on that page and the total number of pages.
        The first page is fetched alone to learn the page count, the rest in parallel.
        """
        max_pages = self.max_pages or MAX_PAGES
        products, page_count = fetch_page(first_page)
        if page_count > max_pages:
            logger.info("Search has %d result pages, only the first %d are read", page_count, max_pages)

        other_pages = range(first_page + 1, first_page + min(page_count, max_pages))
        with ThreadPoolExecutor(max_workers=PAGE_WORKERS) as executor:
            for page_products, _ in executor.map(fetch_page, other_pages):
                products.extend(page_products)

        # Results can shift while they are paged through, so a product may appear twice
        unique = {}
        for product in products:
            unique.setdefault((product['name'], product['url']), product)
        return list(unique.values())

    def _ab_page(self, product_name: str, page: int) -> Tuple[List[Dict], int]:
        response = self._request('AB', 'POST', AB_API_URL, json={
            'operationName': 'GetProductSearch',
            'query': AB_SEARCH_QUERY,
            'variables': {'lang': 'gr', 'searchQuery': product_name, 'pageSize': AB_PAGE_SIZE, 'pageNumber': page},
        })
        if response is None:
            return [], 0

        try:
            data = response.json()
        except ValueError as e:
            logger.warning("Error searching AB: invalid JSON: %s", e)
            return [], 0

        if not isinstance(data, dict):
            logger.warning("Error searching AB: unexpected response format")
            return [], 0

        if data.get('errors'):
            logger.warning("Error searching AB: %s", data['errors'])

        return parse_ab_response(data), ab_page_count(data)

    def _sklavenitis_page(self, product_name: str, page: int) -> Tuple[List[Dict], int]:
        response = self._request('Sklavenitis', 'GET', SKLAVENITIS_SEARCH_URL, params={'Query': product_name, 'pg': page})
        if response is None:
            return [], 0
        return parse_sklavenitis_html(response.content), sklavenitis_page_count(response.text)

    def _mymarket_page(self, product_name: str, page: int) -> Tuple[List[Dict], int]:
        response = self._request('My Market', 'GET', MYMARKET_SEARCH_URL, params={'query': product_name, 'page': page})
        if response is None:
            return [], 0
        products = parse_mymarket_html(response.content)
        return products, mymarket_page_count(response.text, page_size=len(products))

    def search_ab(self, product_name: str) -> List[Dict]:
        """Search AB Vasilopoulos through the GraphQL API used by ab.gr (pages are numbered from 0)."""
        return self._search_all_pages(partial(self._ab_page, product_name), first_page=0)

    def search_sklavenitis(self, product_name: str) -> List[Dict]:
        """Search Sklavenitis by scraping its search result pages."""
        return self._search_all_pages(partial(self._sklavenitis_page, product_name), first_page=1)

    def search_mymarket(self, product_name: str) -> List[Dict]:
        """Search My Market by scraping its search result pages."""
        return self._search_all_pages(partial(self._mymarket_page, product_name), first_page=1)


def _store_searches(scraper: SupermarketScraper) -> Dict[str, Callable[[str], List[Dict]]]:
    return {
        'ab': scraper.search_ab,
        'sklavenitis': scraper.search_sklavenitis,
        'mymarket': scraper.search_mymarket,
    }


def search_store(store: str, product_name: str, max_pages: Optional[int] = None) -> List[Dict]:
    """
    Search one supermarket ('ab', 'sklavenitis' or 'mymarket') for a product.

    Same as search_all_supermarkets for a single store: the relevant products with unit prices,
    best value first. max_pages limits the result pages read (the stores list the closest matches first).
    """
    search = _store_searches(SupermarketScraper(max_pages))[store]
    products = filter_relevant(product_name, {store: search(product_name)})[store]
    for product in products:
        product['unit_price_calc'] = unit_price(product)
    return sort_by_value(products)


def search_all_supermarkets(product_name: str) -> Dict:
    """
    Search all supermarkets for a product and return the relevant products per store.

    Reads every result page of the three supermarkets (in parallel), keeps only the
    products relevant to the search, calculates unit prices (unit_price), and sorts the
    results by best value (lowest unit price first).

    Args:
        product_name (str): Product name to search for

    Returns:
        Dict: Structure:
        {
            'ab': [relevant products, best value first],
            'sklavenitis': [...],
            'mymarket': [...]
        }
        Each product dict includes a unit price in 'unit_price_calc'.
    """
    searches = _store_searches(SupermarketScraper())

    with ThreadPoolExecutor(max_workers=len(searches)) as executor:
        futures = {key: executor.submit(search, product_name) for key, search in searches.items()}

    found = {}
    for key, future in futures.items():
        try:
            found[key] = future.result()
        except Exception:
            # One broken store (e.g. unexpected response format) must not fail the whole search
            logger.exception("Unexpected error searching %s", key)
            found[key] = []

    results = filter_relevant(product_name, found)
    logger.info("Search %r, relevant/found products: %s", product_name,
                ', '.join(f'{key} {len(results[key])}/{len(found[key])}' for key in found))

    for key, products in results.items():
        for product in products:
            product['unit_price_calc'] = unit_price(product)

        results[key] = sort_by_value(products)

    return results
