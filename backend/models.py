import datetime
from sqlalchemy import Column, Integer, BigInteger, SmallInteger, String, Float, DateTime, Date, ForeignKey, Text, Numeric, Boolean, JSON, UniqueConstraint, CheckConstraint, func
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

    # Disclosure tracking (ship #8). Disclosures are not predictions —
    # they're past-tense position statements ("I bought 500 AMD today")
    # that live in the `disclosures` table. These cached aggregates are
    # updated by compute_disclosure_follow_through on its daily run so
    # the leaderboard/profile pages can sort by conviction quality
    # without re-aggregating on every page load.
    disclosure_count = Column(Integer, nullable=False, default=0,
                               server_default="0")
    avg_follow_through_1m = Column(Numeric(10, 4), nullable=True)
    avg_follow_through_3m = Column(Numeric(10, 4), nullable=True)
    avg_follow_through_6m = Column(Numeric(10, 4), nullable=True)
    avg_follow_through_12m = Column(Numeric(10, 4), nullable=True)

    videos = relationship("Video", back_populates="forecaster", cascade="all, delete-orphan")
    predictions = relationship("Prediction", back_populates="forecaster", cascade="all, delete-orphan")
    disclosures = relationship("Disclosure", back_populates="forecaster", cascade="all, delete-orphan")


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
    # Ranked list metadata. Populated only when the YouTube classifier
    # (with ENABLE_RANKED_LIST_EXTRACTION enabled) extracts a prediction
    # from a speaker-declared ranked list ("my top 5 stocks"). Both
    # columns move together — either both set or both NULL.
    #   list_id: human-readable ID invented by Haiku, shared by all items in
    #            the same list ("top5_2026", "avoid_list_q1", etc.)
    #   list_rank: 1-based position within the list (1=top pick), capped at 10
    list_id = Column(String(40), nullable=True)
    list_rank = Column(Integer, nullable=True)
    # Target revision link. When a forecaster publicly revises an existing
    # price target ("moving my AAPL target from $200 to $220"), the new
    # prediction gets revision_of pointing at the previous prediction's
    # id. Flat chain — each revision links only to its immediate
    # predecessor, never walks up. ON DELETE SET NULL so deleting an
    # early prediction just severs the link, never cascades.
    revision_of = Column(Integer, ForeignKey("predictions.id", ondelete="SET NULL"),
                         nullable=True)
    # Scheduled-event metadata. Populated on prediction types whose
    # evaluation window is tied to a specific corporate event rather
    # than a fixed number of days from the prediction date. Current
    # values for event_type:
    #   'earnings' — prediction tied to the company's next earnings
    #                release (ENABLE_EARNINGS_CALL_EXTRACTION).
    # event_date is the scheduled event date when Haiku extracted it
    # from the transcript (or the evaluator later looks it up). Both
    # columns stay NULL for plain ticker_call / sector_call rows.
    event_type = Column(String(32), nullable=True)
    event_date = Column(DateTime, nullable=True)
    # Macro concept identifier for prediction_category='macro_call' rows.
    # The forecaster spoke in macroeconomic terms (e.g. "dollar", "rates
    # up", "gold to 3000"); Haiku emitted a canonical concept name; the
    # insert path resolved it to a tradeable ETF via macro_concept_aliases
    # and stored the prediction as a ticker_call-shaped row on that ETF.
    # macro_concept preserves the original concept so the leaderboard
    # can filter by concept family and the admin UI can audit mappings.
    # NULL for every non-macro row.
    macro_concept = Column(String(64), nullable=True)
    # Pair-call metadata for prediction_category='pair_call' rows. Pair
    # calls express a relative-value view ("Meta beats Google over the
    # next year", "long NVDA short INTC") and are scored on the spread
    # (long_return − short_return) rather than absolute movement. The
    # `ticker` column on pair_call rows is set to pair_long_ticker so
    # the existing ticker index still covers the long leg for filtering;
    # pair_short_ticker is the underperformer. pair_spread_return is
    # computed at scoring time by the evaluator and stored as a decimal
    # percent (e.g. 4.25 means the long beat the short by 4.25%). NULL
    # on every non-pair row.
    pair_long_ticker = Column(String(16), nullable=True)
    pair_short_ticker = Column(String(16), nullable=True)
    pair_spread_return = Column(Numeric(10, 4), nullable=True)
    # Binary-event metadata for prediction_category='binary_event_call'
    # rows. Binary event calls are yes/no predictions on discrete
    # checkable events ("Fed will cut 50bps in March", "AAPL will split
    # by end of 2026"). event_type is REUSED from the earnings_call ship
    # (see above) and extended here with: fed_decision / corporate_action
    # / mna / ipo / index_inclusion / economic_declaration / regulatory /
    # other. expected_outcome_text holds a natural language description
    # of the event Haiku extracted. event_deadline is the hard cutoff —
    # if the event doesn't happen by this date, the row scores MISS.
    # event_resolved_at + event_resolution_source are set by the
    # evaluator when a real-world data source confirms the outcome; they
    # stay NULL until the follow-up ship plumbs in FRED / FOMC /
    # corporate-action data. All NULL on every non-binary row.
    expected_outcome_text = Column(Text, nullable=True)
    event_deadline = Column(Date, nullable=True)
    event_resolved_at = Column(DateTime, nullable=True)
    event_resolution_source = Column(String(64), nullable=True)
    # Metric-forecast metadata for prediction_category='metric_forecast_call'
    # rows. These are numerical predictions for specific fundamental
    # or macro metrics — "NVDA will report $5.20 EPS", "CPI prints
    # 3.2%", "unemployment ticks to 4.5%". Different from earnings_call
    # (which predicts price reaction) and from binary_event_call (which
    # predicts yes/no). Scoring compares the predicted target against
    # the actual released value using category-based tolerance.
    #
    #   metric_type         Canonical metric name (eps / revenue / cpi /
    #                       unemployment / pmi_manufacturing / …). Constrained
    #                       to _METRIC_FORECAST_TYPES in youtube_classifier.py.
    #   metric_target       The forecaster's predicted value. Stored in the
    #                       metric's natural unit (dollars for EPS/revenue,
    #                       decimal rate for percentages — e.g. 0.032 for
    #                       3.2% CPI, 150000 for 150K nonfarm payrolls).
    #   metric_period       Reporting period label ("Q1_2026", "fiscal_2026",
    #                       "Jan_2026"). Free-form — used for dedup and
    #                       FMP earnings lookup.
    #   metric_release_date Scheduled date the actual value will be released.
    #                       Evaluator waits until this date before scoring.
    #   metric_actual       Populated by the evaluator once the real value
    #                       is fetched (from earnings_history for company
    #                       metrics, stubbed for macro metrics).
    #   metric_error_pct    Relative error percent computed at scoring time
    #                       — (actual - target) / target * 100. Used by the
    #                       frontend for the ERROR display.
    # All NULL on every non-metric row.
    metric_type = Column(String(48), nullable=True)
    metric_target = Column(Numeric(18, 6), nullable=True)
    metric_period = Column(String(16), nullable=True)
    metric_release_date = Column(Date, nullable=True)
    metric_actual = Column(Numeric(18, 6), nullable=True)
    metric_error_pct = Column(Numeric(10, 4), nullable=True)
    # Conditional-call metadata for prediction_category='conditional_call'
    # rows. A conditional is "IF trigger_condition THEN outcome" — the
    # outcome side reuses the existing ticker / direction / target_price /
    # window_days columns (scored as a normal ticker_call once the trigger
    # fires). The trigger side is stored in the columns below.
    #
    #   trigger_condition  — free-text natural language description
    #   trigger_type       — enum: price_hold, price_break, economic_data,
    #                        fed_decision, market_event, corporate_action,
    #                        other. Only price_hold and price_break get
    #                        auto-resolved by the evaluator in this ship.
    #   trigger_ticker     — for price-based triggers, the symbol being
    #                        watched (may differ from prediction.ticker).
    #   trigger_price      — for price-based triggers, the threshold.
    #   trigger_deadline   — when the trigger must fire by; if today is
    #                        past this with trigger_fired_at still NULL,
    #                        the evaluator sets outcome='unresolved'.
    #   trigger_fired_at   — timestamp the trigger actually fired. NULL
    #                        until it does. Phase 2 scoring starts here.
    #   outcome_window_days — days after trigger_fired_at for the outcome
    #                        scoring window (separate from window_days so
    #                        we can keep both the original timeframe and
    #                        the phase-2 budget).
    # All NULL for non-conditional rows.
    trigger_condition = Column(Text, nullable=True)
    trigger_type = Column(String(32), nullable=True)
    trigger_ticker = Column(String(16), nullable=True)
    trigger_price = Column(Numeric(12, 4), nullable=True)
    trigger_deadline = Column(DateTime, nullable=True)
    trigger_fired_at = Column(DateTime, nullable=True)
    outcome_window_days = Column(Integer, nullable=True)
    # Source-timestamp metadata (ship #9). Every YouTube-derived
    # prediction can link to the exact second in the video where the
    # forecaster said it via youtube.com/watch?v=VID&t=272s. Populated
    # by backend/jobs/timestamp_matcher.py when ENABLE_SOURCE_TIMESTAMPS
    # is on. Stays NULL on every row extracted with the flag off, on
    # every non-YouTube prediction, and on any extraction where the
    # matcher couldn't find a reliable link.
    #
    #   source_timestamp_seconds    integer second into the video
    #   source_timestamp_method     'word_level' | 'fuzzy_match' |
    #                               'two_pass' | 'unknown'
    #   source_verbatim_quote       exact words Haiku extracted — drives
    #                               both the match AND the frontend audit
    #                               trail tooltip
    #   source_timestamp_confidence 0.000..1.000 match confidence
    source_timestamp_seconds = Column(Integer, nullable=True)
    source_timestamp_method = Column(String(16), nullable=True)
    source_verbatim_quote = Column(Text, nullable=True)
    source_timestamp_confidence = Column(Numeric(4, 3), nullable=True)
    # Evidence preservation — FK to video_transcripts. Populated for
    # every YouTube prediction the pipeline captured a transcript for,
    # so the verbatim quote can be verified against the SHA256-locked
    # full transcript even if the forecaster deletes the video.
    transcript_video_id = Column(String(11), nullable=True, index=True)
    # Prediction metadata enrichment (ship #9 rescoped). Captures
    # extraction-time labels that the fine-tuning backfill depends on:
    # category-aware timeframe inference and conviction classification.
    # Populated by the Haiku classifier when
    # ENABLE_PREDICTION_METADATA_ENRICHMENT is flipped on; stays NULL
    # on every row extracted with the flag off.
    #
    #   inferred_timeframe_days  integer window the prediction targets,
    #                            either explicitly stated by the speaker
    #                            or inferred from the 11-category mapping
    #                            (macro_thesis → 365, technical_chart → 30,
    #                            swing_trade → 14, …)
    #   timeframe_source         'explicit' when the speaker named a date
    #                            or "in 30 days", 'category_default' when
    #                            the window came from a category match.
    #                            NULL predictions with an undeterminable
    #                            timeframe are REJECTED not inserted.
    #   timeframe_category       the category name that produced the
    #                            default window — carried so admin
    #                            diagnostics can show the distribution.
    #   conviction_level         'strong' | 'moderate' | 'hedged' |
    #                            'hypothetical' | 'unknown'. Captured but
    #                            NOT scored yet — lives as label data for
    #                            the fine-tune and shows as a subtle pill
    #                            badge on the prediction card. Leaderboard
    #                            accuracy math is unchanged by this field.
    inferred_timeframe_days = Column(Integer, nullable=True)
    timeframe_source = Column(String(32), nullable=True)
    timeframe_category = Column(String(32), nullable=True)
    conviction_level = Column(String(16), nullable=True)
    # Regime-call metadata for prediction_category='regime_call' rows
    # (ship #12 — structural market phase claims). Regime calls carry
    # NO price target — the claim is about a STRUCTURAL outcome for
    # `regime_instrument` (default SPY) over the evaluation window:
    # "no top yet", "bottom is in", "topping process", "correction
    # not bear market". Scoring is based on max drawdown, max runup,
    # and new-high/new-low counts during the window rather than
    # final price vs target.
    #
    #   regime_type          One of 8 canonical values: bull_continuing,
    #                        bull_starting, topping, bear_starting,
    #                        bear_continuing, bottoming, correction,
    #                        consolidation. Enforced by the validator;
    #                        no DB CHECK constraint so adding a 9th
    #                        value later is a one-liner.
    #   regime_instrument    Ticker/ETF being claimed about (SPY, QQQ,
    #                        IWM, BTC, …). Defaults to 'SPY' when the
    #                        forecaster says "the market" / "stocks".
    #   regime_max_drawdown  Populated by the evaluator at score time —
    #                        max peak-to-trough drawdown inside the
    #                        window (for bull_* / correction rules) OR
    #                        max drawdown from window_start (for
    #                        topping / bear_* rules, depending on the
    #                        per-type rule logic).
    #   regime_max_runup     Populated by the evaluator — max gain from
    #                        window_start or window_low.
    #   regime_new_highs     Count of daily closes above start * 1.01.
    #   regime_new_lows      Count of daily closes below start * 0.99.
    # All NULL for non-regime rows.
    regime_type = Column(String(24), nullable=True)
    regime_instrument = Column(String(16), nullable=True)
    regime_max_drawdown = Column(Numeric(10, 4), nullable=True)
    regime_max_runup = Column(Numeric(10, 4), nullable=True)
    regime_new_highs = Column(Integer, nullable=True)
    regime_new_lows = Column(Integer, nullable=True)
    confidence_tier = Column(Numeric(3, 2), nullable=False, default=1.0)
    # Position disclosure fields: NULL for price_target predictions.
    position_action = Column(String(16), nullable=True)   # open|add|trim|exit
    position_closed_at = Column(DateTime, nullable=True)

    # Ship #12 — soft training-set exclusion. Rows flagged by
    # backend/scripts/ship_12_audit.py (disclosure mis-routes,
    # invented timeframes, unresolvable pronoun references, basket
    # shoehorns, duplicate sources) are kept in place but filtered
    # out of the fine-tune training loader. Leaderboard queries do
    # NOT filter on these — historical scores stay stable.
    excluded_from_training = Column(Boolean, nullable=False, default=False,
                                     server_default="false")
    exclusion_reason = Column(String(64), nullable=True)
    exclusion_flagged_at = Column(DateTime(timezone=True), nullable=True)
    exclusion_rule_version = Column(String(16), nullable=True)

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
    # Count of sector_call predictions extracted in this run. Incremented
    # only when the ENABLE_YOUTUBE_SECTOR_CALLS flag routes a video to
    # the sector-aware Haiku prompt AND the prediction survives
    # map_sector_to_etf + insertion. Useful for tracking the rollout
    # from the admin panel.
    sector_calls_extracted = Column(Integer, nullable=False, default=0,
                                     server_default="0")
    # Count of options-derived ticker_call predictions extracted in
    # this run. Incremented when Haiku marks a prediction with
    # derived_from='options_position' under the
    # ENABLE_OPTIONS_POSITION_EXTRACTION flag — options vocabulary
    # ("buying calls", "selling puts", "iron condor", ...) gets
    # mapped to an equivalent ticker_call direction and stored as
    # prediction_category='ticker_call'. This counter tracks how many
    # of those ticker_call rows came from options language, without
    # introducing a new prediction_category value.
    options_positions_extracted = Column(Integer, nullable=False, default=0,
                                          server_default="0")
    # Count of earnings_call predictions extracted in this run.
    # Incremented when Haiku marks a prediction with
    # derived_from='earnings_call' under the
    # ENABLE_EARNINGS_CALL_EXTRACTION flag. Earnings calls stay as
    # prediction_category='ticker_call' but also carry
    # event_type='earnings' and optionally an event_date. The
    # evaluator scores them via a separate pre-/post-earnings reaction
    # branch (stubbed in this ship — plumbing is follow-up work).
    earnings_calls_extracted = Column(Integer, nullable=False, default=0,
                                       server_default="0")
    # Count of macro_call predictions extracted in this run. Unlike
    # options/earnings which stay as prediction_category='ticker_call',
    # macro_call is a new category value — macroeconomic predictions
    # are a distinct skill and should be filterable as their own class
    # on the leaderboard. The concept-to-ETF mapping lives in the
    # macro_concept_aliases table. Incremented by insert_youtube_prediction
    # when pred._derived_from=='macro_call' resolves to a valid concept.
    macro_calls_extracted = Column(Integer, nullable=False, default=0,
                                    server_default="0")
    # Count of pair_call predictions extracted in this run. Ship #4 of
    # the new prediction types. Pair calls are scored on the spread
    # between two tickers (long outperforms short) rather than on a
    # single ticker's movement, so they land with a new
    # prediction_category='pair_call' value. Stays 0 until
    # ENABLE_PAIR_CALL_EXTRACTION is flipped on.
    pair_calls_extracted = Column(Integer, nullable=False, default=0,
                                   server_default="0")
    # Count of binary_event_call predictions extracted in this run.
    # Ship #6 of the new prediction types. Binary events are yes/no
    # calls on discrete checkable events with a hard deadline. Stays 0
    # until ENABLE_BINARY_EVENT_EXTRACTION is flipped on.
    binary_events_extracted = Column(Integer, nullable=False, default=0,
                                      server_default="0")
    # Count of metric_forecast_call predictions extracted in this run.
    # Ship #7 of the new prediction types. Numerical metric predictions
    # ("NVDA will report $5.20 EPS", "CPI prints 3.2%"). Stays 0 until
    # ENABLE_METRIC_FORECAST_EXTRACTION is flipped on.
    metric_forecasts_extracted = Column(Integer, nullable=False, default=0,
                                         server_default="0")
    # Count of conditional_call predictions extracted in this run.
    # prediction_category='conditional_call' — a new category. The
    # outcome side is stored like a ticker_call (ticker/direction/target/
    # window_days), and the trigger side lives in the new trigger_*
    # columns on predictions. Scoring is phase-based: Phase 1 checks
    # whether the trigger fires inside trigger_deadline, Phase 2 scores
    # the outcome window starting from trigger_fired_at. A new outcome
    # value 'unresolved' is written when the trigger never fires.
    conditional_calls_extracted = Column(Integer, nullable=False, default=0,
                                          server_default="0")
    # Count of disclosure rows extracted in this run. Ship #8 — the
    # final ship in the new prediction type series. Unlike the other
    # ships, disclosures do NOT land in predictions at all; they live
    # in the `disclosures` table and carry follow-through (1/3/6/12m
    # return after the disclosed_at date) instead of HIT/NEAR/MISS.
    # Stays 0 until ENABLE_DISCLOSURE_EXTRACTION is flipped on.
    disclosures_extracted = Column(Integer, nullable=False, default=0,
                                    server_default="0")
    # Source-timestamp matching telemetry — ship #9. When
    # ENABLE_SOURCE_TIMESTAMPS is on, every prediction extracted by
    # the YouTube classifier gets passed through timestamp_matcher to
    # resolve its verbatim_quote to an integer second in the video.
    # timestamps_matched counts successful matches via any path
    # (word_level / fuzzy_match / two_pass); timestamps_failed counts
    # predictions that got source_timestamp_seconds=NULL. Both stay 0
    # when the flag is off or when no predictions were emitted.
    timestamps_matched = Column(Integer, nullable=False, default=0,
                                 server_default="0")
    timestamps_failed = Column(Integer, nullable=False, default=0,
                                server_default="0")
    # Count of regime_call predictions extracted in this run. Regime
    # calls capture structural market phase claims ("no market top",
    # "bottom is in", "topping process", "correction not bear market")
    # with NO price target. Scoring is based on structural price
    # behavior (drawdown, runup, new highs/lows) during the window
    # rather than final price vs target. Stays 0 until
    # ENABLE_REGIME_CALL_EXTRACTION is flipped on.
    regime_calls_extracted = Column(Integer, nullable=False, default=0,
                                     server_default="0")
    # Prediction metadata enrichment telemetry — ship #9 (rescoped).
    # When ENABLE_PREDICTION_METADATA_ENRICHMENT is on, every prediction
    # emitted by the YouTube classifier carries a timeframe + conviction
    # classification. These counters track the per-run distribution so
    # admin diagnostics can surface drift (e.g. "most videos are getting
    # bucketed as macro_thesis with hedged conviction" → likely a prompt
    # issue worth investigating). Rejection counters track the two new
    # Haiku rejection paths introduced by this ship: undeterminable
    # timeframes and unresolvable pronoun references. All stay 0 when
    # the flag is off or when no predictions were emitted.
    timeframes_explicit = Column(Integer, nullable=False, default=0,
                                  server_default="0")
    timeframes_inferred = Column(Integer, nullable=False, default=0,
                                  server_default="0")
    timeframes_rejected = Column(Integer, nullable=False, default=0,
                                  server_default="0")
    reference_rejected = Column(Integer, nullable=False, default=0,
                                 server_default="0")
    conviction_strong = Column(Integer, nullable=False, default=0,
                                server_default="0")
    conviction_moderate = Column(Integer, nullable=False, default=0,
                                  server_default="0")
    conviction_hedged = Column(Integer, nullable=False, default=0,
                                server_default="0")
    conviction_hypothetical = Column(Integer, nullable=False, default=0,
                                      server_default="0")
    conviction_unknown = Column(Integer, nullable=False, default=0,
                                 server_default="0")


class Disclosure(Base):
    """Forecaster position disclosures — past-tense statements about
    what they actually bought, sold, added, trimmed, or hold. NOT a
    prediction. NOT scored with HIT/NEAR/MISS.

    Scoring is "follow-through": what did the stock do in the 1/3/6/12
    months after the disclosed_at date? For buy/add/starter/hold
    actions a POSITIVE return is good follow-through (bought before
    it went up); for sell/trim/exit a NEGATIVE return is good (sold
    before it went down). The sign flip is applied at read time by
    the API endpoints — the raw follow_through_* columns store the
    unsigned stock return so backfills don't have to re-apply the
    action sign.

    Dedup key is source_platform_id = 'yt_{video_id}_{ticker}_{action}_{date}'
    — the same video claiming "I bought 500 AMD today" twice collapses,
    but a buy + an add in the same video both insert (different
    actions), and two different days' disclosures on AMD both insert
    (different source_video_id or different date).
    """
    __tablename__ = "disclosures"

    id = Column(Integer, primary_key=True, index=True)
    forecaster_id = Column(Integer, ForeignKey("forecasters.id"),
                           nullable=False, index=True)
    ticker = Column(String(16), nullable=False, index=True)
    # Action enum — enforced by a CHECK constraint at migration time
    # (see main.py migration block). Kept as String here so SQLAlchemy
    # doesn't try to manage a Postgres enum type.
    action = Column(String(16), nullable=False)
    # Exactly one of size_shares / size_pct / size_qualitative is
    # populated; all can be NULL when Haiku didn't extract a size.
    size_shares = Column(Numeric(12, 2), nullable=True)
    size_pct = Column(Numeric(5, 4), nullable=True)
    size_qualitative = Column(String(16), nullable=True)
    entry_price = Column(Numeric(12, 4), nullable=True)
    reasoning_text = Column(Text, nullable=True)
    disclosed_at = Column(DateTime, nullable=False, index=True)
    source_video_id = Column(String(64), nullable=True)
    source_platform_id = Column(String(128), unique=True, nullable=True)
    follow_through_1m = Column(Numeric(10, 4), nullable=True)
    follow_through_3m = Column(Numeric(10, 4), nullable=True)
    follow_through_6m = Column(Numeric(10, 4), nullable=True)
    follow_through_12m = Column(Numeric(10, 4), nullable=True)
    last_follow_through_update = Column(DateTime, nullable=True)
    # Source-timestamp metadata — ship #9. Mirrors the four
    # source_timestamp_* columns on predictions; populated the same
    # way (via backend/jobs/timestamp_matcher.py) when
    # ENABLE_SOURCE_TIMESTAMPS is on.
    source_timestamp_seconds = Column(Integer, nullable=True)
    source_timestamp_method = Column(String(16), nullable=True)
    source_verbatim_quote = Column(Text, nullable=True)
    source_timestamp_confidence = Column(Numeric(4, 3), nullable=True)
    # Ship #12 — soft training-set exclusion mirror of the predictions
    # columns. Disclosures can also be mis-categorized (e.g. a forward-
    # looking position call that reads like a disclosure), so the
    # fine-tune loader skips these too. Leaderboard follow-through
    # scoring is unaffected.
    excluded_from_training = Column(Boolean, nullable=False, default=False,
                                     server_default="false")
    exclusion_reason = Column(String(64), nullable=True)
    exclusion_flagged_at = Column(DateTime(timezone=True), nullable=True)
    exclusion_rule_version = Column(String(16), nullable=True)
    source_prediction_id = Column(Integer,
                                  ForeignKey("predictions.id",
                                             ondelete="SET NULL"),
                                  nullable=True)
    created_at = Column(DateTime, nullable=False,
                        default=datetime.datetime.utcnow,
                        server_default=func.now())

    forecaster = relationship("Forecaster", back_populates="disclosures")


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


class MacroConceptAlias(Base):
    """Canonical macro concept → ETF proxy mapping used by the YouTube
    classifier's macro_call extraction. The forecaster says "dollar
    strengthening" or "rates are going up"; Haiku emits a canonical
    concept name (e.g. 'dollar', 'rates_up'); the insert path resolves
    the concept to a tradeable ETF (UUP, TBT) via this table.

    direction_bias is either 'direct' (bullish-on-concept means
    bullish-on-ETF) or 'inverse' (bullish-on-concept means bearish-on-
    ETF — used for inverse bond mappings like bullish-on-rates-up →
    bearish-on-TLT). The insert path flips the direction when
    direction_bias='inverse' before storing the prediction.

    aliases is a comma-separated list of natural language phrases
    mapped to the concept, included inline in the Haiku prompt as a
    recognition guide. Admin-editable via /admin/macro-concepts.
    """
    __tablename__ = "macro_concept_aliases"

    id = Column(Integer, primary_key=True, index=True)
    concept = Column(String(64), nullable=False, unique=True)
    direction_bias = Column(String(16), nullable=False, default="direct",
                            server_default="direct")
    primary_etf = Column(String(16), nullable=False)
    secondary_etfs = Column(String(128), nullable=True)
    aliases = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow,
                        server_default=func.now())


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


class VideoTranscript(Base):
    """Immutable evidence preservation for YouTube predictions.

    One row per video_id (not per prediction). The SHA256 hash is
    locked at capture time and never changes, so the verbatim quote
    on any prediction can be re-verified against the stored transcript
    even if the forecaster deletes the video from YouTube.
    """
    __tablename__ = "video_transcripts"

    id = Column(Integer, primary_key=True)
    video_id = Column(String(11), nullable=False, unique=True, index=True)
    channel_name = Column(Text)
    video_title = Column(Text)
    video_publish_date = Column(DateTime(timezone=True))
    transcript_text = Column(Text, nullable=False)
    transcript_format = Column(String(20), default="json3")
    sha256_hash = Column(String(64), nullable=False)
    captured_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    # video_url is a STORED generated column in Postgres; mark as read-only
    # in the ORM so writes never touch it.
    video_url = Column(Text)


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
