# Twitter/X MCP Server

An MCP (Model Context Protocol) server that lets AI assistants interact with your Twitter/X account. No API key required — uses browser cookie authentication via [twikit](https://github.com/d60/twikit).

## Why?

Twitter's API free tier has been deprecated. The paid tiers start at $200/month. This MCP server bypasses that by using browser cookies to authenticate, giving you full access to your account through any MCP-compatible client (Claude Code, Claude Desktop, etc).

## Tools

| Tool | Description |
|---|---|
| `get_me` | Get your profile info |
| `get_my_timeline` | Get your home timeline |
| `get_my_recent_tweets` | Get your recent tweets |
| `post_tweet` | Post a tweet (with optional reply) |
| `delete_tweet` | Delete a tweet by ID |
| `search_tweets` | Search recent tweets |
| `get_user` | Look up any user's profile |
| `get_user_tweets` | Get a user's recent tweets |
| `like_tweet` | Like a tweet |
| `unlike_tweet` | Unlike a tweet |
| `retweet` | Retweet a tweet |
| `follow_user` | Follow a user |
| `unfollow_user` | Unfollow a user |
| `get_trending` | Get trending topics |

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- A Twitter/X account
- [Cookie-Editor](https://cookie-editor.com/) browser extension

### 1. Clone and install

```bash
git clone https://github.com/0xshubhank/twitter-account-mcp.git
cd twitter-account-mcp
uv sync
```

### 2. Export your Twitter cookies

1. Install the [Cookie-Editor](https://cookie-editor.com/) extension in your browser
2. Log in to [x.com](https://x.com)
3. Click the Cookie-Editor icon
4. Click **Export** (copies JSON to clipboard)
5. Save the exported JSON as `cookies.json` in the project root

### 3. Set your username

```bash
cp .env.example .env
```

Edit `.env` and set your Twitter username:

```
TWITTER_USERNAME=your_username
```

### 4. Add to your MCP client

**Claude Code:**

```bash
claude mcp add twitter -- uv run --directory /path/to/twitter-account-mcp python main.py
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "twitter": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/twitter-account-mcp", "python", "main.py"]
    }
  }
}
```

### 5. Verify

```bash
uv run python -c "
import asyncio, main
async def test():
    r = await main.get_me()
    print(f'Connected as @{r[\"username\"]}')
asyncio.run(test())
"
```

## Cookie Expiry

Browser cookies expire periodically. When you start seeing auth errors, re-export your cookies from Cookie-Editor and overwrite `cookies.json`.

## Disclaimer

This project uses an unofficial method to access Twitter. It is not affiliated with or endorsed by Twitter/X. Use at your own risk — your account could potentially be restricted if Twitter detects unusual activity. Keep request rates reasonable.

## License

MIT
