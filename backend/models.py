import datetime
from sqlalchemy import Column, Integer, BigInteger, SmallInteger, String, Float, DateTime, ForeignKey, Text, Numeric, Boolean, JSON, UniqueConstraint, CheckConstraint, func
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
    firm = Column(String, nullable=True)  # e.g. "Goldman Sachs", "UBS" — for institutional analysts
    slug = Column(String, unique=True, nullable=True, index=True)
    rank_last_week = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Cached stats (auto-updated by recalculate_forecaster_stats)
    accuracy_score = Column(Float, nullable=True)
    total_predictions = Column(Integer, default=0)
    correct_predictions = Column(Integer, default=0)
    streak = Column(Integer, default=0)
    alpha = Column(Float, nullable=True)  # avg prediction return - avg SPY return
    avg_return = Column(Float, nullable=True)  # avg actual_return across evaluated predictions

    # Dormancy: forecaster has not made a new prediction in 30+ days.
    # Recomputed by refresh_all_forecaster_stats on every stats refresh.
    last_prediction_at = Column(DateTime, nullable=True, index=True)
    is_dormant = Column(Boolean, nullable=False, default=False, server_default="false")

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
    # Pillar 4: tweet IDs serve as the immutable archive for X predictions.
    # Snowflake-decoded for date verification, reconstructible into a URL.
    tweet_id = Column(BigInteger, nullable=True, index=True)
    video_timestamp_sec = Column(Integer, nullable=True)
    verified_by = Column(String, nullable=True)  # 'ai_parsed'|'manual'|'auto_title'
    evaluation_summary = Column(Text, nullable=True)
    archive_url = Column(Text, nullable=True)
    archived_at = Column(DateTime, nullable=True)
    evaluated_at = Column(DateTime, nullable=True)  # when the system actually scored this prediction
    call_type = Column(String, nullable=True)  # upgrade|downgrade|new_coverage|price_target|rating

    # Prediction classification (added by migrations add_confidence_tier_and_voided.sql
    # + add_position_fields.sql). Defaults match the DB defaults so new ORM-only
    # inserts behave identically to existing rows.
    prediction_type = Column(String(32), nullable=False, default="price_target")
    # Category distinguishes ticker calls (specific stock/crypto picks) from
    # sector calls (broad sector bets mapped to ETFs). Exists alongside
    # prediction_type so the leaderboard can surface sector skill as a
    # separate column without conflating it with individual ticker accuracy.
    prediction_category = Column(String(20), nullable=False, default="ticker_call",
                                 server_default="ticker_call")
    confidence_tier = Column(Numeric(3, 2), nullable=False, default=1.0)
    # Position disclosure fields: NULL for price_target predictions.
    position_action = Column(String(16), nullable=True)   # open|add|trim|exit
    position_closed_at = Column(DateTime, nullable=True)

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


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    admin_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    admin_email = Column(String(255), nullable=False)
    action = Column(String(100), nullable=False)  # e.g. "delete_prediction", "ban_user", "promote_admin"
    target_type = Column(String(50), nullable=True)  # "prediction", "forecaster", "user"
    target_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(128), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


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
    twitter_url = Column(String(255), nullable=True)
    linkedin_url = Column(String(255), nullable=True)
    youtube_url = Column(String(255), nullable=True)
    website_url = Column(String(255), nullable=True)
    subscription_tier = Column(String(20), default="free")  # "free" | "pro" | "institutional"
    referred_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_admin = Column(Integer, default=0)  # 0=false, 1=true
    is_banned = Column(Integer, default=0)  # 0=false, 1=true
    email_notifications = Column(Integer, default=1)  # 0=false, 1=true
    notification_frequency = Column(String(20), default="daily")  # "instant", "daily", "weekly"

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


class NotificationQueue(Base):
    __tablename__ = "notification_queue"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String(10), nullable=False)
    prediction_id = Column(Integer, nullable=True)
    forecaster_name = Column(String(100), nullable=True)
    direction = Column(String(20), nullable=True)
    target_price = Column(Numeric(10, 2), nullable=True)
    context = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)


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


class TickerDiscussion(Base):
    __tablename__ = "ticker_discussions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    text = Column(Text, nullable=False)
    parent_id = Column(Integer, ForeignKey("ticker_discussions.id", ondelete="CASCADE"), nullable=True)
    likes_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class TickerDiscussionLike(Base):
    __tablename__ = "ticker_discussion_likes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    discussion_id = Column(Integer, ForeignKey("ticker_discussions.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "discussion_id", name="uq_discussion_like"),
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


class TrackedXAccount(Base):
    __tablename__ = "tracked_x_accounts"

    id = Column(Integer, primary_key=True, index=True)
    handle = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100))
    tier = Column(Integer, nullable=False)
    follower_count = Column(Integer, default=0)
    notes = Column(Text)
    active = Column(Boolean, default=True)
    added_date = Column(DateTime, default=datetime.datetime.utcnow)
    last_scraped_at = Column(DateTime)
    last_scrape_tweets_found = Column(Integer, default=0)
    last_scrape_predictions_extracted = Column(Integer, default=0)
    total_tweets_scraped = Column(Integer, default=0)
    total_predictions_extracted = Column(Integer, default=0)

    __table_args__ = (
        CheckConstraint("tier BETWEEN 1 AND 4", name="ck_tracked_x_tier"),
    )


class SuggestedXAccount(Base):
    __tablename__ = "suggested_x_accounts"

    id = Column(Integer, primary_key=True, index=True)
    handle = Column(String(50), unique=True, nullable=False)
    mention_count = Column(Integer, default=1)
    first_seen_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.datetime.utcnow)
    dismissed = Column(Boolean, default=False)


class XScraperRejection(Base):
    """Persisted record of every tweet rejected by the X scraper pipeline.
    Used by the admin "Recent Rejections" view for filter tuning.
    Pruned to last 7 days at the start of every scrape run."""
    __tablename__ = "x_scraper_rejections"

    id = Column(Integer, primary_key=True, index=True)
    tweet_id = Column(BigInteger, nullable=False)
    handle = Column(String(50), nullable=False, index=True)
    tweet_text = Column(Text, nullable=False)
    tweet_created_at = Column(DateTime, nullable=True)
    # server_default ensures Postgres has a real DEFAULT clause; the Python
    # default is kept for ORM-side inserts as a belt-and-braces fallback.
    rejected_at = Column(DateTime, default=datetime.datetime.utcnow,
                         server_default=func.now(), index=True)
    rejection_reason = Column(String(50), nullable=False, index=True)
    haiku_reason = Column(Text, nullable=True)
    # JSON maps to JSONB on Postgres automatically
    haiku_raw_response = Column(JSON, nullable=True)
    # 0-4 closeness score from Haiku on rejected tweets (NULL for accepted
    # predictions and for pre-classification rejections like no_tweet_id).
    closeness_level = Column(SmallInteger, nullable=True, index=True)


class ScraperRun(Base):
    """One row per scraper run. Replaces the never-created scheduler_logs
    referenced (and silently caught) by /api/admin/social-stats. Used by
    the admin Social Scrapers card to render last-run funnel counts and
    7d aggregates symmetrically across X and YouTube.

    Lifecycle:
      - INSERT at the top of run_<scraper>() with status='running'
      - UPDATE at the end with finished_at, status='ok'/'error', counts
    """
    __tablename__ = "scraper_runs"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(20), nullable=False, index=True)  # 'x', 'youtube', ...
    started_at = Column(DateTime, nullable=False,
                        default=datetime.datetime.utcnow,
                        server_default=func.now(), index=True)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="running",
                    server_default="running")  # running | ok | error
    items_fetched = Column(Integer, nullable=False, default=0,
                           server_default="0")  # tweets / videos
    items_processed = Column(Integer, nullable=False, default=0,
                             server_default="0")  # passed prefilter / transcripts ok
    items_llm_sent = Column(Integer, nullable=False, default=0,
                            server_default="0")
    items_inserted = Column(Integer, nullable=False, default=0,
                            server_default="0")
    items_rejected = Column(Integer, nullable=False, default=0,
                            server_default="0")
    items_deduped = Column(Integer, nullable=False, default=0,
                           server_default="0")
    error_message = Column(Text, nullable=True)

    # LLM cost / usage aggregates. Populated by scrapers that call an
    # LLM (currently the YouTube monitor). Source-agnostic — any
    # scraper that runs classify_* can push totals here.
    total_input_tokens = Column(BigInteger, nullable=False, default=0,
                                server_default="0")
    total_output_tokens = Column(BigInteger, nullable=False, default=0,
                                 server_default="0")
    total_cache_create_tokens = Column(BigInteger, nullable=False,
                                        default=0, server_default="0")
    total_cache_read_tokens = Column(BigInteger, nullable=False,
                                      default=0, server_default="0")
    estimated_cost_usd = Column(Numeric(10, 4), nullable=False, default=0,
                                server_default="0")
    # Count of Haiku retries triggered by stop_reason=='max_tokens' on
    # the 800-token first-attempt cap. If the retry rate climbs above
    # 5% of items_llm_sent, the monitor emits a warning — see
    # youtube_channel_monitor._run_inner finalize block.
    haiku_retries_count = Column(Integer, nullable=False, default=0,
                                  server_default="0")


class YouTubeScraperRejection(Base):
    """Persisted record of every video rejected by the YouTube scraper
    pipeline. Mirror of x_scraper_rejections — same shape, same 7-day
    prune cadence, same admin role: surface the funnel breakdown so we
    can tune the prefilters and the Haiku prompt without grepping logs.
    """
    __tablename__ = "youtube_scraper_rejections"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(String(20), nullable=True, index=True)
    channel_id = Column(String(30), nullable=True, index=True)
    channel_name = Column(String(200), nullable=True)
    video_title = Column(Text, nullable=True)
    video_published_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=False,
                         default=datetime.datetime.utcnow,
                         server_default=func.now(), index=True)
    rejection_reason = Column(String(50), nullable=False, index=True)
    haiku_reason = Column(Text, nullable=True)
    haiku_raw_response = Column(JSON, nullable=True)
    transcript_snippet = Column(Text, nullable=True)


class SectorEtfAlias(Base):
    """Canonical sector → ETF ticker mapping used by the YouTube classifier's
    sector-call extraction. Multiple aliases (e.g. "semis", "chip stocks",
    "semiconductors") can map to the same canonical_sector + etf_ticker so
    the Haiku prompt can output natural sector names without the classifier
    having to pick an ETF itself. Admin-editable via /admin/sector-aliases.
    """
    __tablename__ = "sector_etf_aliases"

    id = Column(Integer, primary_key=True, index=True)
    alias = Column(String(100), nullable=False, unique=True)
    canonical_sector = Column(String(50), nullable=False, index=True)
    etf_ticker = Column(String(10), nullable=False)
    notes = Column(Text, nullable=True)


class YouTubeChannelMeta(Base):
    """Admin-facing metadata for YouTube channels. FK'd to forecasters so
    the admin page can tier/toggle/annotate the YouTube leaderboard without
    polluting the shared forecasters table with YouTube-only columns.

    Mirrors the shape of tracked_x_accounts for symmetry with the X admin
    page, but stays decoupled from the scraper's own youtube_channels
    tracking table (which drives the actual batch iteration).
    """
    __tablename__ = "youtube_channel_meta"

    id = Column(Integer, primary_key=True, index=True)
    forecaster_id = Column(Integer, ForeignKey("forecasters.id", ondelete="CASCADE"),
                           nullable=False)
    channel_id = Column(String(30), nullable=False)
    tier = Column(Integer, nullable=False, default=4, server_default="4")
    notes = Column(Text, nullable=True)
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    added_date = Column(DateTime, nullable=False, default=datetime.datetime.utcnow,
                        server_default=func.now())
    last_scraped_at = Column(DateTime, nullable=True)
    last_scrape_videos_found = Column(Integer, default=0, server_default="0")
    last_scrape_predictions_extracted = Column(Integer, default=0, server_default="0")
    total_videos_scraped = Column(Integer, default=0, server_default="0")
    total_predictions_extracted = Column(Integer, default=0, server_default="0")
    videos_processed_count = Column(Integer, default=0, server_default="0")
    predictions_extracted_count = Column(Integer, default=0, server_default="0")
    deactivated_at = Column(DateTime, nullable=True)
    deactivation_reason = Column(String(50), nullable=True)

    __table_args__ = (
        UniqueConstraint("forecaster_id", name="uq_yt_meta_forecaster"),
        UniqueConstraint("channel_id", name="uq_yt_meta_channel_id"),
        CheckConstraint("tier BETWEEN 1 AND 4", name="ck_yt_meta_tier"),
    )


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
