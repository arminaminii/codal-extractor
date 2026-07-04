// ============================================
//  CODAL EXPERT - Main JavaScript
// ============================================

(function () {
    'use strict';

    // --- Elements ---
    const input = document.getElementById('symbolInput');
    const form = document.getElementById('searchForm');
    const suggestionsBox = document.getElementById('suggestionsBox');
    const sectorChips = document.getElementById('sectorChips');
    const sectorClearBtn = document.getElementById('sectorClearBtn');
    const btnText = document.getElementById('btnText');
    const btnLoader = document.getElementById('btnLoader');
    const searchBtn = document.getElementById('searchBtn');

    // --- State ---
    let activeIndex = -1;
    let debounceTimer = null;
    let currentResults = [];
    let selectedSector = '';
    let sectorsLoaded = false;
    let sectorData = [];

    // --- Init ---
    if (input) {
        input.addEventListener('input', onInput);
        input.addEventListener('keydown', onKeyDown);
        input.addEventListener('focus', onInput);  // show suggestions on focus if has value
        document.addEventListener('click', onDocumentClick);
        loadSectors();
    }

    // --- Sector Filter ---
    function loadSectors() {
        if (sectorsLoaded) return;
        fetch('/api/sectors/')
            .then(r => r.json())
            .then(data => {
                sectorData = data;
                sectorsLoaded = true;
                renderSectorChips();
            })
            .catch(() => {
                sectorChips.innerHTML = '<span style="color:var(--error-red);font-size:0.8rem;">خطا در بارگذاری لیست صنایع</span>';
            });
    }

    function renderSectorChips() {
        if (!sectorData.length) {
            sectorChips.innerHTML = '';
            return;
        }
        sectorChips.innerHTML = sectorData.map(s =>
            `<button type="button" class="sector-chip" data-sector="${escHtml(s.name)}" onclick="toggleSector('${escHtml(s.name)}')">
                <span class="sector-chip-icon">${s.icon}</span>
                ${escHtml(s.name)}
                <span class="sector-chip-count">(${s.count})</span>
            </button>`
        ).join('');
    }

    window.toggleSector = function (sector) {
        if (selectedSector === sector) {
            clearSectorFilter();
        } else {
            selectedSector = sector;
            document.querySelectorAll('.sector-chip').forEach(chip => {
                chip.classList.toggle('active', chip.dataset.sector === sector);
            });
            sectorClearBtn.classList.add('visible');
            // Re-trigger suggestions if input has value
            if (input.value.trim()) {
                fetchSuggestions(input.value.trim());
            }
        }
    };

    window.clearSectorFilter = function () {
        selectedSector = '';
        document.querySelectorAll('.sector-chip').forEach(c => c.classList.remove('active'));
        sectorClearBtn.classList.remove('visible');
        if (input.value.trim()) {
            fetchSuggestions(input.value.trim());
        }
    };

    // --- Debounced Input ---
    function onInput() {
        clearTimeout(debounceTimer);
        const query = input.value.trim();
        if (!query) {
            hideSuggestions();
            return;
        }
        debounceTimer = setTimeout(() => fetchSuggestions(query), 150);
    }

    // --- Fetch Suggestions ---
    function fetchSuggestions(query) {
        let url = `/api/suggestions/?q=${encodeURIComponent(query)}`;
        if (selectedSector) {
            url += `&sector=${encodeURIComponent(selectedSector)}`;
        }

        fetch(url)
            .then(r => r.json())
            .then(data => {
                currentResults = data;
                activeIndex = -1;
                if (data.length > 0) {
                    renderSuggestions(data, query);
                    showSuggestions();
                } else {
                    hideSuggestions();
                }
            })
            .catch(() => hideSuggestions());
    }

    // --- Render Suggestions ---
    function renderSuggestions(results, query) {
        const queryLower = query.toLowerCase();

        let html = `<div class="suggestions-header">
            <span>نتایج پیشنهادی</span>
            <span><span class="suggestions-count">${results.length}</span> شرکت یافت شد</span>
        </div>`;

        results.forEach((item, idx) => {
            const sym = item.symbol || '';
            const name = item.name || '';
            const sector = item.sector || '';
            const icon = item.sector_icon || '📊';
            const matchType = item.match_type || '';

            // Highlight matching text
            const highlightedSym = highlightText(sym, query);
            const highlightedName = highlightText(name, query);

            // Match badge
            let badge = '';
            if (matchType === 'exact_symbol') {
                badge = '<span class="suggestion-match-badge match-exact">دقیق</span>';
            } else if (matchType === 'starts_symbol' || matchType === 'starts_name') {
                badge = '<span class="suggestion-match-badge match-starts">شروع</span>';
            }

            html += `<div class="suggestion-item" data-index="${idx}" data-symbol="${escHtml(sym)}" onclick="selectSuggestion('${escHtml(sym)}')">
                <div class="suggestion-icon">${icon}</div>
                <div class="suggestion-info">
                    <div class="suggestion-symbol">${highlightedSym} ${badge}</div>
                    <div class="suggestion-name">${highlightedName}</div>
                </div>
                <div class="suggestion-sector">${escHtml(sector)}</div>
            </div>`;
        });

        suggestionsBox.innerHTML = html;
    }

    function highlightText(text, query) {
        if (!text || !query) return escHtml(text);
        const textLower = text.toLowerCase();
        const queryLower = query.toLowerCase();
        const idx = textLower.indexOf(queryLower);

        if (idx === -1) return escHtml(text);

        const before = text.substring(0, idx);
        const match = text.substring(idx, idx + query.length);
        const after = text.substring(idx + query.length);

        return `${escHtml(before)}<span class="highlight-match">${escHtml(match)}</span>${escHtml(after)}`;
    }

    // --- Keyboard Navigation ---
    function onKeyDown(e) {
        const items = suggestionsBox.querySelectorAll('.suggestion-item');
        if (!items.length || !suggestionsBox.classList.contains('active')) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            activeIndex = Math.min(activeIndex + 1, items.length - 1);
            updateActiveItem(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            activeIndex = Math.max(activeIndex - 1, -1);
            updateActiveItem(items);
        } else if (e.key === 'Enter') {
            if (activeIndex >= 0 && items[activeIndex]) {
                e.preventDefault();
                const symbol = items[activeIndex].dataset.symbol;
                selectSuggestion(symbol);
            }
        } else if (e.key === 'Escape') {
            hideSuggestions();
        }
    }

    function updateActiveItem(items) {
        items.forEach((item, i) => {
            item.classList.toggle('active', i === activeIndex);
        });
        if (activeIndex >= 0 && items[activeIndex]) {
            items[activeIndex].scrollIntoView({ block: 'nearest' });
        }
    }

    // --- Select Suggestion ---
    window.selectSuggestion = function (symbol) {
        input.value = symbol;
        hideSuggestions();
        form.submit();
    };

    // --- Show/Hide ---
    function showSuggestions() {
        suggestionsBox.classList.add('active');
    }

    function hideSuggestions() {
        suggestionsBox.classList.remove('active');
        activeIndex = -1;
    }

    function onDocumentClick(e) {
        if (!e.target.closest('.search-wrapper')) {
            hideSuggestions();
        }
    }

    // --- Form Submit: Show Loading ---
    if (form) {
        form.addEventListener('submit', function () {
            hideSuggestions();
            btnText.style.display = 'none';
            btnLoader.style.display = 'inline-flex';
            searchBtn.disabled = true;
        });
    }

    // --- No Results: Load Closest Matches ---
    const noResultsSection = document.getElementById('noResultsSection');
    const closestMatchesGrid = document.getElementById('closestMatchesGrid');

    if (noResultsSection && closestMatchesGrid) {
        const rawQuery = input ? input.value.trim() : '';
        if (rawQuery) {
            fetch(`/api/suggestions/?q=${encodeURIComponent(rawQuery)}`)
                .then(r => r.json())
                .then(data => {
                    if (data.length > 0) {
                        noResultsSection.style.display = 'block';
                        closestMatchesGrid.innerHTML = data.slice(0, 8).map(item => `
                            <a href="?symbol=${encodeURIComponent(item.symbol)}" class="closest-match-card">
                                <div class="match-card-icon">${item.sector_icon || '📊'}</div>
                                <div class="match-card-info">
                                    <div class="match-card-symbol">${escHtml(item.symbol)}</div>
                                    <div class="match-card-name">${escHtml(item.name)}</div>
                                    <div class="match-card-sector">${escHtml(item.sector || '')}</div>
                                </div>
                                <span class="match-card-arrow">←</span>
                            </a>
                        `).join('');
                    }
                })
                .catch(() => {});
        }
    }

    // --- Utility ---
    function escHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

})();