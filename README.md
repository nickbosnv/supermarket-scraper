# Supermarket Price Finder 🛒

Flask web application for comparing product prices across 3 Greek supermarket chains: AB Vasilopoulos, Sklavenitis, and My Market. Every search is done live on the store websites: the app reads all result pages, keeps only the products that match the search, finds the same product in every store, and ranks the supermarkets from cheapest to most expensive. The user can pick another of the likely products, change the product of one store, and keep products as favourites.

It also has a weekly meal planner (`/meals/`): breakfast, lunch and dinner for a week within a budget, with a shopping list priced in the same stores.

## Architecture Overview

```
Flask Server (app.py)
  ↓
Search Endpoint (/search)
  ↓
SupermarketScraper (supermarket_scraper.py) - stores queried in parallel
  ├─→ search_ab() - Queries the ab.gr GraphQL API
  ├─→ search_sklavenitis() - Scrapes the sklavenitis.gr search pages
  └─→ search_mymarket() - Scrapes the mymarket.gr search pages
  (every result page of each store, several pages at a time)
  ↓
filter_relevant() - Keeps the products that match the search
  ↓
Unit Prices (calculated from price and size, else from the store), sorted by value
  ↓
group_products() (matching.py) - The same product in each store, most likely first
  ↓
Return JSON Response
  ↓
Frontend (HTML/CSS/JS) - Supermarkets ranked cheapest first, product choices, favourites
```

## Installation on Raspberry Pi

### With Docker
```bash
git clone <repo-url> ~/supermarket-scraper
cd ~/supermarket-scraper
mkdir -p data
docker compose up -d --build
```

The app runs at `http://<your-rasp-ip>:5000` and restarts with the Pi. Favourites are saved in `data/favourites.json`,
the meal planner's prices, current plan and imported recipes in `data/meal_planner/`.
To update: `git pull && docker compose up -d --build`.

### Without Docker

### 1. SSH into your Raspberry Pi
```bash
ssh pi@raspberrypi.local
# or: ssh pi@<your-rasp-ip>
```

### 2. Clone or copy the project
```bash
mkdir -p ~/projects/price-finder
cd ~/projects/price-finder
```

Copy all files from this directory to the Raspberry Pi

### 3. Install dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Run the Flask app
```bash
python3 app.py
```

The app will start at `http://0.0.0.0:5000`

Optional environment variables:
- `PORT` - port to listen on (default `5000`)
- `FAVOURITES_FILE` - where the favourites are saved (default `favourites.json` next to `app.py`)
- `MEAL_PLANNER_DATA` - folder for the meal planner's price cache, current plan and imported recipes (default `meal_planner/data/`)
- `MEAL_PLANNER_PRICE_TTL_H` - hours the meal planner keeps a price before searching again (default `24`)
- `FLASK_DEBUG=1` - enable debug mode. **Only for local development**: the debugger allows remote code execution, and the app listens on all network interfaces

### 5. Access from your network
```
http://<your-rasp-ip>:5000
Example: http://192.168.1.100:5000
```

## Application Structure

### `app.py` - Flask Server
- **Route `/`** - Serves the main HTML page
- **Route `/search` (POST)** - API endpoint that handles product search requests
  - Input: JSON with `products` array of strings (max 20; blank lines and duplicates are dropped)
  - Output: JSON per search, in the order the searches were given:
    ```json
    {"DETTOL Απολυμαντικο Ρούχων": {
        "products": {"ab": [...], "sklavenitis": [...], "mymarket": [...]},
        "groups": [{"label": "DETTOL Απολυμαντικό Ρούχων 2,5lt", "products": {"ab": 1, "sklavenitis": 0, "mymarket": 0}}]
    }}
    ```
    `products` are all relevant products per store, best value first. `groups` are the product choices,
    most likely first, as indexes into `products`.
- **Route `/favourites`** - The favourites page
- **Routes `/api/favourites`** - `GET` lists the favourites, `POST` saves one (`search`, `label` and
  `products`: `{store: {name, url}}`; the same favourite is saved once), `DELETE /api/favourites/<id>` removes one
- **Routes `/meals/...`** - The meal planner (`meal_planner` blueprint, see below). `meal_planner_search()` gives it
  the products of one store with `search_store()`, as package price and contents (`MEAL_PLANNER_UNITS`).
  Products without a size count as 1 kg at the store's price per kg (loose vegetables) or as 1 piece

### `favourites.py` - Favourites
- Favourites are kept in a JSON file on the server, so every device (phone, computer) sees the same list
- A favourite is a search and the chosen product per store (name and URL). Prices are not stored:
  checking the favourites searches again and picks the saved products by URL
- Writes go through a temporary file (`os.replace`), so a crash never leaves a half-written file

### `meal_planner/` - Meal Planner
A weekly plan of breakfast, lunch and dinner within a budget, with the shopping list priced in one store or in the
cheapest store per product. The page is `meal_planner/templates/meal_planner.html`, the settings are kept with the plan.

- **Plan** (`planner.py`): 300 random plans, then local search (changing one recipe at a time) on the best 3.
  The goal: within the budget and variety (the same main protein not twice in a row and not more than twice a week).
  What is left of a package is not counted against a recipe: it is kept for another time. With "leftovers" on, dinner is cooked twice over and becomes the next day's lunch
- **Changing a meal**: ↻ opens every recipe that fits the meal and the plan's settings (`alternatives()`), with what
  the week would cost with it: first those within the budget (more variety, then cheaper), then the cheapest. The list
  can be searched by recipe or ingredient name (without accents), and each recipe can be read before choosing it
  (`choose()`). Choosing a dinner that is also the next day's lunch changes both. "🎲 Τυχαία" picks the best of 12
  random recipes that are not in the plan yet (`swap()`)
- **Prices** (`pricing.py`): for each ingredient, the package with the lowest **total** cost for the quantity needed
  (not just the best €/kg). Only the first `MEAL_PLANNER_PAGES` (2) result pages are read, as a plan searches about 70
  ingredients. Prices are cached for 24 hours in `price_cache.json`; "Ανανέωση τιμών" searches again.
  An ingredient with no product found gets an estimated price (`fallback_price`), shown as "εκτίμηση".
  Products are searched by title, not by size: when the package is bigger than the recipe needs, the shopping list
  shows ❗ with what is left over (`leftover`)
- **Own recipes** (`custom.py`, tab "Συνταγές μου"): written in a form or pasted as text (`parse()` finds name,
  portions, time, ingredient lines and steps, with the ingredient mapping of `import_akis.py`). An ingredient not in
  the list is searched in the stores by title (sizes and "κουτί", "βάζο" etc. removed) and the user picks the product:
  it becomes a new ingredient in `ingredients_custom.json`, reused in later recipes, and in the store it was picked
  from the plan buys that product. Lines without an ingredient (e.g. "αλάτι") are shown but not costed. Saved in
  `recipes_custom.json`, they can be edited, deleted (not while in the plan), put in a meal of the plan, and chosen
  as the only source ("Μόνο δικές μου")
- Pantry items (oil, spices, vinegar, sugar) are not costed unless the user asks
- **Data**: `data/ingredients.json` and `data/recipes.json` come with the code. The price cache, the current plan
  imported and own recipes go to `MEAL_PLANNER_DATA`
- **API**: `GET /meals/api/meta`, `GET|POST /meals/api/plan` (new plan from the settings),
  `GET /meals/api/alternatives?day=0..6&meal=...` (the recipes for one meal, best first),
  `POST /meals/api/choose` (`{day, meal, recipe_id}`), `POST /meals/api/swap` (`{day, meal}`, a random better recipe),
  `GET /meals/api/recipe/<id>?portions=N`,
  `POST /meals/api/refresh-prices`, `POST /meals/api/reload-recipes`,
  `GET|POST /meals/api/custom` (own recipes, save one), `POST /meals/api/custom/<id>/delete`,
  `POST /meals/api/custom/parse` (`{text}`, a draft recipe), `GET /meals/api/products?q=...&store=...|all`

**Ingredients** (`data/ingredients.json`): `query` is what is searched for in the stores (a list when the stores
name the product differently, e.g. `["ντομάτες", "τομάτες"]`), `match` words that must be in the product name
and `exclude` words that rule it out (lowercase, no accents). The search results are first filtered by
`filter_relevant()`, so `query` should use the words of the product names (e.g. "τοματοπολτός", not "πελτές").

**Recipes** (`data/recipes.json`):
```json
{"id": "one_word", "name": "Όνομα", "meal": ["lunch", "dinner"], "category": "chicken",
 "servings": 4, "time": 45,
 "ingredients": {"chicken_thigh": 1000, "rice": 300},
 "steps": ["Βήμα 1", "Βήμα 2"]}
```
- `meal`: `["breakfast"]` or `["lunch", "dinner"]`
- `category`: breakfast_sweet, breakfast_eggs, breakfast_savory, legumes, ladera, chicken, soup_chicken,
  pasta_chicken, beef, pasta_meat, meat_oven, soup_meat, pork, fish, pasta_fish, pie, salad, veg_fried, eggs
- Quantities in g / ml / pieces for `servings` portions; the ingredients must be in `ingredients.json`.
  Vegetarian / fasting are worked out from the `type` of each ingredient
- Then `POST /meals/api/reload-recipes` or restart the app

**Your own recipes** from any source (a recipe site's API, an export from a recipe app, a JSON file you wrote):
save them as `recipes_<name>.json` in `MEAL_PLANNER_DATA` (with Docker `data/meal_planner/`), in the same format
as above. They are loaded together with the built-in ones, and the settings then show
"Συνταγές: Όλες / Μόνο ενσωματωμένες / Μόνο εισαγόμενες". To take recipes from an API, write a small script
that fetches them, converts them to this format and saves the file. Check the terms of the source: recipes from
a website usually belong to the site, so keep such files for personal use and do not publish them.
Script names `meal_planner/import_*.py` are in `.gitignore`, as are the files in `MEAL_PLANNER_DATA`.

Extra fields for imported recipes:
- `display`: the original ingredient lines, shown in the recipe instead of the converted quantities
- `diet`: `{"vegetarian": true, "vegan": false}`, when it is known better than from the ingredient types
- `source` / `source_name`: link to the original recipe, shown under it
- Ingredients that are not in `ingredients.json` go in `ingredients_<name>.json` in the same folder, in the
  format of `ingredients.json`. A recipe with an unknown ingredient is skipped (logged as a warning)

Then `POST /meals/api/reload-recipes` or restart the app.

### `supermarket_scraper.py` - Core Logic

#### How each store is searched

| Store | Request | Parser | Pages |
|---|---|---|---|
| AB Vasilopoulos | `POST https://www.ab.gr/api/v1/` (GraphQL `GetProductSearch`, query in `AB_SEARCH_QUERY`) | `parse_ab_response()` | `pageNumber` from 0, 50 products per page (`AB_PAGE_SIZE`, the largest the API accepts); count from `pagination.totalPages` |
| Sklavenitis | `GET https://www.sklavenitis.gr/apotelesmata-anazitisis/?Query=...&pg=...` | `parse_sklavenitis_html()` | `pg` from 1, 24 per page; count from "24 από τα 226 προϊόντα" |
| My Market | `GET https://www.mymarket.gr/search?query=...&page=...` | `parse_mymarket_html()` | `page` from 1, 35 per page; count from "1.062 προϊόντα" on the filters button |

Every store returns products with the same keys:
`name`, `brand`, `price`, `size`, `url`, `category`, `unit_price_calc`, `supermarket`.

`category` is the store's own category: AB `categories.name` (e.g. `Φέτα`), Sklavenitis `item_category`
from the analytics JSON (e.g. `Γάλατα Αγελάδος φρέσκα`), My Market all levels of the analytics JSON
(e.g. `Γάλα / Γαλακτοκομικά & Είδη Ψυγείου / Φρέσκο`).

The HTML pages are parsed with lxml (CSS selectors through cssselect). It is about 5 times faster than
BeautifulSoup, which matters because a search like "γάλα" is 30+ pages on My Market.

All three sites show their own unit price (e.g. `12,63 € /κιλό`, `0,07€ Τιμή μεζούρας`). The scrapers return it
as `unit_price_calc`, but `search_all_supermarkets()` replaces it with the price divided by the size when the size
is known (`unit_price()`): store labels can be out of date, e.g. My Market showed 20,48 €/kg for Pringles 165gr
at 2,54 € (the price per kg before a discount), which made it look 35% dearer than AB instead of 2%.
The store's unit price is kept for products without a size, e.g. loose fruit priced per kg.

Only AB returns barcodes (`eanCodes` in the GraphQL API). Sklavenitis and My Market do not show them in
search results or product pages, so products are matched by name (`matching.py`).

Store-specific details:
- **Sklavenitis**: the price is taken from the visible text of `.main-price .price`, not from its
  `data-price` attribute, which for some products is the price per kg. Loose products (fruit, vegetables)
  have no separate unit price; their main price is already per kg.
- **My Market**: the price is read from `.teaser-display-price-whole` / `-fraction`. The `price` in the
  analytics JSON is wrong for products sold by the kg. There is no size field, so the size is taken from the name.

#### Class: `SupermarketScraper`
- `search_ab(product_name)`, `search_sklavenitis(product_name)`, `search_mymarket(product_name)`
  - Read **every** result page of the store (`_search_all_pages()`): the first page gives the page count,
    the rest are requested `PAGE_WORKERS` (4) at a time. At most `MAX_PAGES` (50) pages are read
  - The products the search is about are not always on the first pages (on AB the last page of "γάλα"
    has fresh milks), so no page is skipped
  - Products that appear twice (results shift while paging) are removed
  - Network/HTTP errors are logged; a failed page is skipped and the other pages are kept
  - The stores sometimes drop connections under load, so each request is retried twice (urllib3 `Retry`)

#### Relevance: `relevance(search, product)` / `filter_relevant(search, results)`
The stores return everything that loosely matches (e.g. "γάλα" also finds "Μεγάλα", "Σοκολάτα Γάλακτος",
"Κρεμοσάπουνο Μέλι & Γάλα"), so products are filtered in two steps:

1. **Words.** Names are compared word by word, without accents or case, with Latin/Greek look-alike letters
   unified ("Kάψουλες" with a Latin K). Search words lose their ending (`WORD_ENDINGS`), so "μπανάνες" matches
   "Μπανάνα", and a product word may have at most 3 more letters ("φέτα" matches "φέτας", "γάλα" not "γάλακτος").
   A search word in the other alphabet is compared in Latin letters (`_latin()`), with at most 1 more letter
   (`MAX_EXTRA_LETTERS_OTHER_ALPHABET`): "πάπρικα" matches "Paprika", "γάλα" does not match "Galaxy".
   - `2`: every search word is in the brand or in the name before a descriptor word (`DESCRIPTOR_WORDS`:
     με, σε, για, από, χωρίς, γεύση, άρωμα), e.g. "Τυρί Φέτα ΠΟΠ 400g". Also when the other search words
     come after the descriptor, as long as a search word that is not the brand is before it:
     "Dettol Απολυμαντικό Για Τα Ρούχα" for "dettol απολυμαντικό ρούχων"
   - `1`: every search word is somewhere in the name, e.g. "Τυρόπιτα με Φέτα"
   - `0`: otherwise

   The best level found in any store is used for all stores, so a store that only has "Τυρόπιτα με φέτα"
   shows nothing instead of pies.
2. **Categories.** Names alone cannot tell "Τυροπιτάκια Μυζήθρα Φέτα 1kg" from "Βαρελίσια Φέτα ΠΟΠ".
   Within each store, only the products in the "main" categories of the search are kept: categories whose
   name contains the search (e.g. `Γάλατα Αγελάδος φρέσκα`) or that have a product named after the search
   (`is_named_after()`: the name starts with a search word after the brand, e.g. "ΚΑΡΑΛΗΣ Φέτα ΠΟΠ").
   If there is no main category (e.g. "ariel pods"), step 1 decides alone.
   Brand words are not expected in category names: `Απολυμαντικά ρούχων` is a main category for
   "DETTOL απολυμαντικό ρούχων".

#### Function: `parse_price(text)`
- Parses Greek (`2,49 €`, `1.234,56`) and international (`€2.49`) price formats

#### Function: `parse_unit_price_label(text)`
- Parses the unit price labels shown by the stores into `{'value', 'unit'}`
- Recognized units: κιλ → €/kg, λιτ → €/L, τεμ → €/unit, μεζ/πλύση → €/wash (see `UNIT_LABEL_KEYWORDS`)
- Returns `None` for labels without a unit, e.g. `57,63€ Τελ. τιμή`

#### Function: `unit_price(product)`
- Price divided by the size of the product (`product_quantity()`: from the name, else the store's size field)
- Without a size: the store's unit price, else the full price as €/unit

#### Function: `calculate_unit_price(price, size)`
- Finds quantity and unit anywhere in the size string, e.g. `500ml`, `1,5L`, `250 γρ`, `6x330ml`, `20 τεμ`, `87μεζ`
- Supported units: ml, l, lt, λτ, λιτ, g, gr, γρ, kg, κιλ, τεμ, τμχ, pcs, κάψουλες, μεζ, μεζούρες, πλύσεις
  (see `UNIT_ALIASES`); `parse_quantity()` returns the total quantity, e.g. `6x330ml` → 1.98 L
- Returns: Dict with `value` (unit price) and `unit` (label). If the size cannot be parsed, returns the full price as €/unit

#### Function: `sort_by_value(products)`
- Unit prices in different units are not comparable, so products are grouped by unit
  (most common unit first) and sorted by unit price within each group

#### Function: `search_all_supermarkets(product_name)`
- Calls `search_ab()`, `search_sklavenitis()`, `search_mymarket()` in parallel
- An error in one store does not fail the others
- Keeps the relevant products (`filter_relevant()`) and logs how many were found and kept per store
- Calculates the unit price of every product (`unit_price()`)
- Returns: Dict with all relevant products per supermarket, best value first

#### Function: `search_store(store, product_name, max_pages=None)`
- The same for one store (`'ab'`, `'sklavenitis'` or `'mymarket'`), used by the meal planner
- `max_pages` reads only the first result pages (the stores list the closest matches first); default `MAX_PAGES`

### `matching.py` - The Same Product in Every Store
Each store names products its own way, e.g. AB "Απολυμαντικό Ρούχων 2,5lt" (brand DETTOL),
Sklavenitis "DETTOL Αντιβακτηριδιακό Απολυμαντικό Υγρό Ρούχων 2,5lt", My Market "Dettol Απολυμαντικό Για Τα Ρούχα 2,5lt".
`group_products(results)` puts the products of different stores in one group when:
- **the brand matches** (`same_brand()`: a common word, or the brand in the other name when one has no brand)
- **the size matches** (`same_size()`: same total quantity and unit, from the name or the store's size field;
  products without a size, e.g. loose fruit, only match each other)
- **the names are similar** (`name_similarity()`: at least half of the words of both names are in the other,
  `MIN_NAME_SIMILARITY`), without brand, size, numbers and filler words like "για τα" (`FILLER_WORDS`).
  Words are compared in Latin letters (`_latin()`), because stores write the same word in both alphabets:
  AB "Τσιπς Πάπρικα 165g", Sklavenitis "PRINGLES Σνακ Paprika 165g", My Market "Pringles Πάπρικα 165gr"
- **no variant word differs** (`variant_words()`): words that tell apart products of the same brand and size
  with similar names in two stores, e.g. "Λεβάντα", "Χωρίς Άρωμα", plus words that always mean another variant
  (`VARIANT_PREFIXES`: χωρίς, ελαφρύ, πλήρες, light, zero, decaf, βιολογικό). Stores also add words to some
  names only (AB "Υγρό Απολυμαντικό Ρούχων Λεβάντα Αντιβακτηριδιακό 1.5lt"), so words that are only in one name
  of the single products of a brand and size of two stores are not variant words: in a "dettol" search the
  only 2,5lt products are Sklavenitis "Αντιβακτηριδιακό Απολυμαντικό Υγρό Ρούχων 2,5lt" and AB
  "Απολυμαντικό Ρούχων 2,5lt", so "Αντιβακτηριδιακό" and "Υγρό" do not keep products apart

The most similar pairs are grouped first, a product joins a group only if it matches every product in it,
and a group has at most one product per store. Groups are ordered by number of stores, then cheapest unit
price; the first `MAX_GROUPS` (10) are returned. Products sold in one store only are groups too.

### `templates/index.html` - Search Page
- Input textarea for product list (one per line)
- While typing, favourites that match the current line are suggested below it

### `templates/favourites.html` - Favourites Page
- Favourites list: tap one to check its prices, or check all of them at once

### `static/script.js` - Frontend Logic
- `searchProducts()` / `checkFavourites()` - Send the searches to `/search`
- `makeEntry()` - Selects the saved favourite products (by URL), or else the most likely group
- `rankStores()` - Supermarkets cheapest first by unit price (€/kg, €/L...), or by price if the products
  have different units, shown with 🥇🥈🥉 and how much more each costs per unit than the cheapest
- `renderSuggestions()` / `useSuggestion()` - Favourites whose search or product names have words starting with
  every word typed on the current line; picking one puts its search on the line and shows its saved products
- For every search: the other likely products (`renderChoices()`), and a list per store to pick another
  product of that store or none
- ☆/★ saves or removes the current choice as a favourite
- `escapeHtml()` - All scraped text is escaped before rendering (prevents XSS)
- Supports Ctrl+Enter (Cmd+Enter on Mac) for search

### `static/style.css` - Styling
- Responsive design (mobile-friendly)
- Cheapest supermarket highlighted in green

### `branding/` - Logo and Icons
- `logo-source.png` and `icon-source.png` are the original images
- `make_icons.py` builds `static/img/logo.png`, `static/favicon.ico`, the app icons and the apple touch icon from them (`pip install Pillow`, then `python branding/make_icons.py`)
- `static/manifest.json` lets phones add the app to the home screen with its icon

## How to Modify / Extend

### Add a New Supermarket

1. Write a parser `parse_newstore_html(html)` (or `parse_newstore_response(data)` for a JSON API) that
   returns product dicts with the keys listed above, and a function that reads the number of result pages.
   Use `parse_price()`, `parse_unit_price_label()` and `extract_size()` for the common parts.
2. Add methods to `SupermarketScraper`:
```python
def _newstore_page(self, product_name: str, page: int) -> Tuple[List[Dict], int]:
    response = self._request('New Store', 'GET', NEWSTORE_SEARCH_URL, params={'q': product_name, 'page': page})
    if response is None:
        return [], 0
    return parse_newstore_html(response.content), newstore_page_count(response.text)

def search_newstore(self, product_name: str) -> List[Dict]:
    """Search New Store by scraping its search result pages."""
    return self._search_all_pages(partial(self._newstore_page, product_name), first_page=1)
```
3. Add `'newstore': scraper.search_newstore` to `searches` in `search_all_supermarkets()`
4. Add the store name to `SUPERMARKETS` in `static/script.js`
5. Save a trimmed real response in `tests/fixtures/` and add tests in `tests/test_stores.py` and `tests/test_live.py`

### When a Store Stops Returning Results

1. Run `pytest --live` to see which store broke
2. Open the store's search page with browser DevTools (Network tab for API calls, Elements for HTML)
3. Update the URL, query or selectors in the store's `search_*` method / `parse_*` function
4. Save a new trimmed response in `tests/fixtures/` and update the expectations in `tests/test_stores.py`

### Wrong Products in the Results

- A product that only mentions the search as an ingredient: add the word before it to `DESCRIPTOR_WORDS`
- Singular/plural forms not matching: check `WORD_ENDINGS`
- Add the case to `tests/test_relevance.py` with the real product name

### Wrong Product Matched Between Stores

- Two variants grouped together: add the word that tells them apart to `VARIANT_PREFIXES`
- The same product not grouped: check the brand (`brand` field) and the size of both, and whether a word
  like "για" should be in `FILLER_WORDS`
- Add the case to `tests/test_matching.py` with the real product names

### Wrong Product in the Meal Planner Shopping List

- Add a word of the wrong product to the ingredient's `exclude` in `meal_planner/data/ingredients.json`
- Nothing found (an estimated price): check that `query` uses the words of the product names in that store,
  or add another query to the list
- Then "Ανανέωση τιμών" on the meal planner page, as prices are cached

### Change Unit Price Calculation

Add keywords to `UNIT_LABEL_KEYWORDS` (store labels) or `UNIT_ALIASES` (sizes in product names).

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest                         # unit tests, no network needed
pytest --live                  # also run tests against the real supermarket websites
```

- `tests/test_parsing.py` - price parsing, unit price calculation (`unit_price()`), sorting
- `tests/test_stores.py` - all 3 supermarkets, parsed from saved real responses in `tests/fixtures/`
  (packaged and loose products, categories, page counts, reading all pages, failed and repeated pages,
  missing unit prices, bad data, HTTP/network errors)
- `tests/test_relevance.py` - relevance levels and category filtering, with real product names
- `tests/test_matching.py` - the same product in every store: brand, size, name similarity, variants, ordering
- `tests/test_app.py` - Flask routes, input validation and favourites
- `tests/test_meal_planner.py` - meal planner: products for the planner from the scrapers, plans within the budget,
  choosing another recipe for a meal, own recipes (pasted text, new ingredients, routes), leftovers, the routes
- `tests/test_live.py` - real requests to each supermarket; fails when a site changes its URL, API or markup.
  Also checks that all pages are read, that e.g. "φέτα" returns feta and not frozen pies, and that
  "DETTOL Απολυμαντικο Ρούχων" finds the same 2,5lt product in all 3 stores

The files in `tests/fixtures/` are trimmed copies of real search results. When a store changes its markup,
replace the fixture and update the parser and the expectations together.

## Troubleshooting

**Port already in use?**
- Run with a different port: `PORT=5001 python3 app.py`

**No results from a supermarket?**
- Run `pytest --live` to check whether the store changed its site
- Check the log for `Error searching ...` (network errors, HTTP errors, AB GraphQL errors)
- See "When a Store Stops Returning Results" above
- Test with simpler product names

**Connection timeout?**
- Increase `REQUEST_TIMEOUT` in `supermarket_scraper.py` (currently 10 seconds, per page)
- Check internet connection on Raspberry Pi
- If a store drops connections (`RemoteDisconnected`, `Connection reset`), lower `PAGE_WORKERS`

**A product is missing?**
- The log line `Search '...', relevant/found products: ab 162/376, ...` shows how many products each store
  returned and how many passed the relevance filter (see "Relevance" above)

**Wrong prices?**
- Check `parse_price()`; it handles Greek (`2,49 €`) and international (`€2.49`) formats

## Auto-start on Raspberry Pi Boot (Optional)

Create systemd service:
```bash
sudo nano /etc/systemd/system/price-finder.service
```

Add:
```ini
[Unit]
Description=Price Finder Flask Application
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/projects/price-finder
ExecStart=/home/pi/projects/price-finder/venv/bin/python3 /home/pi/projects/price-finder/app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable price-finder
sudo systemctl start price-finder
sudo systemctl status price-finder
```

View logs:
```bash
sudo journalctl -u price-finder -f
```

## Performance Notes

- Results are always live: every search reads all result pages of the 3 stores, nothing is cached
- A search takes about 4-10 seconds on a PC, depending on the number of pages (e.g. "γάλα" is
  11 pages on AB, 10 on Sklavenitis and 31 on My Market). Expect it to be slower on a Raspberry Pi
- Stores are searched in parallel, 4 pages per store at a time; products are searched one after another
- Too many parallel requests make the stores drop connections; see `PAGE_WORKERS`

## Future Enhancements

- [ ] Store price history for trend analysis
- [ ] Email alerts when product price drops
- [ ] Support for more Greek supermarkets
- [ ] QR code scanning for EAN/barcode lookup
- [ ] Export results to CSV
