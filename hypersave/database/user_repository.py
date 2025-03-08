from hypersave.database.base import BaseRepository
from hypersave.database.models import User
from hypersave.logger import logger


class UserRepository(BaseRepository):
    def __init__(self):
        super().__init__()

    def add(self, user):
        try:
            self._session.merge(user)
            self._session.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False

    def add_string_session(self, t_id, session_string):
        try:
            user = self.get_by_id(t_id)
            user.session_string = session_string
            self._session.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding session string: {e}")
            return False

    def get_string_session(self, t_id):
        try:
            user = self.get_by_id(t_id)
            if not user:
                return None
            return user.session_string
        except Exception as e:
            logger.error(f"Error getting session string: {e}")
            return None

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
