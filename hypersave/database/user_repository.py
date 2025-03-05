from hypersave.database.base import BaseRepository
from hypersave.database.models import User
from hypersave.logger import logger


class UserRepository(BaseRepository):
    def __init__(self):
        super().__init__()

    def get_all(self):
        try:
            return self._session.query(User).all()
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []

    def get_by_id(self, t_id):
        try:
            return self._session.query(User).filter(User.t_id == t_id).first()
        except Exception as e:
            logger.error(f"Error getting user by id: {e}")
            return None
