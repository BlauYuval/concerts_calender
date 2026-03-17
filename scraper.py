#!/usr/bin/env python3
"""
Concert scraper: reads websites.json → scrapes each site → writes concerts_data.json

All three sites use the same multiline block format served by Seated:
  Line 1: date  (e.g. "MAR 18, 2026"  or  "22 Apr 26")
  Line 2: venue name
  Line 3: city, state/country code
  Line 4+: ticket status / notes (ignored)
"""
import asyncio
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import Page, async_playwright

# ── Config ─────────────────────────────────────────────────────────────────────

WEBSITES_FILE = Path("websites.json")
OUTPUT_FILE   = Path("concerts_data.json")

# ── Lookup tables ───────────────────────────────────────────────────────────────

COUNTRY_CODES: dict[str, str] = {
    "UK": "United Kingdom", "GB": "United Kingdom",
    "FR": "France",         "DE": "Germany",
    "NL": "Netherlands",    "BE": "Belgium",
    "DK": "Denmark",        "NO": "Norway",
    "SE": "Sweden",         "IT": "Italy",
    "CH": "Switzerland",    "PL": "Poland",
    "IE": "Ireland",        "NZ": "New Zealand",
    "AU": "Australia",      "CA": "Canada",
    "US": "United States",  "AT": "Austria",
    "ES": "Spain",          "PT": "Portugal",
    "FI": "Finland",        "HU": "Hungary",
    "CZ": "Czech Republic",
}

# Full-name aliases for regions/countries not in COUNTRY_CODES keys
COUNTRY_ALIASES: dict[str, str] = {
    "england":        "United Kingdom",
    "scotland":       "United Kingdom",
    "wales":          "United Kingdom",
    "northern ireland": "United Kingdom",
    "great britain":  "United Kingdom",
    "usa":            "United States",
    "united states of america": "United States",
}

US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL",
    "IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT",
    "NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI",
    "SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC",
}

CANADIAN_PROVINCES = {
    "ON","QC","BC","AB","MB","SK","NS","NB","NL","PE","YT","NT","NU",
}

MONTH_MAP: dict[str, int] = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
    "january":1,"february":2,"march":3,"april":4,"june":6,
    "july":7,"august":8,"september":9,"october":10,
    "november":11,"december":12,
}

# Fallback: well-known cities → (state_or_None, country)
CITY_LOOKUP: dict[str, tuple[Optional[str], str]] = {
    "san francisco": ("CA", "United States"),
    "los angeles":   ("CA", "United States"),
    "las vegas":     ("NV", "United States"),
    "salt lake city":("UT", "United States"),
    "denver":        ("CO", "United States"),
    "minneapolis":   ("MN", "United States"),
    "chicago":       ("IL", "United States"),
    "nashville":     ("TN", "United States"),
    "boston":        ("MA", "United States"),
    "baltimore":     ("MD", "United States"),
    "new york":      ("NY", "United States"),
    "atlanta":       ("GA", "United States"),
    "houston":       ("TX", "United States"),
    "austin":        ("TX", "United States"),
    "dallas":        ("TX", "United States"),
    "portland":      ("OR", "United States"),
    "seattle":       ("WA", "United States"),
    "philadelphia":  ("PA", "United States"),
    "richmond":      ("VA", "United States"),
    "toronto":       ("ON", "Canada"),
    "montreal":      ("QC", "Canada"),
    "vancouver":     ("BC", "Canada"),
    "london":        (None, "United Kingdom"),
    "manchester":    (None, "United Kingdom"),
    "glasgow":       (None, "United Kingdom"),
    "bristol":       (None, "United Kingdom"),
    "paris":         (None, "France"),
    "amsterdam":     (None, "Netherlands"),
    "berlin":        (None, "Germany"),
    "stockholm":     (None, "Sweden"),
    "oslo":          (None, "Norway"),
    "copenhagen":    (None, "Denmark"),
    "brussels":      (None, "Belgium"),
    "milan":         (None, "Italy"),
    "zurich":        (None, "Switzerland"),
    "warsaw":        (None, "Poland"),
    "dublin":        (None, "Ireland"),
    "melbourne":     (None, "Australia"),
    "sydney":        (None, "Australia"),
    "brisbane":      (None, "Australia"),
    "auckland":      (None, "New Zealand"),
    "nantucket":     ("MA", "United States"),
    "shelburne":     ("VT", "United States"),
    "saint paul":    ("MN", "United States"),
    "rothbury":      ("MI", "United States"),
    "marshfield":    ("MA", "United States"),
    "louisville":    ("KY", "United States"),
    "utrecht":       (None, "Netherlands"),
    "ghent":         (None, "Belgium"),
    "fredrikstad":   (None, "Norway"),
    "düsseldorf":    (None, "Germany"),
}

# Lines to skip: either exact matches or lines that start with these phrases
# (using exact/prefix matching avoids false positives inside venue names)
_SKIP_EXACT = {
    "tickets", "sold out", "vip", "passes", "low tickets",
    "join waitlist", "get tickets", "on sale", "free", "rsvp",
    "sign up", "skip to content", "powered by seated",
    "past shows", "follow", "subscribe", "venue upgrade",
}
_SKIP_PREFIXES = ("ticket", "sold", "pass", "vip", "join waitlist",
                  "on sale", "powered by", "get notified", "follow ",
                  "venue upgrade", "supporting ")

# ── Date parsing ────────────────────────────────────────────────────────────────

def parse_date_line(line: str) -> Optional[str]:
    """
    Handles:
      "MAR 18, 2026"   (Couch / Sammy Rae — Seated widget)
      "22 Apr 26"      (Olivia Dean — DD Mon YY)
      "22 April 2026"
      "APR 20, 2026 - APR 21, 2026"  → first date only
    """
    # Strip range suffix
    line = re.sub(r'\s*[-–]\s*\w.*$', '', line).strip()

    # "Month DD[,] YYYY" — e.g. MAR 18, 2026
    m = re.fullmatch(r'([A-Za-z]{3,}\.?)\s+(\d{1,2}),?\s+(\d{4})', line, re.I)
    if m:
        mn = MONTH_MAP.get(m.group(1).rstrip('.').lower())
        dy, yr = int(m.group(2)), int(m.group(3))
        if mn:
            try:
                return date(yr, mn, dy).isoformat()
            except ValueError:
                pass

    # "DD Month YY[YY]" — e.g. 22 Apr 26 or 22 April 2026
    m = re.fullmatch(r'(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{2,4})', line, re.I)
    if m:
        mn = MONTH_MAP.get(m.group(2).lower())
        dy, yr = int(m.group(1)), int(m.group(3))
        if yr < 100:
            yr += 2000
        if mn:
            try:
                return date(yr, mn, dy).isoformat()
            except ValueError:
                pass

    return None


def is_skip_line(line: str) -> bool:
    low = line.lower().strip()
    if low in _SKIP_EXACT:
        return True
    if any(low.startswith(p) for p in _SKIP_PREFIXES):
        return True
    # Pure-digit lines and very short single-word nav items
    if re.fullmatch(r'\d{4}', low):
        return True
    return False


# ── Location parsing ────────────────────────────────────────────────────────────

def normalize_location(raw: str) -> dict:
    """'City, ST' or 'City, Country' → {city, state, country}"""
    raw = raw.strip().rstrip(".,")
    parts = [p.strip() for p in raw.split(",")]

    if len(parts) >= 2:
        city      = parts[0]
        region    = parts[-1].strip()
        region_up = region.upper()

        # Codes that are simultaneously a US state (or CA province) AND an ISO country code:
        #   CA = California  / Canada
        #   DE = Delaware    / Germany
        #   NL = Newfoundland/ Netherlands
        # For these we consult CITY_LOOKUP to disambiguate; all others are unambiguous.
        if region_up in ("CA", "DE", "NL"):
            entry = CITY_LOOKUP.get(city.lower())
            if entry:
                return {"city": city, "state": entry[0], "country": entry[1]}
            # Unknown city: default to the country-code interpretation
            return {"city": city, "state": None, "country": COUNTRY_CODES[region_up]}

        # Unambiguous US state (ME, TX, NY, OR, MA …)
        if region_up in US_STATES:
            return {"city": city, "state": region_up, "country": "United States"}

        # Unambiguous Canadian province (ON, QC, BC …)
        if region_up in CANADIAN_PROVINCES:
            return {"city": city, "state": region_up, "country": "Canada"}

        # ISO 3166-1 country code (UK, FR, AU, IE …)
        if region_up in COUNTRY_CODES:
            return {"city": city, "state": None, "country": COUNTRY_CODES[region_up]}

        # Full country name ("Belgium", "France" …)
        full = next((v for v in COUNTRY_CODES.values() if v.upper() == region_up), None)
        if full:
            return {"city": city, "state": None, "country": full}

        # Alias ("England" → "United Kingdom" …)
        alias = COUNTRY_ALIASES.get(region.lower())
        if alias:
            return {"city": city, "state": None, "country": alias}

        # Fallback: keep region as the country name
        return {"city": city, "state": None, "country": region}

    # Single token: city only (no explicit region)
    city  = raw
    entry = CITY_LOOKUP.get(city.lower())
    if entry:
        return {"city": city, "state": entry[0], "country": entry[1]}

    return {"city": city, "state": None, "country": "Unknown"}


# ── Common block parser ─────────────────────────────────────────────────────────

def parse_blocks(text: str) -> list[tuple[str, str, str]]:
    """
    Splits page text into lines, finds date lines, and collects
    (date_iso, venue, location) triples.

    Returns list of (date_iso, venue, location_str).
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    blocks: list[tuple[str, str, str]] = []
    i = 0
    while i < len(lines):
        date_iso = parse_date_line(lines[i])
        if date_iso:
            # Next non-skip lines are venue then city
            candidates = []
            j = i + 1
            while j < len(lines) and len(candidates) < 2:
                if parse_date_line(lines[j]):
                    break  # hit another date
                if not is_skip_line(lines[j]):
                    candidates.append(lines[j])
                j += 1

            if len(candidates) >= 2:
                venue, location = candidates[0], candidates[1]
                blocks.append((date_iso, venue, location))
            elif len(candidates) == 1:
                # Only venue found, try city lookup
                blocks.append((date_iso, candidates[0], ""))
            i = j
        else:
            i += 1
    return blocks


def make_id(artist: str, date_iso: str, city: str) -> str:
    key = f"{artist}|{date_iso}|{city}".lower()
    return hashlib.md5(key.encode()).hexdigest()[:12]


def dedup(concerts: list) -> list:
    seen: set = set()
    out = []
    for c in concerts:
        k = (c["artist"], c["date"], c["city"].lower())
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


# ── Site scrapers ───────────────────────────────────────────────────────────────

async def scrape_generic(page: Page, url: str, artist: str) -> list:
    """
    Generic scraper that works for Seated-powered pages and similar layouts.
    """
    concerts = []
    try:
        await page.goto(url, wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(3000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1500)
        text = await page.inner_text("body")

        for date_iso, venue, location in parse_blocks(text):
            loc = normalize_location(location) if location else normalize_location(venue)
            # If location was empty, try city lookup for venue name
            if not location:
                entry = CITY_LOOKUP.get(venue.lower())
                if entry:
                    loc = {"city": venue, "state": entry[0], "country": entry[1]}
                    venue = ""

            concerts.append({
                "id":         make_id(artist, date_iso, loc["city"]),
                "artist":     artist,
                "date":       date_iso,
                "city":       loc["city"],
                "state":      loc.get("state"),
                "country":    loc["country"],
                "venue":      venue,
                "source_url": url,
            })
    except Exception as e:
        print(f"[{artist}] error: {e}", file=sys.stderr)
    return concerts


# ── Dispatch ────────────────────────────────────────────────────────────────────

ARTIST_MAP = {
    "couch":                     "Couch",
    "sammy_rae_and_the_friends": "Sammy Rae & The Friends",
    "olivia_dean":               "Olivia Dean",
}


async def main() -> None:
    websites: dict[str, str] = json.loads(WEBSITES_FILE.read_text())
    all_concerts: list = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        try:
            for key, url in websites.items():
                artist = ARTIST_MAP.get(key, key.replace("_", " ").title())
                print(f"Scraping {key} ({artist}) → {url}")
                page = await context.new_page()
                try:
                    concerts = await scrape_generic(page, url, artist)
                    print(f"  → {len(concerts)} concerts found")
                    all_concerts.extend(concerts)
                except Exception as e:
                    print(f"  → failed: {e}", file=sys.stderr)
                finally:
                    await page.close()
        finally:
            await browser.close()

    all_concerts = dedup(all_concerts)
    all_concerts.sort(key=lambda c: c["date"])

    payload = {
        "scraped_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "concerts":   all_concerts,
    }
    OUTPUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nSaved {len(all_concerts)} concerts to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
