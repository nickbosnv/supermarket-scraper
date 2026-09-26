"""
Favourite products, kept in a JSON file on the server so that every device sees the same list.

A favourite is a search and the product the user chose for it in each store, e.g.
{"id": "...", "search": "dettol απολυμαντικό ρούχων", "label": "DETTOL Απολυμαντικό Ρούχων 2,5lt",
 "products": {"ab": {"name": "...", "url": "https://www.ab.gr/..."}, "mymarket": {...}}}
Prices are not stored: they are searched again every time the favourites are checked.
"""
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional

STORES = ('ab', 'sklavenitis', 'mymarket')
MAX_FAVOURITES = 200
MAX_TEXT_LENGTH = 300


class FavouritesError(ValueError):
    """The favourite sent by the browser is not valid."""


def validate_favourite(data) -> Dict:
    """Return a clean favourite from request data, or raise FavouritesError."""
    if not isinstance(data, dict):
        raise FavouritesError('favourite must be an object')

    search = data.get('search')
    label = data.get('label')
    products = data.get('products')
    if not isinstance(search, str) or not search.strip() or len(search) > MAX_TEXT_LENGTH:
        raise FavouritesError('search must be a non-empty string')
    if not isinstance(label, str) or not label.strip() or len(label) > MAX_TEXT_LENGTH:
        raise FavouritesError('label must be a non-empty string')
    if not isinstance(products, dict) or not products:
        raise FavouritesError('products must be an object with at least one store')

    clean_products = {}
    for store, product in products.items():
        if store not in STORES:
            raise FavouritesError(f'unknown store {store!r}')
        if not isinstance(product, dict):
            raise FavouritesError('every product must be an object')
        name, url = product.get('name'), product.get('url')
        if not isinstance(name, str) or not name or len(name) > MAX_TEXT_LENGTH:
            raise FavouritesError('every product needs a name')
        if not isinstance(url, str) or not url.startswith('https://') or len(url) > MAX_TEXT_LENGTH:
            raise FavouritesError('every product needs an https url')
        clean_products[store] = {'name': name, 'url': url}

    return {'search': search.strip(), 'label': label.strip(), 'products': clean_products}


class FavouritesStore:
    """Favourites in a JSON file. Safe to use from several request threads."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> List[Dict]:
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return []

    def _write(self, favourites: List[Dict]) -> None:
        # Write to a temporary file first, so that a crash never leaves a half-written file
        temporary = self.path.with_name(self.path.name + '.tmp')
        temporary.write_text(json.dumps(favourites, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, self.path)

    def list(self) -> List[Dict]:
        with self._lock:
            return self._read()

    def add(self, favourite: Dict) -> Dict:
        """Save a validated favourite and return it with its id. The same favourite is saved once."""
        with self._lock:
            favourites = self._read()
            for existing in favourites:
                if existing['search'] == favourite['search'] and existing['products'] == favourite['products']:
                    return existing
            if len(favourites) >= MAX_FAVOURITES:
                raise FavouritesError(f'too many favourites (max {MAX_FAVOURITES})')

            saved = {'id': uuid.uuid4().hex, **favourite}
            favourites.append(saved)
            self._write(favourites)
            return saved

    def remove(self, favourite_id: str) -> Optional[Dict]:
        """Delete a favourite and return it, or None if there is no such favourite."""
        with self._lock:
            favourites = self._read()
            removed = next((f for f in favourites if f['id'] == favourite_id), None)
            if removed:
                self._write([f for f in favourites if f is not removed])
            return removed
