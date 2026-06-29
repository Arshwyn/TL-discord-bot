# database/models.py
from datetime import datetime
from sqlalchemy import String, Integer, BigInteger, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class UserProfile(Base):
    __tablename__ = "user_profiles"
    discord_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ingame_name: Mapped[str] = mapped_column(String(50), nullable=False)
    primary_weapon: Mapped[str | None] = mapped_column(String(50), nullable=True)     
    secondary_weapon: Mapped[str | None] = mapped_column(String(50), nullable=True)   
    gear_score: Mapped[int] = mapped_column(Integer, default=0)
    
    # NEW: Tracks which static party the user belongs to
    static_group: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    attendance = relationship("EventAttendance", back_populates="user", cascade="all, delete-orphan")

class GuildEvent(Base):
    __tablename__ = "guild_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    recurrence_days: Mapped[int] = mapped_column(Integer, default=0) 
    requires_rsvp: Mapped[bool] = mapped_column(Boolean, default=True)
    
    notify_schedule: Mapped[str] = mapped_column(String(100), default="4320")
    notifies_sent: Mapped[str] = mapped_column(String(100), default="")       
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)        
    
    is_posted: Mapped[bool] = mapped_column(Boolean, default=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    signups = relationship("EventAttendance", back_populates="event", cascade="all, delete-orphan")

class EventAttendance(Base):
    __tablename__ = "event_attendance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("guild_events.id", ondelete="CASCADE"))
    discord_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.discord_id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  
    selected_role: Mapped[str | None] = mapped_column(String(50), nullable=True) 
    event = relationship("GuildEvent", back_populates="signups")
    user = relationship("UserProfile", back_populates="attendance")

class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_name: Mapped[str] = mapped_column(String(100), nullable=False)
    event_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ingame_name: Mapped[str] = mapped_column(String(50), nullable=False)
    signup_status: Mapped[str] = mapped_column(String(20), nullable=False) 
    actual_presence: Mapped[str] = mapped_column(String(20), nullable=False)