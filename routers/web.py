from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import aiosqlite

import urllib.parse

import database
import config
from database import get_db
from ui_strings import get_active, list_locales, set_language, get_current_lang

router = APIRouter()
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))
templates.env.filters["urlencode"] = urllib.parse.quote
templates.env.globals["ui"] = get_active()          # same dict object, mutated on lang change
templates.env.globals["SERVER_TITLE"] = config.SERVER_TITLE


def _filesize(n: int | None) -> str:
    if not n:
        return ""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


templates.env.filters["filesize"] = _filesize


@router.get("/", response_class=RedirectResponse)
async def index():
    return RedirectResponse("/books")


@router.get("/books", response_class=HTMLResponse)
async def books_page(
    request: Request,
    page: int = Query(0, ge=0),
    q: str = Query(""),
    tag: str = Query(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    books, total = await database.get_books(
        db,
        page=page,
        page_size=config.PAGE_SIZE,
        search=q or None,
        tag=tag or None,
    )
    tags = await database.get_tags(db)
    pages = (total + config.PAGE_SIZE - 1) // config.PAGE_SIZE

    tag_map = await database.get_book_tags_map(db, [b.id for b in books])

    return templates.TemplateResponse(
        "books.html",
        {
            "request": request,
            "books": books,
            "tags": tags,
            "total": total,
            "page": page,
            "pages": pages,
            "q": q,
            "tag": tag,
            "page_size": config.PAGE_SIZE,
            "tag_map": tag_map,
        },
    )


@router.get("/books/{book_id}/edit", response_class=HTMLResponse)
async def book_edit_page(
    book_id: str,
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
):
    book = await database.get_book(db, book_id)
    if not book:
        return HTMLResponse("Book not found", status_code=404)
    book_tags = await database.get_book_tags(db, book_id)
    all_tags = await database.get_tags(db)
    return templates.TemplateResponse(
        "book_edit.html",
        {
            "request": request,
            "book": book,
            "book_tags": book_tags,
            "all_tags": all_tags,
        },
    )


@router.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})


@router.get("/tags", response_class=HTMLResponse)
async def tags_page(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    tags = await database.get_tags(db)
    return templates.TemplateResponse("tags.html", {"request": request, "tags": tags})


@router.get("/authors", response_class=HTMLResponse)
async def authors_page(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    authors = await database.get_authors(db)
    return templates.TemplateResponse("authors.html", {"request": request, "authors": authors})


@router.get("/authors/{author_name}", response_class=HTMLResponse)
async def author_books_page(
    author_name: str,
    request: Request,
    page: int = Query(0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    author = urllib.parse.unquote(author_name)
    books, total = await database.get_books(
        db, page=page, page_size=config.PAGE_SIZE,
        author=author, order_by="series NULLS LAST, series_index NULLS LAST, title",
    )
    pages = (total + config.PAGE_SIZE - 1) // config.PAGE_SIZE
    return templates.TemplateResponse(
        "browse_books.html",
        {
            "request": request,
            "books": books,
            "total": total,
            "page": page,
            "pages": pages,
            "browse_title": author,
            "back_url": "/authors",
            "back_label": get_active()["nav_authors"],
            "page_url_base": f"/authors/{author_name}",
        },
    )


@router.get("/series", response_class=HTMLResponse)
async def series_page(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    series_list = await database.get_series_list(db)
    return templates.TemplateResponse("series.html", {"request": request, "series_list": series_list})


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "locales": list_locales(),
            "current_lang": get_current_lang(),
        },
    )


@router.post("/settings/language", response_class=RedirectResponse)
async def change_language(lang: str = Form(...)):
    available = {loc["code"] for loc in list_locales()}
    if lang in available:
        set_language(lang)
    return RedirectResponse("/settings", status_code=303)


@router.get("/series/{series_name}", response_class=HTMLResponse)
async def series_books_page(
    series_name: str,
    request: Request,
    page: int = Query(0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    series = urllib.parse.unquote(series_name)
    books, total = await database.get_books(
        db, page=page, page_size=config.PAGE_SIZE,
        series=series, order_by="series_index NULLS LAST, title",
    )
    pages = (total + config.PAGE_SIZE - 1) // config.PAGE_SIZE
    return templates.TemplateResponse(
        "browse_books.html",
        {
            "request": request,
            "books": books,
            "total": total,
            "page": page,
            "pages": pages,
            "browse_title": series,
            "back_url": "/series",
            "back_label": get_active()["nav_series"],
            "page_url_base": f"/series/{series_name}",
            "show_series_index": True,
        },
    )
