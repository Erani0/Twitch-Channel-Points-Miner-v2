import copy
import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import DataBarRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from TwitchChannelPointsMiner.classes.Settings import FollowersOrder, Settings
from TwitchChannelPointsMiner.constants import GQLOperations
from TwitchChannelPointsMiner.eranio import streak, streak_history
from TwitchChannelPointsMiner.utils import _millify

logger = logging.getLogger(__name__)

COLUMNS = [
    "Streamer",
    "Points",
    "Followdate",
    "Last Stream",
    "Sub",
    "Banned",
    "Watchstreaks",
    "Points gained",
]
INTERVAL_SECONDS = 10 * 60
START_POLL_SECONDS = 5

def style_sheet(sheet) -> None:
    header_fill = PatternFill("solid", fgColor="1F4E78")
    success_fill = PatternFill("solid", fgColor="E8F5E9")
    soft_success_fill = PatternFill("solid", fgColor="F1F8E9")

    header_row = 1
    header_names = {}
    for col_idx in range(1, sheet.max_column + 1):
        header_cell = sheet.cell(row=header_row, column=col_idx)
        header_name = str(header_cell.value or "")
        header_names[header_name] = col_idx
        header_cell.font = Font(bold=True, color="FFFFFF")
        header_cell.fill = header_fill
        header_cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[header_row].height = 22

    sheet.freeze_panes = "A2"

    for header_name in ("Followdate", "Last Stream"):
        col_idx = header_names.get(header_name)
        if col_idx is None:
            continue
        for row_idx in range(2, sheet.max_row + 1):
            cell = sheet.cell(row=row_idx, column=col_idx)
            if cell.value in [None, "", "..."]:
                cell.value = None if cell.value == "..." else cell.value
                continue
            if isinstance(cell.value, str):
                try:
                    parsed = datetime.strptime(cell.value, "%d.%m.%Y").date()
                except ValueError:
                    continue
                cell.value = parsed
            cell.number_format = "DD.MM.YYYY"

    points_idx = header_names.get("Points")
    followdate_idx = header_names.get("Followdate")
    last_stream_idx = header_names.get("Last Stream")
    sub_idx = header_names.get("Sub")
    banned_idx = header_names.get("Banned")
    watch_idx = header_names.get("Watchstreaks")
    gained_idx = header_names.get("Points gained")
    max_points_gained = 0

    for row_idx in range(2, sheet.max_row + 1):
        if points_idx is not None:
            sheet.cell(row=row_idx, column=points_idx).alignment = Alignment(
                horizontal="right", vertical="center"
            )
        if gained_idx is not None:
            gained_cell = sheet.cell(row=row_idx, column=gained_idx)
            gained_cell.alignment = Alignment(
                horizontal="right", vertical="center"
            )
            if isinstance(gained_cell.value, (int, float)):
                max_points_gained = max(max_points_gained, int(gained_cell.value))
            if isinstance(gained_cell.value, (int, float)) and gained_cell.value > 0:
                gained_cell.font = Font(color="2E7D32", bold=True)
                gained_cell.fill = soft_success_fill
        if followdate_idx is not None:
            sheet.cell(row=row_idx, column=followdate_idx).alignment = Alignment(
                horizontal="center", vertical="center"
            )
        if last_stream_idx is not None:
            sheet.cell(row=row_idx, column=last_stream_idx).alignment = Alignment(
                horizontal="center", vertical="center"
            )
        if sub_idx is not None:
            sub_cell = sheet.cell(row=row_idx, column=sub_idx)
            sub_cell.alignment = Alignment(
                horizontal="center", vertical="center"
            )
        if banned_idx is not None:
            banned_cell = sheet.cell(row=row_idx, column=banned_idx)
            banned_cell.alignment = Alignment(
                horizontal="center", vertical="center"
            )
        if watch_idx is not None:
            watch_cell = sheet.cell(row=row_idx, column=watch_idx)
            watch_cell.alignment = Alignment(
                horizontal="center", vertical="center"
            )
            if isinstance(watch_cell.value, (int, float)) and watch_cell.value >= 3:
                watch_cell.font = Font(color="2E7D32", bold=True)
                watch_cell.fill = success_fill
            elif isinstance(watch_cell.value, (int, float)) and watch_cell.value > 0:
                watch_cell.font = Font(color="2E7D32")

    data_ref = f"A1:{get_column_letter(sheet.max_column)}{sheet.max_row}"

    if sheet.max_row >= 2:
        table = Table(displayName="StreamersExportTable", ref=data_ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        sheet.add_table(table)

        if gained_idx is not None and max_points_gained > 0:
            gained_column_letter = get_column_letter(gained_idx)
            gained_range = f"{gained_column_letter}2:{gained_column_letter}{sheet.max_row}"
            sheet.conditional_formatting.add(
                gained_range,
                DataBarRule(
                    start_type="num",
                    start_value=0,
                    end_type="max",
                    end_value=0,
                    color="63C384",
                    showValue=True,
                ),
            )

    column_widths = {
        "Streamer": 20,
        "Points": 10,
        "Followdate": 13,
        "Last Stream": 13,
        "Sub": 8,
        "Banned": 10,
        "Watchstreaks": 14,
        "Points gained": 15,
    }

    for col_idx in range(1, sheet.max_column + 1):
        header_name = str(sheet.cell(row=1, column=col_idx).value or "")
        width = column_widths.get(header_name)
        if width is not None:
            sheet.column_dimensions[get_column_letter(col_idx)].width = width


class ExportState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.path = None
        self.interval = INTERVAL_SECONDS
        self.follow_dates = {}
        self.follow_order = None
        self.follow_loaded = False
        self.streak_lookup_attempted = set()
        self.ban_status = {}
        self.ban_lookup_attempted = set()
        self.day_key = datetime.now().strftime("%Y-%m-%d")
        self.baseline = {}
        self.snapshot = {}
        self.anchor = {}
        self.baseline_dirty = False
        self.baseline_path = None
        self.thread = None
        self.stop = threading.Event()
        self.lock = threading.RLock()


STATE = ExportState()


def safe_account_name(username):
    return "".join(
        ch if (ch.isalnum() or ch in "._-") else "_" for ch in str(username).lower()
    )


def dated_path(directory, username):
    report_date = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(
        directory, f"report_{report_date}_{safe_account_name(username)}.xlsx"
    )


def uses_dated_path(username):
    name = os.path.basename(STATE.path or "")
    return name.startswith("report_") and name.endswith(
        f"_{safe_account_name(username)}.xlsx"
    )


def refresh_path(username):
    if not uses_dated_path(username):
        return
    directory = os.path.dirname(STATE.path) or "logs"
    current = dated_path(directory, username)
    if STATE.path != current:
        STATE.path = current


def configure(username, followers_order=None, interval=INTERVAL_SECONDS, directory="logs"):
    STATE.reset()
    STATE.interval = interval
    STATE.follow_order = followers_order
    STATE.path = dated_path(directory, username)
    STATE.baseline_path = os.path.join(
        directory, f"daily_points_baseline.{safe_account_name(username)}.json"
    )
    load_baseline()


def format_followdate(followed_at):
    if not followed_at:
        return "..."
    if isinstance(followed_at, datetime):
        return followed_at.strftime("%d.%m.%Y")
    try:
        normalized = str(followed_at).replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).strftime("%d.%m.%Y")
    except Exception:
        return "..."


def format_yes_no(value):
    return "yes" if bool(value) else "no"


def format_sub(streamer):
    try:
        return format_yes_no(streamer.viewer_has_points_multiplier())
    except Exception:
        return "no"


def format_timestamp_date(timestamp):
    if timestamp in [None, ""]:
        return "..."
    try:
        return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).strftime(
            "%d.%m.%Y"
        )
    except Exception:
        return "..."


def last_stream_date(miner, streamer):
    created_at = getattr(getattr(streamer, "stream", None), "created_at", None)
    if created_at not in [None, ""]:
        return format_timestamp_date(created_at)
    login = streamer.username
    starts = []
    track = streak.STATE.tracks.get(login)
    if track is not None and track.logical_start:
        starts.append(track.logical_start)
    cache = getattr(miner, "watch_streak_cache", None)
    if cache is not None:
        try:
            starts.extend(
                session.started_at
                for session in list(cache._sessions.values())
                if session.streamer_login == login
                and session.started_at not in [None, ""]
            )
        except Exception:
            pass
    if starts:
        return format_timestamp_date(max(starts))
    return "..."


def history_points_total(streamer):
    history = getattr(streamer, "history", {})
    if not isinstance(history, dict):
        return 0
    total = 0
    for entry in history.values():
        if not isinstance(entry, dict):
            continue
        amount = entry.get("amount", 0)
        if isinstance(amount, (int, float)):
            total += int(amount)
    return max(0, total)


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def dump_json(path, data):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
    except Exception:
        logger.debug("Could not write %s", path, exc_info=True)


def reset_baseline_if_needed():
    day_key = datetime.now().strftime("%Y-%m-%d")
    if day_key != STATE.day_key:
        STATE.day_key = day_key
        STATE.baseline = {}
        STATE.snapshot = {}
        STATE.anchor = {}
        STATE.baseline_dirty = True


def load_baseline():
    today = datetime.now().strftime("%Y-%m-%d")
    STATE.day_key = today
    STATE.baseline = {}
    STATE.snapshot = {}
    STATE.anchor = {}
    STATE.baseline_dirty = False
    if not STATE.baseline_path:
        return
    payload = load_json(STATE.baseline_path, {})
    if not isinstance(payload, dict) or payload.get("day_key") != today:
        return
    stored = payload.get("points_gained")
    if not isinstance(stored, dict):
        return
    normalized = {}
    for username, value in stored.items():
        try:
            normalized[str(username)] = max(0, int(value))
        except Exception:
            continue
    STATE.baseline = normalized
    STATE.snapshot = dict(normalized)


def save_baseline_if_dirty():
    if not STATE.baseline_dirty or not STATE.baseline_path:
        return
    dump_json(
        STATE.baseline_path,
        {
            "schema_version": 2,
            "day_key": STATE.day_key,
            "points_gained": STATE.snapshot,
        },
    )
    STATE.baseline_dirty = False


def points_gained(streamer):
    reset_baseline_if_needed()
    current_total = history_points_total(streamer)
    username = streamer.username
    carried = max(0, int(STATE.baseline.get(username, 0)))
    anchor = STATE.anchor.get(username)
    if anchor is None:
        STATE.anchor[username] = current_total
        return carried
    return max(0, int(carried + max(0, int(current_total - anchor))))


def sync_snapshot(rows):
    snapshot = {}
    for row in rows:
        username = str(row.get("Streamer", "")).strip()
        if not username:
            continue
        try:
            snapshot[username] = max(0, int(row.get("Points gained", 0)))
        except Exception:
            snapshot[username] = 0
    if snapshot != STATE.snapshot:
        STATE.snapshot = snapshot
        STATE.baseline_dirty = True


def fetch_follow_dates(gql, order, limit=100):
    follows = {}
    template = GQLOperations.ChannelFollows
    cursor = ""
    while True:
        payload = copy.deepcopy(template)
        payload["variables"] = {"limit": limit, "order": str(order), "cursor": cursor}
        parsed = gql.post_gql_request_single(
            template["operationName"],
            payload,
            gql.parser.parse_channel_follows_response,
        )
        if parsed is None:
            return follows
        for edge in parsed.follows.edges:
            node = edge.node
            try:
                follows[str(node.login).lower()] = node.self.follower.followed_at
            except AttributeError:
                follows[str(node.login).lower()] = None
        page = parsed.follows.page_info
        if not page.has_next_page or page.end_cursor in (None, "", cursor):
            return follows
        cursor = page.end_cursor


def load_follow_dates(miner):
    if STATE.follow_loaded:
        return
    STATE.follow_loaded = True
    try:
        order = (
            STATE.follow_order
            if STATE.follow_order is not None
            else FollowersOrder.ASC
        )
        STATE.follow_dates = fetch_follow_dates(miner.twitch.gql, order)
    except Exception as error:
        STATE.follow_dates = {}
        logger.warning("Failed to load follower dates for export: %s", error)


def chat_banned(miner, streamer):
    login = streamer.username
    channel_id = str(getattr(streamer, "channel_id", "") or "")
    if not channel_id:
        return STATE.ban_status.get(login, False)
    cached = (getattr(miner.twitch, "channel_bans", None) or {}).get(channel_id)
    if cached and cached[0] is not None:
        STATE.ban_status[login] = bool(cached[0].active(time.time()))
        return STATE.ban_status[login]
    if login in STATE.ban_lookup_attempted:
        return STATE.ban_status.get(login, False)
    STATE.ban_lookup_attempted.add(login)
    try:
        status = miner.twitch.gql.channel_ban_statuses([channel_id]).get(channel_id)
        if status is not None:
            STATE.ban_status[login] = bool(status.active(time.time()))
    except Exception as error:
        logger.debug("Failed to fetch ban status for %s: %s", login, error)
    return STATE.ban_status.get(login, False)


def watch_streak_days(miner, streamer):
    login = streamer.username
    days = streak_history.current_days(login)
    if days is None and login not in STATE.streak_lookup_attempted:
        STATE.streak_lookup_attempted.add(login)
        channel_id = getattr(streamer, "channel_id", None)
        if channel_id:
            try:
                client = streak.STATE.client or streak.GqlClient(miner.twitch.gql)
                value = client.reward_list(channel_id).value
                if value is not None:
                    days = max(0, int(value))
                    streak.STATE.known_length[login] = days
            except Exception as error:
                logger.debug(
                    "Failed to fetch watch streak days for %s: %s", login, error
                )
    return days if days is not None else 0


def build_rows(miner):
    def sort_key(streamer):
        points = streamer.channel_points
        return points if isinstance(points, (int, float)) else float("-inf")

    rows = []
    for streamer in sorted(list(miner.streamers), key=sort_key, reverse=True):
        points = streamer.channel_points
        points_value = points if isinstance(points, (int, float)) else 0
        days = watch_streak_days(miner, streamer)
        if Settings.enable_analytics is True:
            streak_history.record(streamer, days)
        rows.append(
            {
                "Streamer": streamer.username,
                "Points": _millify(points_value),
                "Followdate": format_followdate(
                    STATE.follow_dates.get(streamer.username)
                ),
                "Last Stream": last_stream_date(miner, streamer),
                "Sub": format_sub(streamer),
                "Banned": format_yes_no(chat_banned(miner, streamer)),
                "Watchstreaks": days,
                "Points gained": points_gained(streamer),
            }
        )
    sync_snapshot(rows)
    return rows


def write_xlsx(miner, rows):
    refresh_path(miner.username)
    output_dir = os.path.dirname(STATE.path) or "."
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(COLUMNS)
    for row in rows:
        sheet.append([row.get(column) for column in COLUMNS])
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".streamers_export_", suffix=".xlsx", dir=output_dir
    )
    os.close(tmp_fd)
    try:
        workbook.save(tmp_path)
        workbook = load_workbook(tmp_path)
        sheet = workbook.active
        style_sheet(sheet)
        workbook.save(tmp_path)
        os.replace(tmp_path, STATE.path)
    finally:
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)


def export_snapshot(miner):
    with STATE.lock:
        try:
            load_follow_dates(miner)
            write_xlsx(miner, build_rows(miner))
        except Exception as error:
            logger.warning(
                "Failed to update streamers export %s: %s", STATE.path, error
            )
        finally:
            save_baseline_if_dirty()


def start(miner):
    if STATE.thread is not None and STATE.thread.is_alive():
        return
    STATE.stop.clear()

    def loop():
        while not STATE.stop.wait(START_POLL_SECONDS):
            if miner.running and len(miner.streamers) > 0:
                break
        else:
            return
        export_snapshot(miner)
        while not STATE.stop.wait(STATE.interval):
            if not miner.running:
                break
            export_snapshot(miner)

    STATE.thread = threading.Thread(target=loop, name="Streamers export", daemon=True)
    STATE.thread.start()


def finish(miner):
    STATE.stop.set()
    thread = STATE.thread
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=30)
    if len(getattr(miner, "streamers", [])) > 0:
        export_snapshot(miner)
