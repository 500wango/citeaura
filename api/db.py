"""数据库连接和会话。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from api import config


DATABASE_URL = config.database_url()

engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """提供一个请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
