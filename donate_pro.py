#!/usr/bin/env python3
"""Donate Studio PRO pack — 5 premium donation-alert effects.

Large-canvas (720p landscape / square) transparent alerts: coin fountains,
radial coin explosions, money rain, a golden vortex, and a jackpot finale.
Signature pro visuals: gold coin fountains with gravity + spin + shine,
dollar-bill bursts with flutter, golden particle fields, neon glow, light
rays, screen shake + impact flash, and big golden jelly amount pop-ins.

Pillow + numpy only (no ffmpeg, no scipy, no network). Easing helpers and
the Persian font helper are imported from donate_engine (not duplicated).
"""
import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import donate_engine as _eng  # noqa: F401  (kept for export_gif reuse)
from donate_engine import (
    clamp01, ease_out, ease_in, ease_in_out,
    shake_xy, radial_glow, glow_alpha, star4,
    draw_shock, explosion_flash, make_debris, draw_debris,
    ground_shadow, _font_path, _shape_fa, _HAS_RAQM,
)


# ---------------- cancel machinery (local; mirrors donate_engine) ----------------
class _Cancelled(Exception):
    pass


_pro_cb = None
_pro_max = None


def _pro_frame_iter(F):
    total = F if not _pro_max else min(F, _pro_max)
    for f in range(total):
        if _pro_cb is not None:
            try:
                keep = _pro_cb(f, total)
            except Exception:
                keep = True
            if keep is False:
                raise _Cancelled()
        yield f


# ---------------- Persian text ----------------
def _truetype(path, px):
    try:
        if path:
            return ImageFont.truetype(path, max(8, int(px)))
    except Exception:
        pass
    return ImageFont.load_default()


# B Nazanin lacks U+066C (ARABIC THOUSANDS SEPARATOR ٬) — it renders as
# tofu. Normalize it to U+060C (،) which the font does have.
_SEP_FIX = str.maketrans({"٬": "،"})


def _clean(text):
    return text.translate(_SEP_FIX) if text else text


def _draw_rtl(d, xy, text, font, fill, stroke_width=0, stroke_fill=None):
    text = _clean(text)
    kw = {}
    if stroke_width:
        kw = {"stroke_width": stroke_width, "stroke_fill": stroke_fill}
    if _HAS_RAQM:
        d.text(xy, text, font=font, fill=fill, anchor="mm",
               direction="rtl", **kw)
    else:
        d.text(xy, _shape_fa(text), font=font, fill=fill,
               anchor="mm", **kw)


def _text_size(text, font, stroke_width=0):
    text = _clean(text)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8), (0, 0, 0, 0)))
    kw = {"stroke_width": stroke_width} if stroke_width else {}
    if _HAS_RAQM:
        bb = probe.textbbox((0, 0), text, font=font, direction="rtl", **kw)
    else:
        bb = probe.textbbox((0, 0), _shape_fa(text), font=font, **kw)
    return bb[2] - bb[0], bb[3] - bb[1]


def _jelly(t):
    """Elastic pop-in scale: 0 before trigger, overshoots, settles at 1."""
    if t <= 0:
        return 0.0
    return ease_out(clamp01(t / 0.28)) * (
        1 + 0.30 * math.exp(-3.2 * t) * math.cos(2 * math.pi * 3.0 * t))


def _slam(t):
    """Banner slam: starts huge, elastic-settles at 1."""
    if t <= 0:
        return 0.0
    return 1 + 0.9 * math.exp(-3.5 * t) * math.cos(2 * math.pi * 2.8 * t)


def _jelly_text(base, cx, cy, text, fp, px, scale, color, stroke,
                glow_color=None, alpha=255):
    """Big centered text tile, scaled by an elastic pop factor."""
    if scale <= 0.01 or not text:
        return
    font = _truetype(fp, px)
    tw, th = _text_size(text, font, stroke_width=2)
    pad = int(px * 0.55) + 10
    tile = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    _draw_rtl(td, (tile.width / 2, tile.height / 2), text, font,
              color + (alpha,), stroke_width=2,
              stroke_fill=stroke + (alpha,))
    if glow_color is not None:
        g = glow_alpha(radial_glow(max(tile.width, tile.height),
                                   glow_color, 110), 0.55)
        base.alpha_composite(g, (int(cx - g.width / 2), int(cy - g.height / 2)))
    nw, nh = max(1, int(tile.width * scale)), max(1, int(tile.height * scale))
    tile = tile.resize((nw, nh), Image.LANCZOS)
    base.alpha_composite(tile, (int(cx - nw / 2), int(cy - nh / 2)))


# ---------------- amount helpers (Persian digits) ----------------
_FA_D = "۰۱۲۳۴۵۶۷۸۹"
_DIGIT_MAP = {}
for _a, _b in zip("0123456789", "0123456789"):
    _DIGIT_MAP[_a] = _b
for _i, _c in enumerate("۰۱۲۳۴۵۶۷۸۹"):
    _DIGIT_MAP[_c] = str(_i)
for _i, _c in enumerate("٠١٢٣٤٥٦٧٨٩"):
    _DIGIT_MAP[_c] = str(_i)


def _parse_amount(text):
    """Split e.g. '۱۰۰٬۰۰۰ تومان' -> (100000, 'تومان')."""
    digit_chars = set(_DIGIT_MAP) | set("٬, ")
    n = len(text)
    i = 0
    while i < n and text[i] not in digit_chars:
        i += 1
    j = i
    while j < n and text[j] in digit_chars:
        j += 1
    run = text[i:j]
    val = "".join(_DIGIT_MAP.get(c, "") for c in run)
    val = "".join(c for c in val if c.isdigit())
    if not val:
        return None, text.strip()
    return int(val), text[j:].strip()


def _fa_num(n):
    s = str(int(round(n)))
    grp = []
    while len(s) > 3:
        grp.append(s[-3:])
        s = s[:-3]
    grp.append(s)
    s = "،".join(reversed(grp))  # U+060C: U+066C is missing from B Nazanin
    return "".join(_FA_D[int(c)] if c.isdigit() else c for c in s)


# ---------------- draw primitives ----------------
def _new(w, h):
    return Image.new("RGBA", (w, h), (0, 0, 0, 0))


def _finish(img, f, F, amp):
    """Apply screen shake and return the final frame."""
    fin = _new(*img.size)
    sx, sy = shake_xy(f, F, amp)
    fin.alpha_composite(img, (sx, sy))
    return fin


def _rays(base, cx, cy, R, angle, n, color, alpha, blur=6, fade=1.0):
    """Rotating translucent light-ray wedges from (cx, cy)."""
    a = int(alpha * clamp01(fade))
    if a <= 0:
        return
    ov = _new(*base.size)
    d = ImageDraw.Draw(ov)
    hw = math.pi * 0.055
    for i in range(n):
        a0 = angle + i * 2 * math.pi / n
        d.polygon([(cx, cy),
                   (cx + R * math.cos(a0 - hw), cy + R * math.sin(a0 - hw)),
                   (cx + R * math.cos(a0 + hw), cy + R * math.sin(a0 + hw))],
                  fill=color + (a,))
    if blur:
        ov = ov.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(ov)


def _draw_coin(d, x, y, r, spin, alpha=255, shine=1.0):
    """Golden coin: darker rim, golden face, lighter inner, specular dot.
    `spin` squeezes the x-axis to fake a 3D coin flip."""
    sx = max(0.18, abs(math.cos(spin)))
    w, h = r * 2 * sx, r * 2
    if w < 2.5 or h < 2.5:
        return
    d.ellipse([x - w / 2, y - h / 2, x + w / 2, y + h / 2],
              fill=(176, 118, 22, alpha))
    m = min(max(1.0, r * 0.16), (w - 1) / 2, (h - 1) / 2)
    if m >= 0.5:
        d.ellipse([x - w / 2 + m, y - h / 2 + m,
                   x + w / 2 - m, y + h / 2 - m],
                  fill=(255, 205, 70, alpha))
        iw, ih = (w - 2 * m) * 0.62, (h - 2 * m) * 0.62
        if iw > 1 and ih > 1:
            d.ellipse([x - iw / 2, y - ih / 2, x + iw / 2, y + ih / 2],
                      fill=(255, 232, 150, alpha))
    if shine > 0 and sx > 0.4:
        sw, sh = w * 0.28, h * 0.26
        if sw > 1 and sh > 1:
            sox, soy = -w * 0.16, -h * 0.20
            d.ellipse([x + sox - sw / 2, y + soy - sh / 2,
                       x + sox + sw / 2, y + soy + sh / 2],
                      fill=(255, 255, 255, int(235 * shine * alpha / 255)))


_bill_cache = {}


def _bill_tile(sc):
    """Pre-rendered dollar-bill sprite (green, darker border, $ oval)."""
    key = round(sc, 2)
    if key in _bill_cache:
        return _bill_cache[key]
    bw, bh = int(120 * sc), int(60 * sc)
    pad = int(16 * sc) + 6
    tile = _new(bw + pad * 2, bh + pad * 2)
    d = ImageDraw.Draw(tile)
    x0, y0 = pad, pad
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=int(9 * sc),
                        fill=(46, 160, 67, 255),
                        outline=(18, 92, 38, 255), width=max(2, int(3 * sc)))
    ow, oh = bw * 0.44, bh * 0.64
    d.ellipse([x0 + bw / 2 - ow / 2, y0 + bh / 2 - oh / 2,
               x0 + bw / 2 + ow / 2, y0 + bh / 2 + oh / 2],
              fill=(216, 242, 216, 255), outline=(18, 92, 38, 255), width=2)
    try:
        fnt = ImageFont.load_default(size=max(10, int(28 * sc)))
    except Exception:
        fnt = ImageFont.load_default()
    d.text((x0 + bw / 2, y0 + bh / 2), "$", font=fnt,
           fill=(18, 92, 38, 255), anchor="mm")
    _bill_cache[key] = tile
    return tile


def _draw_bill(base, tile, x, y, rot_deg, flutter, alpha=255):
    """Bill with flutter (y-squash wobble) and rotation."""
    t2 = tile
    if abs(flutter - 1.0) > 0.02:
        t2 = t2.resize((t2.width, max(1, int(t2.height * flutter))),
                       Image.BICUBIC)
    if abs(rot_deg) > 0.5:
        t2 = t2.rotate(rot_deg, resample=Image.BICUBIC, expand=True)
    if alpha < 255:
        t2 = t2.copy()
        a = t2.getchannel("A").point(lambda v: int(v * alpha / 255))
        t2.putalpha(a)
    base.alpha_composite(t2, (int(x - t2.width / 2), int(y - t2.height / 2)))


def _place_avatar(base, av, asp, cx, cy, h, angle=0.0, alpha=1.0):
    w = max(1, int(h * asp))
    s = av.resize((w, max(1, int(h))), Image.LANCZOS)
    if abs(angle) > 0.01:
        s = s.rotate(angle, resample=Image.BICUBIC, expand=True)
    if alpha < 1.0:
        a = s.getchannel("A").point(lambda v: int(v * alpha))
        s.putalpha(a)
    base.alpha_composite(s, (int(cx - s.width / 2), int(cy - s.height / 2)))


def _coin_state(c, t):
    """Fountain-coin physics: erupt with gravity. Returns (x, y, spin, alpha)
    or None when the coin is dead."""
    age = t - c["t0"]
    if age < 0 or age > c["life"]:
        return None
    x = c["x0"] + c["vx"] * age
    y = c["y0"] + c["vy"] * age + 0.5 * c["g"] * age * age
    spin = c["spin"] + c["spin_spd"] * age
    a = int(255 * clamp01(age / 0.08) * clamp01((c["life"] - age) / 0.35))
    return x, y, spin, a


# ================================================================
# PRO 1 — Coin Fountain «فواره سکه»
# ================================================================
def _fx_fountain(F, fps, av, asp, name, amount, w, h, fp, seed):
    rng = random.Random(seed + 101)
    sc = min(w, h) / 360.0
    cx = w / 2
    g = 1750 * sc
    coins = []
    for i in range(64):
        coins.append(dict(
            t0=rng.uniform(0, 2.1), life=rng.uniform(1.2, 1.7),
            x0=cx + rng.uniform(-30, 30) * sc, y0=h - 20 * sc,
            vx=rng.uniform(-280, 280) * sc, vy=-rng.uniform(760, 1160) * sc,
            g=g, r=rng.uniform(13, 23) * sc,
            spin=rng.uniform(0, 6.28),
            spin_spd=rng.uniform(6, 14) * (1 if rng.random() < 0.5 else -1),
            front=(i % 3 == 0)))
    glow_gold = radial_glow(int(min(w, h) * 1.15), (255, 190, 80), 120)
    glow_av = radial_glow(int(min(w, h) * 0.9), (255, 205, 110), 130)
    av_h = int(h * 0.42)
    amt_px = int(min(w, h) / 6.5)
    name_px = int(min(w, h) / 11)
    frames = []
    for f in _pro_frame_iter(F):
        t = f / fps
        img = _new(w, h)
        d = ImageDraw.Draw(img)
        _rays(img, cx, h * 0.55, max(w, h) * 0.75, t * 0.35, 12,
              (255, 200, 110), 26, fade=t / 0.3)
        img.alpha_composite(
            glow_alpha(glow_gold, 0.5 + 0.25 * math.sin(2 * math.pi * 1.5 * t)),
            (int(cx - glow_gold.width / 2), int(h - glow_gold.height * 0.78)))
        for c in coins:
            if c["front"]:
                continue
            st = _coin_state(c, t)
            if st:
                _draw_coin(d, st[0], st[1], c["r"], st[2], alpha=st[3])
        rise = ease_out(clamp01(t / 0.85))
        ay = ((h + av_h * 0.6) - (h + av_h * 0.6 - h * 0.50) * rise
              + 8 * math.sin(2 * math.pi * 1.2 * t) * rise)
        img.alpha_composite(
            glow_alpha(glow_av, 0.55 * rise * (0.8 + 0.2 * math.sin(2 * math.pi * 2 * t))),
            (int(cx - glow_av.width / 2), int(ay - glow_av.height / 2)))
        if rise > 0.01:
            _place_avatar(img, av, asp, cx, ay, int(av_h * (0.9 + 0.1 * rise)))
            ground_shadow(img, cx, h - 8, max(0, h - ay))
        for c in coins:
            if not c["front"]:
                continue
            st = _coin_state(c, t)
            if st:
                _draw_coin(d, st[0], st[1], c["r"], st[2], alpha=st[3])
        if name:
            _jelly_text(img, cx, h * 0.085, name, fp, name_px,
                        _jelly(t - 0.85), (255, 255, 255), (90, 60, 10))
        if amount:
            _jelly_text(img, cx, h * 0.20, amount, fp, amt_px,
                        _jelly(t - 1.05), (255, 205, 80), (150, 95, 20),
                        glow_color=(255, 190, 80))
        frames.append(_finish(img, f, F, 2))
    return frames


# PRO 2 — Coin Explosion «انفجار سکه»
# ================================================================
def _banner_tile(name, amount, fp, w, h):
    f1 = _truetype(fp, int(min(w, h) / 10))
    f2 = _truetype(fp, int(min(w, h) / 7.5))
    t1w, t1h = _text_size(name or " ", f1, stroke_width=2)
    t2w, t2h = _text_size(amount or " ", f2, stroke_width=2)
    bw = max(int(w * 0.5), max(t1w, t2w) + 90)
    bh = t1h + t2h + 80
    tile = _new(bw, bh)
    d = ImageDraw.Draw(tile)
    d.rounded_rectangle([0, 0, bw, bh], radius=26,
                        fill=(14, 16, 28, 222),
                        outline=(255, 200, 90, 255), width=4)
    cy = 40 + t1h / 2
    if name:
        _draw_rtl(d, (bw / 2, cy), name, f1, (255, 255, 255, 255),
                  stroke_width=2, stroke_fill=(60, 40, 10, 255))
    if amount:
        _draw_rtl(d, (bw / 2, cy + t1h / 2 + 14 + t2h / 2), amount, f2,
                  (255, 205, 80, 255), stroke_width=2,
                  stroke_fill=(150, 95, 20, 255))
    return tile


def _fx_explosion(F, fps, av, asp, name, amount, w, h, fp, seed):
    rng = random.Random(seed + 202)
    sc = min(w, h) / 360.0
    cx, cy = w / 2, h * 0.52
    t0 = 0.35
    coins = []
    for _ in range(46):
        ang = rng.uniform(0, 6.283)
        coins.append(dict(ang=ang, spd=rng.uniform(320, 950) * sc,
                          r=rng.uniform(12, 22) * sc,
                          spin=rng.uniform(0, 6.28),
                          spin_spd=rng.uniform(8, 18),
                          drag=rng.uniform(1.8, 2.8)))
    sparks = [dict(x=cx + rng.uniform(-40, 40) * sc,
                   y0=cy, vy=-rng.uniform(150, 420) * sc,
                   t0=t0 + rng.uniform(0, 0.5), life=rng.uniform(0.8, 1.3),
                   s=rng.uniform(4, 9) * sc, ph=rng.uniform(0, 6.28))
              for _ in range(20)]
    debris = make_debris(70, cx, cy, (160, 520), seed + 209)
    glow_c = radial_glow(int(min(w, h) * 0.9), (255, 205, 110), 140)
    banner = _banner_tile(name, amount, fp, w, h) if (name or amount) else None
    av_h = int(h * 0.44)
    frames = []
    for f in _pro_frame_iter(F):
        t = f / fps
        img = _new(w, h)
        d = ImageDraw.Draw(img)
        img.alpha_composite(glow_alpha(glow_c, 0.25),
                            (int(cx - glow_c.width / 2),
                             int(cy - glow_c.height / 2)))
        dt = t - t0
        # radial coin burst with drag
        if dt > 0:
            for c in coins:
                dist = c["spd"] * (1 - math.exp(-c["drag"] * dt)) / c["drag"]
                a = clamp01((1.8 - dt) / 0.6)
                if a <= 0:
                    continue
                x = cx + dist * math.cos(c["ang"])
                y = cy + dist * math.sin(c["ang"]) * 0.8
                _draw_coin(d, x, y, c["r"], c["spin"] + c["spin_spd"] * dt,
                           alpha=int(255 * a))
            # rising gold sparks
            for s in sparks:
                age = t - s["t0"]
                if 0 <= age < s["life"]:
                    y = s["y0"] + s["vy"] * age
                    tw = 0.5 + 0.5 * math.sin(s["ph"] + t * 14)
                    star4(d, s["x"], y, s["s"] * (0.6 + 0.4 * tw),
                          (255, 200, 90, int(255 * (1 - age / s["life"]))))
            draw_debris(d, debris, dt, grav=700 * sc, life=1.4)
            # shockwaves + white-gold flash
            for k, off in enumerate((0, 0.09, 0.18)):
                draw_shock(d, cx, cy, dt - off, 0.45,
                           min(w, h) * (0.5 - k * 0.08),
                           (255, 225, 160), 9 - k * 2)
            fl = explosion_flash(int(min(w, h) * 1.15), dt, life=0.5,
                                 tint=(255, 240, 205))
            if fl:
                img.alpha_composite(
                    fl, (int(cx - fl.width / 2), int(cy - fl.height / 2)))
        # avatar slams in with the impact
        js = _jelly(dt - 0.05)
        if js > 0.01:
            img.alpha_composite(
                glow_alpha(glow_c, 0.7 * js),
                (int(cx - glow_c.width / 2), int(cy - glow_c.height / 2)))
            _place_avatar(img, av, asp, cx, h * 0.66, int(av_h * js))
            ground_shadow(img, cx, h - 8, 0)
        # name/amount banner slams in with bounce
        if banner is not None:
            s = _slam(dt - 0.12)
            if s > 0.01:
                nw = max(1, int(banner.width * s))
                nh = max(1, int(banner.height * s))
                b = banner.resize((nw, nh), Image.LANCZOS)
                img.alpha_composite(b, (int(cx - nw / 2),
                                       int(h * 0.26 - nh / 2)))
        amp = 2 + (13 * math.exp(-2.8 * dt) if dt > 0 else 0)
        frames.append(_finish(img, f, F, amp))
    return frames


# ================================================================
# PRO 3 — Money Rain «باران اسکناس»
# ================================================================
def _fx_rain(F, fps, av, asp, name, amount, w, h, fp, seed):
    rng = random.Random(seed + 303)
    sc = min(w, h) / 360.0
    cx = w / 2
    tile = _bill_tile(sc)
    bills = [dict(x0=rng.uniform(0, w), y0=rng.uniform(-140, -30),
                  enter=rng.uniform(0, 1.2),
                  spd=rng.uniform(150, 280) * sc,
                  sway=rng.uniform(30, 80), ph=rng.uniform(0, 6.28),
                  rot_amp=rng.uniform(15, 35), ph2=rng.uniform(0, 6.28),
                  ph3=rng.uniform(0, 6.28), front=(i < 4))
             for i in range(16)]
    _BILL_SPAN = h + 260  # fall distance before respawning above screen
    sparks = [dict(x=rng.uniform(20, w - 20), y0=rng.uniform(0, h + 160),
                   spd=rng.uniform(60, 160) * sc,
                   s=rng.uniform(4, 9) * sc, ph=rng.uniform(0, 6.28))
              for _ in range(26)]
    glow_c = radial_glow(int(min(w, h) * 0.9), (120, 220, 140), 90)
    av_h = int(h * 0.40)
    val, suffix = _parse_amount(amount) if amount else (None, "")
    amt_px = int(min(w, h) / 6)
    name_px = int(min(w, h) / 12)
    frames = []
    for f in _pro_frame_iter(F):
        t = f / fps
        img = _new(w, h)
        d = ImageDraw.Draw(img)
        _rays(img, cx, h * 0.4, max(w, h) * 0.7, -t * 0.25, 10,
              (200, 255, 200), 20, fade=t / 0.4)
        img.alpha_composite(glow_alpha(glow_c, 0.35),
                            (int(cx - glow_c.width / 2),
                             int(h * 0.55 - glow_c.height / 2)))

        def _bill_pos(b):
            tt = max(0.0, t - b["enter"])
            yy = b["y0"] + b["spd"] * tt
            if yy > h + 120:  # recycle above the screen (yy-h-120 >= 0)
                yy = -140 + ((yy - h - 120) % _BILL_SPAN)
            xx = b["x0"] + b["sway"] * math.sin(2 * math.pi * 0.5 * t + b["ph"])
            rot = b["rot_amp"] * math.sin(2 * math.pi * 0.7 * t + b["ph2"])
            fl = 1 + 0.25 * math.sin(2 * math.pi * 3 * t + b["ph3"])
            return xx, yy, rot, fl

        for b in bills:  # back bills
            if b["front"]:
                continue
            x, y, rot, fl = _bill_pos(b)
            if -80 < y < h + 80:
                _draw_bill(img, tile, x, y, rot, fl)
        # avatar floats in
        fade = ease_out(clamp01(t / 0.4))
        ay = h * 0.70 + 10 * math.sin(2 * math.pi * 1.1 * t)
        if fade > 0.01:
            _place_avatar(img, av, asp, cx, ay, av_h, alpha=fade)
        for b in bills:  # front bills
            if not b["front"]:
                continue
            x, y, rot, fl = _bill_pos(b)
            if -80 < y < h + 80:
                _draw_bill(img, tile, x, y, rot, fl)
        # rising coin sparkles
        for s in sparks:
            yy = h + 20 - ((s["y0"] + s["spd"] * t) % (h + 160))
            tw = 0.5 + 0.5 * math.sin(s["ph"] + t * 12)
            star4(d, s["x"], yy, s["s"] * (0.5 + 0.5 * tw),
                  (255, 200, 90, int(235 * tw)))
        # name fades in; amount counts up, big and golden
        if name:
            a = int(255 * ease_out(clamp01(t / 0.5)))
            if a > 0:
                font = _truetype(fp, name_px)
                _draw_rtl(d, (cx, h * 0.06), name, font,
                          (255, 255, 255, a), stroke_width=2,
                          stroke_fill=(40, 60, 40, a))
        if amount:
            if val is None:
                shown = amount
            else:
                shown = _fa_num(val * ease_out(clamp01(t / 2.6)))
                if suffix:
                    shown += " " + suffix
            _jelly_text(img, cx, h * 0.16, shown, fp, amt_px,
                        _jelly(t - 0.15), (255, 205, 80), (150, 95, 20),
                        glow_color=(255, 190, 80))
        frames.append(_finish(img, f, F, 1.5))
    return frames


# ================================================================
# PRO 4 — Golden Vortex «گردباد طلایی»
# ================================================================
def _fx_vortex(F, fps, av, asp, name, amount, w, h, fp, seed):
    rng = random.Random(seed + 404)
    sc = min(w, h) / 360.0
    cx, cy = w / 2, h * 0.52
    conv = 1.5  # convergence moment (s)
    R0 = min(w, h) * 0.46
    coins = [dict(th0=rng.uniform(0, 6.283),
                  direction=1 if rng.random() < 0.5 else -1,
                  r=rng.uniform(12, 20) * sc,
                  out_spd=rng.uniform(200, 600) * sc)
             for _ in range(44)]

    def _spiral_angle(c, t):
        return c["th0"] + c["direction"] * (2.8 * t + 3.2 * t * t / conv)

    glow_c = radial_glow(int(min(w, h) * 1.0), (255, 195, 90), 140)
    av_h = int(h * 0.44)
    amt_px = int(min(w, h) / 6.5)
    name_px = int(min(w, h) / 11)
    frames = []
    for f in _pro_frame_iter(F):
        t = f / fps
        img = _new(w, h)
        d = ImageDraw.Draw(img)
        burst = math.exp(-2.0 * max(0.0, t - conv)) if t >= conv else 0.0
        _rays(img, cx, cy, max(w, h) * 0.7, t * 3.0, 14, (255, 200, 110),
              44 if t < conv else int(44 * burst), fade=clamp01(t / 0.25))
        img.alpha_composite(glow_alpha(glow_c, 0.30 + 0.55 * burst),
                            (int(cx - glow_c.width / 2),
                             int(cy - glow_c.height / 2)))
        for c in coins:
            if t < conv:
                p = t / conv
                r = R0 * (1 - ease_in_out(p))
                th = _spiral_angle(c, t)
                x = cx + r * math.cos(th)
                y = cy + r * 0.62 * math.sin(th)
                a = 255
            else:
                age = t - conv
                th = _spiral_angle(c, conv)
                dist = (c["out_spd"] * (1 - math.exp(-2.2 * age)) / 2.2
                        + R0 * 0.06)
                x = cx + dist * math.cos(th)
                y = cy + dist * math.sin(th) * 0.8
                a = int(255 * clamp01((1.2 - age) / 0.5))
                if a <= 0:
                    continue
            _draw_coin(d, x, y, c["r"], t * 10, alpha=a)
        if t >= conv:
            draw_shock(d, cx, cy, t - conv, 0.45, min(w, h) * 0.5,
                       (255, 220, 150), 9)
            fl = explosion_flash(int(min(w, h) * 0.8), t - conv, life=0.4,
                                 tint=(255, 220, 150))
            if fl:
                img.alpha_composite(
                    fl, (int(cx - fl.width / 2), int(cy - fl.height / 2)))
        # avatar scales up with the convergence burst
        js = _jelly(t - (conv - 0.2))
        if js > 0.01:
            _place_avatar(img, av, asp, cx, h * 0.66, int(av_h * js))
            ground_shadow(img, cx, h - 8, 0)
        if name:
            _jelly_text(img, cx, h * 0.085, name, fp, name_px,
                        _jelly(t - (conv + 0.1)), (255, 255, 255),
                        (90, 60, 10))
        if amount:
            _jelly_text(img, cx, h * 0.20, amount, fp, amt_px,
                        _jelly(t - (conv + 0.25)), (255, 205, 80),
                        (150, 95, 20), glow_color=(255, 190, 80))
        amp = 2 + (9 * math.exp(-3 * (t - conv)) if t >= conv else 0)
        frames.append(_finish(img, f, F, amp))
    return frames


# ================================================================
# PRO 5 — Jackpot «جکپات» (everything at once)
# ================================================================
def _fx_jackpot(F, fps, av, asp, name, amount, w, h, fp, seed):
    rng = random.Random(seed + 505)
    sc = min(w, h) / 360.0
    cx = w / 2
    t1, t2 = 1.0, 2.7  # impact moments
    g = 1750 * sc
    coins = [dict(t0=rng.uniform(0, 2.8), life=rng.uniform(1.2, 1.7),
                  x0=cx + rng.uniform(-40, 40) * sc, y0=h - 20 * sc,
                  vx=rng.uniform(-300, 300) * sc,
                  vy=-rng.uniform(760, 1160) * sc, g=g,
                  r=rng.uniform(13, 23) * sc, spin=rng.uniform(0, 6.28),
                  spin_spd=rng.uniform(6, 14), front=(i % 3 == 0))
             for i in range(44)]
    tile = _bill_tile(sc)
    bills = [dict(x0=rng.uniform(0, w), y0=rng.uniform(-140, -30),
                  enter=rng.uniform(0, 1.2),
                  spd=rng.uniform(150, 280) * sc,
                  sway=rng.uniform(30, 80), ph=rng.uniform(0, 6.28),
                  rot_amp=rng.uniform(15, 35), ph2=rng.uniform(0, 6.28),
                  ph3=rng.uniform(0, 6.28), front=(i < 3))
             for i in range(12)]
    _BILL_SPAN = h + 260

    def _bill_pos(b, t):
        tt = max(0.0, t - b["enter"])
        yy = b["y0"] + b["spd"] * tt
        if yy > h + 120:
            yy = -140 + ((yy - h - 120) % _BILL_SPAN)
        xx = b["x0"] + b["sway"] * math.sin(2 * math.pi * 0.5 * t + b["ph"])
        rot = b["rot_amp"] * math.sin(2 * math.pi * 0.7 * t + b["ph2"])
        fl = 1 + 0.25 * math.sin(2 * math.pi * 3 * t + b["ph3"])
        return xx, yy, rot, fl
    parts = [dict(x=rng.uniform(20, w - 20), y0=rng.uniform(0, h + 200),
                  spd=rng.uniform(50, 150) * sc,
                  r=rng.uniform(2, 4.5) * sc, ph=rng.uniform(0, 6.28))
             for _ in range(60)]
    glow_c = radial_glow(int(min(w, h) * 1.1), (255, 195, 90), 130)
    av_h = int(h * 0.42)
    amt_px = int(min(w, h) / 5.5)
    name_px = int(min(w, h) / 11)
    frames = []
    for f in _pro_frame_iter(F):
        t = f / fps
        img = _new(w, h)
        d = ImageDraw.Draw(img)
        _rays(img, cx, h * 0.5, max(w, h) * 0.8, t * 0.45, 16,
              (255, 200, 110), 30, fade=t / 0.5)
        img.alpha_composite(
            glow_alpha(glow_c, 0.45 + 0.2 * math.sin(2 * math.pi * 2 * t)),
            (int(cx - glow_c.width / 2), int(h * 0.55 - glow_c.height / 2)))
        # gold particle field
        for p in parts:
            yy = h + 20 - ((p["y0"] + p["spd"] * t) % (h + 200))
            tw = 0.5 + 0.5 * math.sin(p["ph"] + t * 9)
            d.ellipse([p["x"] - p["r"], yy - p["r"], p["x"] + p["r"],
                       yy + p["r"]],
                      fill=(255, 205, 110, int(200 * tw)))
        # back bills + back coins
        for b in bills:
            if b["front"]:
                continue
            xx, yy, rot, fl = _bill_pos(b, t)
            if -80 < yy < h + 80:
                _draw_bill(img, tile, xx, yy, rot, fl)
        for c in coins:
            if c["front"]:
                continue
            st = _coin_state(c, t)
            if st:
                _draw_coin(d, st[0], st[1], c["r"], st[2], alpha=st[3])
        # avatar rises
        rise = ease_out(clamp01((t - 0.4) / 0.8))
        ay = ((h + av_h * 0.6) - (h + av_h * 0.6 - h * 0.50) * rise
              + 8 * math.sin(2 * math.pi * 1.2 * t) * rise)
        if rise > 0.01:
            _place_avatar(img, av, asp, cx, ay, int(av_h * (0.9 + 0.1 * rise)))
            ground_shadow(img, cx, h - 8, max(0, h - ay))
        # front coins + front bills
        for c in coins:
            if not c["front"]:
                continue
            st = _coin_state(c, t)
            if st:
                _draw_coin(d, st[0], st[1], c["r"], st[2], alpha=st[3])
        for b in bills:
            if not b["front"]:
                continue
            xx, yy, rot, fl = _bill_pos(b, t)
            if -80 < yy < h + 80:
                _draw_bill(img, tile, xx, yy, rot, fl)
        # impacts: shockwaves + flash
        for ti, big in ((t1, True), (t2, False)):
            dt = t - ti
            if dt > 0:
                draw_shock(d, cx, h * 0.5, dt, 0.45,
                           min(w, h) * (0.5 if big else 0.35),
                           (255, 225, 160), 9)
                if big:
                    fl = explosion_flash(int(min(w, h) * 1.1), dt, life=0.5,
                                         tint=(255, 235, 190))
                    if fl:
                        img.alpha_composite(
                            fl, (int(cx - fl.width / 2),
                                 int(h * 0.5 - fl.height / 2)))
        # big golden amount + name
        if amount:
            _jelly_text(img, cx, h * 0.20, amount, fp, amt_px,
                        _jelly(t - 1.25), (255, 205, 80), (150, 95, 20),
                        glow_color=(255, 190, 80))
        if name:
            _jelly_text(img, cx, h * 0.085, name, fp, name_px,
                        _jelly(t - 1.45), (255, 255, 255), (90, 60, 10))
        amp = (3 + (12 * math.exp(-2.5 * (t - t1)) if t > t1 else 0)
               + (7 * math.exp(-2.5 * (t - t2)) if t > t2 else 0))
        frames.append(_finish(img, f, F, amp))
    return frames


# ================================================================
# registry + public render API
# ================================================================
_FX = {
    "pro_fountain": (_fx_fountain, 120, 30),
    "pro_explosion": (_fx_explosion, 120, 30),
    "pro_rain": (_fx_rain, 120, 30),
    "pro_vortex": (_fx_vortex, 120, 30),
    "pro_jackpot": (_fx_jackpot, 150, 30),
}

# (id, Persian name, native frame count, native fps)
EFFECTS = [
    ("pro_fountain", "فواره سکه", 120, 30),
    ("pro_explosion", "انفجار سکه", 120, 30),
    ("pro_rain", "باران اسکناس", 120, 30),
    ("pro_vortex", "گردباد طلایی", 120, 30),
    ("pro_jackpot", "جکپات", 150, 30),
]

EFFECT_IDS = [e[0] for e in EFFECTS]


def effect_info(effect_id):
    for eid, fa, nframes, nfps in EFFECTS:
        if eid == effect_id:
            return {"id": eid, "fa_name": fa, "frames": nframes, "fps": nfps}
    raise ValueError("unknown effect: %r" % (effect_id,))


def render_frames(effect_id, avatar, name="", amount="", size=(1280, 720),
                  fps=30, seed=11, on_frame=None, max_frames=None,
                  font_path=None):
    """Render transparent RGBA frames for a PRO effect.

    Effects render natively at the requested canvas: `size` may be a
    (width, height) tuple (e.g. (1280, 720) landscape, (720, 720) square)
    or an int for a square canvas. `fps` is kept for API compatibility
    (used by export_gif, not here). Returns a list of PIL RGBA images,
    or None if cancelled via on_frame. Not reentrant.
    """
    global _pro_cb, _pro_max
    if effect_id not in _FX:
        raise ValueError("unknown effect: %r" % (effect_id,))
    if isinstance(size, (tuple, list)):
        w, h = int(size[0]), int(size[1])
    else:
        w = h = int(size)
    if w < 64 or h < 64:
        raise ValueError("canvas too small: %r" % (size,))
    func, F, _native_fps = _FX[effect_id]
    av = avatar.convert("RGBA")
    asp = av.width / max(1, av.height)
    fp = _font_path(font_path)
    random.seed(seed)
    np.random.seed(seed)
    _pro_cb, _pro_max = on_frame, max_frames
    try:
        frames = func(F, _native_fps, av, asp, name, amount, w, h, fp, seed)
    except _Cancelled:
        return None
    finally:
        _pro_cb, _pro_max = None, None
    return frames


__all__ = ["EFFECTS", "EFFECT_IDS", "effect_info", "render_frames",
           "_parse_amount", "_fa_num"]
