"""FastAPI entry point."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_engine

app = FastAPI(title="Alibi Recovery Manager", version="0.1.0")


@app.get("/health")
def health() -> JSONResponse:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "db": "unavailable", "error": type(exc).__name__},
        )
    return JSONResponse(content={"status": "ok", "db": "ok"})
