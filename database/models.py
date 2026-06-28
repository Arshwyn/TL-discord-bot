# database/models.py
from datetime import datetime
from typing import List, Optional
from sqlalchemy import String, Integer, BigInteger, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(BaseModel := type("Base", (object,), {})):
    """Base class for all SQLAlchemy models using 2.0 style declarative mapping."""
    pass

class Base(discord.ext if False else object): # Placeholder wrapper for ORM declarative base
    pass

from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class UserProfile(Base):
    __tablename__ = "user_profiles"

    # Discord IDs are large integers, standard practice is BigInteger or String
    discord_id: Mapped[int] = column(BigInteger, primary_key=True)
    ingame_name: Mapped[str] = column(String(50), nullable=False)
    primary_weapon: Object = column(String(50), nullable=True)     # e.g., "Greatsword"
    secondary_weapon: Object = column(String(50), nullable=True)   # e.g., "Dagger"
    gear_score: Object = column(Integer, default=0)
    
    # Relationship to tracking sign-ups
    attendance = relationship("EventAttendance", back_populates="user", cascade="all, delete-orphan")

class GuildEvent(Base):
    __tablename__ = "guild_events"

    id: Mapped[int] = column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = column(String(100), nullable=False)
    description: Mapped[str] = column(String(500), nullable=True)
    start_time: Mapped[datetime] = column(DateTime, nullable=False)
    
    # Track states for automation
    is_posted: Mapped[bool] = column(Boolean, default=False)  # Has the 72h poll been deployed?
    message_id: Mapped[int | None] = column(BigInteger, nullable=True) # ID of the active poll embed

    # Relationship to signups
    signups = relationship("EventAttendance", back_populates="event", cascade="all, delete-orphan")

class EventAttendance(Base):
    __tablename__ = "event_attendance"

    id: Mapped[int] = column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = column(ForeignKey("events.id", ondelete="CASCADE"))
    discord_id: Mapped[int] = column(BigInteger, nullable=False)
    status: Mapped[str] = column(String(20))  # 'attending', 'absent', 'tentative'
    selected_role: Mapped[str | None] = column(String(50), nullable=True) # Tank/Healer/DPS at sign-up time