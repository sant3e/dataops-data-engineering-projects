"""Build the annotated C1 composite image.

Output: c1_latest_available.png
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

HERE = Path(__file__).parent
SRC_LINEAGE  = HERE / "dim_mec_calendar_lineage.png"
SRC_CONSUMER = HERE / "dim_mec_calendar_tags.png"
SRC_UPSTREAM = HERE / "upstream_source_tags.png"
OUT          = HERE / "c1_latest_available.png"

# --- design constants ---
CANVAS_W   = 2200
GUTTER     = 28
PAD        = 28
BG         = (24, 26, 33, 255)
BORDER     = (255, 180, 60, 255)     # amber panel borders
LABEL_BG   = (42, 46, 56, 255)
LABEL_FG   = (235, 235, 245, 255)
RED        = (235, 60, 70, 255)      # underlines
CALL_BG    = (60, 28, 30, 235)       # dark red, semi-transparent for callout boxes
CALL_FG    = (255, 235, 235, 255)
CALL_EDGE  = (235, 60, 70, 255)

def _font(size, bold=False):
    paths = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()

FONT_TITLE = _font(34, bold=True)
FONT_LABEL = _font(22, bold=True)
FONT_CALL  = _font(19)
FONT_CALLH = _font(21, bold=True)

# ---------------------------------------------------------------------------
# 1. Annotate each source panel BEFORE resizing — so coordinates stay native
#    and lines stay crisp.
# ---------------------------------------------------------------------------

def _rect_underline(draw, box, color=RED, thickness=5, extend=6):
    """Draw a horizontal line just below the given box."""
    x0, y0, x1, y1 = box
    y = y1 + 2
    draw.line([(x0 - extend, y), (x1 + extend, y)], fill=color, width=thickness)

def _arrow(draw, a, b, color=CALL_EDGE, width=4, head=14):
    import math
    x1, y1 = a
    x2, y2 = b
    draw.line([a, b], fill=color, width=width)
    ang = math.atan2(y2 - y1, x2 - x1)
    for sign in (-1, 1):
        a2 = ang + sign * math.radians(25)
        hx = x2 - head * math.cos(a2)
        hy = y2 - head * math.sin(a2)
        draw.line([(x2, y2), (hx, hy)], fill=color, width=width)

def _callout(canvas, xy, text_lines, max_w=520, align="left"):
    """Draw a dark-red callout box with a header and body."""
    draw = ImageDraw.Draw(canvas, "RGBA")
    x, y = xy
    pad = 14
    lines = []
    for i, line in enumerate(text_lines):
        f = FONT_CALLH if i == 0 else FONT_CALL
        lines.append((line, f))
    # measure
    h_total = pad
    w_total = 0
    for text, f in lines:
        bbox = f.getbbox(text)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        w_total = max(w_total, min(max_w, tw))
        h_total += th + 6
    h_total += pad - 6
    w_total += 2 * pad
    # box
    box = (x, y, x + w_total, y + h_total)
    draw.rectangle(box, fill=CALL_BG, outline=CALL_EDGE, width=3)
    # text
    yy = y + pad
    for text, f in lines:
        draw.text((x + pad, yy), text, fill=CALL_FG, font=f)
        bbox = f.getbbox(text)
        yy += (bbox[3] - bbox[1]) + 6
    return box  # caller may want to draw an arrow from this

# ---- LINEAGE panel ----
lineage = Image.open(SRC_LINEAGE).convert("RGBA")
ld = ImageDraw.Draw(lineage)

# Approx coords for each tile's "Latest event Nh ago" row (refined from
# vertical-brightness probing of the actual image).
LATEST_ROWS = [
    # (x0, y0, x1, y1, label text for annotation)
    (349, 253, 701, 273, "stg_agoda_mec_calendar — 27h"),
    (349, 508, 701, 528, "stg_booking_mec_calendar — 2 mo"),
    (349, 768, 701, 788, "stg_priceline_mec_calendar — 2 mo"),
    (794, 508, 1146, 528, "dim_mec_calendar — 11h"),
]
for (x0, y0, x1, y1, _txt) in LATEST_ROWS:
    _rect_underline(ld, (x0, y0, x1, y1), color=RED, thickness=5, extend=4)

# Callout on the top-right of the lineage panel explaining the behaviour.
# Shifted left-of-edge so it doesn't get clipped by the panel border.
cb = _callout(
    lineage,
    (860, 120),
    [
        "Why 2-month-old upstreams are fine",
        "The downstream dim_mec_calendar is tagged latest_available —",
        "cross_partition_sensor drives it, NOT the asset daemon.",
        "Every day it materialises a fresh partition using whichever",
        "upstream partition is most recent (here: 27h old agoda).",
        "There is no time-window limit — upstreams can be arbitrarily",
        "old. Freshness of latest_available_source upstreams is policed",
        "by dbt tests + health-check sensors, not by the orchestrator.",
    ],
    max_w=560,
)

# ---- CONSUMER tags panel (dim_mec_calendar) ----
consumer = Image.open(SRC_CONSUMER).convert("RGBA")
cd = ImageDraw.Draw(consumer)

# Approx coordinates (image is 1480x540):
#   tags = [..., 'latest_available'] line inside dbt SQL: roughly y≈398, x: 108..765
#   The substring 'latest_available' sits near x: 595..763
# tag pill 'latest_available' in the right sidebar: approx (1179, 451) to (1296, 481)

TAGS_SQL_LINE   = (108, 392, 765, 418)    # full tags= line in SQL
TAG_PILL_CONSUM = (1178, 450, 1297, 482)  # 'latest_available' pill

_rect_underline(cd, TAGS_SQL_LINE, color=RED, thickness=5, extend=4)
_rect_underline(cd, TAG_PILL_CONSUM, color=RED, thickness=5, extend=4)

# Callout shifted to the right (per feedback).
callout_cons_pos = (300, 88)  # top-left of callout
cbox_cons = _callout(
    consumer,
    callout_cons_pos,
    [
        "Consumer → latest_available",
        "This tag on the downstream asset hands it to",
        "cross_partition_sensor. The asset daemon will",
        "not manage it. The sensor fires daily and uses",
        "the most recent partition of any",
        "latest_available_source upstream.",
    ],
    max_w=430,
)
# Arrow from the bottom of the callout to the tags= SQL line.
_arrow(
    cd,
    (cbox_cons[0] + (cbox_cons[2] - cbox_cons[0]) // 2, cbox_cons[3] + 4),
    ((TAGS_SQL_LINE[0] + TAGS_SQL_LINE[2]) // 2, TAGS_SQL_LINE[1] - 6),
)

# ---- UPSTREAM tags panel (stg_agoda_mec_calendar, cropped) ----
upstream = Image.open(SRC_UPSTREAM).convert("RGBA")
ud = ImageDraw.Draw(upstream)

# cropped image is 1501x573.
# From the visible layout:
#   tags= line inside SQL:  roughly y ≈ 410, x: 80..755 (contains 'latest_available_source')
#   Tag pill 'latest_available_source' in right sidebar Tags block: narrow span
#   on its own pill; approx (1020, 462) to (1205, 490). We intentionally stop
#   before x=1205 to avoid underlining the next pill.

TAGS_SQL_LINE_U   = (80, 460, 755, 488)   # full tags= line in SQL
TAG_PILL_UPSTRM   = (1147, 457, 1272, 487)  # 'latest_available_source' pill: +15 right again

_rect_underline(ud, TAGS_SQL_LINE_U, color=RED, thickness=5, extend=4)
_rect_underline(ud, TAG_PILL_UPSTRM, color=RED, thickness=5, extend=4)

# Callout centered horizontally-ish in the upstream panel (moved right).
callout_up_pos = (310, 100)
cbox_up = _callout(
    upstream,
    callout_up_pos,
    [
        "Upstream → latest_available_source",
        "Marks this upstream as 'non-exact-match'.",
        "Downstream consumers will pick its most recent",
        "partition (<= target date), regardless of how",
        "old that partition is.",
    ],
    max_w=430,
)
# Arrow from the right edge of the callout to the tag pill.
_arrow(
    ud,
    (cbox_up[2] + 4, cbox_up[1] + (cbox_up[3] - cbox_up[1]) // 2),
    (TAG_PILL_UPSTRM[0] - 6, (TAG_PILL_UPSTRM[1] + TAG_PILL_UPSTRM[3]) // 2),
)

# ---------------------------------------------------------------------------
# 2. Now assemble the composite (same layout as before, but with the
#    already-annotated panels).
# ---------------------------------------------------------------------------

inner_w = CANVAS_W - 2 * PAD
p1 = lineage.copy()
p1.thumbnail((inner_w, 10_000), Image.LANCZOS)

half_w = (inner_w - GUTTER) // 2
p2 = consumer.copy()
p2.thumbnail((half_w, 10_000), Image.LANCZOS)
p3 = upstream.copy()
p3.thumbnail((half_w, 10_000), Image.LANCZOS)

bot_h = max(p2.height, p3.height)
def _pad_to_height(img, h):
    if img.height == h:
        return img
    bg = Image.new("RGBA", (img.width, h), BG)
    bg.paste(img, (0, 0), img)
    return bg
p2 = _pad_to_height(p2, bot_h)
p3 = _pad_to_height(p3, bot_h)

HEADER_H = 82
LABEL_H  = 50
canvas_h = (
    PAD + HEADER_H
    + LABEL_H + p1.height
    + GUTTER + LABEL_H + bot_h
    + PAD
)

canvas = Image.new("RGBA", (CANVAS_W, canvas_h), BG)
d = ImageDraw.Draw(canvas)

# header
d.rectangle((PAD, PAD, CANVAS_W - PAD, PAD + HEADER_H), fill=LABEL_BG)
d.text(
    (PAD + 22, PAD + 22),
    "Scenario C1 — latest_available",
    fill=LABEL_FG, font=FONT_TITLE,
)

# panel 1 label + image
y = PAD + HEADER_H
d.rectangle((PAD, y, CANVAS_W - PAD, y + LABEL_H), fill=LABEL_BG)
d.text((PAD + 16, y + 13), "① Lineage — red underlines mark each tile's 'Latest event' row", fill=LABEL_FG, font=FONT_LABEL)
y += LABEL_H
p1x = PAD + (inner_w - p1.width) // 2
canvas.paste(p1, (p1x, y), p1)
d.rectangle((p1x - 2, y - 2, p1x + p1.width + 2, y + p1.height + 2), outline=BORDER, width=3)
y += p1.height + GUTTER

# bottom row labels
d.rectangle((PAD, y, PAD + half_w, y + LABEL_H), fill=LABEL_BG)
d.text((PAD + 16, y + 13), "② Consumer tags — dim_mec_calendar (latest_available)", fill=LABEL_FG, font=FONT_LABEL)
d.rectangle((PAD + half_w + GUTTER, y, PAD + half_w + GUTTER + half_w, y + LABEL_H), fill=LABEL_BG)
d.text((PAD + half_w + GUTTER + 16, y + 13), "③ Upstream tags — stg_*_mec_calendar (latest_available_source)", fill=LABEL_FG, font=FONT_LABEL)
y += LABEL_H

# bottom row images
canvas.paste(p2, (PAD, y), p2)
d.rectangle((PAD - 2, y - 2, PAD + p2.width + 2, y + p2.height + 2), outline=BORDER, width=3)
canvas.paste(p3, (PAD + half_w + GUTTER, y), p3)
d.rectangle((PAD + half_w + GUTTER - 2, y - 2, PAD + half_w + GUTTER + p3.width + 2, y + p3.height + 2), outline=BORDER, width=3)

canvas.convert("RGB").save(OUT, "PNG", optimize=True)
print(f"Wrote {OUT} ({canvas.size[0]}x{canvas.size[1]})")
