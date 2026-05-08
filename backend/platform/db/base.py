from sqlalchemy.ext.asyncio import create_async_engine, AsyncAttrs
from sqlalchemy.orm import DeclarativeBase
from backend.platform.settings import get_settings


class Base(AsyncAttrs, DeclarativeBase):
    pass


def get_engine():
    return create_async_engine(get_settings().database_url, echo=False)
