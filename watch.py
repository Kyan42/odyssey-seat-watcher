#!/usr/bin/env python3
"""
Odyssey 70mm seat watcher - Regal Irvine Spectrum, Auditorium 12.

Polls Fandango's seat-map API for the 6:30pm IMAX 70mm showings on
Sep 8/9/10 2026 and sends an ntfy.sh push when NEED_SEATS consecutive
seats open up in the prime centre block (rows F-J, seats 12-28).

Runs on a GitHub Actions cron. State is committed back to the repo so
alerts are de-duplicated between runs.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ---------------- config ----------------
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
PRIME_ROWS = {"F", "G", "H", "I", "J"}
SEAT_MIN = 12
SEAT_MAX = 28
NEED_SEATS = 4
RE_ALERT_MINS = 60          # re-alert if the same seats are still open after this long
FAIL_QUIET_HOURS = 6        # only nag about breakage this often
PACIFIC = ZoneInfo("America/Los_Angeles")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")

SHOWS = [
    {"date": "2026-09-08", "label": "Tue Sep 8, 6:30p",
     "hash": "v2-81b0257a1fbe5c7cb2da29d53ee3904ba2e545937cd6b8bc82435a6ec3228d67"},
    {"date": "2026-09-09", "label": "Wed Sep 9, 6:30p",
     "hash": "v2-aa743d4a1af55dcb7f3a43c0056915a2b09f5835535d5c4768871162202414ea"},
    {"date": "2026-09-10", "label": "Thu Sep 10, 6:30p",
     "hash": "v2-e17f17c965f03db6093d8556d70d45c24fb99c2c75a82b99f11c79a070d94d34"},
]

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
SEAT_RE = re.compile(r"^([A-Z]+)(\d+)$")
EPOCH = "2000-01-01T00:00:00+00:00"

# Test hook: FORCE_ZONE="A:1-39" temporarily widens the target zone so a run is
# guaranteed to trigger, letting you prove the alert path end to end.
_force = os.environ.get("FORCE_ZONE", "").strip()
if _force:
    _rows, _, _span = _force.partition(":")
    _lo, _, _hi = _span.partition("-")
    PRIME_ROWS = set(_rows.split(","))
    SEAT_MIN, SEAT_MAX = int(_lo), int(_hi)


def now():
    return datetime.now(timezone.utc)


def parse_ts(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.fromisoformat(EPOCH)


def log(msg):
    stamp = now().astimezone(PACIFIC).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{stamp}] {msg}", flush=True)


def theater_url(date):
    return f"https://www.fandango.com/regal-irvine-spectrum-aabtb/theater-page?date={date}"


def send_push(title, message, click_url=None, priority="urgent"):
    if not NTFY_TOPIC:
        log("WARN: NTFY_TOPIC is not set, cannot send push")
        return
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": "popcorn",
        "Content-Type": "text/plain; charset=utf-8",
    }
    if click_url:
        headers["Click"] = click_url
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
    except Exception as exc:  # noqa: BLE001 - a failed push must never kill the run
        log(f"WARN: ntfy push failed: {exc}")


def get_seat_map(show):
    """Fetch the seat map.

    Two non-obvious requirements:
      * The Referer header is mandatory - without it Fandango answers
        403 {"error":"FORBIDDEN"}.
      * The request must go through curl, not urllib. Akamai fingerprints the
        TLS handshake and blocks Python's client outright with an HTML
        "Access Denied" page, while curl is let through.
    """
    url = f"https://www.fandango.com/napi/seatMap/{show['hash']}"
    body = os.path.join(tempfile.gettempdir(), f"smap_{show['date']}.json")
    try:
        proc = subprocess.run(
            [
                "curl", "-sS", "--max-time", "45",
                "-A", UA,
                "-H", "Accept: application/json",
                "-H", "Accept-Language: en-US,en;q=0.9",
                "-H", f"Referer: {theater_url(show['date'])}",
                "-H", "X-Requested-With: XMLHttpRequest",
                "-o", body, "-w", "%{http_code}",
                url,
            ],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("curl timed out") from exc

    status = proc.stdout.strip()
    if status != "200":
        raise RuntimeError(f"HTTP {status or '???'} from seatMap API "
                           f"{proc.stderr.strip()}".strip())

    try:
        with open(body, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"could not parse seatMap response: {exc}") from exc

    if not data.get("seats"):
        raise RuntimeError("seatMap response had no seats array")
    return data


def find_prime_blocks(seat_map):
    """Return runs of >= NEED_SEATS consecutively-numbered available seats
    inside the prime zone, e.g. ['H14-H17']."""
    by_row = {}
    for seat in seat_map["seats"]:
        match = SEAT_RE.match(str(seat.get("id", "")))
        if not match:
            continue
        row, num = match.group(1), int(match.group(2))
        if row not in PRIME_ROWS or not (SEAT_MIN <= num <= SEAT_MAX):
            continue
        by_row.setdefault(row, {})[num] = seat.get("status") == "A"

    hits = []
    for row in sorted(by_row):
        run = []
        for num in sorted(by_row[row]):
            if by_row[row][num] and (not run or num == run[-1] + 1):
                run.append(num)
                continue
            if len(run) >= NEED_SEATS:
                hits.append(f"{row}{run[0]}-{row}{run[-1]}")
            run = [num] if by_row[row][num] else []
        if len(run) >= NEED_SEATS:
            hits.append(f"{row}{run[0]}-{row}{run[-1]}")
    return hits


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def main():
    state = load_state()
    failures = 0

    for show in SHOWS:
        key = show["date"]
        prev = state.get(key) or {}
        try:
            seat_map = get_seat_map(show)
            hits = find_prime_blocks(seat_map)
            sig = "|".join(hits)
            total = f"{seat_map.get('totalAvailableSeatCount')}/{seat_map.get('totalSeatCount')}"
            log(f"OK  {key}  total={total}  prime={sig or 'none'}")

            last_alert = parse_ts(prev.get("lastAlert", EPOCH))
            is_new = bool(sig) and sig != prev.get("sig", "")
            is_stale = bool(sig) and (now() - last_alert) >= timedelta(minutes=RE_ALERT_MINS)

            if is_new or is_stale:
                title = f"SEATS OPEN - {show['label']}"
                message = (
                    f"The Odyssey 70mm, Regal Irvine Spectrum\n"
                    f"{len(hits)} block(s) of {NEED_SEATS}+ in the centre: {sig}\n"
                    f"Theatre total: {total}"
                )
                send_push(title, message, click_url=theater_url(key))
                log(f"ALERT  {key}  {sig}")
                state[key] = {"sig": sig, "lastAlert": now().isoformat(), "total": total}
            else:
                state[key] = {
                    "sig": sig,
                    "lastAlert": last_alert.isoformat(),
                    "total": total,
                }

        except Exception as exc:  # noqa: BLE001 - one bad show must not stop the others
            failures += 1
            log(f"ERROR  {key}  {exc}")
            last_fail = parse_ts(prev.get("lastFail", EPOCH))
            if (now() - last_fail) >= timedelta(hours=FAIL_QUIET_HOURS):
                send_push(
                    "Odyssey watcher problem",
                    f"Could not read the seat map for {key}: {exc}",
                    priority="high",
                )
                prev = dict(prev)
                prev["lastFail"] = now().isoformat()
            state[key] = prev

    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.write("\n")

    # Every show failing means something systemic broke - fail the job so
    # GitHub emails as a second line of defence.
    if failures == len(SHOWS):
        log("All shows failed - failing the job to raise a GitHub notification.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
