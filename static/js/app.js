// Global book delete handler used from books.html / browse_books.html
async function deleteBook(bookId, title) {
  const tpl = window.UI?.confirm_delete_book || 'Delete "%s"? This cannot be undone.';
  if (!confirm(tpl.replace('%s', title))) return;
  const resp = await fetch(`/api/books/${bookId}`, { method: 'DELETE' });
  if (resp.ok) {
    document.querySelector(`[onclick*="${bookId}"]`)?.closest('tr')?.remove();
  }
}
