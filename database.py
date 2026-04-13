import aiosqlite
from typing import AsyncGenerator, Optional
from config import DB_PATH
from models import Book, Tag


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        yield db


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS books (
                id           TEXT PRIMARY KEY,
                title        TEXT NOT NULL,
                author       TEXT,
                description  TEXT,
                publisher    TEXT,
                language     TEXT DEFAULT 'en',
                published    TEXT,
                filename     TEXT NOT NULL,
                file_path    TEXT NOT NULL,
                file_size    INTEGER,
                format       TEXT NOT NULL,
                cover_path   TEXT,
                series       TEXT,
                series_index REAL,
                added_at     TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tags (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                name  TEXT UNIQUE NOT NULL
            );

            CREATE TABLE IF NOT EXISTS book_tags (
                book_id  TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                tag_id   INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                PRIMARY KEY (book_id, tag_id)
            );
        """)
        await db.commit()

        # Migrate existing databases that lack the series columns
        existing = {row[1] async for row in await db.execute("PRAGMA table_info(books)")}
        if "series" not in existing:
            await db.execute("ALTER TABLE books ADD COLUMN series TEXT")
        if "series_index" not in existing:
            await db.execute("ALTER TABLE books ADD COLUMN series_index REAL")
        await db.commit()


def _row_to_book(row: aiosqlite.Row) -> Book:
    return Book(
        id=row["id"],
        title=row["title"],
        author=row["author"],
        description=row["description"],
        publisher=row["publisher"],
        language=row["language"] or "en",
        published=row["published"],
        filename=row["filename"],
        file_path=row["file_path"],
        file_size=row["file_size"],
        format=row["format"],
        cover_path=row["cover_path"],
        series=row["series"],
        series_index=row["series_index"],
        added_at=row["added_at"],
        updated_at=row["updated_at"],
    )


async def get_books(
    db: aiosqlite.Connection,
    page: int = 0,
    page_size: int = 50,
    search: Optional[str] = None,
    tag: Optional[str] = None,
    author: Optional[str] = None,
    series: Optional[str] = None,
    order_by: str = "added_at DESC",
) -> tuple[list[Book], int]:
    params: list = []
    where_clauses: list[str] = []

    if search:
        where_clauses.append("(b.title LIKE ? OR b.author LIKE ? OR b.series LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])

    if tag:
        where_clauses.append(
            "b.id IN (SELECT bt.book_id FROM book_tags bt "
            "JOIN tags t ON bt.tag_id = t.id WHERE t.name = ?)"
        )
        params.append(tag)

    if author:
        where_clauses.append("b.author = ?")
        params.append(author)

    if series:
        where_clauses.append("b.series = ?")
        params.append(series)

    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    count_row = await db.execute_fetchall(
        f"SELECT COUNT(*) FROM books b {where}", params
    )
    total = count_row[0][0]

    rows = await db.execute_fetchall(
        f"SELECT b.* FROM books b {where} ORDER BY b.{order_by} LIMIT ? OFFSET ?",
        params + [page_size, page * page_size],
    )
    return [_row_to_book(r) for r in rows], total


async def get_book(db: aiosqlite.Connection, book_id: str) -> Optional[Book]:
    rows = await db.execute_fetchall("SELECT * FROM books WHERE id = ?", [book_id])
    return _row_to_book(rows[0]) if rows else None


async def insert_book(db: aiosqlite.Connection, book: Book) -> None:
    await db.execute(
        """INSERT INTO books
           (id, title, author, description, publisher, language, published,
            filename, file_path, file_size, format, cover_path,
            series, series_index, added_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            book.id, book.title, book.author, book.description,
            book.publisher, book.language, book.published,
            book.filename, book.file_path, book.file_size,
            book.format, book.cover_path,
            book.series, book.series_index,
            book.added_at, book.updated_at,
        ),
    )
    await db.commit()


async def update_book(db: aiosqlite.Connection, book_id: str, fields: dict) -> None:
    fields.pop("id", None)
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [book_id]
    await db.execute(f"UPDATE books SET {set_clause} WHERE id = ?", values)
    await db.commit()


async def delete_book(db: aiosqlite.Connection, book_id: str) -> None:
    await db.execute("DELETE FROM books WHERE id = ?", [book_id])
    await db.commit()


# ── Author / Series aggregates ────────────────────────────────────────────────

async def get_authors(db: aiosqlite.Connection) -> list[dict]:
    """Return list of {author, book_count, cover_path} sorted by author name."""
    rows = await db.execute_fetchall(
        """SELECT author,
                  COUNT(*) as book_count,
                  (SELECT cover_path FROM books b2
                   WHERE b2.author = b.author AND b2.cover_path IS NOT NULL
                   LIMIT 1) as cover_path
           FROM books b
           WHERE author IS NOT NULL AND author != ''
           GROUP BY author
           ORDER BY author COLLATE NOCASE"""
    )
    return [dict(r) for r in rows]


async def get_series_list(db: aiosqlite.Connection) -> list[dict]:
    """Return list of {series, book_count, cover_path} sorted by series name."""
    rows = await db.execute_fetchall(
        """SELECT series,
                  COUNT(*) as book_count,
                  (SELECT cover_path FROM books b2
                   WHERE b2.series = b.series AND b2.cover_path IS NOT NULL
                   ORDER BY b2.series_index NULLS LAST LIMIT 1) as cover_path
           FROM books b
           WHERE series IS NOT NULL AND series != ''
           GROUP BY series
           ORDER BY series COLLATE NOCASE"""
    )
    return [dict(r) for r in rows]


# ── Tags ──────────────────────────────────────────────────────────────────────

async def get_tags(db: aiosqlite.Connection) -> list[Tag]:
    rows = await db.execute_fetchall(
        "SELECT t.id, t.name, COUNT(bt.book_id) as book_count "
        "FROM tags t LEFT JOIN book_tags bt ON t.id = bt.tag_id "
        "GROUP BY t.id ORDER BY t.name"
    )
    return [Tag(id=r["id"], name=r["name"]) for r in rows]


async def get_book_tags(db: aiosqlite.Connection, book_id: str) -> list[Tag]:
    rows = await db.execute_fetchall(
        "SELECT t.id, t.name FROM tags t "
        "JOIN book_tags bt ON t.id = bt.tag_id WHERE bt.book_id = ? ORDER BY t.name",
        [book_id],
    )
    return [Tag(id=r["id"], name=r["name"]) for r in rows]


async def create_tag(db: aiosqlite.Connection, name: str) -> Tag:
    await db.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", [name])
    await db.commit()
    rows = await db.execute_fetchall("SELECT id, name FROM tags WHERE name = ?", [name])
    return Tag(id=rows[0]["id"], name=rows[0]["name"])


async def delete_tag(db: aiosqlite.Connection, tag_id: int) -> None:
    await db.execute("DELETE FROM tags WHERE id = ?", [tag_id])
    await db.commit()


async def rename_tag(db: aiosqlite.Connection, tag_id: int, new_name: str) -> None:
    await db.execute("UPDATE tags SET name = ? WHERE id = ?", [new_name, tag_id])
    await db.commit()


async def add_book_tag(db: aiosqlite.Connection, book_id: str, tag_id: int) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO book_tags (book_id, tag_id) VALUES (?, ?)",
        [book_id, tag_id],
    )
    await db.commit()


async def remove_book_tag(db: aiosqlite.Connection, book_id: str, tag_id: int) -> None:
    await db.execute(
        "DELETE FROM book_tags WHERE book_id = ? AND tag_id = ?", [book_id, tag_id]
    )
    await db.commit()
