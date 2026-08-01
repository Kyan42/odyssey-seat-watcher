# Odyssey 70mm seat watcher

Watches [Fandango](https://www.fandango.com/regal-irvine-spectrum-aabtb/theater-page)
for seats opening up at **The Odyssey in IMAX 70mm**, Regal Irvine Spectrum,
Auditorium 12 — the **6:30pm** showings on **Sep 8, 9 and 10 2026**.

When `4` consecutive seats appear in the prime centre block
(**rows F–J, seats 12–28**) it fires a phone push via [ntfy.sh](https://ntfy.sh).

Runs entirely on GitHub Actions, so no machine of your own needs to be switched
on.

## Scheduling

GitHub's `schedule` trigger turned out to be unusable on its own — in one
observation it fired **1 of 14** expected times, leaving multi-hour gaps.

So the watcher keeps itself alive instead. `watch-a` and `watch-b` are two
workflows that each call the same reusable `seat-watch` workflow, and each is
triggered by the *other* finishing:

```
watch-a ──finishes──▶ watch-b ──finishes──▶ watch-a ──▶ (stops)
```

GitHub caps `workflow_run` chains at **three levels**, so the chain cannot run
forever on its own. Each link therefore polls every 5 minutes for **5.5 hours**,
meaning a single trigger buys roughly **16 hours** of unbroken cover. The cron
schedules on both workflows only have to land once or twice a day to keep it
going, which is well within even the poor observed hit rate.

A `concurrency` group guarantees only one run is ever active, and a chained run
is padded to a 10-minute minimum so a crash can never spin the loop.

For truly unlimited chaining, add an optional `WATCHER_PAT` secret (a
fine-grained personal access token scoped to this repo with **Actions: read and
write**). Each run then queues its own successor up front, which removes the
dependence on both the three-level cap and the cron schedule. Events created
with the built-in `GITHUB_TOKEN` deliberately do not trigger workflows, which is
the only reason this design needs the ping-pong at all. Without the secret the
workflow still runs — it just falls back to the chain plus cron.

```bash
gh secret set WATCHER_PAT --repo Kyan42/odyssey-seat-watcher
```

Once the last show has passed, the watcher disables both workflows itself.

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

`state.json` is kept in the Actions cache (not committed) so the same block
isn't reported over and over. A still-open block is re-announced once an hour.
Committing state was the original approach, but pushing to the default branch
makes GitHub re-register the cron schedule.

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

- `showtimeHashCode` values are baked into `SHOWS`. If Fandango ever rotates
  them the script will start getting 403/404s and will send a throttled
  "watcher problem" push instead of failing silently.
- The watcher can only tell you seats exist. Buying them is still on you.
