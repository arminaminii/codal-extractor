// === Autocomplete ===
const searchInput = document.getElementById('symbolInput');
const suggestionsBox = document.getElementById('suggestionsBox');
const searchForm = document.getElementById('searchForm');
let debounceTimer = null;
let selectedIndex = -1;

if (searchInput && suggestionsBox) {
    searchInput.addEventListener('input', function() {
        clearTimeout(debounceTimer);
        const query = this.value.trim();
        
        if (query.length < 1) {
            hideSuggestions();
            return;
        }

        debounceTimer = setTimeout(() => {
            fetch(`/api/suggestions/?q=${encodeURIComponent(query)}`)
                .then(res => res.json())
                .then(data => {
                    renderSuggestions(data);
                })
                .catch(() => hideSuggestions());
        }, 200);
    });

    searchInput.addEventListener('keydown', function(e) {
        const items = suggestionsBox.querySelectorAll('.suggestion-item');
        if (!items.length) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
            updateHighlight(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            selectedIndex = Math.max(selectedIndex - 1, -1);
            updateHighlight(items);
        } else if (e.key === 'Enter' && selectedIndex >= 0) {
            e.preventDefault();
            items[selectedIndex].click();
        } else if (e.key === 'Escape') {
            hideSuggestions();
        }
    });

    searchInput.addEventListener('focus', function() {
        if (this.value.trim().length >= 1) {
            this.dispatchEvent(new Event('input'));
        }
    });

    document.addEventListener('click', function(e) {
        if (!e.target.closest('.search-wrapper')) {
            hideSuggestions();
        }
    });
}

function renderSuggestions(data) {
    if (!data || data.length === 0) {
        hideSuggestions();
        return;
    }

    suggestionsBox.innerHTML = data.map((item, i) => `
        <div class="suggestion-item" data-symbol="${item.symbol}" data-index="${i}">
            <div class="suggestion-icon">${item.sector_icon}</div>
            <div class="suggestion-info">
                <div class="suggestion-symbol">${highlightMatch(item.symbol, searchInput.value)}</div>
                <div class="suggestion-name">${item.name}</div>
            </div>
            <div class="suggestion-sector">${item.sector}</div>
        </div>
    `).join('');

    selectedIndex = -1;

    suggestionsBox.querySelectorAll('.suggestion-item').forEach(item => {
        item.addEventListener('click', function() {
            searchInput.value = this.dataset.symbol;
            hideSuggestions();
            searchForm.submit();
        });
    });

    suggestionsBox.classList.add('active');
}

function highlightMatch(text, query) {
    const idx = text.toLowerCase().indexOf(query.toLowerCase());
    if (idx === -1) return text;
    return text.substring(0, idx) + 
           '<span class="highlight-match">' + text.substring(idx, idx + query.length) + '</span>' + 
           text.substring(idx + query.length);
}

function updateHighlight(items) {
    items.forEach((item, i) => {
        item.classList.toggle('active', i === selectedIndex);
    });
    if (selectedIndex >= 0) {
        searchInput.value = items[selectedIndex].dataset.symbol;
    }
}

function hideSuggestions() {
    if (suggestionsBox) {
        suggestionsBox.classList.remove('active');
        suggestionsBox.innerHTML = '';
        selectedIndex = -1;
    }
}

// === Search Form Submit ===
if (searchForm) {
    searchForm.addEventListener('submit', function(e) {
        const query = searchInput.value.trim();
        if (!query) {
            e.preventDefault();
            return;
        }
        hideSuggestions();
        
        const btnText = this.querySelector('.btn-text');
        const btnLoader = this.querySelector('.btn-loader');
        if (btnText) btnText.style.display = 'none';
        if (btnLoader) btnLoader.style.display = 'inline-flex';
        
        const submitBtn = this.querySelector('.search-btn');
        if (submitBtn) submitBtn.disabled = true;
    });
}