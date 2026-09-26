import pytest

from supermarket_scraper import filter_relevant, is_named_after, relevance

# Product names below are real search results from the three stores


def _product(name, brand='', category=''):
    return {'name': name, 'brand': brand, 'category': category}


@pytest.mark.parametrize('search, name, brand', [
    ('φέτα', 'Τυρί Φέτα ΠΟΠ Παραδοσιακή σε Άλμη 400g', 'ΑΒ'),
    ('φέτα', 'Βαρελίσια Φέτα ΣΥΝΕΤΑΙΡΙΣΜΟΣ ΚΑΛΑΒΡΥΤΩΝ ΠΟΠ', ''),
    ('ΦΕΤΑ', 'Ήπειρος Φέτα ΠΟΠ Σε Άλμη 400gr', 'Ήπειρος'),
    ('γάλα', 'ΜΑΡΑΤΑ Γάλα Υψηλής Παστερίωσης Πλήρες 1lt', 'ΜΑΡΑΤΑ'),
    ('γαλα', 'Όλυμπος Γάλα Αγελάδος Χωρίς Λακτόζη Freelact 1,5%1lt', ''),
    # Plural and singular forms
    ('μπανάνες', 'Μπανάνες CHIQUITA Εισαγωγής', ''),
    ('μπανάνα', 'Μπανάνες Dole Εισαγωγής Τιμή Κιλού', ''),
    ('μπανάνες', 'Smoothie Φρούτων Bio Μήλο Φράουλα Μπανάνα 100g', ''),
    ('χαρτί υγείας', 'Kleenex Capitonne Χαρτί Υγείας 12άρι 0,867kg', 'Kleenex'),
    # Words in any order
    ('υγείας χαρτί', 'ΓΛΑΡΟΣ Χαρτί Υγείας 3 Φύλλων 10τεμ 1300g', 'ΓΛΑΡΟΣ'),
    # The brand counts even when it is not in the name
    ('ariel', 'Υγρό Πλυντηρίου Ρούχων Color 60 Μεζούρες', 'ARIEL'),
    ('lenor', 'Lenor Μαλακτικό Ρούχων Sensitive 59μεζ 1,20lt', 'Lenor'),
    # Latin letters mixed into Greek words and vice versa
    ('κάψουλες', 'Kάψουλες Πλυντηρίου Ρούχων Allin1 Pods Extra Clean 50 Τεμάχια', ''),
    ('ariel', 'Αriel Απορρυπαντικό Πλυντηρίου Ρούχων Υγρό Alpine 30μεζ', ''),
    # Search words written in the other alphabet
    ('pringles πάπρικα', 'PRINGLES Σνακ Paprika 165g', 'PRINGLES'),
    ('pringles paprika', 'Pringles Πάπρικα 165gr', 'Pringles'),
    # The product is named after a search word, the other words come after "για"
    ('DETTOL Απολυμαντικο Ρούχων', 'Dettol Απολυμαντικό Για Τα Ρούχα 2,5lt', 'Dettol'),
    ('απολυμαντικό ρούχων', 'Dettol Απολυμαντικό Για Τα Ρούχα 2,5lt', 'Dettol'),
])
def test_relevant_product(search, name, brand):
    assert relevance(search, _product(name, brand)) == 2


@pytest.mark.parametrize('search, name', [
    # The search word only describes an ingredient or flavour
    ('φέτα', 'Τυρόπιτα Κοζανίτικη ALFA Κιχί με Φέτα ΠΟΠ & Μυζήθρα 850g'),
    ('φέτα', 'Ήπειρος Αλειφωτή Με Φέτα 200gr'),
    ('μπανάνες', 'Corny Μπάρα Με Σοκολάτα & Μπανάνα 6x25gr'),
    ('γάλα', 'Knorr Πουρές Με Γάλα 291gr'),
    ('μπανάνα', 'ΜΕΒΓΑΛ Κεφίρ με γεύση Μπανάνα 330ml'),
])
def test_product_mentioning_search_as_ingredient(search, name):
    assert relevance(search, _product(name)) == 1


def test_product_mentioning_search_as_ingredient_after_brand():
    # Only the brand is before the descriptor
    assert relevance('knorr γάλα', _product('Knorr Πουρές Με Γάλα 291gr', 'Knorr')) == 1


@pytest.mark.parametrize('search, name', [
    # Another word that starts with the search word
    ('φέτα', 'Μορταδέλα Φέτες 200g'),
    ('γάλα', 'My Koyzina Κρέμα Γάλακτος 12% Λιπαρά 200ml'),
    ('γάλα', 'Filipinos Μπισκότα Mε Σοκολάτα Γάλακτος 118gr'),
    ('γάλα', 'Αντηλιακό Γαλάκτωμα Sensitive SPF50+ 200ml'),
    ('γάλα', 'Galaxy Σοκολάτα Smooth Milk 100g'),
    # The search word inside another word
    ('γάλα', 'Chef Basics Κλιπ Σακούλας Πολύχρωμα Μεγάλα (Συσκευασία 5 Τεμ.)'),
    # Only some of the search words
    ('ariel pods', 'Ariel Απορρυπαντικό Πλυντηρίου Ρούχων Σκόνη Alpine 42Μεζ'),
    ('χαρτί υγείας', 'ZEWA Pure Υγρομάντιλα Τουαλέτας 42τεμ'),
    ('μπανάνες', 'Χουρμάδες Εισαγωγής 250gr'),
])
def test_irrelevant_product(search, name):
    assert relevance(search, _product(name)) == 0


def test_filter_relevant_prefers_products_named_after_search():
    results = {
        'ab': [_product('Τυρί Φέτα ΠΟΠ 400g'), _product('Μορταδέλα Φέτες 200g')],
        'sklavenitis': [_product('Χορτόπιτα ΜΑΡΑΤΑ με Μυζήθρα & Φέτα 850g'), _product('Φέτα Ηπείρου ΚΑΡΑΛΗΣ ΠΟΠ 400g')],
        # Only pies with feta: shows nothing rather than pies next to feta from the other stores
        'mymarket': [_product('Τυρόπιτα με Φέτα 850g')],
    }

    filtered = filter_relevant('φέτα', results)

    assert {key: [p['name'] for p in products] for key, products in filtered.items()} == {
        'ab': ['Τυρί Φέτα ΠΟΠ 400g'],
        'sklavenitis': ['Φέτα Ηπείρου ΚΑΡΑΛΗΣ ΠΟΠ 400g'],
        'mymarket': [],
    }


def test_filter_relevant_falls_back_to_products_mentioning_search():
    # No store sells the product itself, so products with it as an ingredient are shown
    results = {
        'ab': [_product('Κριτσίνια με Σουσάμι 200g'), _product('Φρυγανιές 250g')],
        'mymarket': [_product('Μπάρα Δημητριακών με Σουσάμι 25g')],
    }

    filtered = filter_relevant('σουσάμι', results)

    assert [p['name'] for p in filtered['ab']] == ['Κριτσίνια με Σουσάμι 200g']
    assert [p['name'] for p in filtered['mymarket']] == ['Μπάρα Δημητριακών με Σουσάμι 25g']


def test_filter_relevant_nothing_matches():
    results = {'ab': [_product('Φρυγανιές 250g')], 'mymarket': []}

    assert filter_relevant('φέτα', results) == {'ab': [], 'mymarket': []}


@pytest.mark.parametrize('search, name, brand, expected', [
    ('φέτα', 'Φέτα Ηπείρου ΚΑΡΑΛΗΣ ΠΟΠ 400g', 'ΚΑΡΑΛΗΣ', True),
    # Brand words at the start of the name are skipped
    ('φέτα', 'ΚΑΡΑΛΗΣ Φέτα ΠΟΠ 200g', 'ΚΑΡΑΛΗΣ', True),
    ('μπανάνες', 'Μπανάνα Chiquita Εισαγωγής Τιμή Κιλού', 'Chiquita', True),
    ('χαρτί υγείας', 'Χαρτί Υγείας 2 Φύλλα 24 Ρολά 1.68kg', '', True),
    ('φέτα', 'Τυροπιτάκια Σφολιάτας Μυζήθρα Φέτα 1kg', 'ΑΒ ΕΠΙΛΟΓΗ', False),
    ('γάλα', 'ΔΕΛΤΑ Καθημερινά Φρέσκο Γάλα Πλήρες 1lt', 'ΔΕΛΤΑ', False),
    ('γάλα', 'ΔΕΛΤΑ', 'ΔΕΛΤΑ', False),
])
def test_is_named_after(search, name, brand, expected):
    assert is_named_after(search, _product(name, brand)) is expected


def test_filter_relevant_drops_products_from_other_categories():
    # Real AB results for "φέτα": frozen pies and fish also have the word before any "με"
    results = {'ab': [
        _product('Τυρί Φέτα ΠΟΠ Καλάβρυτα Χελμός 400g', category='Φέτα'),
        _product('Βαρελίσια Φέτα ΠΟΠ 400g', category='Φέτα'),
        _product('Τυροπιτάκια Σφολιάτας Μυζήθρα Φέτα 1kg', category='Κατεψυγμένες Πίτες & Πιτάκια'),
        _product('Σολομός Φέτα 250g', category='Φρέσκα ψάρια & θαλασσινά'),
    ]}

    filtered = filter_relevant('φέτα', results)

    assert [p['name'] for p in filtered['ab']] == ['Τυρί Φέτα ΠΟΠ Καλάβρυτα Χελμός 400g', 'Βαρελίσια Φέτα ΠΟΠ 400g']


def test_filter_relevant_keeps_categories_named_after_search():
    # No product in the fresh milk category starts with "Γάλα", but the category name does
    results = {'sklavenitis': [
        _product('ΔΕΛΤΑ Καθημερινά Φρέσκο Γάλα Πλήρες 1lt', 'ΔΕΛΤΑ', 'Γάλατα Αγελάδος φρέσκα'),
        _product('ΜΑΡΑΤΑ Γάλα Υψηλής Παστερίωσης Πλήρες 1lt', 'ΜΑΡΑΤΑ', 'Γάλατα Αγελάδος υψηλής παστερίωσης'),
        _product('PALMOLIVE Naturals Αφρόλουτρο Γάλα & Μέλι 650ml', 'PALMOLIVE', 'Αφρόλουτρα, Ντους & Άλατα μπάνιου'),
    ]}

    filtered = filter_relevant('γάλα', results)

    assert [p['name'] for p in filtered['sklavenitis']] == [
        'ΔΕΛΤΑ Καθημερινά Φρέσκο Γάλα Πλήρες 1lt',
        'ΜΑΡΑΤΑ Γάλα Υψηλής Παστερίωσης Πλήρες 1lt',
    ]


def test_filter_relevant_compares_categories_per_store():
    results = {
        'ab': [_product('Μπανάνες Dole Cavendish', category='Μπανάνες')],
        # Named after the search in no store category: nothing to compare, all are kept
        'mymarket': [
            _product('Παιδικό Γιαούρτι Μπανάνα 2x115g', category='Παιδικά Γιαούρτια'),
            _product('Φρουτοποτό Σταφύλι Μπανάνα 1lt', category='Χυμοί'),
        ],
    }

    filtered = filter_relevant('μπανάνες', results)

    assert len(filtered['ab']) == 1
    assert len(filtered['mymarket']) == 2


def test_filter_relevant_without_categories():
    results = {'ab': [_product('Kάψουλες Πλυντηρίου Ρούχων Allin1 Pods 60 Τεμάχια', 'ARIEL')]}

    assert filter_relevant('ariel pods', results) == results


def test_filter_relevant_ignores_brand_in_category_names():
    # Real Sklavenitis results for "DETTOL Απολυμαντικο Ρούχων": the 2,5lt product is not named
    # after the search, but its category is, without the brand
    results = {'sklavenitis': [
        _product('DETTOL Απολυμαντικό Καθαριστικό Πλυντηρίου Ρούχων Λεμόνι 250ml', 'DETTOL', 'Αποσκληρυντικά νερού'),
        _product('DETTOL Αντιβακτηριδιακό Απολυμαντικό Υγρό Ρούχων 2,5lt', 'DETTOL', 'Απολυμαντικά ρούχων'),
    ]}

    filtered = filter_relevant('DETTOL Απολυμαντικο Ρούχων', results)

    assert filtered == results


def test_filter_relevant_keeps_products_named_after_search_with_descriptor():
    results = {
        'ab': [_product('Απολυμαντικό Ρούχων 2,5lt', 'DETTOL')],
        'mymarket': [_product('Dettol Απολυμαντικό Για Τα Ρούχα 2,5lt', 'Dettol')],
    }

    assert filter_relevant('DETTOL Απολυμαντικο Ρούχων', results) == results
