import pytest

from supermarket_scraper import (
    calculate_unit_price,
    extract_size,
    parse_price,
    parse_unit_price_label,
    sort_by_value,
    unit_price,
)


@pytest.mark.parametrize('text, expected', [
    ('2,49 €', 2.49),
    ('€2.49', 2.49),
    ('2.49€', 2.49),
    ('1.234,56 €', 1234.56),
    ('1.234.567', 1234567.0),
    ('12 €', 12.0),
    ('Τιμή: 0,99€', 0.99),
    ('3,20.', 3.2),
    ('', None),
    ('-', None),
    ('Μη διαθέσιμο', None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize('price, size, value, unit', [
    # Volume
    (2.0, '500ml', 4.0, '€/L'),
    (2.0, '500 ML', 4.0, '€/L'),
    (3.0, '1,5L', 2.0, '€/L'),
    (3.0, '1.5 lt', 2.0, '€/L'),
    (3.0, '1,5 λτ', 2.0, '€/L'),
    (3.0, '1,5 λιτ', 2.0, '€/L'),
    # Weight
    (1.5, '250 γρ', 6.0, '€/kg'),
    (1.0, '100 GR', 10.0, '€/kg'),
    (1.0, '400g', 2.5, '€/kg'),
    (4.0, '2kg', 2.0, '€/kg'),
    (2.0, '1 κιλό', 2.0, '€/kg'),
    # Pieces
    (6.0, '20 τεμ', 0.3, '€/unit'),
    (6.0, '20 τμχ.', 0.3, '€/unit'),
    (6.0, '12 pcs', 0.5, '€/unit'),
    (17.98, 'Allin1 Pods Alpine 80 κάψουλες', 0.22, '€/unit'),
    # Washes
    (5.49, '87 μεζ', 0.06, '€/wash'),
    (4.59, 'Συμπυκνωμένο Μαλακτικό 59 Μεζούρες', 0.08, '€/wash'),
    (3.95, 'Μαλακτικό Ρούχων 59 πλύσεις', 0.07, '€/wash'),
    # Multipacks
    (3.96, '6x330ml', 2.0, '€/L'),
    (3.96, '6 × 330 ml', 2.0, '€/L'),
    # Size embedded in a product name
    (5.0, 'Lenor Joy Gold 1.5 lt', 3.33, '€/L'),
])
def test_calculate_unit_price(price, size, value, unit):
    assert calculate_unit_price(price, size) == {'value': value, 'unit': unit}


@pytest.mark.parametrize('size', ['', None, 'Lenor', '3 lavages', '0ml'])
def test_calculate_unit_price_falls_back_to_full_price(size):
    assert calculate_unit_price(2.5, size) == {'value': 2.5, 'unit': '€/unit'}


def _unit_price_product(name, size='', store_unit_price=None):
    return {'name': name, 'price': 2.54, 'size': size, 'unit_price_calc': store_unit_price}


@pytest.mark.parametrize('product, expected', [
    # Calculated from the size, not taken from the store label, which was the price before a discount
    (_unit_price_product('Pringles Πάπρικα 165gr', '165gr', {'value': 20.48, 'unit': '€/kg'}),
     {'value': 15.39, 'unit': '€/kg'}),
    # AB keeps the size in a separate field
    (_unit_price_product('Γάλα Υψηλής Παστερίωσης', '1 λιτ'), {'value': 2.54, 'unit': '€/L'}),
    # No size: the store's unit price, e.g. for loose fruit
    (_unit_price_product('Μπανάνες Τιμή Κιλού', '', {'value': 1.88, 'unit': '€/kg'}), {'value': 1.88, 'unit': '€/kg'}),
    # No size and no store unit price
    (_unit_price_product('Ψησταριά'), {'value': 2.54, 'unit': '€/unit'}),
])
def test_unit_price(product, expected):
    assert unit_price(product) == expected


@pytest.mark.parametrize('label, expected', [
    # AB
    ('10,98 €/ κιλ', {'value': 10.98, 'unit': '€/kg'}),
    ('8,78 €/ λιτ', {'value': 8.78, 'unit': '€/L'}),
    ('0,06 €/ μεζ', {'value': 0.06, 'unit': '€/wash'}),
    ('0,3 €/ τεμ', {'value': 0.3, 'unit': '€/unit'}),
    # Sklavenitis
    ('12,63 € /κιλό', {'value': 12.63, 'unit': '€/kg'}),
    ('1,00 € /λίτρο', {'value': 1.0, 'unit': '€/L'}),
    ('0,07 € /πλύση', {'value': 0.07, 'unit': '€/wash'}),
    ('1,00 € /τεμ.', {'value': 1.0, 'unit': '€/unit'}),
    # My Market
    ('13,95€ Τιμή κιλού', {'value': 13.95, 'unit': '€/kg'}),
    ('3,00€ Αρχ. τιμή κιλού', {'value': 3.0, 'unit': '€/kg'}),
    ('21,59€ Τιμή λίτρου', {'value': 21.59, 'unit': '€/L'}),
    ('0,07€ Τιμή μεζούρας', {'value': 0.07, 'unit': '€/wash'}),
    ('0,76€ Τιμή τεμαχίου', {'value': 0.76, 'unit': '€/unit'}),
    # No unit or no price
    ('57,63€ Τελ. τιμή', None),
    ('6,15 € /συσκ.', None),
    ('Τιμή κιλού', None),
    ('', None),
    (None, None),
])
def test_parse_unit_price_label(label, expected):
    assert parse_unit_price_label(label) == expected


@pytest.mark.parametrize('name, size', [
    ('Μοναστήρι Αγνοτύρι 300gr', '300gr'),
    ('NOYNOY Συμπυκνωμένο Γάλα 4x170gr', '4x170gr'),
    ('ΜΑΡΑΤΑ Φρέσκο Γάλα Πλήρες 3,5% 1lt', '1lt'),
    ('Lenor Μαλακτικό Joy Gold 126μεζ 2646ml', '126μεζ'),
    ('Μπανάνες BAJELLA Εισαγωγής', ''),
    ('', ''),
])
def test_extract_size(name, size):
    assert extract_size(name) == size


def _product(value, unit):
    return {'unit_price_calc': {'value': value, 'unit': unit}}


def test_sort_by_value_orders_by_unit_price():
    products = [_product(5, '€/L'), _product(3, '€/L'), _product(4, '€/L')]
    assert [p['unit_price_calc']['value'] for p in sort_by_value(products)] == [3, 4, 5]


def test_sort_by_value_puts_most_common_unit_first():
    # A cheap €/unit fallback must not beat comparable €/L products
    products = [_product(0.5, '€/unit'), _product(5, '€/L'), _product(3, '€/L')]
    assert [p['unit_price_calc'] for p in sort_by_value(products)] == [
        {'value': 3, 'unit': '€/L'},
        {'value': 5, 'unit': '€/L'},
        {'value': 0.5, 'unit': '€/unit'},
    ]


def test_sort_by_value_does_not_interleave_units_with_equal_counts():
    products = [_product(2, '€/kg'), _product(1, '€/L'), _product(3, '€/kg'), _product(4, '€/L')]
    units = [p['unit_price_calc']['unit'] for p in sort_by_value(products)]
    assert units in (['€/L', '€/L', '€/kg', '€/kg'], ['€/kg', '€/kg', '€/L', '€/L'])


def test_sort_by_value_empty():
    assert sort_by_value([]) == []
