import json

import pytest

import app as app_module
import meal_planner
from app import app, meal_planner_search
from meal_planner import DATA, Planner
from meal_planner.pricing import PriceProvider


def fake_store_search(store, query):
    """The same products in every store for any search: one package per unit of the meal planner."""
    return [
        {'name': f'{query} 500g', 'price': 2.0, 'size': 500, 'size_unit': 'g'},
        {'name': f'{query} 1lt', 'price': 1.5, 'size': 1, 'size_unit': 'l'},
        {'name': f'{query} 6τεμ', 'price': 1.8, 'size': 6, 'size_unit': 'τεμ'},
    ]


@pytest.fixture
def provider(tmp_path):
    provider = PriceProvider(str(tmp_path / 'price_cache.json'))
    provider.register(fake_store_search)
    return provider


@pytest.fixture
def planner(tmp_path, provider):
    return Planner(DATA, str(tmp_path), provider)


# --- Products for the meal planner from the scrapers ---

def scraped(name, price, size='', unit_price=None):
    return {'name': name, 'brand': '', 'price': price, 'size': size, 'url': f'https://store/{name}',
            'category': '', 'unit_price_calc': unit_price or {'value': price, 'unit': '€/unit'}}


def test_meal_planner_search_converts_products(monkeypatch):
    searches = []

    def fake_search_store(store, product_name, max_pages=None):
        searches.append((store, product_name, max_pages))
        return [
            scraped('Γάλα Φρέσκο 1lt', 1.05, unit_price={'value': 1.05, 'unit': '€/L'}),
            scraped('Φέτα', 7.96, size='400g'),
            scraped('Αυγά Μεσαία 6τεμ', 1.9),
            scraped('Ντομάτες Εγχώριες', 2.1, unit_price={'value': 2.1, 'unit': '€/kg'}),
            scraped('Μαρούλι Τεμάχιο', 0.8),
            scraped('Απορρυπαντικό 40μεζ', 9.5),
        ]

    monkeypatch.setattr(app_module, 'search_store', fake_search_store)

    products = meal_planner_search('sklavenitis', 'γάλα')

    assert searches == [('sklavenitis', 'γάλα', app_module.MEAL_PLANNER_PAGES)]
    assert [(p['name'], p['price'], p['size'], p['size_unit']) for p in products] == [
        ('Γάλα Φρέσκο 1lt', 1.05, 1.0, 'l'),
        ('Φέτα', 7.96, 0.4, 'kg'),
        ('Αυγά Μεσαία 6τεμ', 1.9, 6.0, 'pcs'),
        # Loose products are priced per kg, products without a size per piece
        ('Ντομάτες Εγχώριες', 2.1, 1, 'kg'),
        ('Μαρούλι Τεμάχιο', 0.8, 1, 'pcs'),
    ]
    assert products[0]['url'] == 'https://store/Γάλα Φρέσκο 1lt'


def test_price_options_filter_by_unit_match_and_exclude(provider):
    ingredient = {'query': 'ντομάτες', 'unit': 'g', 'match': ['τοματ'], 'exclude': ['πελτ']}
    provider.register(lambda store, query: [
        {'name': 'Ντομάτες Εγχώριες', 'price': 2.1, 'size': 1, 'size_unit': 'kg'},
        {'name': 'Πελτές Ντομάτας 410g', 'price': 2.18, 'size': 410, 'size_unit': 'g'},
        {'name': 'Ντομάτες 6τεμ', 'price': 2.0, 'size': 6, 'size_unit': 'pcs'},
        {'name': 'Αγγούρια 500g', 'price': 1.0, 'size': 500, 'size_unit': 'g'},
    ])

    options = provider.options('ab', 'tomato', ingredient)

    assert [(o['name'], o['size']) for o in options] == [('Ντομάτες Εγχώριες', 1000.0)]


def test_price_options_search_every_query(provider):
    queries = []

    def search(store, query):
        queries.append(query)
        return [{'name': f'{query.capitalize()} 1kg', 'price': 2.0, 'size': 1, 'size_unit': 'kg'}]

    provider.register(search)
    ingredient = {'query': ['ντομάτες', 'τομάτες'], 'unit': 'g', 'match': ['τοματ']}

    options = provider.options('ab', 'tomato', ingredient)

    assert queries == ['ντομάτες', 'τομάτες']
    assert [o['name'] for o in options] == ['Ντομάτες 1kg', 'Τομάτες 1kg']


def test_cost_picks_cheapest_total_for_the_quantity(provider):
    provider.register(lambda store, query: [
        {'name': 'Ρύζι 5kg', 'price': 6.0, 'size': 5, 'size_unit': 'kg'},
        {'name': 'Ρύζι 1kg', 'price': 1.5, 'size': 1, 'size_unit': 'kg'},
    ])
    ingredient = {'query': 'ρύζι', 'unit': 'g', 'fallback_price': 2.0}

    cost = provider.cost('rice', ingredient, 1500, ['ab'])

    # 2 x 1kg costs less than 5kg, although 5kg is cheaper per kg
    assert (cost['product'], cost['packs'], cost['cost'], cost['estimated']) == ('Ρύζι 1kg', 2, 3.0, False)


def test_cost_is_estimated_without_products(provider):
    provider.register(lambda store, query: [])
    ingredient = {'query': 'ρύζι', 'unit': 'g', 'fallback_price': 2.0}

    cost = provider.cost('rice', ingredient, 1500, ['ab'])

    assert (cost['product'], cost['cost'], cost['estimated']) == (None, 3.0, True)


def test_broken_search_does_not_fail_the_prices(provider):
    def broken(store, query):
        raise RuntimeError('store down')

    provider.register(broken)

    assert provider.options('ab', 'rice', {'query': 'ρύζι', 'unit': 'g'}) == []


# --- Plans ---

def test_builtin_recipes_use_known_ingredients(planner):
    assert planner.recipes
    for recipe in planner.recipes.values():
        assert set(recipe['ingredients']) <= set(planner.ingredients), recipe['id']


def test_imported_recipes(tmp_path, provider):
    (tmp_path / 'ingredients_mine.json').write_text(json.dumps({'quinoa': {
        'name': 'Κινόα', 'query': 'κινόα', 'unit': 'g', 'fallback_price': 8.0, 'aisle': 'Λοιπά', 'type': 'plant'}}),
        encoding='utf-8')
    recipe = {'meal': ['lunch', 'dinner'], 'category': 'salad', 'servings': 2, 'time': 20, 'steps': ['Βράσε.']}
    (tmp_path / 'recipes_mine.json').write_text(json.dumps([
        {**recipe, 'id': 'quinoa_salad', 'name': 'Σαλάτα κινόα', 'ingredients': {'quinoa': 200, 'tomato': 300}},
        {**recipe, 'id': 'broken', 'name': 'Άγνωστο', 'ingredients': {'unknown': 100}},
    ]), encoding='utf-8')

    planner = Planner(DATA, str(tmp_path), provider)

    assert planner.recipes['quinoa_salad']['imported']
    assert 'broken' not in planner.recipes
    assert planner.eligible(planner.clean_settings({'source': 'imported'}), 'dinner') == ['quinoa_salad']
    assert 'quinoa_salad' not in planner.eligible(planner.clean_settings({'source': 'builtin'}), 'dinner')


def test_generate_plan_within_budget(planner):
    plan = planner.generate({'persons': 2, 'budget': 200, 'store': 'sklavenitis'}, seed=1)

    assert plan['within_budget']
    assert plan['total'] <= 200
    assert [len(day['meals']) for day in plan['days']] == [3] * 7
    assert plan['estimated'] == 0
    items = [item for aisle in plan['shopping'] for item in aisle['items']]
    assert items and all(item['store'] == 'sklavenitis' for item in items)
    # Pantry items are not costed unless asked
    assert not any(planner.ingredients[item['id']].get('pantry') for item in items)


def test_leftovers_cook_dinner_for_next_day_lunch(planner):
    plan = planner.generate({'meals': ['lunch', 'dinner'], 'leftovers': True}, seed=1)

    monday, tuesday = plan['days'][0]['meals'], plan['days'][1]['meals']
    assert monday['dinner']['cook_portions'] == 4
    assert tuesday['lunch']['leftover']
    assert tuesday['lunch']['recipe_id'] == monday['dinner']['recipe_id']


def test_vegetarian_plan_has_no_meat_or_fish(planner):
    plan = planner.generate({'diet': 'vegetarian', 'meals': ['dinner']}, seed=1)

    for cook in plan['cooks']:
        types = {planner.ingredients[i]['type'] for i in planner.recipes[cook['recipe_id']]['ingredients']}
        assert not types & {'meat', 'fish'}


def test_swap_changes_one_meal(planner):
    plan = planner.generate({'meals': ['dinner'], 'leftovers': False}, seed=1)
    before = plan['days'][2]['meals']['dinner']['recipe_id']

    swapped = planner.swap(plan, 2, 'dinner', seed=1)

    assert swapped['days'][2]['meals']['dinner']['recipe_id'] != before


def test_settings_are_cleaned(planner):
    settings = planner.clean_settings({'persons': 50, 'budget': -5, 'store': 'lidl', 'meals': [], 'exclude': ['nope']})

    assert (settings['persons'], settings['budget'], settings['store']) == (12, 0.0, 'sklavenitis')
    assert settings['meals'] == ['dinner']
    assert settings['exclude'] == []


# --- Routes ---

@pytest.fixture
def client(tmp_path, monkeypatch, provider):
    """The meal planner routes with fake prices and the plan in a temporary folder."""
    monkeypatch.setattr(meal_planner, 'PLAN_FILE', str(tmp_path / 'current_plan.json'))
    monkeypatch.setattr(meal_planner, 'price_provider', provider)
    monkeypatch.setattr(meal_planner.planner, 'provider', provider)
    return app.test_client()


def test_meal_planner_page(client):
    response = client.get('/meals/')

    assert response.status_code == 200
    assert 'Πλάνο Γευμάτων' in response.get_data(as_text=True)


def test_index_links_to_meal_planner(client):
    assert 'href="/meals/"' in client.get('/').get_data(as_text=True)


def test_meta_shows_prices_connected(client):
    meta = client.get('/meals/api/meta').get_json()

    assert meta['connected']
    assert set(meta['stores']) == {'ab', 'sklavenitis', 'mymarket'}
    assert meta['recipe_count'] > 0


def test_plan_routes(client):
    assert client.get('/meals/api/plan').get_json() is None

    plan = client.post('/meals/api/plan', json={'persons': 1, 'store': 'cheapest', 'meals': ['dinner']}).get_json()
    assert plan['settings']['store'] == 'cheapest'
    assert client.get('/meals/api/plan').get_json()['cooks'] == plan['cooks']

    swapped = client.post('/meals/api/swap', json={'day': 0, 'meal': 'dinner'})
    assert swapped.status_code == 200

    recipe_id = plan['days'][0]['meals']['dinner']['recipe_id']
    recipe = client.get(f'/meals/api/recipe/{recipe_id}?portions=3').get_json()
    assert recipe['persons'] == 3 and recipe['steps']


def test_swap_without_plan(client):
    response = client.post('/meals/api/swap', json={'day': 0, 'meal': 'dinner'})

    assert response.status_code == 400
    assert response.get_json()['error'] == 'Δεν υπάρχει πλάνο.'


def test_unknown_recipe(client):
    assert client.get('/meals/api/recipe/nope').status_code == 404
