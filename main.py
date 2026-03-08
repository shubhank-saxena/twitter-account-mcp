import json
import os
from pathlib import Path
from urllib.parse import unquote

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from twikit import Client

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


def _tweet_to_dict(tweet) -> dict:
    return {
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


if __name__ == "__main__":
    mcp.run()
