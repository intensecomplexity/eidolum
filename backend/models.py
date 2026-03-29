import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Numeric, UniqueConstraint, CheckConstraint
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

    # Cached stats (auto-updated by recalculate_forecaster_stats)
    accuracy_score = Column(Float, nullable=True)
    total_predictions = Column(Integer, default=0)
    correct_predictions = Column(Integer, default=0)
    streak = Column(Integer, default=0)
    alpha = Column(Float, nullable=True)  # avg prediction return - avg SPY return

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
    external_id = Column(String, nullable=True, unique=True, index=True)  # benzinga_id for dedup
    video_timestamp_sec = Column(Integer, nullable=True)
    verified_by = Column(String, nullable=True)  # 'ai_parsed'|'manual'|'auto_title'
    evaluation_summary = Column(Text, nullable=True)
    archive_url = Column(Text, nullable=True)
    archived_at = Column(DateTime, nullable=True)

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


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100), nullable=True)
    email = Column(String(255), unique=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    avatar_url = Column(Text, nullable=True)
    bio = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    streak_current = Column(Integer, default=0)
    streak_best = Column(Integer, default=0)
    paper_balance = Column(Numeric(20, 2), default=0)
    user_type = Column(String(20), default="player")  # "player" | "analyst"
    onboarding_completed = Column(Integer, default=0)  # 0=false, 1=true
    daily_streak_current = Column(Integer, default=0)
    daily_streak_best = Column(Integer, default=0)
    price_alerts_enabled = Column(Integer, default=1)  # 0=false, 1=true
    weekly_digest_enabled = Column(Integer, default=1)  # 0=false, 1=true
    return_streak_current = Column(Integer, default=0)
    return_streak_best = Column(Integer, default=0)
    last_active_date = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    notification_preferences = Column(Text, nullable=True)  # JSON string
    auth_provider = Column(String(20), default="email")  # "email" | "google"
    xp_total = Column(Integer, default=0)
    xp_level = Column(Integer, default=1)
    xp_today = Column(Integer, default=0)
    xp_last_reset = Column(DateTime, nullable=True)
    custom_title = Column(String(50), nullable=True)
    subscription_tier = Column(String(20), default="free")  # "free" | "pro" | "institutional"
    referred_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    predictions = relationship("UserPrediction", back_populates="user", cascade="all, delete-orphan")
    achievements = relationship("Achievement", back_populates="user", cascade="all, delete-orphan")


class UserPrediction(Base):
    __tablename__ = "user_predictions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String(10), nullable=False, index=True)
    direction = Column(String(10), nullable=False)  # "bullish" | "bearish"
    price_target = Column(String(50), nullable=False)
    price_at_call = Column(Numeric(20, 2), nullable=True)
    evaluation_window_days = Column(Integer, nullable=False)
    reasoning = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    evaluated_at = Column(DateTime, nullable=True)
    outcome = Column(String(20), default="pending", index=True)  # "pending" | "correct" | "incorrect"
    current_price = Column(Numeric(20, 2), nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    last_checked_price = Column(Numeric(20, 2), nullable=True)
    last_alert_type = Column(String(20), nullable=True)
    template = Column(String(50), default="custom")

    __table_args__ = (
        CheckConstraint("direction IN ('bullish', 'bearish')", name="ck_up_direction"),
        CheckConstraint("evaluation_window_days BETWEEN 1 AND 365", name="ck_up_window"),
        CheckConstraint("outcome IN ('pending', 'correct', 'incorrect')", name="ck_up_outcome"),
    )

    user = relationship("User", back_populates="predictions")


class DailyChallenge(Base):
    __tablename__ = "daily_challenges"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False)
    ticker_name = Column(String(100), nullable=True)
    price_at_open = Column(Numeric(20, 2), nullable=True)
    price_at_close = Column(Numeric(20, 2), nullable=True)
    correct_direction = Column(String(10), nullable=True)
    challenge_date = Column(DateTime, nullable=False, unique=True)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    entries = relationship("DailyChallengeEntry", back_populates="challenge", cascade="all, delete-orphan")


class DailyChallengeEntry(Base):
    __tablename__ = "daily_challenge_entries"

    id = Column(Integer, primary_key=True, index=True)
    challenge_id = Column(Integer, ForeignKey("daily_challenges.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    direction = Column(String(10), nullable=False)
    submitted_at = Column(DateTime, default=datetime.datetime.utcnow)
    outcome = Column(String(20), nullable=True)

    __table_args__ = (UniqueConstraint("challenge_id", "user_id", name="uq_challenge_user"),)

    challenge = relationship("DailyChallenge", back_populates="entries")
    user = relationship("User")


class EarningsCalendar(Base):
    __tablename__ = "earnings_calendar"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False)
    earnings_date = Column(DateTime, nullable=False)
    earnings_time = Column(String(20), nullable=True)
    fiscal_quarter = Column(String(10), nullable=True)
    fiscal_year = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (UniqueConstraint("ticker", "earnings_date", name="uq_earnings"),)


class WatchlistItem(Base):
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String(10), nullable=False)
    notify = Column(Integer, default=1)  # 0=false, 1=true
    added_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "ticker", name="uq_watchlist"),)


class PredictionComment(Base):
    __tablename__ = "prediction_comments"

    id = Column(Integer, primary_key=True, index=True)
    prediction_id = Column(Integer, nullable=False)
    prediction_source = Column(String(20), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    comment = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class PredictionReaction(Base):
    __tablename__ = "prediction_reactions"

    id = Column(Integer, primary_key=True, index=True)
    prediction_id = Column(Integer, nullable=False)
    prediction_source = Column(String(20), nullable=False)  # "user" | "analyst"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reaction = Column(String(20), nullable=False)  # "agree" | "disagree" | "bold_call" | "no_way"
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("prediction_id", "prediction_source", "user_id", name="uq_reaction"),
        CheckConstraint("prediction_source IN ('user', 'analyst')", name="ck_reaction_source"),
        CheckConstraint("reaction IN ('agree', 'disagree', 'bold_call', 'no_way')", name="ck_reaction_type"),
    )


class ActivityEvent(Base):
    __tablename__ = "activity_feed_v2"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(50), nullable=False)
    ticker = Column(String(10), nullable=True)
    description = Column(Text, nullable=False)
    data = Column(Text, nullable=True)  # JSON string
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    data = Column(Text, nullable=True)  # JSON string
    read = Column(Integer, default=0)  # 0=false, 1=true
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class DeletionLog(Base):
    __tablename__ = "deletion_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    prediction_id = Column(Integer, ForeignKey("user_predictions.id"), nullable=False)
    deleted_at = Column(DateTime, default=datetime.datetime.utcnow)


class Achievement(Base):
    __tablename__ = "achievements"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    badge_id = Column(String(50), nullable=False)
    unlocked_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "badge_id", name="uq_user_badge"),)

    user = relationship("User", back_populates="achievements")


class Follow(Base):
    __tablename__ = "follows"

    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    following_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), default="accepted")  # "pending" | "accepted" | "declined"
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("follower_id", "following_id", name="uq_follow_pair"),
        CheckConstraint("follower_id != following_id", name="ck_no_self_follow"),
    )

    follower = relationship("User", foreign_keys=[follower_id], backref="following")
    following = relationship("User", foreign_keys=[following_id], backref="followers")


class Duel(Base):
    __tablename__ = "duels"

    id = Column(Integer, primary_key=True, index=True)
    challenger_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    opponent_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker = Column(String(10), nullable=False)
    challenger_direction = Column(String(10), nullable=False)
    opponent_direction = Column(String(10), nullable=False)
    challenger_target = Column(String(50), nullable=False)
    opponent_target = Column(String(50), nullable=False)
    evaluation_window_days = Column(Integer, nullable=False)
    price_at_start = Column(Numeric(20, 2), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    status = Column(String(20), default="pending", index=True)
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    evaluated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("challenger_direction IN ('bullish', 'bearish')", name="ck_duel_cdir"),
        CheckConstraint("opponent_direction IN ('bullish', 'bearish')", name="ck_duel_odir"),
        CheckConstraint("status IN ('pending', 'active', 'completed', 'declined')", name="ck_duel_status"),
    )

    challenger = relationship("User", foreign_keys=[challenger_id])
    opponent = relationship("User", foreign_keys=[opponent_id])
    winner = relationship("User", foreign_keys=[winner_id])


class Season(Base):
    __tablename__ = "seasons"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime, nullable=False)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    theme_color = Column(String(7), nullable=True)
    theme_icon = Column(String(50), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'completed')", name="ck_season_status"),
    )

    entries = relationship("SeasonEntry", back_populates="season", cascade="all, delete-orphan")


class SeasonEntry(Base):
    __tablename__ = "season_entries"

    id = Column(Integer, primary_key=True, index=True)
    season_id = Column(Integer, ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    predictions_made = Column(Integer, default=0)
    predictions_scored = Column(Integer, default=0)
    predictions_correct = Column(Integer, default=0)

    __table_args__ = (UniqueConstraint("season_id", "user_id", name="uq_season_user"),)

    season = relationship("Season", back_populates="entries")
    user = relationship("User")


class XpLog(Base):
    __tablename__ = "xp_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(50), nullable=False)
    xp_gained = Column(Integer, nullable=False)
    description = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class WeeklyChallenge(Base):
    __tablename__ = "weekly_challenges"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    challenge_type = Column(String(50), nullable=False)
    requirements = Column(Text, nullable=False)  # JSON string
    xp_reward = Column(Integer, default=100)
    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime, nullable=False)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class WeeklyChallengeProgress(Base):
    __tablename__ = "weekly_challenge_progress"

    id = Column(Integer, primary_key=True, index=True)
    challenge_id = Column(Integer, ForeignKey("weekly_challenges.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    progress = Column(Integer, default=0)
    completed = Column(Integer, default=0)  # 0=false, 1=true
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("challenge_id", "user_id", name="uq_weekly_progress"),)


class AnalystSubscription(Base):
    __tablename__ = "analyst_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    email = Column(String(255), nullable=True)
    forecaster_name = Column(String(200), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "forecaster_name", name="uq_analyst_sub_user"),
        UniqueConstraint("email", "forecaster_name", name="uq_analyst_sub_email"),
    )

    user = relationship("User")


class Config(Base):
    __tablename__ = "config"
    key = Column(String, primary_key=True)
    value = Column(String)


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
