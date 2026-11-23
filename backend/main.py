from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import engine, Base
from app.routers import auth, data

# Create all tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Jeff Accountant API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(data.router)

@app.get("/")
def health():
    return {"status": "ok", "app": "Jeff Accountant API"}
