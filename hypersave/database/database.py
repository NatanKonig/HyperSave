from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from hypersave.settings import Settings

settings = Settings()


class Database:
    def __init__(self):
        self._engine = create_engine(
            settings.database_url,
            pool_size=50,
            max_overflow=30,
            pool_recycle=1800,
            pool_pre_ping=True,
        )
        self._Session = sessionmaker(bind=self._engine)

    def create_tables(self):
        from hypersave.database.base import BaseRepository

        base_repository = BaseRepository()
        base_repository.metadata.create_all(self._engine)

    def get_session(self):
        return self._Session()
