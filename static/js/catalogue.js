// Catalogue toolbar: picking a sort order applies it immediately.
// Search text and category still submit on Enter or the Search button.
function submitOnSortChange() {
    const sortSelect = document.getElementById('catalogueSort');
    const filtersForm = document.getElementById('catalogueFilters');
    if (!sortSelect || !filtersForm) {
        return;
    }
    sortSelect.addEventListener('change', function() {
        if (typeof filtersForm.requestSubmit === 'function') {
            filtersForm.requestSubmit();
        } else {
            filtersForm.submit();
        }
    });
}

function initCatalogueFilters() {
    submitOnSortChange();
}

document.addEventListener('DOMContentLoaded', initCatalogueFilters);
