import logging
import os
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from favourites import FavouritesError, FavouritesStore, validate_favourite
from matching import group_products
from supermarket_scraper import search_all_supermarkets

MAX_PRODUCTS = 20

app = Flask(__name__)
# Keep results in the order the user typed the products
app.json.sort_keys = False
logging.basicConfig(level=logging.INFO)

favourites = FavouritesStore(os.environ.get('FAVOURITES_FILE', Path(__file__).with_name('favourites.json')))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    data = request.get_json(silent=True)
    products = data.get('products', []) if isinstance(data, dict) else []

    if not isinstance(products, list) or not all(isinstance(p, str) for p in products):
        return jsonify({'error': 'products must be a list of strings'}), 400

    # Drop blank lines and duplicates, keep input order
    products = list(dict.fromkeys(p.strip() for p in products if p.strip()))

    if not products:
        return jsonify({'error': 'No products provided'}), 400

    if len(products) > MAX_PRODUCTS:
        return jsonify({'error': f'Too many products (max {MAX_PRODUCTS})'}), 400

    results = {}
    for product_name in products:
        found = search_all_supermarkets(product_name)
        results[product_name] = {'products': found, 'groups': group_products(found)}

    return jsonify(results)

@app.route('/favourites')
def favourites_page():
    return render_template('favourites.html')

@app.route('/api/favourites', methods=['GET'])
def list_favourites():
    return jsonify(favourites.list())

@app.route('/api/favourites', methods=['POST'])
def add_favourite():
    try:
        favourite = favourites.add(validate_favourite(request.get_json(silent=True)))
    except FavouritesError as error:
        return jsonify({'error': str(error)}), 400
    return jsonify(favourite), 201

@app.route('/api/favourites/<favourite_id>', methods=['DELETE'])
def remove_favourite(favourite_id):
    if favourites.remove(favourite_id) is None:
        return jsonify({'error': 'Favourite not found'}), 404
    return '', 204

if __name__ == '__main__':
    # Never enable debug mode on 0.0.0.0 by default: the Werkzeug debugger allows remote code execution
    debug = os.environ.get('FLASK_DEBUG') == '1'
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=debug)
