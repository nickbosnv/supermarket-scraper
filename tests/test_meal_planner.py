import json

import pytest

import app as app_module
import meal_planner
from app import app, meal_planner_search
from meal_planner import DATA, Planner, custom
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
    # What is left of the packages is kept for another time
    assert cost['leftover'] == 500


def test_cost_buys_the_product_the_user_picked(provider):
    provider.register(lambda store, query: [
        {'name': 'Τυρί Κρέμα 200g', 'price': 1.5, 'size': 200, 'size_unit': 'g'},
        {'name': 'Philadelphia Τυρί Κρέμα 300g', 'price': 3.2, 'size': 300, 'size_unit': 'g'},
    ])
    ingredient = {'query': 'philadelphia', 'unit': 'g', 'fallback_price': 10.0,
                  'product': {'store': 'ab', 'name': 'Philadelphia Τυρί Κρέμα 300g'}}

    picked = provider.cost('my_philadelphia', ingredient, 200, ['ab'])
    other_store = provider.cost('my_philadelphia', ingredient, 200, ['mymarket'])

    # A bigger package than the recipe needs, with 100g left over
    assert (picked['product'], picked['cost'], picked['leftover']) == ('Philadelphia Τυρί Κρέμα 300g', 3.2, 100)
    # Other stores search by the title, cheapest first
    assert other_store['product'] == 'Τυρί Κρέμα 200g'


def test_products_have_sizes_in_the_planner_units(provider):
    provider.register(lambda store, query: [
        {'name': 'Κρέμα Γάλακτος 1lt', 'price': 4.0, 'size': 1, 'size_unit': 'l'},
        {'name': 'Χωρίς μέγεθος', 'price': 1.0, 'size': None, 'size_unit': None},
    ])

    assert provider.products('ab', 'κρέμα') == [
        {'name': 'Κρέμα Γάλακτος 1lt', 'price': 4.0, 'size': 1000.0, 'unit': 'ml', 'url': None, 'store': 'ab'}]


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


def test_alternatives_list_every_fitting_recipe(planner):
    plan = planner.generate({'meals': ['breakfast', 'lunch', 'dinner'], 'leftovers': True}, seed=1)
    current = plan['days'][0]['meals']['dinner']['recipe_id']

    alternatives = planner.alternatives(plan, 0, 'dinner')

    options = alternatives['options']
    assert {o['id'] for o in options} == set(planner.eligible(plan['settings'], 'dinner'))
    # Monday's dinner is also Tuesday's lunch
    assert alternatives['slots'] == [[0, 'dinner'], [1, 'lunch']]
    assert [o['id'] for o in options if o['current']] == [current]
    assert next(o for o in options if o['current'])['total'] == plan['total']
    in_plan = {c['recipe_id'] for c in plan['cooks']} - {current}
    assert {o['id'] for o in options if o['in_plan']} == in_plan & {o['id'] for o in options}
    # Within the budget first
    within = [o['within_budget'] for o in options]
    assert within == sorted(within, reverse=True)


def test_choose_puts_recipe_in_both_leftover_meals(planner):
    plan = planner.generate({'meals': ['lunch', 'dinner'], 'leftovers': True}, seed=1)
    option = next(o for o in planner.alternatives(plan, 0, 'dinner')['options'] if not o['current'])

    chosen = planner.choose(plan, 0, 'dinner', option['id'])

    assert chosen['days'][0]['meals']['dinner']['recipe_id'] == option['id']
    assert chosen['days'][1]['meals']['lunch']['recipe_id'] == option['id']
    assert chosen['total'] == option['total']


def test_choose_rejects_recipe_for_another_meal(planner):
    plan = planner.generate({'meals': ['breakfast', 'dinner']}, seed=1)
    breakfast = plan['days'][0]['meals']['breakfast']['recipe_id']

    with pytest.raises(ValueError):
        planner.choose(plan, 0, 'dinner', breakfast)


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


def test_alternatives_and_choose_routes(client):
    client.post('/meals/api/plan', json={'meals': ['dinner'], 'leftovers': False})

    alternatives = client.get('/meals/api/alternatives?day=3&meal=dinner').get_json()
    option = next(o for o in alternatives['options'] if not o['current'])
    plan = client.post('/meals/api/choose', json={'day': 3, 'meal': 'dinner', 'recipe_id': option['id']}).get_json()

    assert plan['days'][3]['meals']['dinner']['recipe_id'] == option['id']
    assert client.get('/meals/api/plan').get_json()['days'][3]['meals']['dinner']['recipe_id'] == option['id']


def test_alternatives_for_missing_meal(client):
    client.post('/meals/api/plan', json={'meals': ['dinner']})

    response = client.get('/meals/api/alternatives?day=0&meal=breakfast')

    assert response.status_code == 400
    assert response.get_json()['error'] == 'Δεν υπάρχει γεύμα σε αυτή τη θέση.'


def test_choose_unknown_recipe(client):
    client.post('/meals/api/plan', json={'meals': ['dinner']})

    response = client.post('/meals/api/choose', json={'day': 0, 'meal': 'dinner', 'recipe_id': 'nope'})

    assert response.status_code == 400


def test_swap_without_plan(client):
    response = client.post('/meals/api/swap', json={'day': 0, 'meal': 'dinner'})

    assert response.status_code == 400
    assert response.get_json()['error'] == 'Δεν υπάρχει πλάνο.'


def test_unknown_recipe(client):
    assert client.get('/meals/api/recipe/nope').status_code == 404


# --- Own recipes ---

def test_parse_pasted_recipe(planner):
    draft = custom.parse("""Κοτόπουλο με philadelphia
4 μερίδες, 40 λεπτά
Υλικά
- 600 γρ. φιλέτο κοτόπουλο
- 1 κουτί philadelphia 200g
- 2 κ.σ. ελαιόλαδο
- αλάτι, πιπέρι
Εκτέλεση
1. Σοτάρουμε το κοτόπουλο.
2. Προσθέτουμε το τυρί.""", planner.ingredients)

    assert (draft['name'], draft['servings'], draft['time']) == ('Κοτόπουλο με philadelphia', 4, 40)
    assert [(l['ingredient'], l['amount']) for l in draft['lines']] == [
        ('chicken_breast', 600), (None, None), ('olive_oil', 30), (None, None)]
    # Searched in the stores by the title only, with the size as the quantity
    assert draft['lines'][1]['title'] == 'philadelphia'
    assert draft['lines'][1]['hint'] == {'unit': 'g', 'amount': 200}
    assert draft['lines'][3]['free']
    assert draft['steps'] == ['Σοτάρουμε το κοτόπουλο.', 'Προσθέτουμε το τυρί.']


NEW_RECIPE = {
    'name': 'Κοτόπουλο με philadelphia', 'meal': 'main', 'servings': 4, 'time': 40,
    'steps': ['Σοτάρουμε.', ' '],
    'lines': [
        {'text': '600 γρ. κοτόπουλο', 'ingredient': 'chicken_breast', 'amount': 600},
        {'text': '1 κουτί philadelphia', 'amount': 200, 'new': {
            'name': 'philadelphia', 'query': 'philadelphia', 'type': 'dairy',
            'product': {'store': 'ab', 'name': 'Philadelphia 300g', 'price': 3.0, 'size': 300, 'unit': 'g'}}},
        {'text': 'αλάτι, πιπέρι'},
    ],
}


def test_save_own_recipe_with_a_new_ingredient(tmp_path, provider):
    planner = Planner(DATA, str(tmp_path), provider)

    recipe = custom.save(str(tmp_path), planner, NEW_RECIPE)
    planner.reload()

    assert recipe['id'] == 'my_kotopoylo_me_philadelphia'
    assert recipe['ingredients'] == {'chicken_breast': 600, 'my_philadelphia': 200}
    assert recipe['display'] == ['600 γρ. κοτόπουλο', '1 κουτί philadelphia', 'αλάτι, πιπέρι']
    assert recipe['steps'] == ['Σοτάρουμε.']
    assert recipe['category'] == 'chicken'
    ingredient = planner.ingredients['my_philadelphia']
    assert (ingredient['name'], ingredient['unit'], ingredient['type'], ingredient['fallback_price']) == \
        ('Philadelphia', 'g', 'dairy', 10.0)
    assert ingredient['product'] == {'store': 'ab', 'name': 'Philadelphia 300g'}
    own = planner.recipes[recipe['id']]
    assert own['custom'] and not own['imported']
    assert planner.eligible(planner.clean_settings({'source': 'custom'}), 'dinner') == [recipe['id']]
    assert recipe['id'] not in planner.eligible(planner.clean_settings({'source': 'imported'}), 'dinner')

    # The same product in a second recipe reuses the ingredient
    second = custom.save(str(tmp_path), planner, {**NEW_RECIPE, 'name': 'Άλλη'})
    assert set(second['ingredients']) == {'chicken_breast', 'my_philadelphia'}

    # Editing keeps the id
    edited = custom.save(str(tmp_path), planner, {**NEW_RECIPE, 'id': recipe['id'], 'servings': 2})
    assert edited['id'] == recipe['id']
    assert [r['servings'] for r in custom.recipes(str(tmp_path))] == [2, 4]


@pytest.mark.parametrize('change, error', [
    ({'name': ' '}, 'Δώσε όνομα στη συνταγή.'),
    ({'lines': [{'text': 'αλάτι'}]}, 'Η συνταγή χρειάζεται τουλάχιστον ένα υλικό με ποσότητα.'),
    ({'lines': [{'text': 'κοτόπουλο', 'ingredient': 'chicken_breast'}]}, 'Βάλε ποσότητα για «κοτόπουλο».'),
    ({'lines': [{'text': 'x', 'ingredient': 'nope', 'amount': 1}]}, 'Άγνωστο υλικό: nope'),
    ({'id': 'my_nope'}, 'Η συνταγή δεν βρέθηκε.'),
])
def test_save_own_recipe_checks_the_form(tmp_path, provider, change, error):
    planner = Planner(DATA, str(tmp_path), provider)

    with pytest.raises(ValueError, match=error):
        custom.save(str(tmp_path), planner, {**NEW_RECIPE, **change})


@pytest.fixture
def own_client(client, tmp_path, monkeypatch):
    """The routes with own recipes in the temporary folder; the planner gets its recipes back afterwards."""
    planner = meal_planner.planner
    before = planner.recipes, planner.ingredients
    monkeypatch.setattr(meal_planner, 'STATE', str(tmp_path))
    monkeypatch.setattr(planner, 'state_dir', str(tmp_path))
    yield client
    planner.recipes, planner.ingredients = before


def test_own_recipe_routes(own_client):
    recipe = own_client.post('/meals/api/custom', json=NEW_RECIPE).get_json()

    assert [r['id'] for r in own_client.get('/meals/api/custom').get_json()] == [recipe['id']]
    meta = own_client.get('/meals/api/meta').get_json()
    assert meta['source_counts']['custom'] == 1
    assert 'Philadelphia' in [i['name'] for i in meta['ingredients']]

    # It can be put in the plan, and then not deleted
    own_client.post('/meals/api/plan', json={'meals': ['dinner'], 'leftovers': False})
    plan = own_client.post('/meals/api/choose', json={'day': 1, 'meal': 'dinner', 'recipe_id': recipe['id']}).get_json()
    item = next(i for a in plan['shopping'] for i in a['items'] if i['id'] == 'my_philadelphia')
    assert item['leftover'] > 0
    assert own_client.post(f'/meals/api/custom/{recipe["id"]}/delete').status_code == 400
    # Nor become a breakfast while it is a dinner
    response = own_client.post('/meals/api/custom', json={**NEW_RECIPE, 'id': recipe['id'], 'meal': 'breakfast'})
    assert response.status_code == 400

    own_client.post('/meals/api/plan', json={'meals': ['breakfast']})
    assert own_client.post(f'/meals/api/custom/{recipe["id"]}/delete').get_json() == {'ok': True}
    assert own_client.get('/meals/api/custom').get_json() == []
    assert recipe['id'] not in meal_planner.planner.recipes


def test_parse_route(own_client):
    draft = own_client.post('/meals/api/custom/parse', json={'text': 'Σαλάτα\nΥλικά\n2 ντομάτες'}).get_json()

    assert draft['name'] == 'Σαλάτα'
    assert draft['lines'][0]['ingredient'] == 'tomato'


def test_products_route(own_client):
    found = own_client.get('/meals/api/products?q=φέτα&store=ab').get_json()

    assert {p['store'] for p in found['products']} == {'ab'}
    assert found['type'] == 'dairy'
    assert own_client.get('/meals/api/products?q=').status_code == 400
