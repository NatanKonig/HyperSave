from hypersave.database.database import Database
from hypersave.database.models import Base
from hypersave.logger import logger


class BaseRepository:
    def __init__(self):
        self.database = Database()
        self._session = self.database.get_session()
        self.metadata = Base.metadata

    def commit(self):
        try:
            self._session.commit()
        except Exception as e:
            self._session.rollback()
            logger.error(f"Error committing transaction: {e}")
            raise

    def close(self):
        self._session.close()
