# database/db_setup.py
import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from database.models import Base

# Ensure the default data directory exists locally
DB_DIR = "./data"
os.makedirs(DB_DIR, exist_ok=True)
# Optional override via the DATABASE_URL environment variable; the default is unchanged.
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{DB_DIR}/guild_bot.db"

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False}  # Required for multi-threaded SQLite usage in async apps
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Create all tables if they do not exist."""
    Base.metadata.create_all(bind=engine)

def get_db() -> Generator[Session, None, None]:
    """Context manager generation for scoping db sessions inside cog executions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()