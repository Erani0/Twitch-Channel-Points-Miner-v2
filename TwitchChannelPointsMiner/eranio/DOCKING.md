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

Activation: only when the miner was built with `auto_discover_drops=True` (`compat.mine`): the miner then (a) creates one shared `categories` list that the layer extends in place (games with slug under `spiele`, plus games of the top 5 ranked campaigns), (b) sets `wildcard_categories=True`, `drop_pick_stickiness_minutes=0` (stickiness would fight the list order) and caps `category_refresh_interval_hours` at 0.25, unless the caller passed them. With `auto_discover_drops=False` nothing is changed and the layer is off (plain base behaviour).

Cycle: `publish` runs once a minute from the sync loop. It re-reads the file when its mtime changed (order and aktiv apply immediately), rewrites it at most every 15 minutes or after a change, and logs the German status overview every 15 minutes.

Selection (docking in `send_minute_watched_events`): `allows_watch` removes drop-discovered streamers whose campaigns are all switched off, not earnable (sub only, zero minutes, missing precondition) or not linked; explicit and followed streamers are never removed. `pick_key` / `drop_rank` sort by list position first, then by the base key. `reserve` runs before `eranio_streak.apply`: the best ranked drop stream always gets a slot, worse drop streams give way. The streak extension then lends this slot to at most one pending streak for 15 minutes (`streak.loan_info()`, `LOAN_MAX_SECONDS`) and returns it afterwards, even when the streak is unconfirmed (tests simulate it).

Data kept per campaign entry for the dashboard phase (all from v3 objects, `drop_campaigns.json`): `spiel`, `spiel_bild` (game box art URL), `kampagne`, `art` (`Quest` for reward campaigns, else `Drop-Kampagne`), `status`, `endet`, `ende_utc`, `offen`, `naechster_drop`, `naechster_start` (daily/next start), `abo_noetig`, `konto_verbunden`, `drops[]` with `name`, `belohnung`, `bild` (item art URL), `minuten_noetig`, `minuten_aktuell`, `abo_noetig`, `abgeholt`; top level `jetzt` has the currently watched channel (`kanal`, `spiel`, `kampagne`).

Gaps in v3 (not filled with old code):
- v3 `Campaign` objects have no `isAccountConnected`; the link state is only known for campaigns v3 reported as unlinked (`unlinked_drop_report`): `nein` there, `ja` when v3 says linked, otherwise `unbekannt`.
- `Campaign.clear_drops()` removes claimed and not yet started drops before the sync pass. The layer therefore remembers the uncleared campaign in `remember()` (total drops, next start). A campaign that vanishes without a future drop is shown as "alles abgeholt"; a repeating daily drop that reuses the same drop id cannot be told from a finished campaign.
- v3 asks only channels tagged with drops or listed in a campaign allow-list; the old "ask every live followed channel directly" part is not reproduced.
- v3 does not store a per-campaign "no progress" state; "pausiert" is taken from `drop_watch_health` per game, not per campaign.
