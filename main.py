import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import config
from database import init_db
from routers import opds, api, web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.BOOKS_DIR.mkdir(exist_ok=True)
    config.COVERS_DIR.mkdir(exist_ok=True)
    await init_db()
    yield


app = FastAPI(title=config.SERVER_TITLE, docs_url="/api/docs", lifespan=lifespan)


# /files/{uuid}.ext serves with UUID name (internal use / direct links)
# /download/{uuid}.ext serves with human-readable Content-Disposition filename
app.mount("/files", StaticFiles(directory=str(config.BOOKS_DIR)), name="files")
app.mount("/covers", StaticFiles(directory=str(config.COVERS_DIR)), name="covers")
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

app.include_router(opds.router)
app.include_router(api.router)
app.include_router(web.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
