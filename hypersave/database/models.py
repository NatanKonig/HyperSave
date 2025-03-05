from sqlalchemy import (
    BIGINT,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    t_id = Column(BIGINT, primary_key=True)
    t_name = Column(String(100))
    t_username = Column(String(50), unique=True)
    session_string = Column(Text)
    authorized = Column(Boolean, default=False)

    def __init__(self, t_id, t_name, t_username, session_string, authorized):
        self.t_id = t_id
        self.t_name = t_name
        self.t_username = t_username
        self.session_string = session_string
        self.authorized = authorized

    def __str__(self):
        name = None if self.t_name == "" else self.t_name
        username = f"@{self.t_username}" if self.t_username else ""
        return f"{name} - {username}".strip()
