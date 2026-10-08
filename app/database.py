from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import settings
from database_options import database_options

database_url, engine_options = database_options(settings)
engine = create_async_engine(database_url, **engine_options)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    async with async_session_maker() as session:
        yield session
