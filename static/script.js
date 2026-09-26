const SUPERMARKETS = {
    'ab': '🅰️ AB Vasilopoulos',
    'sklavenitis': '🏪 Sklavenitis',
    'mymarket': '🛍️ My Market'
};

const MEDALS = ['🥇', '🥈', '🥉'];

// Display labels for the unit codes returned by the backend
const UNIT_LABELS = {
    '€/unit': '€/τεμ.',
    '€/wash': '€/μεζούρα'
};

// Favourites suggested at most while typing a search
const MAX_SUGGESTIONS = 5;

// Saved favourites, as returned by GET /api/favourites
let favourites = [];

// Favourites picked from the suggestions: {search: favourite id}
let pickedFavourites = {};

// One entry per search shown in the results:
// {search, data: {products: {store: [...]}, groups: [...]}, selection: {store: index},
//  missing: {store: name}, favouriteId: the favourite shown, until the user changes the selection}
let entries = [];

// Scraped text is untrusted, so it must be escaped before going into innerHTML
function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function unitLabel(unit) {
    return UNIT_LABELS[unit] || unit;
}

function unitPriceText(product) {
    const unitPrice = product.unit_price_calc;
    return `${unitPrice.value.toFixed(2)} ${unitLabel(unitPrice.unit)}`;
}

function productLink(product) {
    return /^https?:\/\//i.test(product.url || '')
        ? `<a href="${escapeHtml(product.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(product.name)}</a>`
        : escapeHtml(product.name);
}

// --- Searching ---

async function runSearch(searches) {
    const buttons = document.querySelectorAll('.btn-search, .btn-check-favourites');

    buttons.forEach(button => button.disabled = true);
    document.getElementById('loading').classList.remove('hidden');
    document.getElementById('resultsContainer').classList.add('results-hidden');

    try {
        const response = await fetch('/search', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ products: searches })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Search failed');
        }

        return data;
    } catch (error) {
        console.error('Error:', error);
        alert('Σφάλμα κατά την αναζήτηση. Παρακαλώ δοκιμάστε ξανά.');
        return null;
    } finally {
        buttons.forEach(button => button.disabled = false);
        document.getElementById('loading').classList.add('hidden');
    }
}

async function searchProducts() {
    const searches = document.getElementById('productInput').value
        .split('\n')
        .map(p => p.trim())
        .filter(p => p.length > 0);

    if (searches.length === 0) {
        alert('Παρακαλώ γράψε τουλάχιστον ένα προϊόν');
        return;
    }

    hideSuggestions();
    const data = await runSearch(searches);
    if (data) {
        // A search saved as favourite shows the favourite products again
        entries = Object.entries(data).map(([search, result]) =>
            makeEntry(search, result, favouriteForSearch(search)));
        displayResults();
    }
}

// The favourite picked for a search from the suggestions, else any favourite with that search
function favouriteForSearch(search) {
    return favourites.find(f => f.id === pickedFavourites[search])
        || favourites.find(f => f.search === search);
}

async function checkFavourites(selected = favourites) {
    if (selected.length === 0) {
        alert('Δεν έχεις αγαπημένα ακόμα');
        return;
    }

    const data = await runSearch([...new Set(selected.map(f => f.search))]);
    if (data) {
        entries = selected.map(f => makeEntry(f.search, data[f.search], f));
        displayResults();
    }
}

// The selected product of each store: the saved favourite, else the most likely group
function makeEntry(search, data, favourite) {
    const selection = {};
    const missing = {};

    if (favourite) {
        for (const [store, saved] of Object.entries(favourite.products)) {
            const index = (data.products[store] || []).findIndex(p => p.url === saved.url);
            if (index >= 0) {
                selection[store] = index;
            } else {
                missing[store] = saved.name;
            }
        }
    } else if (data.groups.length > 0) {
        Object.assign(selection, data.groups[0].products);
    }

    return { search, data, selection, missing, favouriteId: favourite ? favourite.id : null };
}

// --- Results ---

function selectedProducts(entry) {
    return Object.keys(SUPERMARKETS)
        .filter(store => entry.selection[store] !== undefined)
        .map(store => ({ store, product: entry.data.products[store][entry.selection[store]] }));
}

// Cheapest store first: by unit price if all products have the same unit, else by price
function rankStores(entry) {
    const chosen = selectedProducts(entry);
    const byUnit = new Set(chosen.map(c => c.product.unit_price_calc.unit)).size === 1;
    const cost = c => byUnit ? c.product.unit_price_calc.value : c.product.price;
    return chosen.map(c => ({ ...c, cost: cost(c) })).sort((a, b) => a.cost - b.cost);
}

function selectedGroup(entry) {
    const stores = Object.keys(entry.selection);
    return entry.data.groups.findIndex(group =>
        Object.keys(group.products).length === stores.length
        && stores.every(store => group.products[store] === entry.selection[store]));
}

function entryLabel(entry) {
    const group = selectedGroup(entry);
    if (group >= 0) {
        return entry.data.groups[group].label;
    }
    const ranked = rankStores(entry);
    return ranked.length > 0 ? ranked[0].product.name : entry.search;
}

function findFavourite(entry) {
    const shown = favourites.find(f => f.id === entry.favouriteId);
    if (shown) {
        return shown;
    }
    const chosen = selectedProducts(entry);
    return favourites.find(f =>
        f.search === entry.search
        && Object.keys(f.products).length === chosen.length
        && chosen.every(c => f.products[c.store] && f.products[c.store].url === c.product.url));
}

function renderProductSelect(entry, store) {
    const products = entry.data.products[store] || [];
    const options = products.map((product, index) => `
        <option value="${index}" ${entry.selection[store] === index ? 'selected' : ''}>
            ${escapeHtml(product.name)} — €${product.price.toFixed(2)} (${escapeHtml(unitPriceText(product))})
        </option>`).join('');

    return `
        <select class="product-select" data-action="choose-product" data-store="${store}" title="Άλλο προϊόν από αυτό το supermarket">
            <option value="" ${entry.selection[store] === undefined ? 'selected' : ''}>— Κανένα προϊόν —</option>
            ${options}
        </select>
    `;
}

function renderRankRow(entry, ranked, index) {
    const { store, product, cost } = ranked[index];
    const difference = index > 0 && ranked[0].cost > 0
        ? `<span class="rank-difference">+${Math.round((cost / ranked[0].cost - 1) * 100)}%</span>`
        : '';

    return `
        <div class="rank-row ${index === 0 ? 'rank-best' : ''}">
            <div class="rank-medal">${MEDALS[index] || ''}</div>
            <div class="rank-body">
                <div class="rank-store">${SUPERMARKETS[store]} ${difference}</div>
                <div class="product-item-name">${productLink(product)}</div>
                <div class="product-size"><strong>Μέγεθος:</strong> ${escapeHtml(product.size || 'N/A')} | <strong>Brand:</strong> ${escapeHtml(product.brand || 'N/A')}</div>
                ${renderProductSelect(entry, store)}
            </div>
            <div class="product-price">
                <div class="price-main">€${product.price.toFixed(2)}</div>
                <div class="price-unit">${escapeHtml(unitPriceText(product))}</div>
            </div>
        </div>
    `;
}

function renderMissingRow(entry, store) {
    const hasProducts = (entry.data.products[store] || []).length > 0;
    const saved = entry.missing[store]
        ? `<div class="product-size">Το αγαπημένο «${escapeHtml(entry.missing[store])}» δεν βρέθηκε</div>`
        : '';

    return `
        <div class="rank-row rank-missing">
            <div class="rank-medal">—</div>
            <div class="rank-body">
                <div class="rank-store">${SUPERMARKETS[store]}</div>
                <div class="empty-result">${hasProducts ? 'Δεν βρέθηκε το ίδιο προϊόν' : 'Δεν βρέθηκαν αποτελέσματα'}</div>
                ${saved}
                ${hasProducts ? renderProductSelect(entry, store) : ''}
            </div>
        </div>
    `;
}

function renderChoices(entry, open) {
    const groups = entry.data.groups;
    if (groups.length < 2) {
        return '';
    }

    const current = selectedGroup(entry);
    const choices = groups.map((group, index) => {
        const products = Object.entries(group.products).map(([store, i]) => entry.data.products[store][i]);
        // Cheapest by unit price, as in the ranking
        const cheapest = products.reduce((best, p) =>
            p.unit_price_calc.value < best.unit_price_calc.value ? p : best);
        return `
            <button class="choice ${index === current ? 'choice-selected' : ''}" data-action="choose-group" data-group="${index}">
                <span class="choice-label">${escapeHtml(group.label)}</span>
                <span class="choice-meta">${products.length}/3 supermarkets · από ${escapeHtml(unitPriceText(cheapest))} (€${cheapest.price.toFixed(2)})</span>
            </button>
        `;
    }).join('');

    return `
        <details class="choices" ${open ? 'open' : ''}>
            <summary>Δεν είναι αυτό; Διάλεξε από ${groups.length} πιθανά προϊόντα</summary>
            <div class="choice-list">${choices}</div>
        </details>
    `;
}

function renderEntry(entry, index, choicesOpen = true) {
    const ranked = rankStores(entry);
    const missing = Object.keys(SUPERMARKETS).filter(store => entry.selection[store] === undefined);
    const favourite = findFavourite(entry);

    return `
        <div class="product-group" data-entry="${index}">
            <div class="product-header">
                <div>
                    <div class="product-name">${escapeHtml(entry.search)}</div>
                    <div class="selected-label">${escapeHtml(entryLabel(entry))}</div>
                </div>
                <button class="btn-favourite ${favourite ? 'is-favourite' : ''}" data-action="favourite"
                        title="${favourite ? 'Αφαίρεση από τα αγαπημένα' : 'Προσθήκη στα αγαπημένα'}">${favourite ? '★' : '☆'}</button>
            </div>
            <div class="ranking">
                ${ranked.map((_, i) => renderRankRow(entry, ranked, i)).join('')}
                ${missing.map(store => renderMissingRow(entry, store)).join('')}
            </div>
            ${renderChoices(entry, choicesOpen)}
        </div>
    `;
}

function displayResults() {
    document.getElementById('results').innerHTML = entries.map((entry, i) => renderEntry(entry, i)).join('');
    document.getElementById('resultsContainer').classList.remove('results-hidden');
}

function rerenderEntry(index) {
    const element = document.querySelector(`.product-group[data-entry="${index}"]`);
    const details = element.querySelector('details.choices');
    element.outerHTML = renderEntry(entries[index], index, details ? details.open : true);
}

// --- Favourites ---

async function loadFavourites() {
    try {
        const response = await fetch('/api/favourites');
        favourites = response.ok ? await response.json() : [];
    } catch (error) {
        console.error('Error:', error);
        favourites = [];
    }
    renderFavourites();
}

// The favourites list is on the favourites page only
function renderFavourites() {
    const list = document.getElementById('favouritesList');
    if (!list) {
        return;
    }
    document.querySelector('.btn-check-favourites').disabled = favourites.length === 0;

    list.innerHTML = favourites.length === 0
        ? '<li class="favourites-empty">Δεν έχεις αγαπημένα ακόμα. Πάτα ☆ σε ένα αποτέλεσμα για να το κρατήσεις.</li>'
        : favourites.map(f => `
            <li class="favourite-item">
                <button class="favourite-name" data-action="check-favourite" data-id="${escapeHtml(f.id)}" title="Έλεγχος τιμής">
                    ${escapeHtml(f.label)} <span class="favourite-search">(${escapeHtml(f.search)})</span>
                </button>
                <button class="favourite-remove" data-action="remove-favourite" data-id="${escapeHtml(f.id)}" title="Αφαίρεση">✕</button>
            </li>
        `).join('');
}

async function removeFavourite(id) {
    const response = await fetch(`/api/favourites/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (!response.ok && response.status !== 404) {
        throw new Error('Delete failed');
    }
    favourites = favourites.filter(f => f.id !== id);
}

async function toggleFavourite(index) {
    const entry = entries[index];
    const existing = findFavourite(entry);

    try {
        if (existing) {
            await removeFavourite(existing.id);
        } else {
            const chosen = selectedProducts(entry);
            if (chosen.length === 0) {
                alert('Διάλεξε πρώτα ένα προϊόν');
                return;
            }
            const response = await fetch('/api/favourites', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    search: entry.search,
                    label: entryLabel(entry),
                    products: Object.fromEntries(chosen.map(c => [c.store, { name: c.product.name, url: c.product.url }]))
                })
            });
            const saved = await response.json();
            if (!response.ok) {
                throw new Error(saved.error || 'Save failed');
            }
            favourites = favourites.filter(f => f.id !== saved.id).concat(saved);
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Σφάλμα στα αγαπημένα. Παρακαλώ δοκιμάστε ξανά.');
    }

    renderFavourites();
    rerenderEntry(index);
}

// --- Favourite suggestions while typing ---

// Lowercase words without accents, final ς as σ, as the backend compares them
function textWords(text) {
    return text.toLowerCase()
        .normalize('NFD').replace(/[̀-ͯ]/g, '')
        .replace(/ς/g, 'σ')
        .split(/[^\p{L}\p{N}]+/u)
        .filter(word => word.length > 0);
}

// The line of the textarea the cursor is on
function currentLine(input) {
    const start = input.value.lastIndexOf('\n', input.selectionStart - 1) + 1;
    const end = input.value.indexOf('\n', input.selectionStart);
    return { start, end: end < 0 ? input.value.length : end };
}

// Favourites whose search, name or store product names have words starting with every typed word
function matchingFavourites(text) {
    const typed = textWords(text);
    if (typed.join('').length < 2) {
        return [];
    }
    return favourites.filter(f => {
        const words = textWords([f.search, f.label, ...Object.values(f.products).map(p => p.name)].join(' '));
        return typed.every(t => words.some(word => word.startsWith(t)));
    }).slice(0, MAX_SUGGESTIONS);
}

function renderSuggestions() {
    const input = document.getElementById('productInput');
    const line = currentLine(input);
    const found = matchingFavourites(input.value.slice(line.start, line.end));
    const box = document.getElementById('suggestions');

    box.innerHTML = found.map(f => `
        <button type="button" class="suggestion" data-id="${escapeHtml(f.id)}">
            <span class="suggestion-label">⭐ ${escapeHtml(f.label)}</span>
            <span class="favourite-search">${escapeHtml(f.search)}</span>
        </button>
    `).join('');
    box.classList.toggle('hidden', found.length === 0);
}

function hideSuggestions() {
    const box = document.getElementById('suggestions');
    if (box) {
        box.classList.add('hidden');
    }
}

// Replace the current line with the search of the favourite, so that its products are shown
function useSuggestion(id) {
    const favourite = favourites.find(f => f.id === id);
    const input = document.getElementById('productInput');
    const line = currentLine(input);

    input.value = input.value.slice(0, line.start) + favourite.search + input.value.slice(line.end);
    pickedFavourites[favourite.search] = favourite.id;
    const cursor = line.start + favourite.search.length;
    input.focus();
    input.setSelectionRange(cursor, cursor);
    hideSuggestions();
}

// --- Events ---

document.addEventListener('DOMContentLoaded', function() {
    // The search box is on the search page only
    const input = document.getElementById('productInput');
    if (input) {
        input.addEventListener('keydown', function(event) {
            // Ctrl+Enter (Cmd+Enter on Mac) starts the search
            if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                searchProducts();
            } else if (event.key === 'Escape') {
                hideSuggestions();
            }
        });
        input.addEventListener('input', renderSuggestions);
        // Later, so that a tap on a suggestion on a phone is not lost
        input.addEventListener('blur', () => setTimeout(hideSuggestions, 200));

        const suggestions = document.getElementById('suggestions');
        // Keep the focus in the textarea, so that its blur does not hide the suggestion being clicked
        suggestions.addEventListener('mousedown', event => event.preventDefault());
        suggestions.addEventListener('click', function(event) {
            const target = event.target.closest('.suggestion');
            if (target) {
                useSuggestion(target.dataset.id);
            }
        });
    }

    const results = document.getElementById('results');
    results.addEventListener('click', function(event) {
        const target = event.target.closest('[data-action]');
        if (!target) {
            return;
        }
        const index = Number(target.closest('.product-group').dataset.entry);

        if (target.dataset.action === 'favourite') {
            toggleFavourite(index);
        } else if (target.dataset.action === 'choose-group') {
            entries[index].selection = { ...entries[index].data.groups[Number(target.dataset.group)].products };
            entries[index].missing = {};
            entries[index].favouriteId = null;
            rerenderEntry(index);
        }
    });

    results.addEventListener('change', function(event) {
        const target = event.target;
        if (target.dataset.action !== 'choose-product') {
            return;
        }
        const entry = entries[Number(target.closest('.product-group').dataset.entry)];

        if (target.value === '') {
            delete entry.selection[target.dataset.store];
        } else {
            entry.selection[target.dataset.store] = Number(target.value);
        }
        delete entry.missing[target.dataset.store];
        entry.favouriteId = null;
        rerenderEntry(entries.indexOf(entry));
    });

    document.getElementById('favouritesList')?.addEventListener('click', async function(event) {
        const target = event.target.closest('[data-action]');
        if (!target) {
            return;
        }

        if (target.dataset.action === 'check-favourite') {
            checkFavourites(favourites.filter(f => f.id === target.dataset.id));
        } else if (target.dataset.action === 'remove-favourite') {
            try {
                await removeFavourite(target.dataset.id);
            } catch (error) {
                console.error('Error:', error);
                alert('Σφάλμα στα αγαπημένα. Παρακαλώ δοκιμάστε ξανά.');
            }
            renderFavourites();
            entries.forEach((_, i) => rerenderEntry(i));
        }
    });

    loadFavourites();
});
