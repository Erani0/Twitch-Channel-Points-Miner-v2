# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**Twitch Channel Points Miner v2** is a Python script that automatically watches Twitch streams to earn channel points. It handles bonus claims, watch streaks, raids, bets/predictions, drops, moments, community goals, and IRC chat presence.

## Running the miner

```sh
pip install -r requirements.txt
python run.py
```

Create `run.py` by copying `example.py` and editing it with your credentials and settings. Cookie-based login is used — on first run it will prompt for credentials interactively, then save cookies to `cookies/<username>.pkl`.

### Docker

```sh
docker run -v $(pwd)/run.py:/usr/src/app/run.py:ro rdavidoff/twitch-channel-points-miner-v2
```

Mount `run.py`, `analytics/`, `cookies/`, and `logs/` as volumes to persist data.

## Architecture

### Core flow

1. `TwitchChannelPointsMiner.mine()` — Entry point; loads streamers, starts all background threads
2. `Twitch.login()` — Loads/creates cookies; authenticates via Twitch
3. `send_minute_watched_events()` — Thread that watches up to 2 streamers, sending minute-watched events via the HLS/spade endpoint (2024 API fix)
4. `WebSocketsPool` — Manages PubSub WebSocket connections to Twitch, each connection supports up to 50 topics
5. `WebSocketsPool.on_message()` — Dispatches PubSub messages by topic to appropriate handlers

### Key classes

| Class | File | Role |
|-------|------|------|
| `TwitchChannelPointsMiner` | `TwitchChannelPointsMiner.py` | Main orchestrator; owns threads, priority system, streamer list |
| `Twitch` | `classes/Twitch.py` | All Twitch GQL API calls; retrieves stream info, channel points, predictions, drops, follows |
| `TwitchLogin` | `classes/TwitchLogin.py` | Cookie-based authentication flow |
| `WebSocketsPool` | `classes/WebSocketsPool.py` | Pool of PubSub WebSocket connections; handles topics, reconnection |
| `TwitchWebSocket` | `classes/TwitchWebSocket.py` | Single WebSocket connection; ping/pong, reconnection logic |
| `Streamer` | `classes/entities/Streamer.py` | Per-streamer state: channel_points, is_online, settings, history, analytics |
| `EventPrediction` | `classes/entities/EventPrediction.py` | Active prediction/bet; stores outcomes, decision, result |
| `Bet` | `classes/entities/Bet.py` | Betting strategy, amount calculation, filter conditions |
| `Campaign` / `Drop` | `classes/entities/Campaign.py`, `Drop.py` | Drop campaigns and individual drops |
| `LoggerSettings` | `logger.py` | Logging config with console/file/notification handlers |

### Priority system

Only 2 streamers can be watched simultaneously. `send_minute_watched_events()` resolves which streamers to watch based on priority list (`Priority.STREAK`, `Priority.DROPS`, `Priority.ORDER`, etc.) and the conditions on each streamer.

### PubSub topics subscribed per streamer

- `video-playback-by-id` — stream online/offline events
- `raid` — incoming raids (if `follow_raid=True`)
- `predictions-channel-v1` — new predictions (if `make_predictions=True`)
- `community-moments-channel-v1` — moments (if `claim_moments=True`)
- `community-points-channel-v1` — community goals (if `community_goals=True`)

Global topics: `community-points-user-v1` (points balance), `predictions-user-v1` (bet results).

### GQL operations

All GraphQL queries are in `constants.py` as `GQLOperations` class constants. They use persisted query hashes. `Twitch.post_gql_request()` handles all GQL calls with auth headers.

### Analytics

Optional Flask server via `twitch_miner.analytics(host, port, refresh, days_ago)`. When enabled, `Streamer.persistent_series()` and `persistent_annotations()` write JSON files to `analytics/<username>/`.

## Key patterns

- **Settings cascade**: `StreamerSettings` defaults are applied via `set_default_settings()` — miner-level settings fill in `None` values on streamer-level settings
- **Thread-safe logging**: QueueListener/QueueHandler pattern in `configure_loggers()` — all log handlers run in a dedicated listener thread
- **`__slots__`**: Most classes use `__slots__` for memory efficiency
- **Silent failures**: GQL/API errors often return empty `{}` rather than raising; always check `response != {}` before accessing keys