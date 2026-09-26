import json

import pytest

import app as app_module
from app import MAX_PRODUCTS, app
from favourites import FavouritesStore


@pytest.fixture
def client():
    return app.test_client()


@pytest.fixture
def searched(monkeypatch):
    """Replace the real search with a stub and record which products were searched."""
    names = []

    def fake_search(product_name):
        names.append(product_name)
        return {'ab': [], 'sklavenitis': [], 'mymarket': []}

    monkeypatch.setattr(app_module, 'search_all_supermarkets', fake_search)
    return names


def test_index(client):
    response = client.get('/')

    assert response.status_code == 200
    assert 'Supermarket Price Finder' in response.get_data(as_text=True)


def test_favourites_page(client):
    response = client.get('/favourites')

    assert response.status_code == 200
    assert 'favouritesList' in response.get_data(as_text=True)


def test_search_returns_results_per_product(client, searched):
    response = client.post('/search', json={'products': ['Lenor', 'Ariel Pods']})

    assert response.status_code == 200
    assert response.get_json() == {
        'Lenor': {'products': {'ab': [], 'sklavenitis': [], 'mymarket': []}, 'groups': []},
        'Ariel Pods': {'products': {'ab': [], 'sklavenitis': [], 'mymarket': []}, 'groups': []},
    }


def test_search_returns_product_choices(client, monkeypatch):
    def product(name, price):
        return {'name': name, 'brand': 'DETTOL', 'price': price, 'size': '', 'url': f'https://x/{price}',
                'category': '', 'unit_price_calc': {'value': price / 2.5, 'unit': '€/L'}, 'supermarket': ''}

    monkeypatch.setattr(app_module, 'search_all_supermarkets', lambda name: {
        'ab': [product('Απολυμαντικό Ρούχων 2,5lt', 8.37)],
        'sklavenitis': [],
        'mymarket': [product('Dettol Απολυμαντικό Για Τα Ρούχα 2,5lt', 7.88)],
    })

    result = client.post('/search', json={'products': ['dettol']}).get_json()['dettol']

    assert result['groups'] == [{'label': 'DETTOL Απολυμαντικό Ρούχων 2,5lt', 'products': {'ab': 0, 'mymarket': 0}}]


def test_search_keeps_input_order(client, searched):
    response = client.post('/search', json={'products': ['zeta', 'alpha', 'mu']})

    assert list(response.get_json()) == ['zeta', 'alpha', 'mu']


def test_search_strips_blanks_and_duplicates(client, searched):
    client.post('/search', json={'products': ['  Lenor ', '', 'Lenor', '   ', 'Ariel']})

    assert searched == ['Lenor', 'Ariel']


@pytest.mark.parametrize('kwargs', [
    {'data': 'not json'},
    {'json': {}},
    {'json': {'products': []}},
    {'json': {'products': ['', '  ']}},
    {'json': {'products': 'Lenor'}},
    {'json': {'products': ['Lenor', 5]}},
    {'json': ['Lenor']},
])
def test_search_rejects_invalid_input(client, searched, kwargs):
    response = client.post('/search', **kwargs)

    assert response.status_code == 400
    assert 'error' in response.get_json()
    assert searched == []


def test_search_rejects_too_many_products(client, searched):
    products = [f'product {i}' for i in range(MAX_PRODUCTS + 1)]

    response = client.post('/search', json={'products': products})

    assert response.status_code == 400
    assert searched == []


def test_search_accepts_max_products(client, searched):
    products = [f'product {i}' for i in range(MAX_PRODUCTS)]

    assert client.post('/search', json={'products': products}).status_code == 200


def test_search_requires_post(client):
    assert client.get('/search').status_code == 405


# --- Favourites ---

FAVOURITE = {
    'search': 'dettol απολυμαντικό ρούχων',
    'label': 'DETTOL Απολυμαντικό Ρούχων 2,5lt',
    'products': {
        'ab': {'name': 'Απολυμαντικό Ρούχων 2,5lt', 'url': 'https://www.ab.gr/el/eshop/p/7147236'},
        'mymarket': {'name': 'Dettol Απολυμαντικό Για Τα Ρούχα 2,5lt',
                     'url': 'https://www.mymarket.gr/dettol-apolymantiko-gia-ta-roucha-25lt'},
    },
}


@pytest.fixture
def favourites_file(monkeypatch, tmp_path):
    path = tmp_path / 'favourites.json'
    monkeypatch.setattr(app_module, 'favourites', FavouritesStore(path))
    return path


def test_favourites_empty(client, favourites_file):
    assert client.get('/api/favourites').get_json() == []


def test_add_favourite(client, favourites_file):
    response = client.post('/api/favourites', json=FAVOURITE)

    assert response.status_code == 201
    saved = response.get_json()
    assert saved == {'id': saved['id'], **FAVOURITE}
    assert client.get('/api/favourites').get_json() == [saved]
    # Kept on disk, so that it survives a restart
    assert json.loads(favourites_file.read_text(encoding='utf-8')) == [saved]


def test_add_same_favourite_twice(client, favourites_file):
    first = client.post('/api/favourites', json=FAVOURITE).get_json()
    second = client.post('/api/favourites', json=FAVOURITE).get_json()

    assert first == second
    assert len(client.get('/api/favourites').get_json()) == 1


@pytest.mark.parametrize('favourite', [
    None,
    [],
    {**FAVOURITE, 'search': ''},
    {**FAVOURITE, 'label': 5},
    {**FAVOURITE, 'products': {}},
    {**FAVOURITE, 'products': {'lidl': {'name': 'x', 'url': 'https://www.lidl-hellas.gr/p/1'}}},
    {**FAVOURITE, 'products': {'ab': {'name': 'x', 'url': 'javascript:alert(1)'}}},
    {**FAVOURITE, 'products': {'ab': {'name': '', 'url': 'https://www.ab.gr/p/1'}}},
])
def test_add_favourite_rejects_invalid_input(client, favourites_file, favourite):
    response = client.post('/api/favourites', json=favourite)

    assert response.status_code == 400
    assert 'error' in response.get_json()
    assert client.get('/api/favourites').get_json() == []


def test_remove_favourite(client, favourites_file):
    saved = client.post('/api/favourites', json=FAVOURITE).get_json()

    assert client.delete(f"/api/favourites/{saved['id']}").status_code == 204
    assert client.get('/api/favourites').get_json() == []


def test_remove_unknown_favourite(client, favourites_file):
    assert client.delete('/api/favourites/nope').status_code == 404
