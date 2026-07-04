// ============================================
//  CODAL EXPERT - Main JavaScript
// ============================================

// --- SVG Icon Map for sectors (no emojis!) ---
var SECTOR_SVG = {
    "بانکی": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18M5 21V7l8-4v18M19 21V11l-6-4"/><path d="M9 9h.01M9 12h.01M9 15h.01M9 18h.01"/></svg>',
    "صنعت بیمه": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
    "خودرویی": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="1" y="3" width="15" height="13" rx="2"/><path d="M16 8h4l3 3v5a2 2 0 0 1-2 2h-1"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg>',
    "محصولات شیمیایی": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 3h6v8l4 8H5l4-8V3z"/><path d="M9 3h6"/><line x1="10" y1="14" x2="14" y2="14"/></svg>',
    "فلزات": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>',
    "فراورده‌های نفتی": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"/><path d="M12 6v6l4 2"/></svg>',
    "سیمانی": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="10" rx="2"/><path d="M16 7V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v3"/></svg>',
    "دارویی": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.5 1.5H8.25A2.25 2.25 0 006 3.75v16.5a2.25 2.25 0 002.25 2.25h7.5A2.25 2.25 0 0018 20.25V3.75a2.25 2.25 0 00-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3"/><path d="M10.5 8.25h3"/><path d="M10.5 11.25h3"/></svg>',
    "کانی‌های غیر فلزی": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>',
    "صنعت ساختمان": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>',
    "صنعت مواد غذایی": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8h1a4 4 0 010 8h-1"/><path d="M2 8h16v9a4 4 0 01-4 4H6a4 4 0 01-4-4V8z"/><line x1="6" y1="1" x2="6" y2="4"/><line x1="10" y1="1" x2="10" y2="4"/><line x1="14" y1="1" x2="14" y2="4"/></svg>',
    "صنعت کاشی": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
    "صنعت پیمانکاری": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>',
    "صنعت حمل و نقل": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="1" y="3" width="15" height="13" rx="2"/><path d="M16 8h2a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2h0"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg>',
    "صنعت رایانه": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>',
    "صنعت تولید برق": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
    "صنعت دستگاه‌های برقی": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>',
    "صنعت لاستیک": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><path d="M12 2a15 15 0 0 1 4 10 15 15 0 0 1-4 10"/><path d="M12 2a15 15 0 0 0-4 10 15 15 0 0 0 4 10"/></svg>',
    "ساخت محصولات فلزی": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>',
    "استخراج فلزات": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 22L12 2l10 20H2z"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    "سرمایه‌گذاری": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>',
    "کشاورزی": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 20h10"/><path d="M10 20c5.5-2.5.8-6.4 3-10"/><path d="M9.5 9.4c1.1.8 1.8 2.2 2.3 3.7-2 .4-3.5.4-4.8-.3-1.2-.6-2.3-1.9-3-4.2 2.8-.5 4.4 0 5.5.8z"/><path d="M14.1 6a7 7 0 00-1.1 4c1.9-.1 3.3-.6 4.3-1.4 1-1 1.6-2.3 1.7-4.6-2.7.1-4 1-4.9 2z"/></svg>',
};

var DEFAULT_SVG = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';

function getSectorSvg(sector) {
    if (!sector) return DEFAULT_SVG;
    var key = sector.replace(/\u200c/g, '').replace(/‌/g, '');
    // Direct match
    if (SECTOR_SVG[sector]) return SECTOR_SVG[sector];
    // Try normalizing keys
    for (var k in SECTOR_SVG) {
        if (k.replace(/\u200c/g, '').replace(/‌/g, '') === key) return SECTOR_SVG[k];
    }
    return DEFAULT_SVG;
}

(function () {
    'use strict';

    // --- Autocomplete ---
    var input = document.getElementById('symbolInput');
    var form = document.getElementById('searchForm');
    var suggestionsBox = document.getElementById('suggestionsBox');
    var activeIndex = -1;
    var debounceTimer = null;
    var currentResults = [];

    if (input && form) {
        input.addEventListener('input', function () {
            clearTimeout(debounceTimer);
            var q = input.value.trim();
            if (!q) { hideSuggestions(); return; }
            debounceTimer = setTimeout(function () { fetchSuggestions(q); }, 150);
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
            .then(function (r) { return r.json(); })
            .then(function (data) {
                currentResults = data;
                activeIndex = -1;
                if (data.length) { renderSuggestions(data, query); showSuggestions(); }
                else hideSuggestions();
            })
            .catch(function () { hideSuggestions(); });
    }

    function renderSuggestions(results, query) {
        var html = '<div class="suggestions-header"><span>نتایج پیشنهادی</span><span><span class="suggestions-count">' + results.length + '</span> شرکت</span></div>';
        for (var i = 0; i < results.length; i++) {
            var item = results[i];
            var sectorSvg = getSectorSvg(item.sector);
            html += '<div class="suggestion-item" data-index="' + i + '" data-symbol="' + esc(item.symbol) + '" onclick="window._selectSug(\'' + esc(item.symbol) + '\')">'
                + '<div class="suggestion-icon" style="color:var(--neon-cyan);">' + sectorSvg + '</div>'
                + '<div class="suggestion-info">'
                + '<div class="suggestion-symbol">' + highlight(item.symbol, query) + '</div>'
                + '<div class="suggestion-name">' + highlight(item.name, query) + '</div>'
                + '</div>'
                + '<div class="suggestion-sector">' + esc(item.sector || '') + '</div>'
                + '</div>';
        }
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
        for (var i = 0; i < items.length; i++) {
            items[i].classList.toggle('active', i === activeIndex);
        }
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
    var dropdownBtn = document.getElementById('sectorDropdownBtn');
    var dropdownPanel = document.getElementById('sectorDropdownPanel');
    var sectorSearch = document.getElementById('sectorDropdownSearch');
    var companyGrid = document.getElementById('companyGrid');
    var gridSection = document.getElementById('companyGridSection');
    var clearBtn = document.getElementById('sectorClearBtn');

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
                dropdownBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg> انتخاب صنعت...<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>';
                if (gridSection) gridSection.classList.remove('visible');
                clearBtn.style.display = 'none';
            });
        }
    }

    function filterSectors(query) {
        var items = dropdownPanel.querySelectorAll('.sector-dropdown-item');
        var q = query.toLowerCase();
        for (var i = 0; i < items.length; i++) {
            var name = (items[i].dataset.sector || '').toLowerCase();
            items[i].style.display = name.indexOf(q) >= 0 ? '' : 'none';
        }
    }

    window._selectSector = function (sector) {
        dropdownBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg> ' + esc(sector) + '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>';
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
                    for (var i = 0; i < companies.length; i++) {
                        var c = companies[i];
                        var svg = getSectorSvg(c.sector);
                        html += '<a href="/reports/' + encodeURIComponent(c.symbol) + '/" class="company-card">'
                            + '<div class="company-card-icon" style="color:var(--neon-cyan);">' + svg + '</div>'
                            + '<div class="company-card-info">'
                            + '<div class="company-card-symbol">' + esc(c.symbol) + '</div>'
                            + '<div class="company-card-name">' + esc(c.name) + '</div>'
                            + '</div>'
                            + '<span class="company-card-arrow"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg></span>'
                            + '</a>';
                    }
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