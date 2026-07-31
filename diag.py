"""Throwaway diagnostic: what exactly does Fandango block from this host?"""
import urllib.parse
import subprocess
import urllib.error
import urllib.request

HASH = "v2-e17f17c965f03db6093d8556d70d45c24fb99c2c75a82b99f11c79a070d94d34"
SEAT = f"https://www.fandango.com/napi/seatMap/{HASH}"
THEATER = "https://www.fandango.com/regal-irvine-spectrum-aabtb/theater-page?date=2026-09-10"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")

FULL = {
    "User-Agent": UA,
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": THEATER,
    "X-Requested-With": "XMLHttpRequest",
}


def probe(label, url, headers):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"{label:32} -> {r.status}  ({len(r.read())} bytes)")
    except urllib.error.HTTPError as e:
        print(f"{label:32} -> {e.code}  {e.read()[:120]!r}")
    except Exception as e:  # noqa: BLE001
        print(f"{label:32} -> ERR {e}")


print("egress IP:", subprocess.run(
    ["curl", "-s", "--max-time", "15", "https://ifconfig.me"],
    capture_output=True, text=True).stdout.strip())

probe("homepage (python)", "https://www.fandango.com/", {"User-Agent": UA})
probe("theatre page (python)", THEATER, {"User-Agent": UA})
probe("seatMap full headers (python)", SEAT, FULL)

out = subprocess.run(
    ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "30",
     "-A", UA, "-H", "Accept: application/json",
     "-H", f"Referer: {THEATER}",
     "-H", "Accept-Language: en-US,en;q=0.9",
     "-H", "X-Requested-With: XMLHttpRequest", SEAT],
    capture_output=True, text=True)
print(f"{'seatMap full headers (curl)':32} -> {out.stdout.strip()}")

for name, tmpl in [
    ("codetabs", "https://api.codetabs.com/v1/proxy?quest={u}"),
    ("allorigins", "https://api.allorigins.win/raw?url={u}"),
]:
    probe(f"seatMap via {name}",
          tmpl.format(u=urllib.parse.quote(SEAT, safe="")),
          {"User-Agent": UA, "Referer": THEATER})

