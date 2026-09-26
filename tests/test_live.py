"""
Tests against the real supermarket websites.

Skipped by default; run with `pytest --live`. A failure here usually means a site
changed its URL, API or markup and the matching parser in supermarket_scraper.py needs updating.
"""
import pytest

from matching import group_products
from supermarket_scraper import SupermarketScraper, relevance, search_all_supermarkets

pytestmark = pytest.mark.live

STORES = ['search_ab', 'search_sklavenitis', 'search_mymarket']

# Products on the first result page of each store; "γάλα" has several pages everywhere
FIRST_PAGE_SIZE = {'search_ab': 50, 'search_sklavenitis': 24, 'search_mymarket': 35}


@pytest.mark.parametrize('search', STORES)
@pytest.mark.parametrize('query', ['γάλα', 'lenor'])
def test_store_returns_products(search, query):
    products = getattr(SupermarketScraper(), search)(query)

    assert products, f'{search} returned no products for {query!r}'
    for product in products:
        assert product['name']
        assert isinstance(product['price'], float) and product['price'] > 0
        assert product['url'].startswith('https://')

    # Most products should come with the store's own unit price
    with_unit_price = [p for p in products if p['unit_price_calc']]
    assert len(with_unit_price) >= len(products) / 2, f'{search}: unit prices missing'


@pytest.mark.parametrize('search', STORES)
def test_store_reads_all_pages(search):
    products = getattr(SupermarketScraper(), search)('γάλα')

    assert len(products) > 2 * FIRST_PAGE_SIZE[search], f'{search}: only {len(products)} products, pages not read'
    assert len({(p['name'], p['url']) for p in products}) == len(products)


@pytest.mark.parametrize('search', STORES)
def test_store_returns_nothing_for_nonsense(search):
    assert getattr(SupermarketScraper(), search)('xqzxqzxqz') == []


@pytest.mark.parametrize('query', ['γάλα', 'φέτα'])
def test_search_all_supermarkets_returns_relevant_products(query):
    results = search_all_supermarkets(query)

    for store in ('ab', 'sklavenitis', 'mymarket'):
        assert len(results[store]) >= 3, f'{store} returned {len(results[store])} products'
        for product in results[store]:
            assert relevance(query, product) == 2, f'{store}: {product["name"]!r} is not {query!r}'


@pytest.mark.parametrize('query, category_word', [('φέτα', 'φέτα'), ('μπανάνες', 'μπανάν')])
def test_most_likely_choice_skips_other_categories(query, category_word):
    # e.g. no frozen pies with feta or banana yogurts, even when they are cheaper per kg
    results = search_all_supermarkets(query)

    best = group_products(results)[0]

    for store, index in best['products'].items():
        product = results[store][index]
        assert category_word in product['category'].lower(), f'{store}: {product["name"]!r} ({product["category"]})'


# The products a user expected for these searches; "dettol" also finds many other
# DETTOL products, whose names use the words of the Sklavenitis name for other variants
@pytest.mark.parametrize('query', ['DETTOL Απολυμαντικο Ρούχων', 'dettol'])
def test_same_product_found_in_every_store(query):
    results = search_all_supermarkets(query)

    best = group_products(results)[0]

    assert {store: results[store][index]['url'] for store, index in best['products'].items()} == {
        'ab': 'https://www.ab.gr/el/eshop/Katharistika-Chartika-and-eidi-spitioy/Leykantika-and-Enischytika-Plysimatos'
              '/Ygra-Leykantika-and-Enischytika-Plysimatos/Apolymantiko-Roychon-2-5lt/p/7147236',
        'sklavenitis': 'https://www.sklavenitis.gr/aporrypantika-eidi-katharismoy/aporrypantika-roychon'
                       '/apolymantika-roychon/dettol-apolumantiko-rouhon-25lt-238338/',
        'mymarket': 'https://www.mymarket.gr/dettol-apolymantiko-gia-ta-roucha-25lt',
    }


def test_same_product_with_name_in_other_alphabet():
    # Sklavenitis writes "Paprika", AB and My Market "Πάπρικα"
    results = search_all_supermarkets('pringles πάπρικα')

    best = group_products(results)[0]

    assert {store: results[store][index]['url'] for store, index in best['products'].items()} == {
        'ab': 'https://www.ab.gr/el/eshop/Proino-snacking-and-rofimata/Snaks/Patatakia-Tsips'
              '/Tsips-Paprika-165g/p/7657366',
        'sklavenitis': 'https://www.sklavenitis.gr/xiroi-karpoi-snak/patatakia-garidakia-alla-snak'
                       '/patatakia/pringles-snak-hot-paprika-165gr/',
        'mymarket': 'https://www.mymarket.gr/pringles-paprika-165gr',
    }
