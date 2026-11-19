# Armi1014 Fork: What's New

This fork focuses on one goal: keep the miner stable and usable at larger streamer counts while keeping updates practical.

Upstream repository:
https://github.com/rdavydov/Twitch-Channel-Points-Miner-v2

Fork repository:
https://github.com/Armi1014/Twitch-Channel-Points-Miner-v2

## Why use this fork

- Better startup behavior on medium/large streamer lists.
- Better runtime resilience when Twitch APIs/PubSub are flaky.
- Better watch streak handling in real-world edge cases.
- Less noisy logs during repeated transient failures.

## Key improvements in this fork

## 1) Startup speed and startup safety

- Streamer bootstrap is parallelized (`ThreadPoolExecutor`) instead of strictly sequential loading.
- Streamer context initialization is also parallelized with a timeout scaled by streamer count.
- Startup connectivity check avoids hanging forever when Twitch is unreachable.
- Miner exits early if no valid streamers remain after initialization.

Relevant code:
- `TwitchChannelPointsMiner/TwitchChannelPointsMiner.py`
- `TwitchChannelPointsMiner/classes/Twitch.py`

## 2) Watch streak reliability upgrades

- Persisted watch streak cache (`logs/watch_streak_cache.<account>.json`) to avoid wasting startup time repeating stale checks.
- Session-based watch streak tracking (attempts, claim state, ended state, broadcast identity).
- Better handling for Twitch observability gaps:
  - if a watch window completes and `WATCH` is observed but `WATCH_STREAK` is not emitted, the miner now ends that streak attempt for that broadcast instead of getting stuck retrying it.

Relevant code:
- `TwitchChannelPointsMiner/WatchStreakCache.py`
- `TwitchChannelPointsMiner/classes/Twitch.py`
- `TwitchChannelPointsMiner/classes/entities/Streamer.py`

## 3) WebSocket / PubSub stability improvements

- Better handling of transient disconnect-style websocket errors (throttled logging to reduce spam).
- Defensive handling for `ERR_BADTOPIC`:
  - invalid topics are removed from resubscribe lists to prevent endless retry noise.
- LISTEN nonce tracking so PubSub RESPONSE errors can be mapped back to the specific failed topic.

Relevant code:
- `TwitchChannelPointsMiner/classes/websocket/pubsub/Pool.py`
- `TwitchChannelPointsMiner/classes/websocket/pubsub/Client.py`
- `TwitchChannelPointsMiner/classes/PubSub.py`

## 4) GQL hardening and observability

- Request timeout in GQL request path.
- Non-2xx HTTP status is surfaced in logs.
- Safer operation-name extraction for single and batched GQL payloads.
- Defensive parsing behavior to avoid common runtime crashes from malformed/partial responses.

Relevant code:
- `TwitchChannelPointsMiner/classes/Twitch.py`

## 5) Priority/selection quality

- Priority behavior and tie-breaking around STREAK/DROPS/SUBSCRIBED have been tightened and regression-tested.
- Added explicit `Priority.FAVORITE` + `StreamerSettings.favorite` for predictable `STREAK -> FAVORITE -> ...` policy.
- STREAK selection now rotates eligible candidates to reduce starvation when many channels go live together.

Relevant tests:
- `tests/test_priority_selection.py`
- `tests/test_priority_sorting.py`
- `tests/test_priority_favorite.py`
- `tests/test_watch_streak_fallback.py`
- `tests/test_websocket_badtopic.py`

## 5b) Drops always get their own slot (drop_campaigns.json)

- With `auto_discover_drops=True` one of the two watch slots belongs to drops permanently; watch streaks use the other one and can no longer push drops out.
- Twitch's drops dashboard returns no campaigns for the TV login (`dropCampaigns: null`), so campaigns are now found without it: on live channels the miner already watches that carry the drops tag, on live drop channels of every game seen before, and in the inventory (campaigns in progress). Rewards already claimed are recognised from the inventory. No second login is needed.
- Every 15 minutes the list is refreshed; `drop_campaigns.json` next to `run.py` shows each campaign with game, status (running, no live channel right now, paused, all claimed, ended), end, open drops, progress towards the next drop and the channels it counts on. Ended and finished entries are removed 14 days after the campaign end.
- The file order is the working order: the highest listed campaign that has a live channel is watched, a campaign moved higher takes over as soon as it has a live channel. New campaigns go below the last campaign of the same game, otherwise to the end. `aktiv: false` skips a campaign or (under `spiele`) a whole game. The file is read every minute; a file saved with mistakes repairs itself (small slips fixed, otherwise order and `aktiv` recovered, otherwise last valid state) and the broken text is kept as `drop_campaigns.fehlerhaft.json`.
- The drop channel is replaced when it goes offline or shows no progress for 25 minutes; a campaign that shows no progress on its channels (for example subscription-only drops) is paused for 6 hours. Drops that need 0 minutes are not used to decide the order. A channel from your own streamer list is reused instead of being added twice.
- The `safe.directory` line that `run.py` adds to `~/.gitconfig` on every start is de-duplicated automatically.
- Existing installations update as usual; `run.py` is never overwritten and the new behaviour only starts once `auto_discover_drops=True` is set.

Relevant tests:
- `tests/test_drop_priority_file.py`
- `tests/test_drop_discovery.py`

## 6) Compatibility note

- Package metadata in this fork currently targets Python `>=3.10`.

Relevant file:
- `setup.py`

## What is still limited by Twitch

- Watch streak observability is not fully deterministic because Twitch can omit/alter signals depending on feature configuration and runtime behavior.
- This fork mitigates those cases, but cannot fully control Twitch-side API behavior.

## Quick install from this fork

```bash
git clone https://github.com/Armi1014/Twitch-Channel-Points-Miner-v2.git
cd Twitch-Channel-Points-Miner-v2
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

## Recent reliability patch reference

- Commit: `689136d`
- URL: https://github.com/Armi1014/Twitch-Channel-Points-Miner-v2/commit/689136d
