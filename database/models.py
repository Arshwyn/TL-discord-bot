# database/models.py
from datetime import datetime
from sqlalchemy import String, Integer, BigInteger, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class UserProfile(Base):
    __tablename__ = "user_profiles"
    # Composite Primary Key: Discord ID + Custom Build Name
    discord_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    build_name: Mapped[str] = mapped_column(String(50), primary_key=True) 
    
    build_type: Mapped[str] = mapped_column(String(20), nullable=False) # 'PvE' or 'PvP'
    ingame_name: Mapped[str] = mapped_column(String(50), nullable=False)
    primary_weapon: Mapped[str | None] = mapped_column(String(50), nullable=True)     
    secondary_weapon: Mapped[str | None] = mapped_column(String(50), nullable=True)   
    gear_score: Mapped[int] = mapped_column(Integer, default=0)
    static_group: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gear_screenshot_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    loot_wins: Mapped[int] = mapped_column(Integer, default=0) 
    attendance = relationship("EventAttendance", back_populates="user", cascade="all, delete-orphan")

class GuildEvent(Base):
    __tablename__ = "guild_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    recurrence_days: Mapped[int] = mapped_column(Integer, default=0) 
    requires_rsvp: Mapped[bool] = mapped_column(Boolean, default=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    voice_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
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
    
    discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  
    selected_role: Mapped[str | None] = mapped_column(String(50), nullable=True) 
    
    event = relationship("GuildEvent", back_populates="signups")
    # Setup relationship mapping
    user = relationship(
        "UserProfile", 
        primaryjoin="EventAttendance.discord_id==UserProfile.discord_id",
        foreign_keys=[discord_id],
        back_populates="attendance",
        viewonly=True
    )

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

class LootItem(Base):
    __tablename__ = "loot_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_name: Mapped[str] = mapped_column(String(100), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False) 
    winner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rolls = relationship("LootRoll", back_populates="item", cascade="all, delete-orphan")

class LootRoll(Base):
    __tablename__ = "loot_rolls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    loot_item_id: Mapped[int] = mapped_column(ForeignKey("loot_items.id", ondelete="CASCADE"))
    discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    roll_type: Mapped[str] = mapped_column(String(20), nullable=False) 
    item = relationship("LootItem", back_populates="rolls")

class BotConfig(Base):
    __tablename__ = "bot_config"
    setting_key: Mapped[str] = mapped_column(String(50), primary_key=True)
    setting_value: Mapped[str] = mapped_column(String(255), nullable=False)