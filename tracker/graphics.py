"""SVG output: embeddable badges and price-history charts (no dependencies)."""
from datetime import timedelta
from html import escape

from .common import parse_iso, pct

# Approximate advance widths of Verdana 11px (the shields.io badge font), in px.
_W = {c: 7.0 for c in "ABCDEFGHKNOPQRSTUVXYZ"}
_W.update({c: 6.2 for c in "abdeghnopqu0123456789$"})
_W.update({c: 5.6 for c in "ckvxyz"})
_W.update({c: 3.0 for c in "fijlrt.,:;'|!() "})
_W.update({"M": 8.6, "W": 10.0, "m": 9.7, "w": 8.2, "%": 10.8, "-": 4.4, "·": 4.2, "I": 4.2, "J": 4.6, "L": 6.0})


def text_width(s):
    return sum(_W.get(c, 6.6) for c in s)


def badge(label, value, href_title=""):
    """A two-part flat badge, like shields.io: dark label, purple value."""
    lw, vw = int(text_width(label) + 14), int(text_width(value) + 14)
    w = lw + vw
    t = escape(href_title or f"{label}: {value}")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="{t}">
<title>{t}</title>
<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
<clipPath id="r"><rect width="{w}" height="20" rx="3" fill="#fff"/></clipPath>
<g clip-path="url(#r)"><rect width="{lw}" height="20" fill="#2b2d33"/><rect x="{lw}" width="{vw}" height="20" fill="#5a3fd1"/><rect width="{w}" height="20" fill="url(#s)"/></g>
<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
<text x="{lw / 2:.1f}" y="15" fill="#010101" fill-opacity=".3">{escape(label)}</text><text x="{lw / 2:.1f}" y="14">{escape(label)}</text>
<text x="{lw + vw / 2:.1f}" y="15" fill="#010101" fill-opacity=".3">{escape(value)}</text><text x="{lw + vw / 2:.1f}" y="14">{escape(value)}</text>
</g></svg>
'''


def price_chart(series, now, days=120, width=720, height=220, title="Implied chance over time"):
    """series: [(label, css_color_var, [(datetime, price), ...]), ...] -> inline SVG, or '' if no data."""
    start = now - timedelta(days=days)
    pts_all = [(t, p) for _, _, pts in series for t, p in pts if t >= start]
    if not pts_all:
        return ""
    top = max(p for _, p in pts_all)
    ymax = 1.0 if top > 0.6 else 0.6 if top > 0.4 else 0.4 if top > 0.2 else 0.2 if top > 0.1 else 0.1
    L, R, T, B = 44, 12, 12, 26
    pw, ph = width - L - R, height - T - B
    t0 = min(t for t, _ in pts_all)
    span = max((now - t0).total_seconds(), 86400)

    def x(t):
        return L + (t - t0).total_seconds() / span * pw

    def y(p):
        return T + ph - min(p, ymax) / ymax * ph

    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
           f"<title>{escape(title)}</title>", '<g class="grid">']
    for i in range(5):
        v = ymax * i / 4
        out.append(f'<line x1="{L}" x2="{width - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>')
        out.append(f'<text x="{L - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{pct(v)}</text>')
    out.append("</g>")
    # Month ticks
    m = t0.replace(day=1, hour=0, minute=0, second=0)
    while m <= now:
        if m >= t0:
            out.append(f'<text x="{x(m):.1f}" y="{height - 8}" text-anchor="middle">{m.strftime("%b")}</text>')
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
    for label, color, pts in series:
        pts = sorted((t, p) for t, p in pts if t >= start)
        if not pts:
            continue
        d = " ".join(f"{'M' if i == 0 else 'L'}{x(t):.1f},{y(p):.1f}" for i, (t, p) in enumerate(pts))
        out.append(f'<path d="{d}" fill="none" stroke="var({color})" stroke-width="2" stroke-linejoin="round"/>')
        lt, lp = pts[-1]
        out.append(f'<circle cx="{x(lt):.1f}" cy="{y(lp):.1f}" r="3.2" fill="var({color})"><title>{escape(label)}: {pct(lp)}</title></circle>')
    out.append("</svg>")
    return "\n".join(out)


def history_points(rows, source, market, since=None):
    pts = []
    for r in rows:
        if r["source"] == source and r["market"] == market:
            t = parse_iso(r["ts"])
            if t and (since is None or t >= since):
                pts.append((t, float(r["price"])))
    return sorted(pts)
