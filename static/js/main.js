// ============================================
//  CODAL EXPERT - Main JavaScript
// ============================================

(function () {
    'use strict';

    // --- Autocomplete ---
    const input = document.getElementById('symbolInput');
    const form = document.getElementById('searchForm');
    const suggestionsBox = document.getElementById('suggestionsBox');
    let activeIndex = -1;
    let debounceTimer = null;
    let currentResults = [];

    if (input && form) {
        input.addEventListener('input', function () {
            clearTimeout(debounceTimer);
            const q = input.value.trim();
            if (!q) { hideSuggestions(); return; }
            debounceTimer = setTimeout(() => fetchSuggestions(q), 150);
        });
        input.addEventListener('keydown', onKeyDown);
        input.addEventListener('focus', function () {
            if (input.value.trim()) {
                clearTimeout(debounceTimer);
                fetchSuggestions(input.value.trim());
            }
        });
        document.addEventListener('click', function (e) {
            if (!e.target.closest('.search-wrapper')) hideSuggestions();
        });
    }

    function fetchSuggestions(query) {
        fetch('/api/suggestions/?q=' + encodeURIComponent(query))
            .then(r => r.json())
            .then(data => {
                currentResults = data;
                activeIndex = -1;
                if (data.length) { renderSuggestions(data, query); showSuggestions(); }
                else hideSuggestions();
            })
            .catch(() => hideSuggestions());
    }

    function renderSuggestions(results, query) {
        let html = '<div class="suggestions-header"><span>نتایج پیشنهادی</span><span><span class="suggestions-count">' + results.length + '</span> شرکت</span></div>';
        results.forEach(function (item, idx) {
            html += '<div class="suggestion-item" data-index="' + idx + '" data-symbol="' + esc(item.symbol) + '" onclick="window._selectSug(\'' + esc(item.symbol) + '\')">'
                + '<div class="suggestion-icon">' + esc(item.sector_icon || '') + '</div>'
                + '<div class="suggestion-info">'
                + '<div class="suggestion-symbol">' + highlight(item.symbol, query) + '</div>'
                + '<div class="suggestion-name">' + highlight(item.name, query) + '</div>'
                + '</div>'
                + '<div class="suggestion-sector">' + esc(item.sector || '') + '</div>'
                + '</div>';
        });
        suggestionsBox.innerHTML = html;
    }

    function onKeyDown(e) {
        var items = suggestionsBox.querySelectorAll('.suggestion-item');
        if (!items.length || !suggestionsBox.classList.contains('active')) return;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            activeIndex = Math.min(activeIndex + 1, items.length - 1);
            updateActive(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            activeIndex = Math.max(activeIndex - 1, -1);
            updateActive(items);
        } else if (e.key === 'Enter' && activeIndex >= 0) {
            e.preventDefault();
            window._selectSug(items[activeIndex].dataset.symbol);
        } else if (e.key === 'Escape') {
            hideSuggestions();
        }
    }

    function updateActive(items) {
        items.forEach(function (el, i) { el.classList.toggle('active', i === activeIndex); });
        if (activeIndex >= 0 && items[activeIndex]) items[activeIndex].scrollIntoView({ block: 'nearest' });
    }

    window._selectSug = function (sym) {
        input.value = sym;
        hideSuggestions();
        window.location.href = '/reports/' + encodeURIComponent(sym) + '/';
    };

    function showSuggestions() { suggestionsBox.classList.add('active'); }
    function hideSuggestions() { suggestionsBox.classList.remove('active'); activeIndex = -1; }

    // --- Sector Dropdown ---
    const dropdownBtn = document.getElementById('sectorDropdownBtn');
    const dropdownPanel = document.getElementById('sectorDropdownPanel');
    const sectorSearch = document.getElementById('sectorDropdownSearch');
    const companyGrid = document.getElementById('companyGrid');
    const gridSection = document.getElementById('companyGridSection');
    const clearBtn = document.getElementById('sectorClearBtn');

    if (dropdownBtn && dropdownPanel) {
        dropdownBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            var isOpen = dropdownPanel.classList.contains('open');
            dropdownPanel.classList.toggle('open');
            dropdownBtn.classList.toggle('open');
            if (!isOpen && sectorSearch) { sectorSearch.value = ''; sectorSearch.focus(); filterSectors(''); }
        });

        document.addEventListener('click', function (e) {
            if (!e.target.closest('.sector-dropdown-wrap')) {
                dropdownPanel.classList.remove('open');
                dropdownBtn.classList.remove('open');
            }
        });

        if (sectorSearch) {
            sectorSearch.addEventListener('input', function () { filterSectors(sectorSearch.value); });
        }

        if (clearBtn) {
            clearBtn.addEventListener('click', function () {
                dropdownBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg> انتخاب صنعت...';
                if (gridSection) gridSection.classList.remove('visible');
                clearBtn.style.display = 'none';
            });
        }
    }

    function filterSectors(query) {
        var items = dropdownPanel.querySelectorAll('.sector-dropdown-item');
        var q = query.toLowerCase();
        items.forEach(function (item) {
            var name = (item.dataset.sector || '').toLowerCase();
            item.style.display = name.indexOf(q) >= 0 ? '' : 'none';
        });
    }

    window._selectSector = function (sector) {
        dropdownBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg> ' + esc(sector);
        dropdownPanel.classList.remove('open');
        dropdownBtn.classList.remove('open');
        if (clearBtn) clearBtn.style.display = 'inline-flex';

        // Load companies via AJAX
        if (companyGrid && gridSection) {
            companyGrid.innerHTML = '<div class="empty-state"><div class="spinner"></div><p style="margin-top:0.75rem">در حال بارگذاری...</p></div>';
            gridSection.classList.add('visible');

            fetch('/api/companies/?sector=' + encodeURIComponent(sector))
                .then(function (r) { return r.json(); })
                .then(function (companies) {
                    if (!companies.length) {
                        companyGrid.innerHTML = '<div class="empty-state"><p>شرکتی در این صنعت یافت نشد</p></div>';
                        return;
                    }
                    var html = '<div class="company-grid-header"><h3>شرکت‌های ' + esc(sector) + '</h3><span class="grid-count">' + companies.length + ' شرکت</span></div><div class="company-grid">';
                    companies.forEach(function (c) {
                        html += '<a href="/reports/' + encodeURIComponent(c.symbol) + '/" class="company-card">'
                            + '<div class="company-card-icon">' + esc(c.sector_icon || '') + '</div>'
                            + '<div class="company-card-info">'
                            + '<div class="company-card-symbol">' + esc(c.symbol) + '</div>'
                            + '<div class="company-card-name">' + esc(c.name) + '</div>'
                            + '</div>'
                            + '<span class="company-card-arrow"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg></span>'
                            + '</a>';
                    });
                    html += '</div>';
                    companyGrid.innerHTML = html;
                })
                .catch(function () {
                    companyGrid.innerHTML = '<div class="empty-state"><p>خطا در بارگذاری</p></div>';
                });
        }
    };

    // --- Reports page: show nav link ---
    var reportsNavLink = document.getElementById('reportsNavLink');
    if (reportsNavLink) {
        reportsNavLink.style.display = '';
    }

    // --- Utility ---
    function esc(str) {
        if (!str) return '';
        var d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    function highlight(text, query) {
        if (!text || !query) return esc(text);
        var idx = text.toLowerCase().indexOf(query.toLowerCase());
        if (idx === -1) return esc(text);
        return esc(text.substring(0, idx))
            + '<span class="highlight-match">' + esc(text.substring(idx, idx + query.length)) + '</span>'
            + esc(text.substring(idx + query.length));
    }

})();