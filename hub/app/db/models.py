"""SQLAlchemy async ORM models."""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True)
    sub = Column(String(512), unique=True, nullable=False, index=True)
    fabric_uuid = Column(String(255), nullable=True)
    roles_json = Column(Text, default="[]")
    admin = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    last_login = Column(DateTime, onupdate=func.now(), server_default=func.now())

    # relationships
    servers = relationship("Server", back_populates="user", cascade="all, delete-orphan")
    token_stores = relationship("TokenStore", back_populates="user", cascade="all, delete-orphan")


class Server(Base):
    __tablename__ = "servers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), default="")
    state = Column(String(32), default="stopped")  # pending | ready | stopping | stopped
    started_at = Column(DateTime, nullable=True)
    last_activity = Column(DateTime, nullable=True)
    pod_name = Column(String(255), nullable=True)

    user = relationship("User", back_populates="servers")


class TokenStore(Base):
    __tablename__ = "token_stores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    id_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    fabric_tokens_json = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, onupdate=func.now(), server_default=func.now())

    user = relationship("User", back_populates="token_stores")
