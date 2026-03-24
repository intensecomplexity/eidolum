"""
YouTube Data API v3 integration for fetching channel videos.
Quota-safe: NEVER uses search.list (100 units).
Uses playlistItems.list (1 unit) and channels.list (1 unit) instead.
"""
import os
import datetime
from typing import Optional

from services.youtube_quota import quota, SYNC_INTERVAL_HOURS, MAX_VIDEOS_PER_SYNC

try:
    from googleapiclient.discovery import build
    YOUTUBE_AVAILABLE = True
except ImportError:
    YOUTUBE_AVAILABLE = False


YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")


def get_youtube_client():
    if not YOUTUBE_AVAILABLE or not YOUTUBE_API_KEY:
        return None
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def can_sync_channel(forecaster) -> bool:
    """Check if enough time has passed since last sync for this channel."""
    if forecaster.last_synced_at is None:
        return True
    elapsed = datetime.datetime.utcnow() - forecaster.last_synced_at
    return elapsed >= datetime.timedelta(hours=SYNC_INTERVAL_HOURS)


def get_next_sync_allowed(forecaster) -> Optional[datetime.datetime]:
    """Return the earliest datetime this channel can be synced again."""
    if forecaster.last_synced_at is None:
        return None  # can sync now
    return forecaster.last_synced_at + datetime.timedelta(hours=SYNC_INTERVAL_HOURS)


def _get_uploads_playlist_id(client, channel_id: str) -> Optional[str]:
    """Fetch the uploads playlist ID via channels.list (1 unit). Returns None on failure."""
    def _call():
        request = client.channels().list(
            part="contentDetails",
            id=channel_id,
        )
        response = request.execute()
        items = response.get("items", [])
        if not items:
            return None
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    return quota.safe_request("channels.list", 1, _call, fallback=None)


def get_uploads_playlist_id(client, forecaster, db) -> Optional[str]:
    """Get uploads playlist ID, using cached value from DB when available."""
    if forecaster.uploads_playlist_id:
        return forecaster.uploads_playlist_id

    playlist_id = _get_uploads_playlist_id(client, forecaster.channel_id)
    if playlist_id:
        forecaster.uploads_playlist_id = playlist_id
        db.commit()
    return playlist_id


def fetch_channel_videos(channel_id: str, max_results: int = 50,
                         forecaster=None, db=None) -> list[dict]:
    """
    Fetch recent videos from a YouTube channel using playlistItems.list (1 unit per page).
    NEVER uses search.list.

    If forecaster and db are provided, uses cached uploads_playlist_id and
    stops at last_fetched_video_id for incremental syncs.
    """
    client = get_youtube_client()
    if client is None:
        return []

    # Get uploads playlist ID
    if forecaster and db:
        playlist_id = get_uploads_playlist_id(client, forecaster, db)
    else:
        playlist_id = _get_uploads_playlist_id(client, channel_id)

    if not playlist_id:
        return []

    videos = []
    page_token = None
    stop_at_video_id = forecaster.last_fetched_video_id if forecaster else None
    remaining = min(max_results, MAX_VIDEOS_PER_SYNC)

    while remaining > 0:
        page_size = min(remaining, 50)

        def _call(pt=page_token, ps=page_size):
            request = client.playlistItems().list(
                part="snippet",
                playlistId=playlist_id,
                maxResults=ps,
                pageToken=pt,
            )
            return request.execute()

        response = quota.safe_request("playlistItems.list", 1, _call, fallback=None)
        if response is None:
            break

        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            video_id = snippet.get("resourceId", {}).get("videoId")
            if not video_id:
                continue

            # Stop if we've reached the last video we already fetched
            if stop_at_video_id and video_id == stop_at_video_id:
                remaining = 0
                break

            published_raw = snippet.get("publishedAt", "")
            published_at = None
            if published_raw:
                try:
                    published_at = datetime.datetime.fromisoformat(
                        published_raw.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except ValueError:
                    pass

            videos.append({
                "youtube_id": video_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": published_at,
                "thumbnail_url": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
            })
            remaining -= 1
            if remaining <= 0:
                break

        next_page = response.get("nextPageToken")
        if not next_page or remaining <= 0:
            break
        page_token = next_page

    return videos


def get_channel_info(channel_id: str) -> Optional[dict]:
    """Fetch channel metadata (subscriber count, etc.) via channels.list (1 unit)."""
    client = get_youtube_client()
    if client is None:
        return None

    def _call():
        request = client.channels().list(
            part="snippet,statistics",
            id=channel_id,
        )
        return request.execute()

    response = quota.safe_request("channels.list", 1, _call, fallback=None)
    if response is None:
        return None

    items = response.get("items", [])
    if not items:
        return None
    item = items[0]
    stats = item.get("statistics", {})
    snippet = item.get("snippet", {})
    return {
        "subscriber_count": int(stats.get("subscriberCount", 0)),
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "thumbnail_url": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
    }
