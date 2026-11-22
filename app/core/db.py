import os
import sys
from typing import Generator, Optional, Any
from sqlmodel import SQLModel, create_engine, Session

from app.core.config import settings
import app.models  # Ensures all models are registered with SQLModel metadata


def get_sqlite_engine(db_url: str = settings.DATABASE_URL):
    # Ensure directory exists if SQLite local file path
    if db_url.startswith("sqlite:///"):
        file_path = db_url.replace("sqlite:///", "")
        dir_name = os.path.dirname(file_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

    return create_engine(
        db_url,
        echo=False,
        connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {},
    )


engine = get_sqlite_engine()


def init_db(engine_instance=None) -> None:
    """Create all database tables based on registered SQLModel definitions."""
    target_engine = engine_instance or engine
    SQLModel.metadata.create_all(target_engine)


def get_session(engine_instance=None) -> Generator[Session, None, None]:
    """Yield a database session for use in requests or services."""
    target_engine = engine_instance or engine
    with Session(target_engine) as session:
        yield session


def get_setting(key: str, default: Optional[str] = None, engine_instance=None) -> Optional[str]:
    """Retrieve system configuration value from system_settings table."""
    from app.models.entities import SystemSetting
    target_engine = engine_instance or engine
    with Session(target_engine) as session:
        row = session.get(SystemSetting, key)
        return row.value if row else default


def set_setting(key: str, value: str, description: Optional[str] = None, engine_instance=None):
    """Upsert system configuration value into system_settings table."""
    from app.models.entities import SystemSetting, utcnow
    target_engine = engine_instance or engine
    with Session(target_engine) as session:
        row = session.get(SystemSetting, key)
        if row:
            row.value = value
            row.updated_at = utcnow()
            if description:
                row.description = description
        else:
            row = SystemSetting(key=key, value=value, description=description, updated_at=utcnow())
            session.add(row)
        session.commit()
        session.refresh(row)
        return row


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        print(f"Initializing database at: {settings.DATABASE_URL}...")
        init_db()
        print("Database schema successfully created!")
    else:
        print("Usage: python -m app.core.db init")
