import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP, Image
from mcp.types import TextContent
from twikit import Client

MAX_VIDEO_DURATION_MS = 5 * 60 * 1000  # 5 minutes
VIDEO_FRAME_COUNT = 6

load_dotenv()

mcp = FastMCP("twitter-account")

COOKIES_FILE = Path(__file__).parent / "cookies.json"

_client: Client | None = None
_my_user_id: str | None = None
_my_screen_name: str | None = None


async def get_client() -> Client:
    global _client, _my_user_id, _my_screen_name
    if _client is not None:
        return _client

    if not COOKIES_FILE.exists():
        raise FileNotFoundError(
            "cookies.json not found. Export cookies from your browser "
            "(use Cookie-Editor extension) while logged into x.com, "
            "then save the JSON to cookies.json in the project root."
        )

    client = Client("en-US")

    with open(COOKIES_FILE, "r") as f:
        raw = json.load(f)

    # Support both Cookie-Editor format (list of dicts) and twikit format (flat dict)
    if isinstance(raw, list):
        cookies = {c["name"]: c["value"] for c in raw}
    else:
        cookies = raw

    client.set_cookies(cookies)

    # Extract user ID from twid cookie (format: u%3D<user_id> or u=<user_id>)
    twid = cookies.get("twid", "")
    _my_user_id = unquote(twid).replace("u=", "")

    # Screen name from env, or fetch from settings API
    _my_screen_name = os.environ.get("TWITTER_USERNAME")
    if not _my_screen_name:
        response, _ = await client.v11.settings()
        _my_screen_name = response["screen_name"]

    _client = client
    return client


async def _download(url: str) -> bytes:
    """Download a URL and return the raw bytes."""
    async with httpx.AsyncClient() as http:
        resp = await http.get(url, follow_redirects=True, timeout=60)
        resp.raise_for_status()
        return resp.content


def _extract_video_frames(video_bytes: bytes, count: int = VIDEO_FRAME_COUNT) -> list[bytes]:
    """Extract evenly-spaced frames from a video using ffmpeg."""
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = Path(tmpdir) / "video.mp4"
        video_path.write_bytes(video_bytes)

        # Get duration
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True,
        )
        duration = float(probe.stdout.strip() or "0")
        if duration <= 0:
            return []

        # Calculate timestamps for evenly-spaced frames
        interval = duration / (count + 1)
        timestamps = [interval * (i + 1) for i in range(count)]

        frames = []
        for i, ts in enumerate(timestamps):
            frame_path = Path(tmpdir) / f"frame_{i}.jpg"
            subprocess.run(
                ["ffmpeg", "-v", "quiet", "-ss", str(ts), "-i", str(video_path),
                 "-frames:v", "1", "-q:v", "2", str(frame_path)],
                capture_output=True,
            )
            if frame_path.exists():
                frames.append(frame_path.read_bytes())

        return frames


async def _get_video_url(media) -> str | None:
    """Get the best MP4 URL from a video media object."""
    if not (hasattr(media, "video_info") and media.video_info):
        return None
    variants = media.video_info.get("variants", [])
    mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
    if not mp4s:
        return None
    return max(mp4s, key=lambda v: v.get("bitrate", 0))["url"]


async def _parse_media(media_list) -> list:
    """Parse tweet media into Image objects and text descriptions.

    Returns a list of MCP content blocks (Image, TextContent).
    """
    content = []

    for media in media_list:
        if media.type == "photo":
            img_bytes = await _download(media.media_url)
            content.append(TextContent(type="text", text=f"[Image from tweet]"))
            content.append(Image(data=img_bytes, format="jpeg"))

        elif media.type in ("video", "animated_gif"):
            duration_ms = getattr(media, "duration_millis", 0) or 0

            # Always include thumbnail
            thumb_bytes = await _download(media.media_url)
            content.append(TextContent(type="text", text=f"[Video thumbnail — duration: {duration_ms / 1000:.1f}s]"))
            content.append(Image(data=thumb_bytes, format="jpeg"))

            # For videos under 5 min, extract frames
            if duration_ms > 0 and duration_ms <= MAX_VIDEO_DURATION_MS:
                video_url = await _get_video_url(media)
                if video_url:
                    video_bytes = await _download(video_url)
                    frames = await asyncio.to_thread(
                        _extract_video_frames, video_bytes
                    )
                    for i, frame_bytes in enumerate(frames):
                        content.append(TextContent(
                            type="text",
                            text=f"[Video frame {i + 1}/{len(frames)}]",
                        ))
                        content.append(Image(data=frame_bytes, format="jpeg"))

            # Try to get subtitles
            if hasattr(media, "get_subtitles"):
                try:
                    subs = await media.get_subtitles()
                    if subs:
                        content.append(TextContent(
                            type="text",
                            text=f"[Video subtitles]\n{subs}",
                        ))
                except Exception:
                    pass

    return content


def _media_to_dict(media) -> dict:
    result = {
        "type": media.type,
        "url": media.media_url,
    }
    if media.type == "video" and hasattr(media, "video_info") and media.video_info:
        variants = media.video_info.get("variants", [])
        mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
        if mp4s:
            best = max(mp4s, key=lambda v: v.get("bitrate", 0))
            result["video_url"] = best["url"]
    return result


def _tweet_to_dict(tweet) -> dict:
    result = {
        "id": tweet.id,
        "text": tweet.text,
        "author": tweet.user.name if tweet.user else None,
        "username": tweet.user.screen_name if tweet.user else None,
        "created_at": tweet.created_at,
        "likes": tweet.favorite_count,
        "retweets": tweet.retweet_count,
        "replies": tweet.reply_count,
        "views": tweet.view_count,
    }
    if tweet.media:
        result["media"] = [_media_to_dict(m) for m in tweet.media]
    if tweet.urls:
        result["urls"] = [
            {"display": u["display_url"], "expanded": u["expanded_url"]}
            for u in tweet.urls
        ]
    return result


def _user_to_dict(user) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "username": user.screen_name,
        "description": user.description,
        "followers": user.followers_count,
        "following": user.following_count,
        "tweets": user.statuses_count,
        "created_at": user.created_at,
        "location": user.location,
        "verified": user.is_blue_verified,
    }


@mcp.tool()
async def get_me() -> dict:
    """Get the authenticated user's profile information."""
    client = await get_client()
    user = await client.get_user_by_screen_name(_my_screen_name)
    return _user_to_dict(user)


@mcp.tool()
async def get_my_timeline(count: int = 20) -> list[dict]:
    """Get the authenticated user's home timeline.

    Args:
        count: Number of tweets to return (default 20).
    """
    client = await get_client()
    tweets = await client.get_timeline(count=count)
    return [_tweet_to_dict(t) for t in tweets]


@mcp.tool()
async def get_my_recent_tweets(count: int = 20) -> list[dict]:
    """Get the authenticated user's recent tweets.

    Args:
        count: Number of tweets to return.
    """
    client = await get_client()
    tweets = await client.get_user_tweets(_my_user_id, "Tweets", count=count)
    return [_tweet_to_dict(t) for t in tweets]


@mcp.tool()
async def post_tweet(text: str, reply_to: str | None = None) -> dict:
    """Post a new tweet.

    Args:
        text: The tweet text.
        reply_to: Optional tweet ID to reply to.
    """
    client = await get_client()
    tweet = await client.create_tweet(text=text, reply_to=reply_to)
    return {"id": tweet.id, "text": tweet.text}


async def _tweet_with_context(tweet) -> list:
    """Build rich content blocks for a tweet: metadata + parsed media."""
    tweet_data = _tweet_to_dict(tweet)
    content: list = [TextContent(type="text", text=json.dumps(tweet_data, indent=2))]

    if tweet.media:
        media_content = await _parse_media(tweet.media)
        content.extend(media_content)

    return content


@mcp.tool()
async def get_tweet(tweet_id: str) -> list:
    """Get a single tweet by its ID with full media context.

    Images are returned inline. Videos under 5 minutes are parsed
    into keyframes. Includes subtitles when available.

    Args:
        tweet_id: The ID of the tweet to fetch.
    """
    client = await get_client()
    tweets = await client.get_tweets_by_ids([tweet_id])
    if not tweets:
        return [TextContent(type="text", text=f"Tweet {tweet_id} not found.")]
    return await _tweet_with_context(tweets[0])


@mcp.tool()
async def delete_tweet(tweet_id: str) -> dict:
    """Delete a tweet by ID.

    Args:
        tweet_id: The ID of the tweet to delete.
    """
    client = await get_client()
    await client.delete_tweet(tweet_id)
    return {"deleted": True}


@mcp.tool()
async def search_tweets(query: str, count: int = 20) -> list[dict]:
    """Search tweets.

    Args:
        query: Search query (supports Twitter search operators).
        count: Number of results.
    """
    client = await get_client()
    tweets = await client.search_tweet(query, "Latest", count=count)
    return [_tweet_to_dict(t) for t in tweets]


@mcp.tool()
async def get_user(username: str) -> dict:
    """Get a user's profile by username.

    Args:
        username: Twitter username (without @).
    """
    client = await get_client()
    user = await client.get_user_by_screen_name(username)
    return _user_to_dict(user)


@mcp.tool()
async def get_user_tweets(username: str, count: int = 20) -> list[dict]:
    """Get recent tweets from a specific user.

    Args:
        username: Twitter username (without @).
        count: Number of tweets to return.
    """
    client = await get_client()
    user = await client.get_user_by_screen_name(username)
    tweets = await client.get_user_tweets(user.id, "Tweets", count=count)
    return [_tweet_to_dict(t) for t in tweets]


@mcp.tool()
async def like_tweet(tweet_id: str) -> dict:
    """Like a tweet.

    Args:
        tweet_id: The ID of the tweet to like.
    """
    client = await get_client()
    await client.favorite_tweet(tweet_id)
    return {"liked": True}


@mcp.tool()
async def unlike_tweet(tweet_id: str) -> dict:
    """Unlike a tweet.

    Args:
        tweet_id: The ID of the tweet to unlike.
    """
    client = await get_client()
    await client.unfavorite_tweet(tweet_id)
    return {"unliked": True}


@mcp.tool()
async def retweet(tweet_id: str) -> dict:
    """Retweet a tweet.

    Args:
        tweet_id: The ID of the tweet to retweet.
    """
    client = await get_client()
    await client.retweet(tweet_id)
    return {"retweeted": True}


@mcp.tool()
async def follow_user(username: str) -> dict:
    """Follow a user.

    Args:
        username: Twitter username to follow (without @).
    """
    client = await get_client()
    user = await client.get_user_by_screen_name(username)
    await client.follow_user(user.id)
    return {"following": True}


@mcp.tool()
async def unfollow_user(username: str) -> dict:
    """Unfollow a user.

    Args:
        username: Twitter username to unfollow (without @).
    """
    client = await get_client()
    user = await client.get_user_by_screen_name(username)
    await client.unfollow_user(user.id)
    return {"unfollowed": True}


@mcp.tool()
async def get_trending() -> list[dict]:
    """Get current trending topics."""
    client = await get_client()
    trends = await client.get_trends("trending")
    return [{"name": t.name, "count": t.posts_count} for t in trends]


@mcp.tool()
async def get_bookmarks(count: int = 20) -> list[dict]:
    """Get the authenticated user's saved/bookmarked tweets.

    Args:
        count: Number of bookmarks to return.
    """
    client = await get_client()
    tweets = await client.get_bookmarks(count=count)
    return [_tweet_to_dict(t) for t in tweets]


@mcp.tool()
async def get_bookmark_context(index: int = 0) -> list:
    """Get full context of a bookmarked tweet including parsed media.

    Images are returned inline. Videos under 5 minutes are parsed
    into keyframes.

    Args:
        index: Which bookmark to get context for (0 = most recent).
    """
    client = await get_client()
    tweets = await client.get_bookmarks(count=index + 1)
    if index >= len(tweets):
        return [TextContent(type="text", text=f"Bookmark at index {index} not found.")]
    return await _tweet_with_context(tweets[index])


@mcp.tool()
async def bookmark_tweet(tweet_id: str) -> dict:
    """Bookmark/save a tweet.

    Args:
        tweet_id: The ID of the tweet to bookmark.
    """
    client = await get_client()
    await client.bookmark_tweet(tweet_id)
    return {"bookmarked": True}


@mcp.tool()
async def unbookmark_tweet(tweet_id: str) -> dict:
    """Remove a tweet from bookmarks.

    Args:
        tweet_id: The ID of the tweet to unbookmark.
    """
    client = await get_client()
    await client.delete_bookmark(tweet_id)
    return {"unbookmarked": True}


if __name__ == "__main__":
    mcp.run()
