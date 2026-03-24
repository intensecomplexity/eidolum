from __future__ import annotations
import datetime
from typing import Optional
from pydantic import BaseModel, computed_field


class VideoOut(BaseModel):
    id: int
    youtube_id: Optional[str]
    title: str
    published_at: Optional[datetime.datetime]
    thumbnail_url: Optional[str]
    view_count: int

    model_config = {"from_attributes": True}


class PredictionOut(BaseModel):
    id: int
    ticker: str
    direction: str
    target_price: Optional[float]
    entry_price: Optional[float]
    prediction_date: datetime.datetime
    evaluation_date: Optional[datetime.datetime]
    window_days: int
    outcome: str
    actual_return: Optional[float]
    sp500_return: Optional[float]
    alpha: Optional[float]
    sector: Optional[str]
    context: Optional[str]
    forecaster_id: int
    video_id: Optional[int]

    model_config = {"from_attributes": True}


class ForecasterSummary(BaseModel):
    id: int
    name: str
    handle: str
    channel_url: Optional[str]
    subscriber_count: int
    profile_image_url: Optional[str]
    accuracy_rate: float       # 0–100
    total_predictions: int
    evaluated_predictions: int
    correct_predictions: int
    alpha: float               # avg alpha vs S&P
    sector_strengths: list[dict]

    model_config = {"from_attributes": True}


class ForecasterDetail(BaseModel):
    id: int
    name: str
    handle: str
    channel_url: Optional[str]
    subscriber_count: int
    profile_image_url: Optional[str]
    bio: Optional[str]
    accuracy_rate: float
    total_predictions: int
    evaluated_predictions: int
    correct_predictions: int
    alpha: float
    sector_strengths: list[dict]
    predictions: list[PredictionOut]
    accuracy_over_time: list[dict]   # [{date, cumulative_accuracy}]

    model_config = {"from_attributes": True}


class AssetConsensus(BaseModel):
    ticker: str
    total_predictions: int
    bullish_count: int
    bearish_count: int
    bullish_pct: float
    recent_predictions: list[dict]   # includes forecaster info
    top_accurate_forecasters: list[dict]

    model_config = {"from_attributes": True}


class SyncResponse(BaseModel):
    message: str
    channels_synced: int
    videos_fetched: int
    predictions_parsed: int
