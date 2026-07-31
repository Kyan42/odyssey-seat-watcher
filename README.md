# Odyssey 70mm seat watcher

Watches [Fandango](https://www.fandango.com/regal-irvine-spectrum-aabtb/theater-page)
for seats opening up at **The Odyssey in IMAX 70mm**, Regal Irvine Spectrum,
Auditorium 12 — the **6:30pm** showings on **Sep 8, 9 and 10 2026**.

When `4` consecutive seats appear in the prime centre block
(**rows F–J, seats 12–28**) it fires a phone push via [ntfy.sh](https://ntfy.sh).

Runs entirely on GitHub Actions every 15 minutes, so no machine of your own
needs to be switched on.

## How it works

`watch.py` calls Fandango's undocumented seat-map endpoint:

```
GET https://www.fandango.com/napi/seatMap/{showtimeHashCode}
```

No auth or cookies are needed, but two things are easy to get wrong:

1. **A `Referer` header pointing at the theatre page is mandatory.** Without it
   the API returns `403 {"error":"FORBIDDEN"}`.
2. **The request has to be made with `curl`, not Python's `urllib`.** Akamai
   fingerprints the TLS handshake and serves Python an HTML *Access Denied*
   page, while curl from the very same host and IP gets a clean `200`.

The response contains every seat as `{"id": "F14", "status": "A" | "R", ...}`,
where `A` means available. The script groups seats by row, finds runs of
consecutively-numbered available seats inside the target zone, and pushes an
alert when a run is long enough.

`state.json` is committed back to the repo after each run so the same block
isn't reported over and over. A still-open block is re-announced once an hour.

## Setup

The only secret is the ntfy topic:

```bash
gh secret set NTFY_TOPIC --body "your-topic-name"
```

Then install the [ntfy app](https://ntfy.sh/#subscribe-phone) and subscribe to
that same topic. Anyone who knows a topic name can read it, so keep it obscure.

## Tuning

Edit the config block at the top of `watch.py`:

| Setting | Meaning |
| --- | --- |
| `PRIME_ROWS` | Rows that count as "prime" |
| `SEAT_MIN` / `SEAT_MAX` | Seat-number window within those rows |
| `NEED_SEATS` | How many consecutive seats you need |
| `RE_ALERT_MINS` | How often to re-announce a block that is still open |

## Caveats

- GitHub's cron is best-effort and can slip by several minutes under load.
- `showtimeHashCode` values are baked into `SHOWS`. If Fandango ever rotates
  them the script will start getting 403/404s and will send a throttled
  "watcher problem" push instead of failing silently.
- The watcher can only tell you seats exist. Buying them is still on you.
