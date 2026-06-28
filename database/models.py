# database/models.py
from datetime import datetime
from sqlalchemy import String, Integer, BigInteger, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models using 2.0 style declarative mapping."""
    pass

class UserProfile(Base):
    __tablename__ = "user_profiles"

    # Discord IDs are large integers, mapped natively using BigInteger
    discord_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ingame_name: Mapped[str] = mapped_column(String(50), nullable=False)
    primary_weapon: Mapped[str | None] = mapped_column(String(50), nullable=True)     # e.g., "Greatsword"
    secondary_weapon: Mapped[str | None] = mapped_column(String(50), nullable=True)   # e.g., "Dagger"
    gear_score: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationship tracking sign-ups
    attendance = relationship("EventAttendance", back_populates="user", cascade="all, delete-orphan")

class GuildEvent(Base):
    __tablename__ = "guild_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    
    # Track states for automation
    is_posted: Mapped[bool] = mapped_column(Boolean, default=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Relationship to signups
    signups = relationship("EventAttendance", back_populates="event", cascade="all, delete-orphan")

class EventAttendance(Base):
    __tablename__ = "event_attendance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("guild_events.id", ondelete="CASCADE"))
    discord_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.discord_id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # 'attending', 'absent', 'tentative'
    selected_role: Mapped[str | None] = mapped_column(String(50), nullable=True) # Tank/Healer/DPS

    # Relationships linking back
    event = relationship("GuildEvent", back_populates="signups")
    user = relationship("UserProfile", back_populates="attendance")