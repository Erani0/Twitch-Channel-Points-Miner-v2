# Docking points

All own code lives in `TwitchChannelPointsMiner/eranio/` (plus the new top-level shim `TwitchChannelPointsMiner/run_config_migration.py`, which does not exist in the base). Edits in base files are kept to a few lines so that a merge of the base branch produces few or no conflicts. Base: release 3.22.0 (795629a).

## 1. Base files touched (phase 0/1)

| File | Change | Why |
|---|---|---|
| `TwitchChannelPointsMiner/__init__.py` | one added line after the existing import: `from .eranio import TwitchChannelPointsMiner` | `from TwitchChannelPointsMiner import TwitchChannelPointsMiner` in existing run.py files returns the compatible class. The base import line and the `__version__` line stay untouched. |
| `TwitchChannelPointsMiner/classes/Settings.py` | `Priority`: two members `STREAK_LENGTH_ASCENDING`, `STREAK_LENGTH_DESCENDING` after `POINTS_DESCENDING`; `Events`: member `SUBSCRIPTION` after `CHAT_MENTION` | Old run.py files and notifier lists reference these names. Enum members cannot be added from outside cleanly. Until phase 2, both STREAK_LENGTH values are mapped to `Priority.STREAK` by `eranio/compat.py` (`normalize_priority`), so the base selection never sees them. `Events.SUBSCRIPTION` exists only so that old configs resolve; the base does not emit it. |

New files (no base counterpart): `eranio/__init__.py`, `eranio/compat.py`, `eranio/git_config.py`, `eranio/run_config_migration.py`, `eranio/DOCKING.md`, `TwitchChannelPointsMiner/run_config_migration.py` (re-export shim), `tests/test_eranio_compat.py`, `tests/fixtures/eranio_egg_run.py`.

## 2. Behaviour of the compatibility class (`eranio/compat.py`)

- Subclass of the base miner; signature keeps the old positional order (`username, password, claim_drops_startup, enable_analytics, disable_ssl_cert_verification, disable_at_in_nickname, watch_only_drops, stop_watch_when_drops_completed, auto_discover_drops, priority, logger_settings, streamer_settings, watch_streak_max_parallel, watch_streak_min_offline_seconds, use_hermes`), all base-only options go through `**v3_options`.
- Passed through: everything the base has (`claim_drops_startup`, `enable_analytics`, SSL and nickname flags, `priority`, `logger_settings`, `streamer_settings`).
- Accepted and stored on the instance, not yet used: `watch_only_drops`, `stop_watch_when_drops_completed` (also as `mine()` keywords), `auto_discover_drops`, `watch_streak_max_parallel`, `watch_streak_min_offline_seconds` (default 1800). Used by later phases.
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

Phase 2, watch streak selection
- `classes/Twitch.py`, `Twitch.send_minute_watched_events` (about line 6606; the `for prior in priority` loop around line 6940 with branches `Priority.STREAK` ~6979, `Priority.DROPS` ~6988) and `Twitch._has_pending_watch_streak` (about 6414); `streak_priority` / `_may_share_drop_slot` around 7337 for the shared drop slot.
- Hook idea: one call in the `Priority.STREAK` branch to `eranio.streak.select(...)` which returns the ordered indexes (STREAK_LENGTH ascending/descending, `watch_streak_max_parallel`, rotation, `watch_streak_min_offline_seconds`). Cache: `TwitchChannelPointsMiner/WatchStreakCache.py` (base class, created in `TwitchChannelPointsMiner.__init__` line ~629, path `logs/.state/watch_streak_cache.<user>.json`); our old path was `logs/watch_streak_cache.<user>.json`, so the eranio layer must read the old path as a fallback.
- `classes/entities/Streamer.py` `StreamerSettings` (`watch_streak`) stays unchanged.

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
