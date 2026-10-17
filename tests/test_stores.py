import json
import logging

import pytest
import requests

from conftest import FakeResponse, load_fixture
import supermarket_scraper
from supermarket_scraper import (
    SupermarketScraper,
    ab_page_count,
    mymarket_category,
    mymarket_page_count,
    parse_ab_response,
    parse_mymarket_html,
    parse_sklavenitis_html,
    search_all_supermarkets,
    search_store,
    sklavenitis_page_count,
)

# The fixtures are trimmed copies of real search responses from each store.
# When a store changes its markup, save new fixtures and update the parsers and expectations.

AB_JSON = json.loads(load_fixture('ab_search.json'))
SKLAVENITIS_HTML = load_fixture('sklavenitis_search.html')
MYMARKET_HTML = load_fixture('mymarket_search.html')

ALL_STORES = {
    'ab.gr': FakeResponse(AB_JSON),
    'sklavenitis.gr': FakeResponse(SKLAVENITIS_HTML),
    'mymarket.gr': FakeResponse(MYMARKET_HTML),
}


@pytest.fixture
def scraper():
    return SupermarketScraper()


# --- AB Vasilopoulos (GraphQL API) ---

def test_ab_parses_products():
    products = parse_ab_response(AB_JSON)

    assert [p['name'] for p in products] == [
        'Γάλα Υψηλής Θερμικής Επεξεργασίας Πλήρες 1lt',
        'Γάλα Υψηλής Θερμικής Επεξεργασίας Ελαφρύ 1lt',
        'Συμπυκνωμένο Μαλακτικό Ocean Breeze 87 Μεζούρες',
    ]
    assert products[0] == {
        'name': 'Γάλα Υψηλής Θερμικής Επεξεργασίας Πλήρες 1lt',
        'brand': 'ΑΒ ΕΠΙΛΟΓΗ',
        'price': 1.05,
        'size': '1 λιτ',
        'url': 'https://www.ab.gr/el/eshop/Galaktokomika-Fytika-Rofimata-and-Eidi-Psygeioy/Gala-and-Fytika-Rofimata/'
               'Gala-Ypsilis-Pasteriosis/Gala-Ypsilis-Thermikis-Epexergasias-Plires-1lt/p/7344931',
        'category': 'Γάλα Υψηλής Παστερίωσης',
        'unit_price_calc': {'value': 1.05, 'unit': '€/L'},
        'supermarket': 'AB Vasilopoulos',
    }
    assert products[2]['brand'] == 'LENOR'
    assert products[2]['size'] == '87 μεζ'
    assert products[2]['unit_price_calc'] == {'value': 0.06, 'unit': '€/wash'}


def test_ab_product_without_category():
    data = {'data': {'productSearch': {'products': [_ab_product(value=1.0)]}}}
    data['data']['productSearch']['products'][0]['categories'] = []

    assert parse_ab_response(data)[0]['category'] == ''


def _ab_product(**price):
    return {'name': 'Test', 'url': '/p/1', 'price': price}


def test_ab_prefers_discounted_price():
    data = {'data': {'productSearch': {'products': [
        _ab_product(value=3.0, discountedPriceFormatted='€2,40', supplementaryPriceLabel1='4,8 €/ κιλ'),
    ]}}}

    product = parse_ab_response(data)[0]

    assert product['price'] == 2.4
    assert product['unit_price_calc'] == {'value': 4.8, 'unit': '€/kg'}


def test_ab_falls_back_to_price_value():
    data = {'data': {'productSearch': {'products': [_ab_product(value=3.0, discountedPriceFormatted=None)]}}}

    assert parse_ab_response(data)[0]['price'] == 3.0


def test_ab_skips_products_without_name_or_price():
    data = {'data': {'productSearch': {'products': [
        {'name': '', 'price': {'value': 1.0}},
        {'name': 'No price', 'price': None},
        {'name': 'Zero', 'price': {'value': 0}},
    ]}}}

    assert parse_ab_response(data) == []


@pytest.mark.parametrize('data', [
    {},
    {'data': None},
    {'data': {'productSearch': None}},
    {'data': {'productSearch': {'products': []}}},
    {'errors': [{'message': 'Bad query'}], 'data': None},
])
def test_ab_empty_or_error_response(data):
    assert parse_ab_response(data) == []


def test_ab_returns_every_product_on_page():
    data = {'data': {'productSearch': {'products': [_ab_product(value=1.0)] * 30}}}

    assert len(parse_ab_response(data)) == 30


@pytest.mark.parametrize('data, expected', [
    (AB_JSON, 1),
    ({'data': {'productSearch': {'pagination': {'totalPages': 11}}}}, 11),
    ({'data': {'productSearch': {'pagination': {'totalPages': 0}}}}, 1),
    ({'data': {'productSearch': {'products': []}}}, 1),
    ({'data': None}, 1),
])
def test_ab_page_count(data, expected):
    assert ab_page_count(data) == expected


def test_ab_sends_graphql_search(fake_http, scraper):
    calls = fake_http({'ab.gr': FakeResponse(AB_JSON)})

    assert len(scraper.search_ab('γάλα')) == 3

    assert len(calls) == 1
    assert calls[0]['method'] == 'POST'
    assert calls[0]['url'] == 'https://www.ab.gr/api/v1/'
    assert calls[0]['json']['operationName'] == 'GetProductSearch'
    assert calls[0]['json']['variables'] == {'lang': 'gr', 'searchQuery': 'γάλα', 'pageSize': 50, 'pageNumber': 0}
    assert calls[0]['kwargs']['timeout'] > 0


def test_ab_logs_graphql_errors(fake_http, scraper, caplog):
    fake_http({'ab.gr': FakeResponse({'errors': [{'message': 'Bad query'}], 'data': None})})

    assert scraper.search_ab('x') == []
    assert 'Bad query' in caplog.text


@pytest.mark.parametrize('response', [
    FakeResponse('<html>not json</html>'),
    FakeResponse([1, 2, 3]),
])
def test_ab_unexpected_response(fake_http, scraper, response):
    fake_http({'ab.gr': response})

    assert scraper.search_ab('x') == []


# --- Sklavenitis (HTML) ---

def test_sklavenitis_parses_products():
    products = parse_sklavenitis_html(SKLAVENITIS_HTML)

    assert len(products) == 4
    assert products[0] == {
        'name': 'ΜΑΡΑΤΑ Γάλα Υψηλής Παστερίωσης Πλήρες 1lt',
        'brand': 'ΜΑΡΑΤΑ',
        'price': 1.0,
        'size': '1lt',
        'url': 'https://www.sklavenitis.gr/galata-rofimata-chymoi-psygeioy/galata-psygeioy/'
               'galata-agelados-ypsilis-pasteriosis/marata-gala-upsils-pasteriosis-plres-1lt-240867/',
        'category': 'Γάλατα Αγελάδος υψηλής παστερίωσης',
        'unit_price_calc': {'value': 1.0, 'unit': '€/L'},
        'supermarket': 'Sklavenitis',
    }


def test_sklavenitis_loose_product_priced_per_kg():
    # Loose bananas: no separate unit price, the main price is already per kg
    bananas = parse_sklavenitis_html(SKLAVENITIS_HTML)[1]

    assert bananas['name'] == 'Μπανάνες BAJELLA Εισαγωγής'
    assert bananas['price'] == 1.28
    assert bananas['unit_price_calc'] == {'value': 1.28, 'unit': '€/kg'}


def test_sklavenitis_packaged_product_uses_package_price():
    # Packaged bananas: 2,34 € per package, 1,95 € per kg
    bananas = parse_sklavenitis_html(SKLAVENITIS_HTML)[2]

    assert bananas['name'] == 'Μπανάνες DOLE Βιολογικές Εισαγωγής'
    assert bananas['price'] == 2.34
    assert bananas['unit_price_calc'] == {'value': 1.95, 'unit': '€/kg'}


def test_sklavenitis_ignores_per_kg_data_price():
    # For this product data-price="12,30" is the price per kg, not the package price (6,15 €)
    feta = parse_sklavenitis_html(SKLAVENITIS_HTML)[3]

    assert feta['name'] == 'Βαρελίσια Φέτα ΣΥΝΕΤΑΙΡΙΣΜΟΣ ΚΑΛΑΒΡΥΤΩΝ ΠΟΠ'
    assert feta['brand'] == 'ΣΥΝΕΤΑΙΡΙΣΜΟΣ ΚΑΛΑΒΡΥΤΩΝ'
    assert feta['price'] == 6.15
    assert feta['unit_price_calc'] == {'value': 12.3, 'unit': '€/kg'}


def test_sklavenitis_sends_search(fake_http, scraper):
    calls = fake_http({'sklavenitis.gr': FakeResponse(SKLAVENITIS_HTML)})

    assert len(scraper.search_sklavenitis('γάλα')) == 4

    assert len(calls) == 1
    assert calls[0]['method'] == 'GET'
    assert calls[0]['url'] == 'https://www.sklavenitis.gr/apotelesmata-anazitisis/'
    assert calls[0]['params'] == {'Query': 'γάλα', 'pg': 1}


@pytest.mark.parametrize('html, expected', [
    pytest.param(SKLAVENITIS_HTML.decode('utf-8'), 1, id='fixture'),
    ('<span class="current-page">\r\n\t\t24 από τα 226 προϊόντα\r\n\t</span>', 10),
    ('<span class="current-page">24 από τα 1.226 προϊόντα</span>', 52),
    ('<span class="current-page">24 από τα 24 προϊόντα</span>', 1),
    ('<html>No results</html>', 1),
])
def test_sklavenitis_page_count(html, expected):
    assert sklavenitis_page_count(html) == expected


def test_sklavenitis_skips_incomplete_products():
    html = '''<div class="productList">
        <div class="product"><div class="main-price"><div class="price">1,00 €</div></div></div>
        <div class="product"><h4 class="product__title"><a href="/p">No price</a></h4></div>
    </div>'''

    assert parse_sklavenitis_html(html.encode()) == []


# --- My Market (HTML) ---

def test_mymarket_parses_products():
    products = parse_mymarket_html(MYMARKET_HTML)

    assert len(products) == 3
    assert products[0] == {
        'name': 'NOYNOY Συμπυκνωμένο Γάλα 4x170gr',
        'brand': 'NOYNOY',
        'price': 3.28,
        'size': '4x170gr',
        'url': 'https://www.mymarket.gr/noynoy-sympyknomeno-gala-4x170gr',
        'category': 'Γάλα / Γαλακτοκομικά & Είδη Ψυγείου / Εβαπορέ',
        'unit_price_calc': {'value': 4.82, 'unit': '€/kg'},
        'supermarket': 'My Market',
    }


def test_mymarket_category_levels_in_any_order():
    # The fixture's bananas have the top level "Φρούτα & Λαχανικά" as category3
    bananas = parse_mymarket_html(MYMARKET_HTML)[1]
    in_usual_order = {'category': 'Φρούτα & Λαχανικά', 'category2': 'Φρούτα', 'category3': 'Μπανάνες, Χουρμάδες'}

    assert bananas['category'] == mymarket_category(in_usual_order) == 'Μπανάνες, Χουρμάδες / Φρούτα / Φρούτα & Λαχανικά'


@pytest.mark.parametrize('analytics, expected', [
    ({'category': 'Τρόφιμα', 'category2': 'Λάδι, Ελιές'}, 'Λάδι, Ελιές / Τρόφιμα'),
    ({'category': 'Τρόφιμα', 'category2': None, 'category3': ''}, 'Τρόφιμα'),
    ({}, ''),
])
def test_mymarket_category_missing_levels(analytics, expected):
    assert mymarket_category(analytics) == expected


def test_mymarket_product_sold_by_kg():
    bananas = parse_mymarket_html(MYMARKET_HTML)[1]

    assert bananas['name'] == 'Μπανάνες Dole Εισαγωγής Τιμή Κιλού'
    assert bananas['price'] == 1.88
    assert bananas['unit_price_calc'] == {'value': 1.88, 'unit': '€/kg'}


def test_mymarket_product_without_unit_price():
    # "Τελ. τιμή" (final price) has no unit, so the unit price is left to search_all_supermarkets
    grill = parse_mymarket_html(MYMARKET_HTML)[2]

    assert grill['price'] == 57.63
    assert grill['unit_price_calc'] is None


def test_mymarket_sends_search(fake_http, scraper):
    calls = fake_http({'mymarket.gr': FakeResponse(MYMARKET_HTML)})

    assert len(scraper.search_mymarket('γάλα')) == 3

    assert len(calls) == 1
    assert calls[0]['method'] == 'GET'
    assert calls[0]['url'] == 'https://www.mymarket.gr/search'
    assert calls[0]['params'] == {'query': 'γάλα', 'page': 1}


@pytest.mark.parametrize('html, page_size, expected', [
    pytest.param(MYMARKET_HTML.decode('utf-8'), 3, 1, id='fixture'),
    ('<button data-action="findastic#hideFilters" type="button">\n   1.062 προϊόντα\n</button>', 35, 31),
    ('<button data-action="findastic#hideFilters" type="button">61 προϊόντα</button>', 35, 2),
    ('<button data-action="findastic#hideFilters" type="button">61 προϊόντα</button>', 0, 1),
    # Other product counts on the page are ignored
    ('<p>Δείτε 20 προϊόντα</p>', 35, 1),
])
def test_mymarket_page_count(html, page_size, expected):
    assert mymarket_page_count(html, page_size) == expected


def test_mymarket_skips_products_without_price():
    html = '<article class="product--teaser"><h3><a href="/p">No price</a></h3></article>'

    assert parse_mymarket_html(html.encode()) == []


# --- Common behaviour of all stores ---

STORE_SEARCHES = [
    ('search_ab', 'ab.gr', FakeResponse(AB_JSON)),
    ('search_sklavenitis', 'sklavenitis.gr', FakeResponse(SKLAVENITIS_HTML)),
    ('search_mymarket', 'mymarket.gr', FakeResponse(MYMARKET_HTML)),
]


@pytest.mark.parametrize('search, domain, ok_response', STORE_SEARCHES)
@pytest.mark.parametrize('failure', [
    FakeResponse('Not found', status_code=404),
    FakeResponse('Server error', status_code=500),
    requests.Timeout('timed out'),
    requests.ConnectionError('no network'),
])
def test_store_request_failures(fake_http, scraper, caplog, search, domain, ok_response, failure):
    fake_http({domain: failure})

    with caplog.at_level(logging.WARNING):
        assert getattr(scraper, search)('x') == []

    assert 'Error searching' in caplog.text


@pytest.mark.parametrize('search, domain, ok_response', STORE_SEARCHES)
def test_store_every_product_has_required_fields(fake_http, scraper, search, domain, ok_response):
    fake_http({domain: ok_response})

    for product in getattr(scraper, search)('x'):
        assert product['name']
        assert product['price'] > 0
        assert product['url'].startswith('https://')
        assert set(product) == {'name', 'brand', 'price', 'size', 'url', 'category', 'unit_price_calc', 'supermarket'}


@pytest.mark.parametrize('parse', [parse_sklavenitis_html, parse_mymarket_html])
def test_html_store_empty_page(parse):
    assert parse(b'<html><body>No results</body></html>') == []


# --- Reading all result pages ---
# Each store gets small pages of 2 products; make_page(names, page_count) builds a page
# in the store's format, page_of(params, json) tells which page was requested.

def _ab_page(names, page_count):
    products = [{'name': name, 'url': f'/p/{name}', 'price': {'value': 1.0}} for name in names]
    return FakeResponse({'data': {'productSearch': {'products': products, 'pagination': {'totalPages': page_count}}}})


def _sklavenitis_page(names, page_count):
    items = ''.join(
        f'<div class="product"><h4 class="product__title"><a href="/{name}">{name}</a></h4>'
        f'<div class="main-price"><div class="price">1,00 €</div></div></div>'
        for name in names
    )
    return FakeResponse(f'<div class="productList">{items}</div>'
                        f'<span class="current-page">{len(names)} από τα {2 * page_count} προϊόντα</span>')


def _mymarket_page(names, page_count):
    items = ''.join(
        f'<article class="product--teaser"><h3><a href="/{name}">{name}</a></h3>'
        f'<span class="teaser-display-price-whole">1</span></article>'
        for name in names
    )
    return FakeResponse(f'<button data-action="findastic#hideFilters">{2 * page_count} προϊόντα</button>{items}')


PAGINATED_STORES = [
    ('search_ab', 'ab.gr', 0, lambda params, json: json['variables']['pageNumber'], _ab_page),
    ('search_sklavenitis', 'sklavenitis.gr', 1, lambda params, json: params['pg'], _sklavenitis_page),
    ('search_mymarket', 'mymarket.gr', 1, lambda params, json: params['page'], _mymarket_page),
]

# Pages by offset from the store's first page number
THREE_PAGES = [['A1', 'A2'], ['B1', 'B2'], ['C1', 'C2']]


def _serve_pages(fake_http, domain, first_page, page_of, make_page, pages):
    def respond(params, json):
        index = page_of(params, json) - first_page
        if not 0 <= index < len(pages):
            return FakeResponse('Not found', status_code=404)
        if isinstance(pages[index], (FakeResponse, Exception)):
            return pages[index]
        return make_page(pages[index], len(pages))

    calls = fake_http({domain: respond})
    return lambda: sorted(page_of(call['params'], call['json']) - first_page for call in calls)


@pytest.mark.parametrize('search, domain, first_page, page_of, make_page', PAGINATED_STORES)
def test_store_reads_all_pages(fake_http, scraper, search, domain, first_page, page_of, make_page):
    requested = _serve_pages(fake_http, domain, first_page, page_of, make_page, THREE_PAGES)

    products = getattr(scraper, search)('x')

    assert [p['name'] for p in products] == ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']
    assert requested() == [0, 1, 2]


@pytest.mark.parametrize('search, domain, first_page, page_of, make_page', PAGINATED_STORES)
def test_store_reads_at_most_max_pages(fake_http, scraper, monkeypatch, search, domain, first_page, page_of, make_page):
    monkeypatch.setattr(supermarket_scraper, 'MAX_PAGES', 2)
    requested = _serve_pages(fake_http, domain, first_page, page_of, make_page, THREE_PAGES)

    products = getattr(scraper, search)('x')

    assert [p['name'] for p in products] == ['A1', 'A2', 'B1', 'B2']
    assert requested() == [0, 1]


@pytest.mark.parametrize('search, domain, first_page, page_of, make_page', PAGINATED_STORES)
def test_store_keeps_other_pages_when_one_fails(fake_http, scraper, search, domain, first_page, page_of, make_page):
    pages = [['A1', 'A2'], requests.Timeout('timed out'), ['C1', 'C2']]
    _serve_pages(fake_http, domain, first_page, page_of, make_page, pages)

    products = getattr(scraper, search)('x')

    assert [p['name'] for p in products] == ['A1', 'A2', 'C1', 'C2']


@pytest.mark.parametrize('search, domain, first_page, page_of, make_page', PAGINATED_STORES)
def test_store_removes_products_repeated_on_next_page(fake_http, scraper, search, domain, first_page, page_of, make_page):
    # Results shifted between requests, so A2 is also the first product of page 2
    _serve_pages(fake_http, domain, first_page, page_of, make_page, [['A1', 'A2'], ['A2', 'B1']])

    products = getattr(scraper, search)('x')

    assert [p['name'] for p in products] == ['A1', 'A2', 'B1']


# --- All supermarkets together ---

def test_search_all_supermarkets_keeps_only_relevant_products(fake_http):
    fake_http(ALL_STORES)

    results = search_all_supermarkets('γάλα')

    assert set(results) == {'ab', 'sklavenitis', 'mymarket'}
    # The softener, bananas, feta and grill in the fixtures are dropped
    assert [p['name'] for p in results['ab']] == [
        'Γάλα Υψηλής Θερμικής Επεξεργασίας Πλήρες 1lt',
        'Γάλα Υψηλής Θερμικής Επεξεργασίας Ελαφρύ 1lt',
    ]
    assert [p['name'] for p in results['sklavenitis']] == ['ΜΑΡΑΤΑ Γάλα Υψηλής Παστερίωσης Πλήρες 1lt']
    assert [p['name'] for p in results['mymarket']] == ['NOYNOY Συμπυκνωμένο Γάλα 4x170gr']


def test_search_all_supermarkets_store_without_relevant_products(fake_http):
    fake_http(ALL_STORES)

    results = search_all_supermarkets('μπανάνες')

    assert results['ab'] == []
    assert [p['unit_price_calc'] for p in results['sklavenitis']] == [
        {'value': 1.28, 'unit': '€/kg'},
        {'value': 1.95, 'unit': '€/kg'},
    ]
    assert [p['unit_price_calc'] for p in results['mymarket']] == [{'value': 1.88, 'unit': '€/kg'}]


def test_search_all_supermarkets_drops_products_from_other_categories(fake_http):
    def ab_product(name, price, category):
        return {'name': name, 'url': f'/p/{name}', 'categories': [{'name': category}],
                'price': {'value': price, 'supplementaryPriceLabel1': f'{price * 2} €/ κιλ'}}

    # The cheapest "Φέτα" per kg is a frozen pie
    fake_http({'ab.gr': FakeResponse({'data': {'productSearch': {'products': [
        ab_product('Τυροπιτάκια Σφολιάτας Μυζήθρα Φέτα 500g', 1.25, 'Κατεψυγμένες Πίτες & Πιτάκια'),
        ab_product('Φέτα ΠΟΠ 500g', 4.98, 'Φέτα'),
    ]}}})})

    results = search_all_supermarkets('φέτα')

    assert [p['name'] for p in results['ab']] == ['Φέτα ΠΟΠ 500g']


def test_search_all_supermarkets_sorts_by_value(fake_http):
    prices = [1.20, 0.99, 1.50, 1.05, 2.10]
    data = {'data': {'productSearch': {'products': [
        {'name': f'Γάλα {i} 1lt', 'url': f'/p/{i}', 'price': {'value': price, 'supplementaryPriceLabel1': f'{price} €/ λιτ'}}
        for i, price in enumerate(prices)
    ]}}}
    fake_http({'ab.gr': FakeResponse(data)})

    results = search_all_supermarkets('γάλα')

    # Every relevant product is returned, so that the user can choose any of them
    assert [p['price'] for p in results['ab']] == [0.99, 1.05, 1.20, 1.50, 2.10]


def test_search_all_supermarkets_calculates_unit_price_without_size(fake_http):
    # "Τελ. τιμή" (final price) has no unit and the name has no size, so it is €/unit
    fake_http(ALL_STORES)

    results = search_all_supermarkets('ψησταριά')

    assert [p['unit_price_calc'] for p in results['mymarket']] == [{'value': 57.63, 'unit': '€/unit'}]


def test_search_all_supermarkets_calculates_missing_unit_price(fake_http):
    data = {'data': {'productSearch': {'products': [
        {'name': 'Φέτα 400g', 'url': '/p/1', 'price': {'value': 6.0, 'supplementaryPriceLabel2': ''}},
    ]}}}
    fake_http({'ab.gr': FakeResponse(data)})

    results = search_all_supermarkets('φέτα')

    # No size and no store unit price: calculated from the product name
    assert results['ab'][0]['unit_price_calc'] == {'value': 15.0, 'unit': '€/kg'}


def test_search_all_supermarkets_isolates_broken_store(fake_http, monkeypatch, caplog):
    fake_http(ALL_STORES)

    def broken(self, product_name):
        raise RuntimeError('boom')

    monkeypatch.setattr(SupermarketScraper, 'search_ab', broken)

    results = search_all_supermarkets('γάλα')

    assert results['ab'] == []
    assert len(results['sklavenitis']) == 1
    assert len(results['mymarket']) == 1
    assert 'Unexpected error searching ab' in caplog.text


def test_search_all_supermarkets_all_down(fake_http):
    fake_http({})

    assert search_all_supermarkets('γάλα') == {'ab': [], 'sklavenitis': [], 'mymarket': []}


def test_search_store_reuses_one_scraper_per_max_pages(fake_http):
    fake_http(ALL_STORES)
    supermarket_scraper._scraper.cache_clear()

    first = search_store('sklavenitis', 'γάλα', max_pages=2)
    again = search_store('sklavenitis', 'γάλα', max_pages=2)
    search_store('ab', 'γάλα')

    assert len(first) == 1 and again == first
    # One scraper (and its connections) for max_pages=2 and one for all pages
    assert supermarket_scraper._scraper.cache_info()[:2] == (1, 2)
    assert supermarket_scraper._scraper(2).max_pages == 2
