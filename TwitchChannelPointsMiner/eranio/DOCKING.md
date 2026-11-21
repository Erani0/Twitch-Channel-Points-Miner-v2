# Docking points

All own code lives in `TwitchChannelPointsMiner/eranio/` (plus the new top-level shim `TwitchChannelPointsMiner/run_config_migration.py`, which does not exist in the base). Edits in base files are kept to a few lines so that a merge of the base branch produces few or no conflicts. Base: release 3.22.0 (795629a).

## 1. Base files touched (phase 0/1)

| File | Change | Why |
|---|---|---|
| `TwitchChannelPointsMiner/__init__.py` | one added line after the existing import: `from .eranio import TwitchChannelPointsMiner` | `from TwitchChannelPointsMiner import TwitchChannelPointsMiner` in existing run.py files returns the compatible class. The base import line and the `__version__` line stay untouched. |
| `TwitchChannelPointsMiner/classes/Settings.py` | `Priority`: two members `STREAK_LENGTH_ASCENDING`, `STREAK_LENGTH_DESCENDING` after `POINTS_DESCENDING`; `Events`: member `SUBSCRIPTION` after `CHAT_MENTION` | Old run.py files and notifier lists reference these names. Enum members cannot be added from outside cleanly. Both STREAK_LENGTH values are mapped to `Priority.STREAK` by `eranio/compat.py` (`normalize_priority`), so the base selection never sees them; the original list (`requested_priority`) feeds the ordering in `eranio/streak.py`. `Events.SUBSCRIPTION` exists only so that old configs resolve; the base does not emit it. |

| `TwitchChannelPointsMiner/classes/Twitch.py` (phase 2) | `_has_pending_watch_streak`: 5 lines at the top (lazy import, `eranio_streak.is_pending`, return when it is not `None`); `send_minute_watched_events`: one lazy import line at the start and one `eranio_streak.apply(...)` call replacing `streamers_watching = filtered_streamers_watching` (before the category pick logging) | The streak decision (RewardList as source of truth, fan-out, ordering, drop slot loan) lives in `eranio/streak.py`. Without a configured extension (`STATE.configured` false) `is_pending` returns `None` and `apply` returns the base selection unchanged, so base tests and a plain base miner behave as before. |
| `tests/conftest.py` (phase 2) | autouse fixture `reset_eranio_streak_state` | The extension state is module-global; every test starts clean. |

| `TwitchChannelPointsMiner/classes/Twitch.py` (phase 3) | `send_minute_watched_events`: import line `eranio_drops`; one `and eranio_drops.allows_watch(...)` line in the `streamers_index` filter; `category_order = eranio_drops.pick_key(...)` plus four `key=category_expiration` replaced by `key=category_order` (two tier sorts, two tier minimums); `_drop_rank` returns `eranio_drops.drop_rank(...)`; the list passed to `eranio_streak.apply` is wrapped in `eranio_drops.reserve(...)`. `sync_campaigns`: import line, `eranio_drops.remember(campaign)` right after `Campaign(...)` is built (before `clear_drops`), `eranio_drops.publish(self, campaigns, streamers)` after `__sync_drop_progress`. | Drop order from `drop_campaigns.json`, on/off, fixed drop slot, file output. Without `drops.configure` (auto_discover_drops false) every hook is a no-op: `allows_watch` True, `pick_key` returns the base key, `drop_rank` the base rank, `reserve` and `publish` return/do nothing. |
| `tests/conftest.py` (phase 3) | autouse fixture also resets `drops.STATE` | module-global state |

New files (no base counterpart): `eranio/drops.py`, `tests/test_eranio_drops.py`, `eranio/streak.py`, `eranio/streak_cache.py`, `tests/test_eranio_streaks.py`, `eranio/__init__.py`, `eranio/compat.py`, `eranio/git_config.py`, `eranio/run_config_migration.py`, `eranio/DOCKING.md`, `TwitchChannelPointsMiner/run_config_migration.py` (re-export shim), `tests/test_eranio_compat.py`, `tests/fixtures/eranio_egg_run.py`.

## 2. Behaviour of the compatibility class (`eranio/compat.py`)

- Subclass of the base miner; signature keeps the old positional order (`username, password, claim_drops_startup, enable_analytics, disable_ssl_cert_verification, disable_at_in_nickname, watch_only_drops, stop_watch_when_drops_completed, auto_discover_drops, priority, logger_settings, streamer_settings, watch_streak_max_parallel, watch_streak_min_offline_seconds, use_hermes`), all base-only options go through `**v3_options`.
- Passed through: everything the base has (`claim_drops_startup`, `enable_analytics`, SSL and nickname flags, `priority`, `logger_settings`, `streamer_settings`).
- Accepted and stored on the instance: `watch_only_drops`, `stop_watch_when_drops_completed` (also as `mine()` keywords, not used yet), `auto_discover_drops` (phase 3: switches the drop layer on, see section 7). Used in phase 2 via `streak.configure(...)`: `watch_streak_max_parallel`, `watch_streak_min_offline_seconds` (default 1800), `requested_priority`, the base `WatchStreakCache`, and a one-time migration of `logs/watch_streak_cache.<user>.json` (version 4) into `logs/.state/` (only when the new file does not exist yet; the old file stays untouched).
- `password` is accepted and dropped (never stored).
- `use_hermes` is accepted; one INFO line says the classic event connection (PubSub) is used.
- `priority` containing `STREAK_LENGTH_*`: replaced by `STREAK` (deduplicated) before it reaches the base; the original is kept in `requested_priority`.
- `update_check` defaults to `False` for old run.py files (the base check looks at a foreign release feed; updates come through the run.py self-update).
- `mine()`: accepts `None` for `streamers`/`blacklist`, and the old `watch_only_drops` / `stop_watch_when_drops_completed` keywords. The old 5th and 6th positional parameters are not supported positionally (base order wins there).
- `analytics()`: the base refuses a non-loopback host without password (`ValueError`), which would break every existing run.py with `host="0.0.0.0"`. The compat class builds the server with a loopback host for the check and sets the real host afterwards, with a WARNING. With a password, or on loopback, the base method runs unchanged. This replicates the base constructor call of `AnalyticsServer` (host, port, refresh, days_ago, username, password, log_poll_interval, logs_file); the guard tests must cover that signature. Decision for the owner: keep the old open behaviour or require a password.
- `dedupe_git_safe_directories()` (ported to `eranio/git_config.py`) is called at the start of the constructor.

## 3. Cookies

`cookies/<username>.pkl`: the base `TwitchLogin.load_cookies` reads the old pickle (list of `{"name","value"}`) with a restricted unpickler and rewrites the file as JSON. Verified by test. Consequence: after the first start on the new code the file is JSON; the old version cannot read it (rollback needs a new login or the backed-up cookie file).

## 4. Self update of run.py

The run.py template in the egg does `git fetch`, `git reset --hard origin/master`, deletes a fixed list of dev files (tests, setup.py, pyproject.toml, uv.lock, docs files, Dockerfile, ...) at each start and installs `requirements.txt` when `.setup_done` is missing. It also imports `TwitchChannelPointsMiner.run_config_migration` (now provided by the shim) and inserts missing literal-default keyword arguments into the constructor call. Notes: `docs/`, `tools/`, `supervisor/`, `config.example.py` of the base are not in the deletion list and will stay on disk; the base needs Python >= 3.11 (egg image is python_3.11).

## 5. Planned docking points (later phases, nothing implemented yet)

Phase 2, watch streak selection (implemented)
- `eranio/streak.py`: `is_pending` (delegated from `Twitch._has_pending_watch_streak`), `apply` (called once per watcher iteration with the snapshot list, the base selection and the memoized `_is_drop_stream`), `configure`, `STATE`. Source of truth is the GQL RewardList (state, value, achievementTimestamp, missedStreams) per channel, fetched through the base GQL client (`gql.post_gql_request_single`), at most once per 3 minutes per channel (immediate on first sight, then from 5 watched minutes, give up after 30 watched minutes). Logical streams: broadcasts with a gap below `watch_streak_min_offline_seconds` share one done state; synthetic ids (`login:ISO-time`) are merged into the real session.
- Phase 4 hook: `streak.loan_info()` (active, login, started_at, expires_at, `max_seconds` 900, `cooldown_until`) and `streak.wants_drop_slot(snapshot, unserved, now)`. The drop slot is only lent to one pending streak at a time for at most 15 minutes, then returns, followed by a 10 minute pause before the next loan; `apply` already enforces this for the base drop pick. A fixed drop slot of phase 4 must ask `loan_info()` and give the slot back at `expires_at`.
- `streak_cache.py`: reads the old cache format and converts it to base sessions.
- Cache: the base `WatchStreakCache` (`logs/.state/watch_streak_cache.<user>.json`) is extended through its public methods and its lock, no parallel cache; missed-stream warnings are remembered in `logs/.state/eranio_streak_missed.<user>.json`.
- Remaining original notes: `classes/Twitch.py` `Twitch.send_minute_watched_events` (the `for prior in priority` loop with `Priority.STREAK` / `Priority.DROPS`), `streak_priority` / `_may_share_drop_slot` stay base code and use `_has_pending_watch_streak`; `classes/entities/Streamer.py` `StreamerSettings` (`watch_streak`) unchanged.

Phase 3, drop campaign list (`drop_campaigns.json`) and fixed drop slot
- Campaign data: `Twitch.sync_campaigns` (about 11988) and `Twitch.__sync_campaigns` (about 10339), inventory `Twitch.get_drops_inventory` (3832), `Twitch.claim_all_drops_from_inventory` (11329), `Twitch.__get_campaigns_details` (10038), `Twitch.__get_drops_enabled_directory` (6077). The file layer reads campaigns after `__sync_campaigns` through one hook that passes the campaign list to `eranio.drops` and receives order/active flags back.
- Drop slot in the selection: same loop as phase 2 (`prior == Priority.DROPS`, about 6988) and `_may_share_drop_slot`; the fixed slot beside streak slots is an extra block after the loop.
- Miner: `mine()` options `watch_only_drops`, `stop_watch_when_drops_completed`, `auto_discover_drops` are already stored by the compat class; the discovery thread starts from `compat.mine()` before `super().mine()` (no base edit).

Phase 4, dashboard
- `classes/AnalyticsServer.py`: routes registered via `self.app.add_url_rule` (about lines 1006 to 1050), `before_request` authentication (~897), `check_assets` (780), `get_assets_folder` (227), data endpoints `/streamers`, `/json_all`, `/log`. Own routes are added by a function in `eranio/dashboard.py` that receives the Flask app; one call at the end of the `AnalyticsServer` constructor.
- Assets: `assets/charts.html`, `assets/script.js`, `assets/style.css`, `assets/dark-theme.css`, `assets/tail_buffer.js`. Preferred: own files under `assets/eranio/` and one include line in `charts.html`; the old dashboard design replaces the base page content in a later step.

Settings
- Global flags go through `Settings` (`classes/Settings.py`, `Settings.__slots__` is closed: new global values live on the miner instance or in `eranio/state.py`, not on `Settings`).
- `Priority` handling: see section 1.

## 6. Places where the base prints its own name, version or repository (to be handled in a later phase, unchanged now)

- `TwitchChannelPointsMiner.py` line ~699 to 700: startup log lines `Twitch Channel Points Miner - {__version__}` and `{GITHUB_REPOSITORY_URL}`.
- `TwitchChannelPointsMiner.py` `__check_for_update` (~1580 to 1610): update message with `{GITHUB_REPOSITORY_URL}/releases/latest` (inactive by default through the compat class, `update_check=False`).
- `constants.py` lines 46 and 47: `GITHUB_REPOSITORY_URL`, `GITHUB_LATEST_RELEASE_API`.
- `classes/AnalyticsServer.py` line ~561 to 564: `currentVersion=__version__`, `updateReleaseUrl` sent to the dashboard (update banner).
- `assets/charts.html`: `<title>` (line 7), about block with repository links and badges (lines ~122 to 176), credit line (~459).
- `assets/windows_shell.html` line ~634: version text (Windows shell, not used here).
- `utils/Utils.py` `check_versions` (~377): User-Agent `Twitch-Channel-Points-Miner/{version}` and request to the release API (network only).
- `classes/DropBadgeCatalog.py` (~21) and `classes/TwitchDropsApp.py` (~19, ~28): gist URLs and a comment naming the upstream scraper (network/source only).
- `__init__.py`: `__version__` value is shown in the log and dashboard; the target version string is set in phase 6.4.
- License files and headers stay unchanged.

## 7. Drop campaign list (phase 3, `eranio/drops.py`)

Principle: no own discovery, no own requests. Every campaign field comes from v3 objects: the `Campaign`/`Drop` objects built by `Twitch.sync_campaigns` (dashboard, inventory, channel campaigns, reward campaigns/quests, badge campaigns), `Twitch.unlinked_drop_report()` (account link state), `Twitch.drop_watch_health` (v3 stall detection, shown as "pausiert"), the streamers' `stream.campaigns` / `campaigns_ids` (live channels) and v3's category/wildcard discovery. If v3 changes how campaigns are found, the layer keeps working as long as these objects keep their shape. v3's own `drops_by_category.json` (analytics) is written from raw snapshots and has no campaign order or state, so it is not reused as source; the same drop fields are mapped from the live objects.

Activation: only when the miner was built with `auto_discover_drops=True` (`compat.mine`): the miner then (a) creates one shared `categories` list that the layer extends in place (games with slug under `spiele`, plus games of the top 5 ranked campaigns), (b) sets `wildcard_categories=True` and `drop_pick_stickiness_minutes=0` (stickiness would fight the list order), unless the caller passed them. `category_refresh_interval_hours` is the configured value (base default 6); the earlier cap at 0.25 is gone (3.0.8): every refresh adds and removes hundreds of category channels. With `auto_discover_drops=False` nothing is changed and the layer is off (plain base behaviour).

Chat of discovered channels (3.0.8, `compat.without_discovered_chat`, always active): `category_chat=None` becomes `ChatPresence.NEVER`, keyword or positional. The base gives every chat its own IRC connection; with drop discovery that were 350 to 400 connections per account, Twitch then refused further chats for the account (also in the app) and the container ran out of threads (`can't start new thread`, segment polls failed). An explicit `category_chat` value is kept.

Streams watched (3.0.8, base file `TwitchChannelPointsMiner.py`, `_normalize_streams_watched`): accepts 1, 2 or 3 (base: 1 or 2), settings page choice (1, 2, 3). For testing whether Twitch credits a third channel.

First config (3.0.9, `config_file.default_config_text`): built from `eranio/templates/config.py` (the owner's settings: chat never, category chat never, 2 streams plus the drop slot, watch streak parallel 2, category refresh 2 hours, Android login, followers) instead of the base `config.example.py`; `STREAMERS` holds only `eranio`. `__USERNAME__` and `__PORT__` become the fallback values behind `TWITCH_USER` / `SERVER_PORT`. A config converted from an old run.py gets `Streamer("eranio")` appended when it is missing (`ensure_always_watched`).

Egg install script (3.0.8): an existing `run.py` that is not the thin launcher is copied to `run.py.v2-sicherung` (dated name if that exists) before the thin template replaces it, so a reinstall over an old installation converts its settings instead of starting with an empty default config.

Cycle: `publish` runs once a minute from the sync loop. It re-reads the file when its mtime changed (order and aktiv apply immediately), rewrites it at most every 15 minutes or after a change, and logs the German status overview every 15 minutes.

Selection (docking in `send_minute_watched_events`): `allows_watch` removes drop-discovered streamers whose campaigns are all switched off, not earnable (sub only, zero minutes, missing precondition) or not linked; explicit and followed streamers are never removed. `pick_key` / `drop_rank` sort by list position first, then by the base key. `reserve` runs before `eranio_streak.apply`: the best ranked drop stream always gets a slot, worse drop streams give way. The streak extension then lends this slot to at most one pending streak for 15 minutes (`streak.loan_info()`, `LOAN_MAX_SECONDS`) and returns it afterwards, even when the streak is unconfirmed (tests simulate it).

Data kept per campaign entry for the dashboard phase (all from v3 objects, `drop_campaigns.json`): `spiel`, `spiel_bild` (game box art URL), `kampagne`, `art` (`Quest` for reward campaigns, else `Drop-Kampagne`), `status`, `endet`, `ende_utc`, `offen`, `naechster_drop`, `naechster_start` (daily/next start), `abo_noetig`, `konto_verbunden`, `drops[]` with `name`, `belohnung`, `bild` (item art URL), `minuten_noetig`, `minuten_aktuell`, `abo_noetig`, `abgeholt`; top level `jetzt` has the currently watched channel (`kanal`, `spiel`, `kampagne`).

Gaps in v3 (not filled with old code):
- v3 `Campaign` objects have no `isAccountConnected`; the link state is only known for campaigns v3 reported as unlinked (`unlinked_drop_report`): `nein` there, `ja` when v3 says linked, otherwise `unbekannt`.
- `Campaign.clear_drops()` removes claimed and not yet started drops before the sync pass. The layer therefore remembers the uncleared campaign in `remember()` (total drops, next start). A campaign that vanishes while its end is in the future is never "alles abgeholt": it shows "heute erledigt, wird täglich neu geprüft" (or "nächster Drop ab ..."), stays listed and is re-checked every 15 minutes and at every day change, so a reset or re-added daily drop (same or new id) turns it back to "läuft" and eligible for the pick. "alles abgeholt" only after the campaign end.
- v3 asks only channels tagged with drops or listed in a campaign allow-list; the old "ask every live followed channel directly" part is not reproduced.
- v3 does not store a per-campaign "no progress" state; "pausiert" is taken from `drop_watch_health` per game, not per campaign.

## 8. Dashboard (phase 4, `eranio/dashboard.py`, `eranio/streak_history.py`, `assets/eranio/`)

Base lines touched:

| File | Change |
|---|---|
| `classes/AnalyticsServer.py` | end of `__init__`: import of `eranio.dashboard` and `dashboard.install(self.app, self)` (4 lines). Everything else of the base server (auth code, endpoints, cache, log tail) stays unchanged. |
| `classes/entities/Streamer.py` | new method `persistent_streak_days(days)` after `persistent_series` (writes the key `streak` into the analytics JSON, same shape as the old version: `{"x": ms, "y": days}`). |
| `TwitchChannelPointsMiner.py` | startup log: the repository URL line removed (name and our own version stay); `__check_for_update`: the container/release-page instruction text replaced by one neutral sentence ("Restart the miner to install the update."). |
| `constants.py` | `GITHUB_REPOSITORY_URL` / `GITHUB_LATEST_RELEASE_API` point to our own repository (Erani0/Twitch-Channel-Points-Miner-v2). |
| `__init__.py` | `__version__` is our own number (3.0.0), not the base number. A merge of the base release will conflict on this one line: keep ours. |
| `eranio/streak.py` | `run_check` records the RewardList value through `streak_history.record` (3 lines). |
| `eranio/compat.py` | `analytics()` always builds the open dashboard (the old `password` argument is accepted and ignored), `mine()` starts `streak_history.start(self)`. |
| `.gitignore` | `!assets/eranio/*.js` (the base ignores `*.js`). |

`dashboard.install` replaces view functions after the base registered them (`app.view_functions[...]`), so the base routes keep their names:
- `index` renders `assets/eranio/index.html` (our old page plus Drops view, "Now watching" box, log pause button, delete dialog, update banner).
- `static` serves only `assets/eranio/` (css, js, png, ico, svg, jpg, gif). The base pages and scripts in `assets/` (`charts.html`, `script.js`, `style.css`, `windows_shell.html`, ...) are no longer reachable and carry the base branding; they stay in the repository unchanged.
- `streamers` adds `watch_streak_days` (last value of the `streak` series).
- `web_config` and `test_web_notification` answer 404; a `before_request` guard (inserted first) answers 404 for everything under `/config` and keeps the loopback Host check with a neutral message. The base cross-site check (Origin / Sec-Fetch-Site on POST/DELETE) and the path checks of `/json/<name>` and `DELETE /streamers/<name>` (only names from `streamers_available()`) stay active.
- New routes: `/drops` (campaigns from `drop_campaigns.json` with whitelisted fields, current channel, history from `drops_by_category.json` split into claimed and expired), `/watching` (`now_watching.json` plus streak and drop slot loan state, reasons Drop, Badge, Streak, Points), `/update_info` (reads `__version__` from the master `__init__.py` of our repository, cached 6 hours, 30 minutes after a failure, compared with our own version).
- Images: server side `safe_image` keeps only https URLs on `jtvnw.net`, `twitchcdn.net`, `twitch.tv`, `ttvnw.net`; the page checks again and falls back to a Font Awesome icon (set already loaded by the old page, no new CDN). All texts are inserted with `textContent`.

Streak history (old display kept): `streak_history.record` writes the days into the per-streamer analytics JSON at most when the value changed or every 6 hours; sources are the RewardList value of `streak.py` (`Track.value`) and the days migrated from the old cache file (`STATE.known_length`). A thread (`Streak history`, started in `compat.mine`) syncs all streamers every 15 minutes. Old analytics files stay readable, existing `streak` entries are appended to. Not ported: the old Excel export of streamers (column "Watchstreaks"): the base has no such export (`streamers_export_path` does not exist there).

Section 6 status: startup repository line removed, update text neutral, release URL no longer passed to a page (our page does not use it), dashboard title/about/badges/credit line live only in the unserved base `assets/charts.html`. Still present as invisible text: gist URLs in `DropBadgeCatalog.py` / `TwitchDropsApp.py`, User-Agent string in `utils/Utils.py: check_versions` (network only, `update_check` is off by default), license files and headers.

`eranio/V3_BASE` (content `<base version> <commit>`) is read only by tooling and never shown or served.

## 9. External access and web server

- The egg run.py calls `analytics(host="0.0.0.0", port=SERVER_PORT, ...)`. `compat.analytics` builds the server with the temporary host 127.0.0.1 and sets `host = "0.0.0.0"` right afterwards; every host check of the base (`require_authentication`) and of our guard reads `self.host` at request time, so nothing computed at construction blocks. Tests (`tests/test_eranio_compat.py`) request the page, all assets and all endpoints with the Host headers `185.228.178.24:5000`, `n02.eranio.de:5000`, `n02.eranio.de` and a private address, with same-origin browser headers (Origin, Referer, Sec-Fetch-Site), including POST and DELETE: all answer 200 or 204. One test starts `AnalyticsServer.run()` for real and checks that waitress listens on `0.0.0.0` and that the dashboard answers on 127.0.0.1 and on the machine's own address.
- The base server runs on waitress only (`from waitress.server import create_server` inside `run()`); there is no werkzeug fallback. Without waitress the dashboard thread dies with an ImportError and mining continues without a dashboard. `waitress==3.0.2` is in `requirements.txt` and `setup.py`; the egg install step runs `pip install -r requirements.txt`, so it is installed there.

## 10. Streamers export (`eranio/export.py`)

Ported from the old version, same columns (Streamer, Points, Followdate, Last Stream, Sub, Banned, Watchstreaks, Points gained), same style (header colours, table, data bar, widths), same file name `logs/report_<YYYY-MM-DD>_<account>.xlsx` (rolls over at midnight, old file stays), same trigger: first export once the miner runs and streamers are loaded, then every 10 minutes (thread "Streamers export", started in `compat.mine`), and a last export when the miner stops (`finally` in `compat.mine`, covers the signal handler). The daily "Points gained" baseline file `logs/daily_points_baseline.<account>.json` keeps its old format. Dependency: `openpyxl==3.1.5` added to `requirements.txt` and `setup.py`; pandas is not needed (the sheet is written with openpyxl directly, result identical).

Data sources on the new base (the old helpers do not exist there):
- Watchstreaks: `streak_history.current_days` (RewardList value, then the days migrated from the old cache), one RewardList request per streamer if neither is known; each export also records the value into the analytics file.
- Followdate: ChannelFollows pages read once at the first export (`followed_at` of the base parser).
- Banned: the base `ChannelBanStatus` query (`gql.channel_ban_statuses`, cache `twitch.channel_bans`), asked once per streamer when the cache has no entry.
- Last Stream: stream start of the streak track or the newest session of the base watch streak cache (the base `Stream` has no `created_at`).
- Sub: "yes" when the account has an active points multiplier for the channel (the old tier lookup is not in the base query; same result for subscribers).

## 11. Settings page, config/config.py, launcher, Android login (phase 4b)

Base files touched: none. Everything is in `eranio/` plus `assets/eranio/` (`settings.html`, `settings.js`, `settings.css`, one added toolbar link in `index.html`). `eranio/dashboard.py` passes `settings_enabled` to the page template (1 line). `eranio/export.py` now uses the base ChannelBanStatus query (`gql.channel_ban_statuses`, cache `twitch.channel_bans`).

### Launcher (`eranio/launcher.py`)
`run(port, config_password, host=None, config_dir=None, legacy_run_py=None)` is the only call of the future thin run.py. It sets the environment variables `ERANIO_DASHBOARD_PORT`, `ERANIO_DASHBOARD_HOST`, `ERANIO_CONFIG_PASSWORD` and then calls the base `runner.main(["--config-dir", <dir>, "--legacy-runner", <old run.py>])` unchanged (conversion for existing config.py is skipped by the base, migration `_load_config`, hot reload watcher `_watch_config`, `restart_process`, `run_config` are all base code). Defaults: config dir `<dir of the started run.py>/config`, old run.py `<dir>/run.py.old` when it exists.
- Deviation 1 (no base change): when `config/config.py` is missing and an old run.py exists, the launcher converts first with `eranio/config_file.convert`, because the base `convert_runner` refuses run.py files that use module-level variables (`TWITCH_USER`, `SERVER_PORT` in the egg run.py) and it renames the old run.py. `convert` inlines those variables, drops `config_password`, calls the base `convert_runner` on a temporary copy (so the real run.py is never renamed or touched), then moves our options into `ERANIO_CONFIG` and makes sure `MINE_CONFIG['categories']` exists (the base editor needs it).
- Deviation 2: if that conversion fails, the launcher falls back to the old run.py itself (`run_legacy`, German text without Docker wording, `execve` of `python -u <old run.py>`, env `ERANIO_LEGACY_RUN=1`). The base `_run_legacy` is never reached because the config directory always exists and config.py exists when `main` is called. A broken existing config.py is not replaced: the base raises RuntimeError and the launcher prints it as `FEHLER: ...` (exit code 1).
- Dashboard values: `compat.analytics()` calls `config_file.dashboard_overrides`, so host, port and `config_password` of run.py win over `ANALYTICS_CONFIG`. A config with `ANALYTICS_CONFIG = None` has no dashboard at all (the base never calls `analytics()`).
- Pelican: the egg restart is done by the panel; the base `restart_process` (execv) is what the base uses for restarts requested by the miner. There is no restart button on the settings page; restart-only changes say so.

### ERANIO_CONFIG (own block in config/config.py)
Top-level dict after the base blocks. Allowed keys (`config_file.ERANIO_KEYS`): `auto_discover_drops`, `watch_streak_max_parallel`, `watch_streak_min_offline_seconds`, `priority` (names like `Priority.STREAK_LENGTH_ASCENDING`), `watch_only_drops`, `stop_watch_when_drops_completed`, `use_hermes`. Missing block or key = constructor value. Read without executing the file (`config_file.read_eranio_block`, AST), applied in `compat.__init__` when `Settings.config_path` (set by the base `run_config`) or the launcher config dir is known; they win over the constructor arguments. They apply after a restart only. Unknown keys are ignored with a warning.

### Update guard (must be re-checked on every base update)
`tests/test_eranio_settings.py` runs the base `migrate_config` from every `CONFIG_VERSION` (none, 1 to 11) over a config containing `ERANIO_CONFIG` and a comment, `runner._load_config`, `migrate_web_config` with a `web-config.json`, and 13 base editor actions (streamer add, edit, reorder, remove, categories, category, sources, logging, updates, login, notifier on/off) and asserts the block source stays byte-identical. Findings with the current base: the block survives all of them. Known behaviour: the base migration adds a default `priority` to `MINER_CONFIG`; `ERANIO_CONFIG['priority']` still wins because the compat miner applies it last. If a base step ever drops the block, re-append it after migration inside `config_file`/`launcher` and extend these tests. The base editor requires `STREAMERS` and `MINE_CONFIG['categories']` to be literal lists.

### Settings page (`eranio/settings_page.py`, `eranio/settings_model.py`)
- Exists only when run.py passes `config_password` (`analytics(config_password="...")` or the launcher): otherwise every `/settings*` route is 404 and the dashboard shows no link. The dashboard itself stays open. Password: sha256 plus `hmac.compare_digest`; 5 failures lock the client IP for 10 minutes; session cookie `miner_settings` (HttpOnly, SameSite=Strict, random token, 12 hours idle); logout; nothing is logged or sent back.
- Saves go to `config/config.py` through the base editor (`update_managed_web_config`, all base actions unchanged) plus own in-place edits (`update_eranio`, `update_miner`, `update_logger`, `update_defaults`, `update_bet`, `update_mine`, `update_streamer_extra`) built on the base helpers (`_set_dict_items`, `_insert_item_bytes`, atomic `_replace_config_bytes`, compile check). Before every save `config.py.eranio.bak` is written (one rolling copy); the base migration keeps its own `.v<N>.bak` files. These base helpers have leading underscores: re-check their signatures on every base update.
- Live without restart (base watcher): streamers added or removed, categories, wildcard options. Everything else after the next restart; the page labels every section.
- Not offered on the page (base only or unsafe): update check, SSL verification switch, colour palette, bet filter conditions, streamer source order, dashboard host/port/password.

### Android login (`eranio/android.py`)
Offer only, never blocking: `compat.mine` calls `android.offer()`, which logs the instruction once (base `ANDROID_LOGIN_URL`) when `cookies/<user>-android.pkl` is missing and starts (a) a daemon reader on stdin (raw `os.read`, survives closed or missing stdin) and (b) a one-time read of `TWITCH_ANDROID_LOGIN`. The settings page has a field as well. Validation and storage are the base `TwitchLogin` (`__accept_android_token` checks client id and account, `save_cookies` writes the JSON cookie file). The base switches the whole client with the `android_login` constructor option, which cannot change at runtime, so a stored login becomes active after a restart once "Android-Login nutzen" (base action `update_login`) is on. The token is never logged or returned.

## 12. Thin run.py, switch of existing installations, egg, update tooling (phase 4b.6 to 5)

Base files touched: none.

### Thin run.py (`eranio/templates/run.py`, single source of truth)
Same for everyone. It keeps the old self-updater unchanged in behaviour (git fetch, compare with `origin/master`, `git reset --hard origin/master`, delete list of development files, `pip install -r requirements.txt` when `.setup_done` is missing, restart through `os.execv`), changes into its own folder first, reads `--port` (fallback `SERVER_PORT`, default 5000) and the optional `CONFIG_PASSWORD` environment variable, then calls `eranio.launcher.run(port=..., config_password=..., host="0.0.0.0")`. A crash restarts the process after 15 seconds, as before. `upgrade.thin_source(password)` renders it (the only variable part is the default of `CONFIG_PASSWORD`, used when the old run.py had a `config_password`). The egg install script copies this file (no second copy).

### Switch of an existing installation (`eranio/upgrade.py`)
Entry point kept: the old run.py calls `TwitchChannelPointsMiner.run_config_migration.ensure_constructor_kwargs(file_path, class_name, expected_kwargs)` (shim for `eranio/run_config_migration.py`) after its updater has reset the code to the new master. The function first calls `upgrade.switch_if_needed(file_path)`:
- only when the file is named `run.py`, is the started script (`sys.argv[0]`), and `ERANIO_LEGACY_RUN` is not set;
- only for a big old run.py (contains a `TwitchChannelPointsMiner(` call, not the thin marker);
- no `config/config.py` yet: `config_file.convert` writes it (all settings, `ERANIO_CONFIG`, the egg username stays `os.environ.get("TWITCH_USER")`), verified through `runner._load_config`; an existing `config.py` is never touched or converted again;
- backup `run.py.v2-sicherung` (existing backup is kept, a timestamp is added to the new one), thin run.py written atomically (`run.py.neu`, then `os.replace`), then `os.execv` of the thin run.py with the same arguments;
- any failure: a created `config.py` is removed again, run.py stays untouched, one German warning, the old run.py continues through the compatible class (its old behaviour of adding constructor keywords stays).
Second run: the thin file is detected, nothing happens.

### Launcher additions
Legacy file candidates: `run.py.v2-sicherung`, then `run.py.old`. Without `config.py` and without a legacy file the launcher creates `config/config.py` from `config.example.py` (`config_file.create_default`: username from `TWITCH_USER`, dashboard on 0.0.0.0 with the given port, analytics on, update check off, time zone Europe/Berlin, `ERANIO_CONFIG`) and continues; without `TWITCH_USER` it stops with a German message. The replacements are plain text replacements of the base template: the guard test `test_base_template_still_produces_a_usable_default_config` fails when a base update changes one of those lines.

### Egg (`egg-twitch-channel-points-miner/`)
Same uuid, image, startup command and `update_url`. All old variables stay (`TWITCH_PASS` is now optional and unused), new optional ones with empty default: `CONFIG_PASSWORD`, `TWITCH_ANDROID_LOGIN`. The install script no longer writes settings: it clones, copies, removes development files as before, copies the thin run.py (atomically) and creates `config/`; it never touches `config/`, cookies, logs, analytics or `drop_campaigns.json`.

### Update tooling
`tools/update_from_v3.py` (wrappers `.sh`, `.ps1`): fetch of the remote named `v3`, merge into `update/v3-<version>` without pushing, conflicts only tolerated in the `__version__` line (own number wins, other lines of both sides are merged), `eranio/V3_BASE` updated, tests, German summary. `.github/workflows/v3-update-check.yml` runs it daily when the repository variable `V3_REPO_URL` is set and opens a pull request with the change list and the test result; it never merges. Guard tests for all docking points: `tests/test_eranio_docking.py`; rehearsal of the whole upgrade path: `tests/test_eranio_upgrade.py`; tool tests: `tests/test_eranio_update_tool.py`.

| classes/gql/Integration.py | channel_follows: fall back to the last edge cursor when Twitch omits pageInfo.endCursor (otherwise only the first 100 follows load) |

## 3.0.16: Skip channels without channel points

- The online filter in `Twitch.send_minute_watched_events` also requires `eranio.points.has_points(streamer)` unless the stream qualifies for Drops (`__drops_condition`). Channels whose `communityPointsSettings.isEnabled` is false (no Affiliate/Partner, or points switched off) never earn points or streaks, so they no longer take a points or streak slot.
- `eranio.points` asks Twitch in the background (one GQL request with one alias per channel, up to 15 per request, the Twitch limit for aliases), caches the answer for 24 hours in analytics/<account>/points_check_eranio.json (survives restarts), retries a failed check after 10 minutes and treats unknown channels as allowed. Each channel without points is logged once.
- Found on 20.11.2026: sintica, vanaessa, myersprincessttv and takotaretriver98 held two of three slots for hours without a single point. An earlier change that polled stream segments for every channel (3.0.15) was based on that wrong reading and was reverted.
- Tests: `tests/conftest.py` resets the cache and disables the background worker, so no test sends a request.

## 3.0.19: Campaigns Twitch already completed

- `Twitch.sync_campaigns` keeps the inventory that `claim_all_drops_from_inventory` just read (`_drop_inventory_state.inventory`) and calls `eranio.awards.mark_awarded(campaign, inventory, shared_ids)` for every new `Campaign` before `eranio_drops.remember` and `clear_drops`.
- A drop counts as done when its campaign is no longer in `dropCampaignsInProgress` and every benefit ID of the drop appears in `gameEventDrops` with `lastAwardedAt` inside the drop's window. Benefit IDs used by more than one drop among the loaded campaigns are never trusted. Names are not compared.
- Found on 21.11.2026: Black Desert "Master Class 26 (Nov 20)" was finished (2 Hour Reward awarded 00:53 UTC), but Twitch drops a finished campaign from the inventory and sends `self: null` in its details, so the campaign looked new with 0 minutes and was watched for eight hours without progress. The base check `__drop_benefits_were_awarded` was skipped because the reward name "2 Hour Reward" also belongs to older Black Desert campaigns.
- Drop history (`drop_history_eranio.json`): rows without `drop_id` no longer use the time in their key, so a restart does not add the same drop again; existing duplicates are merged on the next read, keeping the earliest time.
- "hat keine Kanalpunkte" is now a debug line (more than 800 lines a night, mostly drop channels).

## 3.0.20: Quests (channel-bound and category-bound)

- New `eranio/quests.py`. Every 10 minutes (called from `drops._publish`) it reads `ViewerRewardDropInventory` and, once per 6 hours per campaign, a hand-written `dropsCampaign` query with the channels (`id login`) and categories of each reward group. Base v3 drops every reward group limited to channels (`_watch_group_categories` returns nothing for them), so creator quests such as "LACY GTA 6 MARATHON BADGE" were listed with 0 minutes and never watched.
- `drops._build_views` ends with `quests.patch_views(views)`: a channel quest gets its drops, progress, channel ids and logins from Twitch's quest data; a category quest keeps its v3 drops and gets `quest_slugs` (all categories Twitch counts it in). Twitch files some category quests under "Special Events" (Pokemon Evolutions counts in DJs, Just Chatting, Music and 18 more).
- `drops.matched_ids` matches a channel quest by channel id whatever the stream's game, and a category quest by any of its categories. `_sync_categories` adds up to three categories per top campaign, Just Chatting, DJs, Music and Special Events first.
- Base edit in `Twitch.send_minute_watched_events`: `_is_drop_stream` also returns `eranio_drops.quest_stream(...)`, true for a live channel of a ranked channel quest with minutes left. That makes the base pick it for the single drop slot and poll its HLS segments; without segments Twitch counts nothing (checked live on 21.11. with zarbex as a points stream: 0 minutes in 10).
- Channels of quests are added to the running miner through the base `add_streamers` (once, in a background thread). Claimable quest groups are claimed with `claim_drop_rewards("<user>#<campaign>#<group>")`, at most once per hour each.
- `DropFile.rank` no longer skips campaigns whose game account is not linked (owner's decision: collect anyway, linking later delivers them).
- File and dashboard: `abo_hinweis` ("Sub nötig" or "N Subs nötig, auch verschenkt") as a campaign badge, per drop `abos`, and the quest channel under the details.

## 3.0.23: The drop slot is not given away for streaks

- `streak.apply`: a watched drop stream stays a drop holder even when its own watch streak is pending (the streak counts while it is watched). Before, such a stream was taken out of the drop holders and dropped whenever the two streak slots were already full, which threw quest channels such as lacy out of the drop slot right after they were picked.
- Lending the drop slot to a pending streak (15 minutes, then 10 minutes pause) is now opt-in (`streak.configure(lend_drop_slot=True)`), off by default: open drops keep their slot until nothing is left to watch for (owner's decision 21.11.).

## 3.0.24: Work order, drop list editor, self-check

- Work order (`DropFile.arrange`, used by `ordered`, `rank` and `write`): games keep the order of their first campaign in `drop_campaigns.json`; inside a game, with `einstellungen.innerhalb_spiel_automatisch` (default true), daily drops come first (repeating quest groups, or a campaign running 26 hours or less), then the shortest remaining watch time, then the manual order. Without it the manual campaign order counts exactly.
- `einstellungen.creator_quests` (default true): channel-bound quests are collected; false keeps them in the list with status "Creator-Quest ausgeschaltet" and no drop slot or added channel.
- Quests without a game (creator quests) join a known game when the campaign name contains its name or its three-letter acronym (GTA for Grand Theft Auto VI), see `drops.guess_game`.
- Settings page: tab "Drop-Reihenfolge" (`/settings/api/drops`, GET and POST, login required). Games and campaigns are moved by dragging the grip (pointer events, works with mouse and touch) or with arrows, each with an on/off switch, plus both switches above. Saving writes `drop_campaigns.json` under the drop layer's lock and reloads its settings, so it applies at the next sync without a restart.
- New `eranio/selfcheck.py`, run from `drops._publish`: the inventory is read every 30 minutes. A drop pick with status "läuft" whose Twitch minutes do not move for 60 minutes is paused for 2 hours (status "pausiert (Selbstkontrolle ...)", left out of the ranking). A top campaign without a live channel for 2 hours while channels of its categories are online, and anything Twitch awarded that is not in the miner's list, are reported. Reports go to the log (WARNING) and to `hinweise_selbstkontrolle` in the file, which the Drops tab and the editor show.
- The current drop pick (`jetzt`) now comes from the actual drop slot first and is written as soon as it changes; the Drops tab frames it and names the channel.

## 3.0.25: Category quests on matching streams, game names from the file

- `drops.quest_stream` is also true for a live stream whose category belongs to a ranked category quest (`STATE.quest_category_slugs`, e.g. Pokemon Evolutions in DJs or Just Chatting), so a followed DJ channel can take the drop slot and get its segments polled. The ranking still decides which campaign wins.
- `guess_game` also knows the games listed under `spiele` in the file, so creator quests join "Grand Theft Auto VI" even when no regular GTA campaign is live at the moment.

## 3.0.26: One drop stream

- `drops.reserve` keeps exactly one drop stream (the best ranked); further drop streams are left out instead of sharing the slot. Twitch counts drop and quest minutes on one channel only, so several DJ channels for the same Pokemon quest only took points slots away.

## 3.0.27: Live status of category quests

- `_live_ids` also counts a live stream in one of a category quest's categories, so Pokemon Evolutions shows "läuft" while a DJ channel collects it.

## 3.0.28: Linked accounts only, followed channels only

- Options in `drop_campaigns.json` under `einstellungen` (and on the settings page, tab Drop-Reihenfolge): `nur_verbundene_konten`, `nur_gefolgte_kanaele`, `immer_sammeln` (list of games or campaign names, matched by slug, exempt from both). All default off, so nothing changes unless switched on.
- Linked only: `drops.fetch_links` asks `currentUser.dropCampaigns { id self { isAccountConnected } }` every 30 minutes over the miner's own GQL session (works with the Android login; the TV login returns an empty list). Campaigns without a linked account (and campaigns missing from that list, such as quests) are left out of the ranking with status "aus: Spielkonto nicht verbunden". If Twitch gives no answer the filter stays off.
- Followed only: `_sync_categories` only searches categories of `immer_sammeln` games, quest channels and quest categories only come from those, and `compat.mine` forces `wildcard_categories=False` at start. Set `wildcard_categories` to False in config.py too, because a config reload would read it again.
- Both hand-written GQL queries (`EranioQuestDetails`, `EranioDropLinks`) are now literal in the payload so `test_gql_named_operations` can read them.
