// ── Single book delete ────────────────────────────────────────────────────────
async function deleteBook(bookId, title) {
  const tpl = window.UI?.confirm_delete_book || 'Delete "%s"? This cannot be undone.';
  if (!confirm(tpl.replace('%s', title))) return;
  const resp = await fetch(`/api/books/${bookId}`, { method: 'DELETE' });
  if (resp.ok) {
    document.querySelector(`tr[data-book-id="${bookId}"]`)?.remove();
    updateBulkBar();
  }
}

// ── Bulk selection ────────────────────────────────────────────────────────────
function selectedIds() {
  return Array.from(document.querySelectorAll('.book-select:checked')).map(c => c.value);
}

function updateBulkBar() {
  const ids = selectedIds();
  const bar = document.getElementById('bulk-bar');
  const countEl = document.getElementById('bulk-count');
  if (!bar) return;
  if (ids.length === 0) {
    bar.style.display = 'none';
  } else {
    bar.style.display = 'flex';
    const tpl = ids.length === 1
      ? (window.UI?.bulk_selected_singular || '1 book selected')
      : (window.UI?.bulk_selected || '%d books selected').replace('%d', ids.length);
    countEl.textContent = tpl;
  }
  document.querySelectorAll('#books-table tbody tr').forEach(tr => {
    const cb = tr.querySelector('.book-select');
    tr.classList.toggle('selected-row', cb?.checked === true);
  });
}

function clearSelection() {
  document.querySelectorAll('.book-select').forEach(c => c.checked = false);
  const selectAll = document.getElementById('select-all');
  if (selectAll) selectAll.checked = false;
  updateBulkBar();
}

document.addEventListener('DOMContentLoaded', () => {
  const selectAll = document.getElementById('select-all');
  if (!selectAll) return;

  selectAll.addEventListener('change', () => {
    document.querySelectorAll('.book-select').forEach(c => c.checked = selectAll.checked);
    updateBulkBar();
  });

  document.querySelectorAll('.book-select').forEach(cb => {
    cb.addEventListener('change', () => {
      const all = document.querySelectorAll('.book-select');
      const checked = document.querySelectorAll('.book-select:checked');
      selectAll.indeterminate = checked.length > 0 && checked.length < all.length;
      selectAll.checked = checked.length === all.length;
      updateBulkBar();
    });
  });
});

// ── Bulk delete ───────────────────────────────────────────────────────────────
async function bulkDelete() {
  const ids = selectedIds();
  if (ids.length === 0) return;
  const tpl = (window.UI?.bulk_delete_confirm || 'Delete %d books? This cannot be undone.').replace('%d', ids.length);
  if (!confirm(tpl)) return;

  const resp = await fetch('/api/books/bulk-delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  });
  if (!resp.ok) { alert(window.UI?.bulk_delete_failed || 'Delete failed'); return; }

  ids.forEach(id => document.querySelector(`tr[data-book-id="${id}"]`)?.remove());
  clearSelection();
}

// ── Bulk edit ─────────────────────────────────────────────────────────────────
function bulkEdit() {
  const ids = selectedIds();
  if (ids.length === 0) return;
  ['bulk-author','bulk-series','bulk-series-index','bulk-language','bulk-add-tags','bulk-remove-tags']
    .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });

  const countEl = document.getElementById('bulk-modal-count');
  if (countEl) {
    const tpl = (window.UI?.bulk_apply_btn || 'Apply to %d books').replace('%d', ids.length);
    countEl.textContent = tpl;
  }
  new bootstrap.Modal(document.getElementById('bulkEditModal')).show();
}

async function bulkEditSubmit() {
  const ids = selectedIds();
  if (ids.length === 0) return;

  const body = { ids };
  const author = document.getElementById('bulk-author').value.trim();
  const series = document.getElementById('bulk-series').value.trim();
  const seriesIndex = document.getElementById('bulk-series-index').value.trim();
  const language = document.getElementById('bulk-language').value.trim();
  const addTagsRaw = document.getElementById('bulk-add-tags').value.trim();
  const removeTagsRaw = document.getElementById('bulk-remove-tags').value.trim();

  if (author)        body.author = author;
  if (series !== '')  body.series = series;
  if (seriesIndex)   body.series_index = seriesIndex;
  if (language)      body.language = language;
  if (addTagsRaw)    body.add_tags    = addTagsRaw.split(',').map(s => s.trim()).filter(Boolean);
  if (removeTagsRaw) body.remove_tags = removeTagsRaw.split(',').map(s => s.trim()).filter(Boolean);

  bootstrap.Modal.getInstance(document.getElementById('bulkEditModal'))?.hide();

  const resp = await fetch('/api/books/bulk-edit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) { alert(window.UI?.bulk_edit_failed || 'Edit failed'); return; }

  clearSelection();
  location.reload();
}
