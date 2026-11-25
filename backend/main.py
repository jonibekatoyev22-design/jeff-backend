from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.config import settings
from app.database import engine, Base
from app.routers import auth, data, files

Base.metadata.create_all(bind=engine)

# Lightweight, idempotent column migration — there's no Alembic here, and
# create_all() only creates tables that don't exist yet, never adds columns
# to a table that's already live in Postgres. Safe to run on every boot.
def _migrate():
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR"))
            conn.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE"))
    except Exception:
        pass  # e.g. local sqlite dev DB, which doesn't support IF NOT EXISTS here — harmless

_migrate()

app = FastAPI(title="Jeff Accountant API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(data.router)
app.include_router(files.router)

@app.get("/")
def health():
    return {"status": "ok", "app": "Jeff Accountant API"}
