// Global book delete handler used from books.html
async function deleteBook(bookId, title) {
  if (!confirm(`Delete "${title}"? This cannot be undone.`)) return;
  const resp = await fetch(`/api/books/${bookId}`, { method: 'DELETE' });
  if (resp.ok) {
    const row = document.querySelector(`[onclick*="${bookId}"]`)?.closest('tr');
    row?.remove();
  }
}
