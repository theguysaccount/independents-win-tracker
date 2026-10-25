"""Shared helpers: HTTP with retries, JSON files, names, US states, formatting."""
import gzip
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CONFIG = os.path.join(ROOT, "config", "tracker.json")
UA = "independents-win-tracker/1.0 (+https://github.com/theguysaccount/independents-win-tracker)"

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia", "AS": "American Samoa", "GU": "Guam", "MP": "Northern Mariana Islands",
    "PR": "Puerto Rico", "VI": "U.S. Virgin Islands",
}
STATE_BY_NAME = {v.lower(): k for k, v in STATES.items()}
# States with a single at-large House seat (district "00" at the FEC, "AL" in market tickers).
AT_LARGE = {"AK", "DE", "ND", "SD", "VT", "WY"}


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def http_get(url, *, timeout=60, retries=3, headers=None, method="GET"):
    """Fetch a URL and return (body bytes, response headers). Retries 429/5xx and network errors."""
    last = None
    for attempt in range(retries):
        if attempt:
            time.sleep(min(30, 3 * 2 ** attempt))
        req = urllib.request.Request(url, method=method, headers={
            "User-Agent": UA, "Accept-Encoding": "gzip", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body, {k.lower(): v for k, v in r.headers.items()}
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
    raise last


def get_json(url, **kw):
    body, _ = http_get(url, **kw)
    return json.loads(body)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path, obj, *, compact=False):
    """Write JSON atomically, so a crash never leaves a half-written data file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def load_config():
    return read_json(CONFIG, {})


def fold(s):
    """Lowercase ASCII letters only: 'Macías' -> 'macias', "O'Brien" -> 'obrien'."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", s.lower())


def slugify(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V"}
_HONORIFICS = {"MR", "MRS", "MS", "DR", "HON", "REV", "PROF", "GEN", "COL", "SGT", "CAPT", "ESQ", "PHD", "MD"}


def _cap(word):
    w = word.lower()
    if re.fullmatch(r"(ii|iii|iv|v)", w):
        return w.upper()
    out = "-".join(p[:1].upper() + p[1:] for p in w.split("-"))
    out = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), out)
    out = re.sub(r"\bO'([a-z])", lambda m: "O'" + m.group(1).upper(), out)
    return out


def person_name(raw):
    """'OSBORN, DAN' -> 'Dan Osborn'; 'KILEY, KEVIN' -> 'Kevin Kiley'; 'SMITH, JOHN A JR' -> 'John Smith Jr.'

    Keeps the first given name only. FEC and Voteview list legal names; pages prefer the
    name a prediction market or the congress-legislators dataset uses when one exists.
    """
    raw = (raw or "").strip()
    if "," not in raw:
        return " ".join(_cap(w) for w in raw.split())
    last, rest = raw.split(",", 1)
    tokens = [t.strip(".") for t in re.split(r"[\s,]+", rest) if t.strip(".")]
    suffix = [t for t in tokens if t.upper() in _SUFFIXES]
    given = [t for t in tokens if t.upper() not in _SUFFIXES and t.upper() not in _HONORIFICS]
    first = _cap(given[0]) if given else ""
    name = " ".join(x for x in [first, " ".join(_cap(w) for w in last.split())] if x)
    if suffix:
        s = suffix[0].upper()
        name += " " + (s.title() + "." if s in ("JR", "SR") else s)
    return name


def surname(raw):
    """Last name, folded: from 'OSBORN, DAN' or 'Dan Osborn' or 'Todd Achilles (I)'."""
    raw = re.sub(r"\([^)]*\)", "", raw or "").strip()
    if "," in raw:
        return fold(raw.split(",", 1)[0].split()[-1] if raw.split(",", 1)[0].split() else "")
    words = [w for w in raw.split() if w.strip(".").upper() not in _SUFFIXES]
    return fold(words[-1]) if words else ""


def given(raw):
    raw = re.sub(r"\([^)]*\)", "", raw or "").strip()
    if "," in raw:
        rest = [t for t in re.split(r"[\s,]+", raw.split(",", 1)[1]) if t.strip(".")]
        rest = [t for t in rest if t.strip(".").upper() not in _HONORIFICS]
        return fold(rest[0]) if rest else ""
    words = raw.split()
    return fold(words[0]) if len(words) > 1 else ""


def money(x):
    """$11.0M / $272K / $8,500."""
    if x is None:
        return "n/a"
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1e9:
        return f"{sign}${x / 1e9:.1f}B"
    if x >= 1e6:
        return f"{sign}${x / 1e6:.1f}M"
    if x >= 1e4:
        return f"{sign}${x / 1e3:.0f}K"
    return f"{sign}${x:,.0f}"


def pct(p):
    """0.255 -> '25.5%', 0.26 -> '26%', 0.001 -> '0.1%', 0.0004 -> '<0.1%'."""
    if p is None:
        return "n/a"
    v = round(p * 100, 1)
    if 0 < p * 100 < 0.05:
        return "<0.1%"
    if 99.95 < p * 100 < 100:
        return ">99.9%"
    return (f"{v:.0f}" if v == int(v) else f"{v:.1f}") + "%"


def race_key(state, office, district=None):
    """'NE-S', 'AK-H-00', 'CA-H-06'."""
    return f"{state}-S" if office == "S" else f"{state}-H-{(district or '00').zfill(2)}"


def race_label(state, office, district=None, short=False):
    name = STATES.get(state, state)
    if office == "S":
        return f"{state} Senate" if short else f"{name} U.S. Senate"
    d = (district or "00").zfill(2)
    if d == "00":
        return f"{state}-AL" if short else f"{name} at-large U.S. House seat"
    return f"{state}-{d}" if short else f"{name}'s {ordinal(int(d))} congressional district"


def ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
