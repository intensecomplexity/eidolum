import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from database import Base


class Forecaster(Base):
    __tablename__ = "forecasters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    handle = Column(String, unique=True, nullable=False)
    channel_id = Column(String, unique=True, nullable=True)
    platform = Column(String, default="youtube")  # "youtube" | "reddit" | "x"
    channel_url = Column(String, nullable=True)
    subscriber_count = Column(Integer, default=0)
    profile_image_url = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    rank_last_week = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Quota-safe sync fields
    uploads_playlist_id = Column(String, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    last_fetched_video_id = Column(String, nullable=True)

    videos = relationship("Video", back_populates="forecaster", cascade="all, delete-orphan")
    predictions = relationship("Prediction", back_populates="forecaster", cascade="all, delete-orphan")


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, index=True)
    forecaster_id = Column(Integer, ForeignKey("forecasters.id"), nullable=False)
    youtube_id = Column(String, unique=True, nullable=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    published_at = Column(DateTime, nullable=True)
    thumbnail_url = Column(String, nullable=True)
    view_count = Column(Integer, default=0)

    # Quota-safe tracking fields
    fetched_at = Column(DateTime, default=datetime.datetime.utcnow)
    raw_title = Column(String, nullable=True)
    raw_description = Column(Text, nullable=True)
    processed = Column(Integer, default=0)  # 0=unprocessed, 1=processed

    forecaster = relationship("Forecaster", back_populates="videos")
    predictions = relationship("Prediction", back_populates="video")


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    forecaster_id = Column(Integer, ForeignKey("forecasters.id"), nullable=False)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=True)

    ticker = Column(String, nullable=False, index=True)
    direction = Column(String, nullable=False)       # "bullish" | "bearish"
    target_price = Column(Float, nullable=True)
    entry_price = Column(Float, nullable=True)
    prediction_date = Column(DateTime, nullable=False)
    evaluation_date = Column(DateTime, nullable=True)
    window_days = Column(Integer, default=30)
    time_horizon = Column(String, nullable=True)  # "short" | "medium" | "long" | "custom"

    # "correct" | "incorrect" | "pending"
    outcome = Column(String, default="pending")
    actual_return = Column(Float, nullable=True)     # percent, e.g. 12.5
    sp500_return = Column(Float, nullable=True)
    alpha = Column(Float, nullable=True)             # actual_return - sp500_return

    # Simulated current movement for pending predictions (demo)
    current_return = Column(Float, nullable=True)

    # Conflict of interest
    has_conflict = Column(Integer, default=0)  # 0 or 1 (SQLite boolean)
    conflict_note = Column(Text, nullable=True)

    sector = Column(String, nullable=True)
    context = Column(Text, nullable=True)            # snippet from title/desc

    # Evidence system
    exact_quote = Column(Text, nullable=True)
    quote_context = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)
    source_type = Column(String, nullable=True)  # 'youtube'|'twitter'|'reddit'|'article'
    source_title = Column(Text, nullable=True)
    source_platform_id = Column(String, nullable=True)
    video_timestamp_sec = Column(Integer, nullable=True)
    verified_by = Column(String, nullable=True)  # 'ai_parsed'|'manual'|'auto_title'

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    forecaster = relationship("Forecaster", back_populates="predictions")
    video = relationship("Video", back_populates="predictions")


class ActivityFeedItem(Base):
    __tablename__ = "activity_feed"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String, nullable=False)  # "prediction_new" | "prediction_resolved" | "rank_change" | "forecaster_added"
    forecaster_id = Column(Integer, ForeignKey("forecasters.id"), nullable=True)
    ticker = Column(String, nullable=True)
    direction = Column(String, nullable=True)
    outcome = Column(String, nullable=True)
    actual_return = Column(Float, nullable=True)
    message = Column(Text, nullable=False)
    rank_from = Column(Integer, nullable=True)
    rank_to = Column(Integer, nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class QuotaLog(Base):
    __tablename__ = "quota_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    endpoint = Column(String, nullable=False)
    units = Column(Integer, nullable=False)
    total_today = Column(Integer, nullable=False)


class UserFollow(Base):
    __tablename__ = "user_follows"
    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, nullable=False, index=True)
    forecaster_id = Column(Integer, ForeignKey("forecasters.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class AlertPreference(Base):
    __tablename__ = "alert_preferences"
    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, nullable=False, index=True)
    alert_type = Column(String, nullable=False)  # 'new_prediction' | 'prediction_resolved' | 'rank_change' | 'weekly_digest'
    enabled = Column(Integer, default=1)  # 0 or 1

class AlertQueue(Base):
    __tablename__ = "alert_queue"
    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    scheduled_at = Column(DateTime, default=datetime.datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)
    type = Column(String, nullable=False)  # matches alert_type

class NewsletterSubscriber(Base):
    __tablename__ = "newsletter_subscribers"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False)
    subscribed_at = Column(DateTime, default=datetime.datetime.utcnow)
    unsubscribed_at = Column(DateTime, nullable=True)


class SavedPrediction(Base):
    __tablename__ = "saved_predictions"
    id = Column(Integer, primary_key=True, index=True)
    user_identifier = Column(String, nullable=False, index=True)
    prediction_id = Column(Integer, ForeignKey("predictions.id"), nullable=False)
    personal_note = Column(Text, nullable=True)
    saved_at = Column(DateTime, default=datetime.datetime.utcnow)


class DisclosedPosition(Base):
    __tablename__ = "disclosed_positions"
    id = Column(Integer, primary_key=True, index=True)
    forecaster_id = Column(Integer, ForeignKey("forecasters.id"), nullable=False)
    ticker = Column(String, nullable=False, index=True)
    position_type = Column(String, nullable=False)  # 'long' | 'short' | 'sold'
    disclosed_at = Column(DateTime, nullable=True)
    source_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)


def get_youtube_timestamp_url(video_id, seconds):
    if not video_id:
        return None
    if seconds:
        return f"https://youtube.com/watch?v={video_id}&t={seconds}"
    return f"https://youtube.com/watch?v={video_id}"


def format_timestamp(seconds):
    if seconds is None:
        return None
    return f"{seconds // 60}:{seconds % 60:02d}"
