# Twitch Channel Points Miner (Erani0 fork)

This is my personal fork of `Twitch-Channel-Points-Miner-v2`. I run it myself, on my own Pterodactyl/Pelican Panel server, farming channel points, drops and watch streaks across a fairly large streamer list, so most of what's in here got added because something actually broke or annoyed me in real use — not because it sounded good on paper.

A quick note on lineage, because it matters for understanding what's below: this started as [rdavydov's original project](https://github.com/rdavydov/Twitch-Channel-Points-Miner-v2), got picked up and hardened by [Armi1014's reliability fork](https://github.com/Armi1014/Twitch-Channel-Points-Miner-v2), and this repo continues from there with a pretty different set of priorities: self-hosting on a game panel, mobile-friendly dashboard, drop hunting that doesn't depend on you manually listing every streamer, and a watch streak system that's been rewritten more than once because Twitch keeps changing what it tells us.

> Not affiliated with Twitch. This is automation of a public website — use it at your own risk, and don't be surprised if Twitch changes something and breaks part of it. It happens.

## Quick start

If you're just running it locally / on a normal server:

```sh
git clone https://github.com/Erani0/Twitch-Channel-Points-Miner-v2.git
cd Twitch-Channel-Points-Miner-v2
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Copy `example.py` to `run.py`, fill in your Twitch username/streamer list, and run it with `python run.py`. That's the whole setup for a plain install.

### Running it on Pterodactyl / Pelican Panel

This is honestly the main way I use it, and it's the part that's most specific to this fork. There's a ready-made egg in [`egg-twitch-channel-points-miner/`](egg-twitch-channel-points-miner) that you can import into your panel. It clones the repo straight from GitHub, builds a `run.py` for you, and then on every container start it:

1. Compares your local git commit against `origin/master` and does a `git reset --hard` if there's a newer version — so you get updates just by restarting the server, no manual `git pull`.
2. Patches your `run.py` to add any *new* settings that got introduced since you installed, without touching your streamer list or anything else you've customized. This part exists because I got tired of new features silently doing nothing for people who installed a while ago and never knew there was a new option to turn on. It only ever adds missing keyword arguments — if it can't do that safely (say, your `run.py` got hand-edited into something the parser doesn't recognize), it leaves the file alone and logs a warning instead of guessing.
3. Strips out dev-only files (tests, CI config, `.claude/`, etc.) so your container doesn't carry around stuff it doesn't need.

Your `run.py` itself is never tracked by git (it's in `.gitignore`), so your personal streamer list and account settings survive updates. Same goes for `settings.json` if you use one for API keys — deliberately ignored, never gets swept into a commit by accident.

## What's actually different from upstream

The short version: better GQL query resilience, a watch streak system that doesn't quietly lose your streak on day two, drop hunting that can find channels you never added yourself, a dashboard that doesn't look like it's from 2019 and actually works on a phone, and a config file that upgrades itself.

Longer version, by area:

### GraphQL query maintenance

Twitch's GQL API uses "persisted query" hashes for most requests — opaque IDs that map to a query defined server-side. Twitch rotates these occasionally without warning, and when they go stale you start seeing things like `PersistedQueryNotFound` or requests that quietly return nothing useful. Upstream has fallen behind on this more than once. This fork tracks hash updates as they're found and reported (the `PlaybackAccessToken` and `ChannelPointsContext` hashes both got refreshed here after upstream users reported the old ones failing), and error handling around GQL responses is generally more defensive — missing/unexpected fields log a warning and get skipped instead of throwing an unhandled exception halfway through a run.

### Watch streaks

This got rewritten from a simple timestamp check into a proper session-based cache (`WatchStreakCache.py`) that tracks attempts, claim state, and broadcast identity per streamer, persisted to `logs/watch_streak_cache.<account>.json` so a restart doesn't throw away what it already knows.

One specific bug worth mentioning because it took a while to track down: `streamer.stream.broadcast_id` only gets refreshed once the stream info is actually re-fetched, which happens *after* the streak-priority logic runs. On the day after a stream ends, that meant the streak session lookup could still find yesterday's already-closed session for a split second, and treat today's brand-new broadcast as "already handled" — which could silently miss the window Twitch gives you to keep a streak alive. Fixed now, but it's the kind of bug that only shows up if you're watching streaks across many days, which is exactly the use case this fork cares about.

### Drop auto-discovery

New, and the one feature I'd flag as "use with reasonable expectations": if you turn on `auto_discover_drops=True`, the miner will look at currently active drop campaigns and try to find a live channel participating in one — even if it's not in your streamer list — and watch it in the shared slot until every drop in that campaign is claimed, then move to the next campaign. It respects the same one-channel-at-a-time rule Twitch applies to drop progress, and it never touches the slot reserved for your own configured streamers/streaks.

For campaigns with a channel whitelist, this is solid — it reuses the same stream-liveness query the rest of the miner already relies on. For open campaigns (any channel playing a given game counts), it uses a directory search query that, like the persisted-query hashes above, isn't something Twitch documents and could stop working if they change it. I've tried to make that fail quietly (logs and skips instead of crashing) rather than pretend it's bulletproof.

### Priority and selection

A few things added on top of upstream's priority system:

- `Priority.FAVORITE`, so you can pin specific streamers ahead of the general pool without reordering your whole list.
- `Priority.STREAK_LENGTH_ASCENDING` / `Priority.STREAK_LENGTH_DESCENDING` — sort streamers by how many days into a watch streak they already are. Put `STREAK_LENGTH_DESCENDING` near the top of your priority list and the miner leans toward protecting streaks you've already built up over ones that just started.
- Per-streamer `points_limit`, so a channel you've already farmed enough points from gets skipped in favor of ones that still need attention (pending streak claims still bypass this, on purpose).

### Dashboard / analytics

The Flask-based analytics server got a full visual rework — dark theme, a layout that doesn't fall apart on a phone screen, a console/log view that's actually usable on mobile instead of an afterthought. There's also cache-busting on the static assets, because GitHub's CDN caching used to mean you'd update the miner and still see the old dashboard until you force-refreshed five times.

### Everything else worth a mention

- Streamer bootstrap and context initialization are parallelized instead of strictly sequential, so a large streamer list doesn't take forever to become usable at startup.
- Startup connectivity checks time out instead of hanging forever if Twitch is unreachable.
- Hermes (Twitch's newer websocket transport) is available alongside the legacy PubSub client, with defensive handling for bad/expired topics so a single failing subscription doesn't spam your logs forever.
- The streamer export (`.xlsx` report in `logs/`) includes current points, points gained since baseline, watch streak days, sub status, and chat-ban status, styled and sorted automatically.

## What this fork won't promise

It won't promise Twitch will never change something that breaks a query hash — that's genuinely out of anyone's control, and it's happened to upstream, to the Armi1014 fork, and to this one. What it does promise is that when it happens, the failure is visible in the logs instead of silent, and fixes tend to land here reasonably fast because I'm running this on my own account and notice quickly when something's off.

## Docs

- [FAQ](FAQ.md)
- [Example config](example.py)
- [Contributing](CONTRIBUTING.md)
- [Pterodactyl/Pelican egg](egg-twitch-channel-points-miner)

## Credits

- [rdavydov](https://github.com/rdavydov/Twitch-Channel-Points-Miner-v2) for the original project.
- [Armi1014](https://github.com/Armi1014/Twitch-Channel-Points-Miner-v2) for the reliability-focused fork this one continues from.

## Disclaimer

Not affiliated with Twitch. This automates a public website's normal viewing behavior — understand the platform's rules before running it, and use it at your own risk.
