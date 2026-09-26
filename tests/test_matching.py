import pytest

from matching import (
    MAX_GROUPS,
    group_products,
    name_similarity,
    name_words,
    product_quantity,
    same_brand,
    same_size,
    variant_words,
)

# Product names below are real search results from the three stores


def _product(name, brand='', price=1.0, unit_price=None, size=''):
    return {
        'name': name,
        'brand': brand,
        'price': price,
        'size': size,
        'url': f'https://example.com/{name}',
        'unit_price_calc': {'value': unit_price if unit_price is not None else price, 'unit': '€/L'},
    }


# Real results for "DETTOL Απολυμαντικο Ρούχων"
DETTOL = {
    'ab': [
        _product('Απολυμαντικό Ρούχων 1,5lt', 'DETTOL', 5.99, 3.99, '1,5 λιτ'),
        _product('Απολυμαντικό Ρούχων 2,5lt', 'DETTOL', 8.37, 3.35, '2,5 λιτ'),
        _product('Απολυμαντικό Ρούχων Χωρίς Άρωμα 1,5lt', 'DETTOL', 5.99, 3.99, '1,5 λιτ'),
        _product('Υγρό Απολυμαντικό Ρούχων Λεβάντα Αντιβακτηριδιακό 1.5lt', 'DETTOL', 5.99, 3.99, '1,5 λιτ'),
    ],
    'sklavenitis': [
        _product('DETTOL Απολυμαντικό Καθαριστικό Πλυντηρίου Ρούχων Λεμόνι 250ml', 'DETTOL', 4.96, 19.84),
        _product('DETTOL Αντιβακτηριδιακό Απολυμαντικό Υγρό Ρούχων 2,5lt', 'DETTOL', 7.59, 3.04),
        _product('DETTOL Αντιβακτηριδιακό Απολυμαντικό Υγρό Ρούχων 1,5lt', 'DETTOL', 5.55, 3.70),
    ],
    'mymarket': [
        _product('Dettol Απολυμαντικό Για Τα Ρούχα 2,5lt', 'Dettol', 7.88, 3.15),
        _product('Dettol Απολυμαντικό Για Τα Ρούχα 1,5lt', 'Dettol', 5.50, 3.67),
        _product('Dettol Απολυμαντικό Για τα Ρούχα Λεβάντα 1,5lt', 'Dettol', 5.50, 3.67),
        _product('Dettol Απολυμαντικό Για Τα Ρούχα Χωρίς Άρωμα 1,5lt', 'Dettol', 5.50, 3.67),
    ],
}


def _names(results, group):
    return {store: results[store][index]['name'] for store, index in group['products'].items()}


def test_name_words_leave_out_brand_size_and_filler_words():
    product = _product('Dettol Απολυμαντικό Για Τα Ρούχα 2,5lt', 'Dettol')
    assert name_words(product) == ['apolimantik', 'ruh']


def test_name_words_shorten_variant_words():
    assert name_words(_product('Καφές Espresso Decaf 250g')) == name_words(_product('Καφές Espresso Decafeine 250gr'))


@pytest.mark.parametrize('greek, latin', [
    ('PRINGLES Σνακ Πάπρικα 165g', 'PRINGLES Snack Paprika 165g'),
    ('Μπανάνες Chiquita', 'Bananas Chiquita'),
])
def test_name_words_same_in_both_alphabets(greek, latin):
    assert name_similarity(name_words(_product(greek)), name_words(_product(latin))) == 1.0


def test_brand_in_both_alphabets():
    assert same_brand(_product('Γάλα 1lt', 'ΔΕΛΤΑ'), _product('Γάλα 1lt', 'Delta'))


@pytest.mark.parametrize('a, b, expected', [
    ('Απολυμαντικό Ρούχων 2,5lt', 'Dettol Απολυμαντικό Για Τα Ρούχα 2,5lt', 1.0),
    ('Απολυμαντικό Ρούχων 2,5lt', 'Αντιβακτηριδιακό Απολυμαντικό Υγρό Ρούχων 2,5lt', 4 / 6),
    ('Απολυμαντικό Ρούχων', 'Φέτα ΠΟΠ', 0.0),
])
def test_name_similarity(a, b, expected):
    assert name_similarity(name_words(_product(a, 'Dettol')), name_words(_product(b, 'Dettol'))) == pytest.approx(expected)


@pytest.mark.parametrize('name, size, expected', [
    ('Απολυμαντικό Ρούχων 2,5lt', '', (2.5, 'L')),
    # The AB size field is used when the name has no size
    ('Γάλα Υψηλής Παστερίωσης', '1,5 λιτ', (1.5, 'L')),
    ('Kάψουλες Πλυντηρίου Allin1 Pods Alpine 60 Τεμάχια', '', (60, 'unit')),
    ('Μπανάνες Εισαγωγής Τιμή Κιλού', '', None),
])
def test_product_quantity(name, size, expected):
    assert product_quantity(_product(name, size=size)) == expected


@pytest.mark.parametrize('a, b, expected', [
    ((2.5, 'L'), (2.5, 'L'), True),
    ((1.5, 'L'), (1.5000001, 'L'), True),
    ((1.5, 'L'), (2.5, 'L'), False),
    ((1.0, 'L'), (1.0, 'kg'), False),
    # Loose products (no size) only match each other
    (None, None, True),
    ((0.4, 'kg'), None, False),
])
def test_same_size(a, b, expected):
    assert same_size(a, b) is expected


@pytest.mark.parametrize('a, b, expected', [
    (_product('Γάλα 1lt', 'ΔΕΛΤΑ'), _product('ΔΕΛΤΑ Γάλα 1lt', 'Δέλτα'), True),
    (_product('Γάλα 1lt', 'ΔΕΛΤΑ'), _product('Γάλα 1lt', 'ΟΛΥΜΠΟΣ'), False),
    # A missing brand must be in the name
    (_product('Φέτα ΠΟΠ 400g', 'ΔΩΡΙΚΗ'), _product('Χώτος Φέτα ΠΟΠ Τιμή Κιλού'), False),
    (_product('Φέτα ΠΟΠ 400g', 'ΔΩΔΩΝΗ'), _product('Δωδώνη Φέτα ΠΟΠ 400g'), True),
    (_product('Μπανάνες Εισαγωγής'), _product('Μπανάνες Εισαγωγής'), True),
])
def test_same_brand(a, b, expected):
    assert same_brand(a, b) is expected


def test_variant_words_found_in_two_stores():
    variants = variant_words(DETTOL)

    # AB and My Market both sell a lavender and an unscented variant of the same size
    assert {'levant', 'arom'} <= variants
    # Only AB names one variant "Υγρό Αντιβακτηριδιακό"
    assert 'antivaktiridiak' not in variants


def test_group_products_finds_same_product_in_every_store():
    groups = group_products(DETTOL)

    # The most likely choice is the one sold in every store and cheapest per litre
    assert _names(DETTOL, groups[0]) == {
        'ab': 'Απολυμαντικό Ρούχων 2,5lt',
        'sklavenitis': 'DETTOL Αντιβακτηριδιακό Απολυμαντικό Υγρό Ρούχων 2,5lt',
        'mymarket': 'Dettol Απολυμαντικό Για Τα Ρούχα 2,5lt',
    }
    assert groups[0]['label'] == 'DETTOL Απολυμαντικό Ρούχων 2,5lt'


def test_group_products_finds_same_product_when_stores_name_it_differently():
    # Real results for "dettol": the stores also use "Αντιβακτηριδιακό Υγρό" in their own names
    # of different variants, so it would count as a variant word
    results = {store: list(products) for store, products in DETTOL.items()}
    results['ab'] += [
        _product('Κρεμοσάπουνο Αντιβακτηριδιακό Lavender Ανταλλακτικό 500ml', 'DETTOL', 2.1),
        _product('Κρεμοσάπουνο Honey Vanilla Ανταλλακτικό 500ml', 'DETTOL', 2.1),
    ]
    results['mymarket'] += [
        _product('Dettol Ενυδατικο Κρεμoσάπουνο Αντλία 250ml', 'Dettol', 2.1),
        _product('Dettol Αντιβακτηριδιακό Υγρό Κρεμοσάπουνο Με Αντλία Sensitive 250ml', 'Dettol', 2.1),
    ]

    groups = [_names(results, group) for group in group_products(results)]

    # Every store sells a single 2,5lt product, so their names tell how each store names it
    assert 'antivaktiridiak' not in variant_words(results)
    assert groups[0]['sklavenitis'] == 'DETTOL Αντιβακτηριδιακό Απολυμαντικό Υγρό Ρούχων 2,5lt'
    assert {
        'ab': 'Απολυμαντικό Ρούχων 1,5lt',
        'sklavenitis': 'DETTOL Αντιβακτηριδιακό Απολυμαντικό Υγρό Ρούχων 1,5lt',
        'mymarket': 'Dettol Απολυμαντικό Για Τα Ρούχα 1,5lt',
    } in groups


def test_variant_words_only_from_similar_names():
    # A liquid soap and a cleaner of the same size are not variants of one product
    results = {
        'ab': [_product('Κρεμοσάπουνο Λεβάντα 250ml', 'DETTOL'), _product('Καθαριστικό Πλυντηρίου Λεμόνι 250ml', 'DETTOL')],
        'mymarket': [_product('Dettol Κρεμοσάπουνο 250ml', 'Dettol'), _product('Dettol Καθαριστικό Πλυντηρίου 250ml', 'Dettol')],
    }

    assert 'kremosapun' not in variant_words(results)


def test_group_products_matches_flavour_written_in_other_alphabet():
    # Real results for "pringles": Sklavenitis writes "Paprika", AB and My Market "Πάπρικα"
    results = {
        'ab': [_product('Τσιπς Sour Cream & Onion 165g', 'PRINGLES', 2.29),
               _product('Τσιπς Πάπρικα 165g', 'PRINGLES', 2.50)],
        'sklavenitis': [_product('PRINGLES Σνακ Sour Cream & Onion 165g', 'PRINGLES', 2.29),
                        _product('PRINGLES Σνακ Paprika 165g', 'PRINGLES', 2.29)],
        'mymarket': [_product('Pringles Sour Cream & Onion 165gr', 'Pringles', 2.54),
                     _product('Pringles Πάπρικα 165gr', 'Pringles', 2.54)],
    }

    groups = [group['products'] for group in group_products(results)]

    assert groups == [{'ab': 0, 'sklavenitis': 0, 'mymarket': 0}, {'ab': 1, 'sklavenitis': 1, 'mymarket': 1}]


def test_group_products_keeps_variants_apart():
    groups = [_names(DETTOL, group) for group in group_products(DETTOL)]

    assert {
        'ab': 'Απολυμαντικό Ρούχων 1,5lt',
        'sklavenitis': 'DETTOL Αντιβακτηριδιακό Απολυμαντικό Υγρό Ρούχων 1,5lt',
        'mymarket': 'Dettol Απολυμαντικό Για Τα Ρούχα 1,5lt',
    } in groups
    assert {
        'ab': 'Υγρό Απολυμαντικό Ρούχων Λεβάντα Αντιβακτηριδιακό 1.5lt',
        'mymarket': 'Dettol Απολυμαντικό Για τα Ρούχα Λεβάντα 1,5lt',
    } in groups
    assert {
        'ab': 'Απολυμαντικό Ρούχων Χωρίς Άρωμα 1,5lt',
        'mymarket': 'Dettol Απολυμαντικό Για Τα Ρούχα Χωρίς Άρωμα 1,5lt',
    } in groups
    # Products sold in one store only are choices too
    assert {'sklavenitis': 'DETTOL Απολυμαντικό Καθαριστικό Πλυντηρίου Ρούχων Λεμόνι 250ml'} in groups


def test_group_products_puts_every_product_in_one_group():
    groups = group_products(DETTOL)

    chosen = [(store, index) for group in groups for store, index in group['products'].items()]
    assert len(chosen) == len(set(chosen)) == sum(map(len, DETTOL.values()))


def test_group_products_always_different_variants():
    # "Χωρίς λακτόζη" is a different product even if only one store has both
    results = {
        'ab': [_product('Τυρί Φέτα ΠΟΠ Παραδοσιακή σε Άλμη 400g', 'ΗΠΕΙΡΟΣ')],
        'sklavenitis': [_product('Φέτα ΗΠΕΙΡΟΣ ΠΟΠ σε Άλμη Χωρίς λακτόζη 400g', 'ΗΠΕΙΡΟΣ')],
    }

    assert len(group_products(results)) == 2


def test_group_products_needs_same_size():
    results = {
        'ab': [_product('Kάψουλες Πλυντηρίου Ρούχων Allin1 Pods Alpine 33 Τεμάχια', 'ARIEL')],
        'sklavenitis': [_product('ARIEL Allin1 Pods Απορρυπαντικό Πλυντηρίου Ρούχων Alpine 80 κάψουλες', 'ARIEL')],
    }

    assert len(group_products(results)) == 2


def test_group_products_joins_group_only_if_it_matches_every_product():
    results = {
        'ab': [_product('Γάλα Φρέσκο Επιλεγμένο 1lt', 'ΔΕΛΤΑ')],
        'sklavenitis': [_product('ΔΕΛΤΑ Γάλα Φρέσκο Επιλεγμένο Αγελάδος Ελληνικό 1lt', 'ΔΕΛΤΑ')],
        # Similar enough to the AB name, but not to the Sklavenitis one
        'mymarket': [_product('Δέλτα Γάλα Επιλεγμένο Βιταμίνες Ασβέστιο 1lt', 'Δέλτα')],
    }

    groups = group_products(results)

    assert [sorted(group['products']) for group in groups] == [['ab', 'sklavenitis'], ['mymarket']]


def test_group_products_most_stores_first_then_cheapest():
    results = {
        'ab': [_product('Γάλα Φρέσκο 1lt', 'ΑΛΦΑ', 1.1), _product('Γάλα Φρέσκο 1lt', 'ΒΗΤΑ', 1.5)],
        'mymarket': [_product('Γάλα Φρέσκο 1lt', 'ΒΗΤΑ', 1.4), _product('Γάλα Φρέσκο 1lt', 'ΓΑΜΜΑ', 0.9)],
    }

    groups = group_products(results)

    assert [group['products'] for group in groups] == [{'ab': 1, 'mymarket': 0}, {'mymarket': 1}, {'ab': 0}]


def test_group_products_limits_choices():
    results = {'ab': [_product(f'Προϊόν {chr(0x3b1 + i)} 1lt', price=i + 1) for i in range(MAX_GROUPS + 5)]}

    assert len(group_products(results)) == MAX_GROUPS


def test_group_products_nothing_found():
    assert group_products({'ab': [], 'sklavenitis': [], 'mymarket': []}) == []
