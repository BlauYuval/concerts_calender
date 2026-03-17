#!/usr/bin/env python3
"""
Reads concerts_data.json → generates concerts_calendar.html
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path

INPUT_FILE  = Path("concerts_data.json")
OUTPUT_FILE = Path("concerts_calendar.html")

# ── Country colour palette ──────────────────────────────────────────────────────
# Each entry: (border-color, background-gradient-start, pill-text-color)
COUNTRY_COLORS: dict[str, tuple[str, str, str]] = {
    "United States":    ("#3B82F6", "#1e3a5f", "#93C5FD"),
    "United Kingdom":   ("#EF4444", "#5f1e1e", "#FCA5A5"),
    "Canada":           ("#F97316", "#5f2a1e", "#FED7AA"),
    "France":           ("#818CF8", "#1e2250", "#C7D2FE"),
    "Germany":          ("#9CA3AF", "#2e2e2e", "#E5E7EB"),
    "Netherlands":      ("#FB923C", "#5f3a1e", "#FED7AA"),
    "Belgium":          ("#FBBF24", "#4a3a10", "#FDE68A"),
    "Denmark":          ("#EC4899", "#5a1040", "#FBCFE8"),
    "Norway":           ("#A78BFA", "#2a1e5f", "#DDD6FE"),
    "Sweden":           ("#60A5FA", "#1a2a4a", "#BFDBFE"),
    "Italy":            ("#34D399", "#0f3a22", "#BBF7D0"),
    "Switzerland":      ("#F87171", "#4a1010", "#FECACA"),
    "Poland":           ("#F472B6", "#4a1030", "#FBCFE8"),
    "Ireland":          ("#10B981", "#0a3a22", "#A7F3D0"),
    "Australia":        ("#0EA5E9", "#0a2a40", "#BAE6FD"),
    "New Zealand":      ("#06B6D4", "#083040", "#A5F3FC"),
    "Austria":          ("#E11D48", "#4a0a1a", "#FECDD3"),
    "Spain":            ("#FACC15", "#4a3a00", "#FEF08A"),
}
DEFAULT_COLORS = ("#6B7280", "#1e1e2a", "#D1D5DB")


def get_colors(country: str) -> tuple[str, str, str]:
    return COUNTRY_COLORS.get(country, DEFAULT_COLORS)


def format_location(concert: dict) -> str:
    parts = [concert["city"]]
    if concert.get("state"):
        parts.append(concert["state"])
    parts.append(concert["country"])
    return ", ".join(parts)


def format_date_display(date_iso: str) -> dict:
    try:
        d = date.fromisoformat(date_iso)
        return {
            "day":     d.strftime("%-d"),
            "weekday": d.strftime("%a").upper(),
            "month":   d.strftime("%b").upper(),
            "year":    str(d.year),
            "iso":     date_iso,
            "past":    d < date.today(),
        }
    except ValueError:
        return {"day": "?", "weekday": "???", "month": "???", "year": "????", "iso": date_iso, "past": False}


def build_html(scraped_at: str, concerts: list) -> str:
    today = date.today()

    # Build unique country list (ordered by first appearance)
    countries_seen: list[str] = []
    for c in concerts:
        if c["country"] not in countries_seen:
            countries_seen.append(c["country"])

    artists_seen: list[str] = []
    for c in concerts:
        if c["artist"] not in artists_seen:
            artists_seen.append(c["artist"])

    # Serialise for JS
    concerts_js = json.dumps(concerts, ensure_ascii=False)

    # Country legend items
    legend_items = ""
    for country in countries_seen:
        accent, _, pill = get_colors(country)
        legend_items += (
            f'<button class="legend-btn" data-country="{country}" '
            f'style="border-color:{accent};color:{pill}" '
            f'onclick="toggleCountry(this)">{country}</button>\n'
        )

    # Artist legend items
    artist_items = ""
    for artist in artists_seen:
        artist_items += (
            f'<button class="legend-btn artist-btn" data-artist="{artist}" '
            f'onclick="toggleArtist(this)">{artist}</button>\n'
        )

    # Country CSS vars
    country_css = ""
    for country in countries_seen:
        accent, bg, pill = get_colors(country)
        slug = country.lower().replace(" ", "-")
        country_css += (
            f'  .country-{slug} {{ '
            f'--accent: {accent}; --card-bg: {bg}; --pill-color: {pill}; }}\n'
        )

    # Scraped timestamp
    try:
        ts = datetime.strptime(scraped_at, "%Y-%m-%dT%H:%M:%SZ")
        scraped_str = ts.strftime("%-d %b %Y, %H:%M UTC")
    except Exception:
        scraped_str = scraped_at

    total = len(concerts)
    upcoming = sum(1 for c in concerts if c["date"] >= today.isoformat())

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Concert Calendar</title>
  <style>
    /* ── Reset & base ─────────────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg:       #0d0d14;
      --surface:  #15151f;
      --surface2: #1c1c29;
      --border:   #2a2a3e;
      --text:     #e8e8f4;
      --muted:    #7070a0;
      --radius:   12px;
      --font:     'Segoe UI', system-ui, -apple-system, sans-serif;
    }}

    html {{ scroll-behavior: smooth; }}

    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--font);
      min-height: 100vh;
      line-height: 1.5;
    }}

    /* ── Header ──────────────────────────────────────────── */
    .site-header {{
      position: sticky;
      top: 0;
      z-index: 100;
      background: rgba(13,13,20,0.92);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--border);
      padding: 1rem 1.5rem;
    }}

    .header-inner {{
      max-width: 1100px;
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      flex-wrap: wrap;
    }}

    .site-title {{
      font-size: 1.25rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }}

    .site-title span {{
      opacity: 0.4;
      font-weight: 400;
    }}

    .stats {{
      font-size: 0.8rem;
      color: var(--muted);
    }}

    /* ── Filters ─────────────────────────────────────────── */
    .filters {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 1rem 1.5rem;
    }}

    .filters-inner {{
      max-width: 1100px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }}

    .filter-row {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      flex-wrap: wrap;
    }}

    .filter-label {{
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--muted);
      min-width: 60px;
    }}

    .legend-btn {{
      display: inline-flex;
      align-items: center;
      padding: 0.3rem 0.75rem;
      border-radius: 999px;
      border: 1.5px solid #555;
      background: transparent;
      color: var(--text);
      font-size: 0.78rem;
      cursor: pointer;
      transition: opacity 0.15s, transform 0.1s;
      font-family: var(--font);
    }}

    .legend-btn:hover {{ opacity: 0.85; transform: translateY(-1px); }}
    .legend-btn.inactive {{ opacity: 0.25; }}

    .btn-all {{
      border-color: var(--border) !important;
      color: var(--muted) !important;
    }}

    /* ── Main ────────────────────────────────────────────── */
    .main {{
      max-width: 1100px;
      margin: 2rem auto;
      padding: 0 1.5rem 4rem;
    }}

    /* ── Month group ─────────────────────────────────────── */
    .month-group {{
      margin-bottom: 2.5rem;
    }}

    .month-heading {{
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.15em;
      color: var(--muted);
      margin-bottom: 0.75rem;
      padding-bottom: 0.5rem;
      border-bottom: 1px solid var(--border);
    }}

    .cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 0.75rem;
    }}

    /* ── Concert card ────────────────────────────────────── */
    .card {{
      --accent: #6B7280;
      --card-bg: #1e1e2a;
      --pill-color: #D1D5DB;

      display: flex;
      gap: 0.9rem;
      align-items: flex-start;
      padding: 0.9rem 1rem;
      border-radius: var(--radius);
      background: var(--card-bg);
      border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
      border-left: 3px solid var(--accent);
      transition: transform 0.15s, box-shadow 0.15s, opacity 0.2s;
      position: relative;
      overflow: hidden;
    }}

    .card::before {{
      content: '';
      position: absolute;
      inset: 0;
      background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 6%, transparent), transparent 60%);
      pointer-events: none;
    }}

    .card:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    }}

    .card.hidden {{ display: none; }}

    .card.past {{
      opacity: 0.45;
      filter: grayscale(40%);
    }}

    /* Date block */
    .card-date {{
      display: flex;
      flex-direction: column;
      align-items: center;
      min-width: 44px;
      text-align: center;
      line-height: 1;
    }}

    .card-date .weekday {{
      font-size: 0.6rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--accent);
      margin-bottom: 0.15rem;
    }}

    .card-date .day {{
      font-size: 1.6rem;
      font-weight: 800;
      color: var(--text);
      line-height: 1;
    }}

    .card-date .month-yr {{
      font-size: 0.65rem;
      color: var(--muted);
      margin-top: 0.15rem;
    }}

    /* Info block */
    .card-info {{
      flex: 1;
      min-width: 0;
    }}

    .card-artist {{
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--pill-color);
      margin-bottom: 0.25rem;
    }}

    .card-venue {{
      font-size: 0.92rem;
      font-weight: 600;
      color: var(--text);
      margin-bottom: 0.2rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    .card-location {{
      font-size: 0.78rem;
      color: var(--muted);
      display: flex;
      align-items: center;
      gap: 0.3rem;
    }}

    .card-location .flag {{
      opacity: 0.6;
      font-size: 0.9rem;
    }}

    /* ── Empty state ─────────────────────────────────────── */
    .empty-state {{
      text-align: center;
      padding: 4rem 1rem;
      color: var(--muted);
      display: none;
    }}

    .empty-state.visible {{ display: block; }}

    /* ── Footer ──────────────────────────────────────────── */
    .footer {{
      text-align: center;
      padding: 2rem;
      font-size: 0.75rem;
      color: var(--muted);
      border-top: 1px solid var(--border);
    }}

    /* ── Toggle past ─────────────────────────────────────── */
    .toggle-past {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      background: none;
      border: 1px solid var(--border);
      color: var(--muted);
      border-radius: 999px;
      padding: 0.3rem 0.75rem;
      font-size: 0.78rem;
      cursor: pointer;
      font-family: var(--font);
      transition: border-color 0.15s, color 0.15s;
    }}

    .toggle-past:hover {{ border-color: var(--muted); color: var(--text); }}
    .toggle-past.active {{ border-color: #6366f1; color: #a5b4fc; }}

    /* ── Country-specific colours ────────────────────────── */
{country_css}

    /* ── Responsive ──────────────────────────────────────── */
    @media (max-width: 600px) {{
      .site-header, .filters {{ padding: 0.75rem 1rem; }}
      .main {{ padding: 0 1rem 3rem; margin-top: 1rem; }}
      .cards-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>

<!-- Header -->
<header class="site-header">
  <div class="header-inner">
    <div class="site-title">Concert Calendar <span>/ upcoming shows</span></div>
    <div class="stats" id="stats">{upcoming} upcoming · {total} total · updated {scraped_str}</div>
  </div>
</header>

<!-- Filters -->
<div class="filters">
  <div class="filters-inner">
    <div class="filter-row">
      <span class="filter-label">Artist</span>
      <button class="legend-btn btn-all artist-btn active" data-artist="all" onclick="toggleArtist(this)">All</button>
      {artist_items}
    </div>
    <div class="filter-row">
      <span class="filter-label">Country</span>
      <button class="legend-btn btn-all active" data-country="all" onclick="toggleCountry(this)">All</button>
      {legend_items}
    </div>
    <div class="filter-row">
      <span class="filter-label">View</span>
      <button class="toggle-past active" id="btnPast" onclick="togglePast(this)">Show past shows</button>
    </div>
  </div>
</div>

<!-- Calendar -->
<main class="main" id="main"></main>

<div class="empty-state" id="emptyState">No concerts match your filters.</div>

<!-- Footer -->
<footer class="footer">
  Data scraped from official artist websites · auto-updated daily via GitHub Actions
</footer>

<script>
  const RAW = {concerts_js};

  // Country slug helper
  function slug(s) {{
    return s.toLowerCase().replace(/\\s+/g, '-').replace(/[^a-z0-9-]/g, '');
  }}

  // State
  let activeArtist  = 'all';
  let activeCountry = 'all';
  let showPast      = true;

  function countryFlag(country) {{
    const flags = {{
      'United States':  '🇺🇸', 'United Kingdom': '🇬🇧', 'Canada': '🇨🇦',
      'France': '🇫🇷', 'Germany': '🇩🇪', 'Netherlands': '🇳🇱',
      'Belgium': '🇧🇪', 'Denmark': '🇩🇰', 'Norway': '🇳🇴',
      'Sweden': '🇸🇪', 'Italy': '🇮🇹', 'Switzerland': '🇨🇭',
      'Poland': '🇵🇱', 'Ireland': '🇮🇪', 'Australia': '🇦🇺',
      'New Zealand': '🇳🇿', 'Austria': '🇦🇹', 'Spain': '🇪🇸',
    }};
    return flags[country] || '🌍';
  }}

  function formatLocation(c) {{
    let parts = [c.city];
    if (c.state) parts.push(c.state);
    parts.push(c.country);
    return parts.join(', ');
  }}

  function render() {{
    const today = new Date().toISOString().slice(0, 10);
    const main  = document.getElementById('main');
    const empty = document.getElementById('emptyState');

    const filtered = RAW.filter(c => {{
      if (!showPast && c.date < today) return false;
      if (activeArtist  !== 'all' && c.artist  !== activeArtist)  return false;
      if (activeCountry !== 'all' && c.country !== activeCountry) return false;
      return true;
    }});

    if (filtered.length === 0) {{
      main.innerHTML = '';
      empty.classList.add('visible');
      return;
    }}
    empty.classList.remove('visible');

    // Group by YYYY-MM
    const groups = {{}};
    filtered.forEach(c => {{
      const key = c.date.slice(0, 7);
      (groups[key] = groups[key] || []).push(c);
    }});

    const monthNames = [
      'January','February','March','April','May','June',
      'July','August','September','October','November','December'
    ];

    let html = '';
    for (const [ym, concerts] of Object.entries(groups).sort()) {{
      const [yr, mo] = ym.split('-');
      const heading = `${{monthNames[parseInt(mo)-1]}} ${{yr}}`;
      html += `<section class="month-group"><h2 class="month-heading">${{heading}}</h2><div class="cards-grid">`;

      concerts.forEach(c => {{
        const d = new Date(c.date + 'T12:00:00');
        const day    = d.getDate();
        const wday   = ['SUN','MON','TUE','WED','THU','FRI','SAT'][d.getDay()];
        const mon    = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'][d.getMonth()];
        const isPast = c.date < today;
        const cs     = `country-${{slug(c.country)}}`;

        html += `
          <article class="card ${{cs}}${{isPast ? ' past' : ''}}" data-artist="${{c.artist}}" data-country="${{c.country}}" data-date="${{c.date}}">
            <div class="card-date">
              <span class="weekday">${{wday}}</span>
              <span class="day">${{day}}</span>
              <span class="month-yr">${{mon}} ${{d.getFullYear()}}</span>
            </div>
            <div class="card-info">
              <div class="card-artist">${{c.artist}}</div>
              <div class="card-venue">${{c.venue || '—'}}</div>
              <div class="card-location">
                <span class="flag">${{countryFlag(c.country)}}</span>
                ${{formatLocation(c)}}
              </div>
            </div>
          </article>`;
      }});

      html += '</div></section>';
    }}

    main.innerHTML = html;

    // Update stats
    const upcoming = filtered.filter(c => c.date >= today).length;
    document.getElementById('stats').textContent =
      `${{upcoming}} upcoming · ${{filtered.length}} shown · updated {scraped_str}`;
  }}

  function toggleArtist(btn) {{
    const val = btn.dataset.artist;
    activeArtist = val;
    document.querySelectorAll('.artist-btn').forEach(b => b.classList.toggle('active', b.dataset.artist === val));
    render();
  }}

  function toggleCountry(btn) {{
    const val = btn.dataset.country;
    activeCountry = val;
    document.querySelectorAll('[data-country]').forEach(b => b.classList.toggle('active', b.dataset.country === val));
    render();
  }}

  function togglePast(btn) {{
    showPast = !showPast;
    btn.classList.toggle('active', showPast);
    render();
  }}

  // Initial render
  render();
</script>
</body>
</html>
"""
    return html


def main() -> None:
    if not INPUT_FILE.exists():
        print(f"Error: {INPUT_FILE} not found — run scraper.py first", file=sys.stderr)
        sys.exit(1)

    data = json.loads(INPUT_FILE.read_text())
    scraped_at = data.get("scraped_at", "")
    concerts   = data.get("concerts", [])

    if not concerts:
        print("Warning: no concerts in data file", file=sys.stderr)

    html = build_html(scraped_at, concerts)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Generated {OUTPUT_FILE} with {len(concerts)} concerts")


if __name__ == "__main__":
    main()
