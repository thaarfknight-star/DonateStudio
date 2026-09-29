#!/usr/bin/env python3
"""Donate Studio engine \u2014 8 procedural transparent donation-alert effects.

Refactored from donate-gifs/build2.py. Pillow-only (no ffmpeg, no scipy).
"""
import math, os, random, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from PIL import features as _pil_features
try:
    import arabic_reshaper  # noqa
    from bidi.algorithm import get_display  # noqa
    _HAS_RESHAPER = True
except Exception:
    _HAS_RESHAPER = False
_HAS_RAQM = _pil_features.check("raqm")
W = H = 480
CX = W // 2
DEFAULT_FONT_PATH = os.path.expanduser("~/workspace/user/files/BNazanin.ttf")

# ---------------- easing ----------------
def clamp01(x): return max(0.0, min(1.0, x))
def phase(t, a, b): return clamp01((t - a) / (b - a)) if b > a else 0.0
def ease_out(x): x = clamp01(x); return 1 - (1 - x) ** 2
def ease_in(x): x = clamp01(x); return x * x
def ease_in_out(x): x = clamp01(x); return x * x * (3 - 2 * x)
def lerp(a, b, x): return a + (b - a) * x

# ---------------- avatar ----------------
def remove_bg_floodfill(im, thresh=232):
    """Drop near-white background connected to the image borders (no scipy)."""
    from collections import deque
    im = im.convert("RGBA")
    arr = np.asarray(im)
    near = (arr[..., :3] > thresh).all(axis=2)
    h, w = near.shape
    seen = np.zeros((h, w), dtype=bool)
    dq = deque()
    for x in range(w):
        for y in (0, h - 1):
            if near[y, x] and not seen[y, x]:
                seen[y, x] = True
                dq.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if near[y, x] and not seen[y, x]:
                seen[y, x] = True
                dq.append((y, x))
    while dq:
        y, x = dq.popleft()
        if y > 0 and near[y - 1, x] and not seen[y - 1, x]:
            seen[y - 1, x] = True; dq.append((y - 1, x))
        if y < h - 1 and near[y + 1, x] and not seen[y + 1, x]:
            seen[y + 1, x] = True; dq.append((y + 1, x))
        if x > 0 and near[y, x - 1] and not seen[y, x - 1]:
            seen[y, x - 1] = True; dq.append((y, x - 1))
        if x < w - 1 and near[y, x + 1] and not seen[y, x + 1]:
            seen[y, x + 1] = True; dq.append((y, x + 1))
    alpha = np.where(seen, 0, 255).astype(np.uint8)
    am = Image.fromarray(alpha, "L").filter(ImageFilter.GaussianBlur(1.5))
    im.putalpha(am)
    bbox = am.point(lambda v: 255 if v > 10 else 0).getbbox()
    if bbox:
        pad = 10
        im = im.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                      min(w, bbox[2] + pad), min(h, bbox[3] + pad)))
    return im


def load_avatar_file(path):
    """Load an avatar image; strip near-white background if it has no alpha."""
    im = Image.open(path).convert("RGBA")
    if im.getchannel("A").getextrema() != (255, 255):
        return im  # already has transparency
    try:
        return remove_bg_floodfill(im)
    except Exception:
        return im


def default_avatar():
    """Best-effort default avatar: transparent cutout if present, else any
    image in ~/workspace/avatars, else a generated placeholder."""
    cands = [os.path.expanduser(
        "~/workspace/your_files/donate-gifs/taha_avatar_transparent.png")]
    adir = os.path.expanduser("~/workspace/avatars")
    if os.path.isdir(adir):
        for fn in sorted(os.listdir(adir)):
            if fn.lower().endswith((".webp", ".png", ".jpg", ".jpeg")):
                cands.append(os.path.join(adir, fn))
    for p in cands:
        if os.path.isfile(p):
            try:
                return load_avatar_file(p)
            except Exception:
                continue
    im = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([20, 20, 380, 380], fill=(90, 200, 170, 255))
    d.ellipse([60, 60, 340, 340], fill=(25, 55, 65, 255))
    return im


AV = None
asp = 1.0
def sprite(h): return AV.resize((int(h * asp), h), Image.LANCZOS)

# ---------------- draw helpers ----------------
def place_avatar(base, sp, cx, cy, sx, sy, angle, alpha_mul=1.0):
    nw, nh = max(1, int(sp.width * sx)), max(1, int(sp.height * sy))
    s = sp.resize((nw, nh), Image.LANCZOS)
    if abs(angle) > 0.01:
        s = s.rotate(angle, resample=Image.BICUBIC, expand=True)
    if alpha_mul < 1.0:
        a = s.getchannel("A").point(lambda v: int(v * alpha_mul))
        s.putalpha(a)
    base.alpha_composite(s, (int(cx - s.width / 2), int(cy - s.height / 2)))

class Actor:
    def __init__(self, sp):
        self.sp = sp; self.ghosts = []
        self.home_x, self.home_y = CX, 300
        self.reset()
    def reset(self):
        self.x, self.y = self.home_x, self.home_y
        self.rot, self.sx, self.sy, self.alpha = 0.0, 1.0, 1.0, 1.0
        self.ghosts = []
    def record_ghost(self, alpha=0.16):
        self.ghosts.append((self.x, self.y, self.sx, self.sy, self.rot, alpha))
        if len(self.ghosts) > 7: self.ghosts.pop(0)
    def clear_ghosts(self): self.ghosts = []
    def draw(self, base):
        for (x, y, sx, sy, rot, al) in self.ghosts:
            place_avatar(base, self.sp, x, y, sx, sy, rot, al)
        place_avatar(base, self.sp, self.x, self.y, self.sx, self.sy, self.rot, self.alpha)

def radial_glow(size, color, max_alpha=150):
    g = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(g)
    for r in range(size // 2, 0, -3):
        a = int(max_alpha * (1 - r / (size / 2)) ** 1.7)
        d.ellipse([size/2-r, size/2-r, size/2+r, size/2+r], fill=a)
    glow = Image.new("RGBA", (size, size), color + (0,))
    glow.putalpha(g)
    return glow

def glow_alpha(glow, k):
    g = glow.copy()
    a = g.getchannel("A").point(lambda v: int(v * max(0.0, min(1.0, k))))
    g.putalpha(a)
    return g

def star4(d, x, y, r, color):
    pts = []
    for k in range(8):
        ang = math.pi / 2 + k * math.pi / 4
        rr = r if k % 2 == 0 else r * 0.36
        pts.append((x + rr * math.cos(ang), y + rr * math.sin(ang)))
    d.polygon(pts, fill=color)

def poly_rot(d, x, y, w, h, ang, color, outline=None):
    ca, sa = math.cos(ang), math.sin(ang)
    pts = []
    for px, py in [(-w/2,-h/2), (w/2,-h/2), (w/2,h/2), (-w/2,h/2)]:
        pts.append((x + px*ca - py*sa, y + px*sa + py*ca))
    d.polygon(pts, fill=color, outline=outline)

def draw_shock(d, cx, cy, age, life, max_r, color, width=8):
    if age < 0 or age > life: return
    k = age / life
    r = max_r * (1 - (1 - k) ** 2)
    a = int(190 * (1 - k))
    d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=color + (a,), width=width)

def explosion_flash(size, age, life=0.55, tint=(255, 150, 60)):
    if age < 0 or age > life: return None
    k = age / life
    r = int(size * (0.15 + 1.25 * k)); c = size // 2
    a = int(255 * (1 - k))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([c-r, c-r, c+r, c+r], fill=tint + (a,))
    r2 = int(r * 0.68); d.ellipse([c-r2, c-r2, c+r2, c+r2], fill=(255, 200, 110, a))
    r3 = int(r * 0.38); d.ellipse([c-r3, c-r3, c+r3, c+r3], fill=(255, 255, 230, min(255, a+30)))
    return img.filter(ImageFilter.GaussianBlur(5))

def draw_speedlines(d, cx, cy, f, n, seed):
    rng = random.Random(seed)
    for i in range(n):
        ang = rng.uniform(0, 6.283) + 0.30 * (f * 0.05)
        r1 = rng.uniform(130, 210); ln = rng.uniform(30, 90)
        x1, y1 = cx + r1*math.cos(ang), cy + r1*math.sin(ang)
        x2, y2 = cx + (r1+ln)*math.cos(ang), cy + (r1+ln)*math.sin(ang)
        d.line([(x1, y1), (x2, y2)], fill=(255, 255, 255, 130), width=3)

def shake_xy(f, F, amp):
    t = f / F
    sx = amp * (math.sin(2*math.pi*5*t) + 0.5*math.sin(2*math.pi*9*t + 1.3))
    sy = amp * (math.sin(2*math.pi*7*t + 0.7) + 0.5*math.sin(2*math.pi*11*t + 2.1))
    return int(sx), int(sy)

def ground_shadow(base, x, ground_y, h_lift, max_w=200):
    # shadow shrinks/fades as the actor rises
    k = clamp01(1 - h_lift / 260)
    w = max_w * (0.45 + 0.55 * k); a = int(90 * k)
    d = ImageDraw.Draw(base)
    d.ellipse([x-w/2, ground_y-12, x+w/2, ground_y+12], fill=(0, 0, 0, a))

# ---------------- souls (Deadlock spirit orbs) ----------------
SOUL_CORE = (190, 255, 225)
def draw_soul(base, d, x, y, px, py, r, alpha=255, glow=None):
    if glow is not None:
        gs = int(r * 7)
        base.alpha_composite(glow_alpha(glow, alpha / 255 * 0.8),
                             (int(x - gs/2), int(y - gs/2)))
    d.line([(px, py), (x, y)], fill=(120, 255, 200, int(alpha * 0.55)), width=int(r*0.9))
    d.ellipse([x-r, y-r, x+r, y+r], fill=SOUL_CORE + (alpha,))
    d.ellipse([x-r*0.45, y-r*0.45, x+r*0.45, y+r*0.45],
              fill=(255, 255, 255, alpha))

def make_soul_stream(n, seed):
    rng = random.Random(seed); out = []
    for i in range(n):
        ang = rng.uniform(0, 6.283)
        edge = rng.choice(['t', 'l', 'r'])
        if edge == 't': x, y = rng.uniform(0, W), -30
        elif edge == 'l': x, y = -30, rng.uniform(0, H)
        else: x, y = W + 30, rng.uniform(0, H)
        out.append(dict(x0=x, y0=y, off=i / n, r=rng.uniform(7, 12),
                        wob=rng.uniform(0, 6.28), wob_amp=rng.uniform(6, 18)))
    return out

def draw_soul_stream(base, d, souls, tx, ty, t, F, fps, cycle=1.0,
                     seek_frac=0.62, glow=None, fade_ends=True):
    """Each soul: spawn at edge -> seek target -> absorbed. Loops seamlessly."""
    for s in souls:
        local = (t / cycle + s['off']) % 1.0
        if local > seek_frac:  # absorbed, waiting to respawn
            continue
        p = ease_in(local / seek_frac)
        x = lerp(s['x0'], tx, p) + s['wob_amp'] * math.sin(s['wob'] + t * 9) * (1 - p)
        y = lerp(s['y0'], ty, p) + s['wob_amp'] * 0.6 * math.cos(s['wob'] * 1.3 + t * 7) * (1 - p)
        px = lerp(s['x0'], tx, ease_in(max(0, local - 0.03) / seek_frac))
        py = lerp(s['y0'], ty, ease_in(max(0, local - 0.03) / seek_frac))
        a = 255
        if fade_ends:
            a = int(255 * clamp01(local / 0.06) * clamp01((seek_frac - local) / 0.05 + 0.4))
        draw_soul(base, d, x, y, px, py, s['r'] * (0.6 + 0.4 * p), alpha=a, glow=glow)

# ---------------- projectiles / impacts ----------------
def draw_tracer(d, x1, y1, x2, y2, prog, color=(255, 230, 160)):
    hx = lerp(x1, x2, prog); hy = lerp(y1, y2, prog)
    tx = lerp(x1, x2, max(0, prog - 0.18)); ty = lerp(y1, y2, max(0, prog - 0.18))
    d.line([(tx, ty), (hx, hy)], fill=color + (110,), width=9)
    d.line([(tx, ty), (hx, hy)], fill=(255, 255, 255, 235), width=3)

def draw_muzzle(base, d, x, y, seed, glow):
    rng = random.Random(seed)
    gs = 120
    base.alpha_composite(glow_alpha(glow, 0.95), (int(x - gs/2), int(y - gs/2)))
    for k in range(9):
        ang = k * math.pi / 4.5 + rng.uniform(-0.25, 0.25)
        L = rng.uniform(20, 52)
        d.line([(x, y), (x + L*math.cos(ang), y + L*math.sin(ang))],
               fill=(255, 214, 140, 255), width=6)
    d.ellipse([x-15, y-15, x+15, y+15], fill=(255, 244, 210, 255))
    d.ellipse([x-7, y-7, x+7, y+7], fill=(255, 255, 255, 255))

def draw_shell(d, x, y, rot):
    poly_rot(d, x, y, 9, 5, rot, (235, 190, 80), outline=(150, 110, 30))

def draw_puff(d, x, y, r, alpha, color=(150, 140, 130)):
    d.ellipse([x-r, y-r, x+r, y+r], fill=color + (alpha,))

def draw_sparks(d, x, y, seed, n=7):
    rng = random.Random(seed)
    for _ in range(n):
        ang = rng.uniform(0, 6.283); L = rng.uniform(8, 30)
        d.line([(x, y), (x + L*math.cos(ang), y + L*math.sin(ang))],
               fill=(255, 220, 150, 230), width=3)
    star4(d, x, y, 10, (255, 245, 210, 255))

# ---------------- lightning ----------------
def bolt_points(x1, y1, x2, y2, seed, displace=46):
    rng = random.Random(seed)
    pts = [(x1, y1), (x2, y2)]
    for _ in range(4):
        new = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            mx, my = (a[0]+b[0])/2, (a[1]+b[1])/2
            dx, dy = b[0]-a[0], b[1]-a[1]
            L = math.hypot(dx, dy) + 1e-6
            off = rng.uniform(-displace, displace)
            new.append((mx - dy/L*off, my + dx/L*off))
            new.append(b)
        pts = new; displace *= 0.5
    return pts

def draw_bolt(d, x1, y1, x2, y2, seed):
    pts = bolt_points(x1, y1, x2, y2, seed)
    d.line(pts, fill=(150, 200, 255, 130), width=10)
    d.line(pts, fill=(255, 255, 255, 235), width=3)

# ---------------- black hole ----------------
def draw_vortex(d, cx, cy, r, f, seed=0):
    if r <= 1: return
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(6, 3, 14, 255))
    d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=(170, 110, 255, 220), width=3)
    for k in range(3):
        rr = r * (1.3 + 0.4 * k)
        a0 = f * 0.30 + k * 2.1 + seed
        d.arc([cx-rr, cy-rr*0.60, cx+rr, cy+rr*0.60],
              start=math.degrees(a0) % 360, end=math.degrees(a0) % 360 + 210,
              fill=(150, 95, 255, 190), width=11 - k * 3)
    d.ellipse([cx-r*0.45, cy-r*0.45, cx+r*0.45, cy+r*0.45], fill=(0, 0, 0, 255))

def draw_spiral_in(d, cx, cy, n, prog, f, seed, R=210, colors=((140,255,205),(255,170,90))):
    rng = random.Random(seed)
    offs = [rng.uniform(0, 1) for _ in range(n)]
    for i in range(n):
        p = (prog + offs[i]) % 1.0
        ang = offs[i] * 6.283 + f * 0.22 + p * 5.0
        rad = R * (1 - p) + 14
        x = cx + rad * math.cos(ang); y = cy + rad * 0.62 * math.sin(ang)
        s = 3 + 5 * (1 - p)
        col = colors[i % 2] + (int(230 * (1 - p * 0.5)),)
        d.ellipse([x-s, y-s, x+s, y+s], fill=col)

# ---------------- debris burst ----------------
def make_debris(n, cx, cy, speed, seed, kinds=('rect', 'circle', 'spark')):
    rng = random.Random(seed); ps = []
    for _ in range(n):
        ang = rng.uniform(0, 6.283); sp = rng.uniform(*speed)
        ps.append(dict(x=cx, y=cy, vx=sp*math.cos(ang), vy=sp*math.sin(ang) - 140,
                       size=rng.uniform(3, 9),
                       color=rng.choice([(255,150,70),(255,200,120),(140,255,205),(200,140,255),(255,120,90)]),
                       kind=rng.choice(kinds), rot=rng.uniform(0, 6.28)))
    return ps

def draw_debris(d, ps, age, grav=560, life=1.25):
    if age < 0 or age > life: return
    k = 1 - age / life
    for p in ps:
        x = p['x'] + p['vx'] * age
        y = p['y'] + p['vy'] * age + 0.5 * grav * age * age
        a = int(255 * k); s = p['size'] * (0.45 + 0.55 * k)
        col = p['color'] + (a,)
        if p['kind'] == 'rect':
            poly_rot(d, x, y, s, s*0.6, p['rot'] + age*7, col)
        elif p['kind'] == 'circle':
            d.ellipse([x-s/2, y-s/2, x+s/2, y+s/2], fill=col)
        else:
            star4(d, x, y, s, col)

# ================================================================
# LEVEL 1 — Soul Harvest: souls stream in, avatar absorbs them
# ================================================================
def level1():
    F, fps = 48, 24
    sp = sprite(300); act = Actor(sp); act.home_y = 300
    glow_teal = radial_glow(200, (120, 255, 200), 130)
    glow_warm = radial_glow(430, (255, 190, 120), 120)
    souls = make_soul_stream(7, seed=101)
    for s in souls: s['r'] = s['r'] + 3.0  # bigger, more readable
    arrive = [0.22 + i * (0.68 / 7) for i in range(7)]
    frames = []
    for f in _frame_iter(F):
        t = f / F
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        img.alpha_composite(glow_alpha(glow_warm, 0.55 + 0.2 * math.sin(2*math.pi*t)), (25, 25))
        act.reset()
        # absorb pops: gaussian around each arrival
        pop = sum(math.exp(-(((t - ta) % 1.0 if (t - ta) % 1.0 < 0.5 else (t - ta) % 1.0 - 1.0) / 0.035) ** 2) for ta in arrive)
        pop = min(pop, 1.4)
        act.y = 300 - 10 * math.sin(2*math.pi*t)
        act.sx = act.sy = 1 + 0.055 * pop
        act.rot = 1.5 * math.sin(2*math.pi*t)
        d = ImageDraw.Draw(img)
        # souls: orbit then dive in, staggered arrivals
        for i, s in enumerate(souls):
            ta = arrive[i]
            local = (t - (ta - 0.62)) % 1.0
            if local > 0.62: continue
            if local < 0.30:  # orbit
                q = ease_in_out(local / 0.30)
                ang = s['wob'] + t * 2.2 + i
                r = lerp(208, 96, q)
                x = act.x + r * math.cos(ang); y = act.y - 20 + r * 0.7 * math.sin(ang)
                px, py = act.x + 208*math.cos(ang - 0.15), act.y - 20 + 208*0.7*math.sin(ang - 0.15)
            else:  # dive
                q = ease_in((local - 0.30) / 0.32)
                ang = s['wob'] + (ta - 0.32) * 2.2 + i
                sx0, sy0 = act.x + 96*math.cos(ang), act.y - 20 + 67*math.sin(ang)
                x = lerp(sx0, act.x, q); y = lerp(sy0, act.y - 30, q)
                px, py = lerp(sx0, act.x, ease_in(max(0, q-0.08))), lerp(sy0, act.y-30, ease_in(max(0, q-0.08)))
            a = int(255 * clamp01(local / 0.06))
            if local > 0.58: a = int(255 * clamp01((0.62 - local) / 0.04))
            draw_soul(img, d, x, y, px, py, s['r'], alpha=a, glow=glow_teal)
            if abs((t - ta + 0.5) % 1.0 - 0.5) < 0.012:  # absorb ring
                draw_shock(d, act.x, act.y - 30, 0.02, 0.3, 90, (140, 255, 205), 6)
        # absorb glow on avatar
        if pop > 0.05:
            img.alpha_composite(glow_alpha(glow_teal, 0.42 * pop),
                                (int(act.x)-100, int(act.y)-140))
        ground_shadow(img, act.x, 452, 0)
        act.draw(img)
        frames.append(img)
    return frames, fps, "donate_01.gif"

# ================================================================
# LEVEL 2 — Shoulder Dash: crouch, dash, impact (both directions)
# ================================================================
def level2():
    F, fps = 60, 30
    sp = sprite(300); act = Actor(sp); act.home_y = 310
    glow_warm = radial_glow(440, (255, 175, 100), 130)
    dust_seed = 202
    frames = []
    for f in _frame_iter(F):
        t = f / F
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        img.alpha_composite(glow_alpha(glow_warm, 0.5 + 0.25*abs(math.sin(2*math.pi*2*t))), (20, 20))
        d = ImageDraw.Draw(img)
        half = 0 if t < 0.5 else 1
        ht = (t % 0.5) / 0.5  # 0..1 within half
        x0, x1 = (CX - 150, CX + 150) if half == 0 else (CX + 150, CX - 150)
        direction = 1 if half == 0 else -1
        act.reset()
        if ht < 0.14:  # anticipation: crouch + lean back
            q = ease_out(ht / 0.14)
            act.x = x0 - direction * 26 * q
            act.y = 310 + 16 * q
            act.sx, act.sy = 1 + 0.14*q, 1 - 0.13*q
            act.rot = -7 * direction * q
        elif ht < 0.42:  # DASH
            q = ease_in_out((ht - 0.14) / 0.28)
            act.x = lerp(x0, x1, q)
            act.y = 310 - 26 * math.sin(math.pi * q)
            act.sx, act.sy = 1 + 0.28*math.sin(math.pi*q), 1 - 0.20*math.sin(math.pi*q)
            act.rot = 13 * direction * math.sin(math.pi * q)
            act.record_ghost(alpha=0.20)
            draw_speedlines(d, act.x, act.y - 40, f, 22, seed=dust_seed + half)
        elif ht < 0.62:  # impact: dust + squash + shake
            q = (ht - 0.42) / 0.20
            act.x = x1 + direction * 26 * math.sin(math.pi*q) * (1-q)
            act.y = 310 + 10 * math.sin(math.pi * q)
            act.sx, act.sy = 1 - 0.12*math.sin(math.pi*q), 1 + 0.13*math.sin(math.pi*q)
            act.rot = -4 * direction * math.sin(math.pi*q)
            rng = random.Random(dust_seed + half)
            for _ in range(16):
                ang = rng.uniform(-1.2, 1.2) + (0 if direction > 0 else math.pi)
                rr = 30 + 130 * ease_out(q)
                dx, dy = x1 + rr*math.cos(ang)*direction, 418 + rr*0.35*math.sin(abs(ang))
                draw_puff(d, dx, dy, 8 + 22*q, int(150*(1-q)))
        else:  # recover to idle
            q = ease_in_out((ht - 0.62) / 0.38)
            act.x = x1; act.y = 310 - 6*math.sin(2*math.pi*q)
            act.rot = 2*math.sin(2*math.pi*q)
        ground_shadow(img, act.x, 452, 310 - act.y + 26)
        act.draw(img)
        fin = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bump = 0
        if 0.42 < ht < 0.62: bump = 7 * math.sin(math.pi * (ht-0.42)/0.20)
        sx, sy = shake_xy(f, F, 2 + bump)
        fin.alpha_composite(img, (sx, sy))
        frames.append(fin)
    return frames, fps, "donate_02.gif"

# ================================================================
# LEVEL 3 — Gunfight: recoil, muzzle flash, tracers, shells, smoke
# ================================================================
def level3():
    F, fps = 72, 24
    sp = sprite(300); act = Actor(sp); act.home_y = 305
    glow_warm = radial_glow(440, (255, 180, 105), 125)
    glow_flash = radial_glow(120, (255, 220, 150), 200)
    bursts = [[0.06 + k*0.048 for k in range(5)], [0.52 + k*0.048 for k in range(5)]]
    shots = [s for b in bursts for s in b]
    rng = random.Random(303)
    shell_seeds = [rng.uniform(0, 100) for _ in shots]
    spark_pts = [(18, rng.uniform(120, 380)) for _ in shots]
    frames = []
    for f in _frame_iter(F):
        t = f / F
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        img.alpha_composite(glow_alpha(glow_warm, 0.5 + 0.2*math.sin(2*math.pi*t)), (20, 25))
        d = ImageDraw.Draw(img)
        act.reset()
        # base combat lean
        act.x = CX + 20; act.y = 305 - 8*math.sin(2*math.pi*t)
        act.rot = -4
        # reload dip
        rd = phase(t, 0.80, 0.87) - phase(t, 0.90, 0.97)
        act.y += 26 * rd; act.rot += 6 * rd
        # recoil from recent shots
        rec = 0
        for s in shots:
            age = f - s * F
            if 0 <= age < 9: rec += (1 - age / 9)
        act.x += 15 * rec; act.rot -= 3.5 * rec
        act.sx, act.sy = 1 + 0.03*rec, 1 - 0.02*rec
        gun_x, gun_y = act.x - 138, act.y - 46
        # per-shot effects
        for i, s in enumerate(shots):
            age = f - s * F
            if age < 0 or age > 34: continue
            if age < 3:  # muzzle flash
                draw_muzzle(img, d, gun_x, gun_y, seed=int(shell_seeds[i]*10)+f, glow=glow_flash)
            if age < 7:  # tracer
                draw_tracer(d, gun_x, gun_y, spark_pts[i][0], spark_pts[i][1], age/7)
            if 6 <= age < 11:  # impact sparks
                draw_sparks(d, spark_pts[i][0], spark_pts[i][1], seed=i*7+f)
            if 0 <= age < 16:  # shell casing
                q = age / 16
                shx = gun_x + 40*q + 30*q*q
                shy = gun_y - 60*q + 190*q*q
                if shy < 470: draw_shell(d, shx, shy, shell_seeds[i] + age*0.4)
            if 2 <= age < 30:  # smoke
                q = (age-2) / 28
                draw_puff(d, gun_x + 20*q + 6*math.sin(i+age*0.2), gun_y - 24*q - 10*q,
                          6 + 16*q, int(110*(1-q)))
        ground_shadow(img, act.x, 452, 0)
        act.draw(img)
        fin = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        kick = 3 * rec
        sx, sy = shake_xy(f, F, 2 + kick)
        fin.alpha_composite(img, (sx, sy))
        frames.append(fin)
    return frames, fps, "donate_03.gif"

# ================================================================
# LEVEL 4 — The Hook: windup, chain throw, yank a soul home
# ================================================================
def level4():
    F, fps = 72, 24
    sp = sprite(300); act = Actor(sp); act.home_y = 305
    glow_teal = radial_glow(200, (120, 255, 200), 150)
    glow_warm = radial_glow(440, (255, 180, 105), 120)
    hand_rel = (52, -72)
    target = (CX + 178, 118)
    frames = []
    for f in _frame_iter(F):
        t = f / F
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        img.alpha_composite(glow_alpha(glow_warm, 0.5 + 0.2*math.sin(2*math.pi*t)), (20, 25))
        d = ImageDraw.Draw(img)
        act.reset()
        act.x, act.y = CX, 305 - 8*math.sin(2*math.pi*t)
        hook = None; orb = None; yanking = 0
        if t < 0.15:  # windup: lean back
            q = ease_in_out(t / 0.15)
            act.x += 26*q; act.rot = -9*q
            act.sx, act.sy = 1 + 0.06*q, 1 - 0.05*q
        elif t < 0.30:  # throw: lunge forward, hook flies out
            q = ease_out((t - 0.15) / 0.15)
            act.x -= 34*q; act.rot = 7*q
            act.sx, act.sy = 1 + 0.10*q, 1 - 0.07*q
            hx = lerp(act.x + hand_rel[0], target[0], q)
            hy = lerp(act.y + hand_rel[1], target[1], q)
            hook = (hx, hy)
        elif t < 0.36:  # grab
            q = (t - 0.30) / 0.06
            act.x = CX - 34; act.rot = 7
            hook = target
            orb = (target[0], target[1], 1 + 0.25*math.sin(q*math.pi))
        elif t < 0.56:  # YANK back
            q = ease_in((t - 0.36) / 0.20)
            yanking = math.sin(math.pi * min(q*1.4, 1))
            act.x = lerp(CX - 34, CX + 44, q)
            act.rot = lerp(7, -10, q)
            act.sx, act.sy = 1 + 0.16*math.sin(math.pi*q), 1 - 0.10*math.sin(math.pi*q)
            hx = lerp(target[0], act.x + hand_rel[0] + 44, q)
            hy = lerp(target[1], act.y + hand_rel[1], q)
            hook = (hx, hy); orb = (hx, hy, 1.15)
            if q > 0.02: act.record_ghost(alpha=0.18)
        elif t < 0.64:  # absorb!
            q = (t - 0.56) / 0.08
            act.x = CX + 44 - 44*ease_out(q)
            act.rot = -10 + 10*ease_out(q)
            act.sx = act.sy = 1 + 0.10*math.sin(math.pi*q)
            img.alpha_composite(glow_alpha(glow_teal, 0.8*(1-q)), (CX-100, 205-100))
            draw_shock(d, act.x, act.y - 40, q*0.25, 0.3, 110, (140, 255, 205), 7)
        else:  # recover
            q = ease_in_out((t - 0.64) / 0.36)
            act.x = CX; act.rot = 2*math.sin(2*math.pi*q)*(1-q)
        # chain + hook + orb
        if hook is not None:
            hx0, hy0 = act.x + hand_rel[0], act.y + hand_rel[1]
            n_links = 9
            for li in range(1, n_links):
                qq = li / n_links
                lx = lerp(hx0, hook[0], qq)
                ly = lerp(hy0, hook[1], qq) + 14*math.sin(math.pi*qq)
                d.ellipse([lx-4, ly-4, lx+4, ly+4], outline=(190, 190, 200, 255), width=3)
            d.line([(hx0, hy0), (hook[0], hook[1])], fill=(150, 150, 160, 160), width=2)
            hx, hy = hook
            d.ellipse([hx-9, hy-9, hx+9, hy+9], outline=(220, 220, 230, 255), width=4)
            for pa in (0.5, 2.6, 4.7):
                d.line([(hx, hy), (hx+14*math.cos(pa), hy+14*math.sin(pa))],
                       fill=(220, 220, 230, 255), width=4)
        if orb is not None:
            ox, oy, os = orb
            draw_soul(img, d, ox, oy, ox-14, oy+10, 15*os, glow=glow_teal)
        ground_shadow(img, act.x, 452, 0)
        act.draw(img)
        fin = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shk = 6*yanking + (8 if 0.56 <= t < 0.64 else 0)*math.sin(math.pi*(t-0.56)/0.08)
        sx, sy = shake_xy(f, F, 2 + shk)
        fin.alpha_composite(img, (sx, sy))
        frames.append(fin)
    return frames, fps, "donate_04.gif"

# ================================================================
# LEVEL 5 — Stormcall: levitate, lightning strikes, slam
# ================================================================
def level5():
    F, fps = 84, 28
    sp = sprite(290); act = Actor(sp); act.home_y = 320
    glow_storm = radial_glow(460, (150, 190, 255), 150)
    glow_warm = radial_glow(440, (255, 180, 105), 110)
    strike_x = [CX-165, CX-100, CX-38, CX+48, CX+112, CX+170]
    strike_t = [0.24 + k*0.075 for k in range(6)]
    ground_y = 440
    frames = []
    for f in _frame_iter(F):
        t = f / F
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        storm_k = phase(t, 0.18, 0.30) - phase(t, 0.68, 0.80)
        img.alpha_composite(glow_alpha(glow_storm, 0.25 + 0.65*storm_k), (10, 10))
        img.alpha_composite(glow_alpha(glow_warm, 0.45*(1-storm_k)), (20, 25))
        d = ImageDraw.Draw(img)
        act.reset()
        # levitate
        rise = ease_out(phase(t, 0.06, 0.24)) - ease_in(phase(t, 0.70, 0.78))
        act.y = 320 - 118*rise + 6*math.sin(2*math.pi*3*t)*rise
        act.rot = 4*math.sin(2*math.pi*2*t)*rise
        act.sx = act.sy = 1 + 0.03*rise
        # lightning strikes
        shk = 0
        for k, st in enumerate(strike_t):
            age = f - st*F
            if age < 0 or age > 12: continue
            sx = strike_x[k]
            if age < 5:  # bolt flickers
                draw_bolt(d, sx + random.Random(k*13+f).uniform(-8,8), -20, sx, ground_y, seed=k*101+f)
                fl = explosion_flash(300, age/fps, life=0.3, tint=(170, 205, 255))
                if fl: img.alpha_composite(fl, (int(sx)-150, ground_y-260))
            if 0 <= age < 10:
                q = age/10
                draw_shock(d, sx, ground_y, q*0.35, 0.4, 120, (170, 205, 255), 7)
                rng = random.Random(k*7)
                for _ in range(8):
                    dx = sx + rng.uniform(-40, 40)
                    draw_puff(d, dx, ground_y - 8, 6+14*q, int(120*(1-q)), color=(160,170,185))
            shk += 5*max(0, 1-age/12)
        # body arcs while levitating
        if 0.24 < t < 0.70 and f % 2 == 0:
            rng = random.Random(f)
            for _ in range(3):
                ax = act.x + rng.uniform(-70, 70); ay = act.y + rng.uniform(-90, 60)
                draw_bolt(d, act.x + rng.uniform(-40,40), act.y - 60, ax, ay, seed=f*3+_)
        # slam impact
        if 0.70 <= t < 0.80:
            q = (t-0.70)/0.10
            draw_shock(d, act.x, ground_y, q*0.4, 0.45, 210, (200, 220, 255), 10)
            draw_shock(d, act.x, ground_y, max(0, q-0.25)*0.4, 0.45, 150, (255, 220, 160), 7)
            shk += 12*math.sin(math.pi*q)
            fl = explosion_flash(380, q*0.4, life=0.45, tint=(190, 210, 255))
            if fl: img.alpha_composite(fl, (CX-190, ground_y-330))
        # landing squash
        if 0.78 <= t < 0.90:
            q = (t-0.78)/0.12
            act.sx, act.sy = 1 - 0.10*math.sin(math.pi*q), 1 + 0.12*math.sin(math.pi*q)
        ground_shadow(img, act.x, 452, 320 - act.y + 118*rise)
        act.draw(img)
        fin = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sx, sy = shake_xy(f, F, 2 + min(shk, 14))
        fin.alpha_composite(img, (sx, sy))
        frames.append(fin)
    return frames, fps, "donate_05.gif"

# ================================================================
# LEVEL 6 — Singularity: spin up, black hole, detonation
# ================================================================
def level6():
    F, fps = 84, 28
    sp = sprite(290); act = Actor(sp); act.home_y = 315
    glow_void = radial_glow(460, (150, 95, 255), 160)
    glow_warm = radial_glow(440, (255, 180, 105), 100)
    vx, vy = CX, 195
    debris = make_debris(110, vx, vy, (120, 460), seed=606)
    frames = []
    for f in _frame_iter(F):
        t = f / F
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        img.alpha_composite(glow_alpha(glow_warm, 0.4), (20, 25))
        d = ImageDraw.Draw(img)
        act.reset()
        # spin-up
        spin = phase(t, 0.04, 0.26)
        pull = phase(t, 0.30, 0.63)
        # vortex radius timeline
        vr = 0
        if t < 0.30: vr = 0
        elif t < 0.37: vr = 78*ease_out((t-0.30)/0.07)
        elif t < 0.60: vr = 78
        elif t < 0.66: vr = 78*(1-ease_in((t-0.60)/0.06))
        if 0.04 <= t < 0.28:
            act.rot = 720*ease_in_out(spin)
            for gi in range(4, 0, -1):
                place_avatar(img, sp, act.x, act.y, 1.02, 1.02, act.rot - gi*22, 0.10*gi)
        else:
            act.rot = 720 if t >= 0.28 else 0
        if 0.30 <= t < 0.66:  # braced against the pull
            act.x = CX + 34*pull
            act.rot = 720 - 8*pull
            act.sx, act.sy = 1 + 0.08*pull, 1 - 0.05*pull
        det = 0
        if 0.66 <= t < 0.74:  # DETONATION
            q = (t-0.66)/0.08; det = math.sin(math.pi*q)
            fl = explosion_flash(470, q*0.5, life=0.55, tint=(190, 130, 255))
            if fl: img.alpha_composite(fl, (5, 5))
            draw_debris(d, debris, q*0.9)
            for k in range(3):
                draw_shock(d, vx, vy, max(0, q*0.5 - k*0.09), 0.5, 230 - k*40, (190, 150, 255), 9)
            act.x = CX + 34 - 70*ease_out(q)
            act.rot = 720 - 8 + 22*ease_out(q)
        elif t >= 0.74:  # settle
            q = ease_in_out((t-0.74)/0.26)
            act.x = CX - 36 + 36*q
            act.rot = 720 + 14 - 14*q
            act.sx = act.sy = 1
        if vr > 1:
            img.alpha_composite(glow_alpha(glow_void, 0.35 + 0.45*pull), (10, 10))
            draw_vortex(d, vx, vy, vr, f)
            if 0.34 < t < 0.62:
                draw_spiral_in(d, vx, vy, 44, phase(t, 0.34, 0.62), f, seed=607)
        ground_shadow(img, act.x, 452, 0)
        act.draw(img)
        fin = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shk = 4*pull + 15*det
        sx, sy = shake_xy(f, F, 2 + shk)
        fin.alpha_composite(img, (sx, sy))
        frames.append(fin)
    return frames, fps, "donate_06.gif"

# ================================================================
# LEVEL 7 — Full Combo: dash -> gunfire -> hook -> storm -> boom
# ================================================================
def level7():
    F, fps = 108, 30
    sp = sprite(290); act = Actor(sp); act.home_y = 310
    glow_teal = radial_glow(200, (120, 255, 200), 150)
    glow_storm = radial_glow(460, (150, 190, 255), 140)
    glow_void = radial_glow(460, (150, 95, 255), 150)
    glow_warm = radial_glow(440, (255, 180, 105), 110)
    shots = [0.185 + k*0.034 for k in range(5)]
    spark_x = [20, 30, 14, 26, 18]
    spark_y = [150, 260, 330, 210, 300]
    hand_rel = (52, -72); hook_target = (CX + 170, 120)
    strike_x = [CX-140, CX-50, CX+60, CX+150]
    strike_t = [0.645 + k*0.028 for k in range(4)]
    debris = make_debris(90, CX, 200, (120, 420), seed=707)
    frames = []
    for f in _frame_iter(F):
        t = f / F
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        img.alpha_composite(glow_alpha(glow_warm, 0.4), (20, 25))
        d = ImageDraw.Draw(img)
        act.reset()
        shk_extra = 0
        # --- dash in [0, 0.16]
        if t < 0.16:
            if t < 0.05:
                q = ease_out(t/0.05)
                act.x = CX-195 - 20*q; act.y = 326 + 14*q
                act.sx, act.sy = 1+0.13*q, 1-0.12*q; act.rot = -7*q
            else:
                q = ease_in_out((t-0.05)/0.11)
                act.x = lerp(CX-215, CX, q); act.y = 326 - 24*math.sin(math.pi*q)
                act.sx, act.sy = 1+0.26*math.sin(math.pi*q), 1-0.18*math.sin(math.pi*q)
                act.rot = 12*math.sin(math.pi*q)
                act.record_ghost(alpha=0.2)
                draw_speedlines(d, act.x, act.y-40, f, 18, seed=71)
            if 0.13 < t < 0.16:
                q = (t-0.13)/0.03
                rng = random.Random(72)
                for _ in range(10):
                    draw_puff(d, CX + rng.uniform(-50,50), 425, 6+16*q, int(140*(1-q)))
        # --- gunfire [0.18, 0.36]
        elif t < 0.38:
            act.x, act.y = CX, 310 - 6*math.sin(2*math.pi*t); act.rot = -4
            rec = 0
            for i, s in enumerate(shots):
                age = f - s*F
                if 0 <= age < 9: rec += 1 - age/9
                if 0 <= age < 3:
                    draw_muzzle(img, d, act.x-138, act.y-46, seed=i*31+f,
                                glow=radial_glow(120, (255,220,150), 200))
                if 0 <= age < 7:
                    draw_tracer(d, act.x-138, act.y-46, spark_x[i], spark_y[i], age/7)
                if 6 <= age < 11:
                    draw_sparks(d, spark_x[i], spark_y[i], seed=i*7+f)
            act.x += 14*rec; act.rot -= 3*rec
            shk_extra = 3*rec
        # --- hook [0.40, 0.56]
        elif t < 0.58:
            lt = (t-0.40)/0.18
            act.x, act.y = CX, 308
            hook = None
            if lt < 0.35:
                q = ease_out(lt/0.35)
                act.x -= 30*q; act.rot = 7*q
                hook = (lerp(act.x+hand_rel[0], hook_target[0], q),
                        lerp(act.y+hand_rel[1], hook_target[1], q))
            else:
                q = ease_in((lt-0.35)/0.65)
                act.x = lerp(CX-30, CX+40, q); act.rot = lerp(7, -9, q)
                act.record_ghost(alpha=0.16)
                hook = (lerp(hook_target[0], act.x+hand_rel[0]+40, q),
                        lerp(hook_target[1], act.y+hand_rel[1], q))
                shk_extra = 5*math.sin(math.pi*q)
                if q > 0.9:
                    img.alpha_composite(glow_alpha(glow_teal, 0.7), (CX-100, 205-100))
            if hook:
                hx0, hy0 = act.x+hand_rel[0], act.y+hand_rel[1]
                for li in range(1, 9):
                    qq = li/9
                    lx = lerp(hx0, hook[0], qq); ly = lerp(hy0, hook[1], qq)+12*math.sin(math.pi*qq)
                    d.ellipse([lx-4,ly-4,lx+4,ly+4], outline=(190,190,200,255), width=3)
                d.ellipse([hook[0]-9,hook[1]-9,hook[0]+9,hook[1]+9], outline=(220,220,230,255), width=4)
        # --- storm [0.60, 0.76]
        elif t < 0.78:
            img.alpha_composite(glow_alpha(glow_storm, 0.7), (10, 10))
            rise = ease_out(phase(t,0.60,0.66)) - ease_in(phase(t,0.72,0.76))
            act.y = 310 - 110*rise; act.rot = 5*math.sin(4*math.pi*t)*rise
            for k, st in enumerate(strike_t):
                age = f - st*F
                if 0 <= age < 5:
                    draw_bolt(d, strike_x[k], -20, strike_x[k], 440, seed=k*55+f)
                    shk_extra += 4
                if 0 <= age < 9:
                    draw_shock(d, strike_x[k], 440, age/30, 0.35, 110, (170,205,255), 7)
            if 0.72 <= t < 0.78:
                q = (t-0.72)/0.06
                draw_shock(d, act.x, 440, q*0.35, 0.4, 190, (200,220,255), 9)
                shk_extra += 10*math.sin(math.pi*q)
        # --- singularity boom [0.80, 0.92]
        elif t < 0.94:
            lt = (t-0.80)/0.14
            if lt < 0.45:
                vr = 66*ease_out(lt/0.45)
                img.alpha_composite(glow_alpha(glow_void, 0.6), (10, 10))
                draw_vortex(d, CX, 200, vr, f)
                draw_spiral_in(d, CX, 200, 36, lt/0.45, f, seed=708)
                act.x = CX + 26*lt; act.rot = -7*lt
                shk_extra = 4
            else:
                q = (lt-0.45)/0.55
                fl = explosion_flash(470, q*0.5, life=0.55, tint=(190,130,255))
                if fl: img.alpha_composite(fl, (5, 5))
                draw_debris(d, debris, q*0.85)
                draw_shock(d, CX, 200, q*0.45, 0.5, 220, (190,150,255), 9)
                act.x = CX + 26 - 60*ease_out(q); act.rot = -7 + 18*ease_out(q)
                shk_extra = 14*math.sin(math.pi*min(q*1.3,1))
        # --- hero pose [0.94, 1]
        else:
            q = ease_in_out((t-0.94)/0.06)
            act.x = CX - 34 + 34*q
            act.sx, act.sy = 1 - 0.08*math.sin(math.pi*q), 1 + 0.10*math.sin(math.pi*q)
            act.rot = 11 - 11*q
            draw_shock(d, CX, 300, q*0.3, 0.35, 130, (140,255,205), 6)
            img.alpha_composite(glow_alpha(glow_teal, 0.5*(1-q)+0.15), (CX-100, 200-100))
        ground_shadow(img, act.x, 452, max(0, 310-act.y))
        act.draw(img)
        fin = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sx, sy = shake_xy(f, F, 2 + shk_extra)
        fin.alpha_composite(img, (sx, sy))
        frames.append(fin)
    return frames, fps, "donate_07.gif"

# ================================================================
# LEVEL 8 — LEGENDARY: storm + souls + singularity, all at once
# ================================================================
def level8():
    F, fps = 120, 30
    sp = sprite(285); act = Actor(sp); act.home_y = 310
    glow_teal = radial_glow(220, (120, 255, 200), 160)
    glow_storm = radial_glow(470, (150, 190, 255), 160)
    glow_void = radial_glow(470, (150, 95, 255), 170)
    glow_warm = radial_glow(440, (255, 180, 105), 100)
    souls = make_soul_stream(11, seed=808)
    strike_x = [CX-170, CX-110, CX-45, CX+30, CX+100, CX+165, CX-70, CX+135]
    strike_t = [0.14 + k*0.042 for k in range(8)]
    shots = [0.16 + k*0.05 for k in range(6)]
    debris = make_debris(130, CX, 205, (130, 480), seed=809)
    frames = []
    for f in _frame_iter(F):
        t = f / F
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        img.alpha_composite(glow_alpha(glow_warm, 0.35), (20, 25))
        d = ImageDraw.Draw(img)
        act.reset()
        shk = 0
        # rise + slow heroic spin [0, 0.14]
        rise = ease_out(phase(t, 0.02, 0.14)) - ease_in(phase(t, 0.86, 0.97))
        act.y = 310 - 100*rise + 5*math.sin(2*math.pi*3*t)
        # storm phase [0.12, 0.48]
        storm = phase(t, 0.12, 0.18) - phase(t, 0.46, 0.54)
        if storm > 0:
            img.alpha_composite(glow_alpha(glow_storm, 0.75*storm), (5, 5))
            act.rot = 200*storm*t*3 + 4*math.sin(6*math.pi*t)
            for gi in range(4, 0, -1):
                place_avatar(img, sp, act.x, act.y, 1.04, 1.04,
                             act.rot - gi*18, 0.09*gi)
            for k, st in enumerate(strike_t):
                age = f - st*F
                if 0 <= age < 5:
                    draw_bolt(d, strike_x[k], -20, strike_x[k], 440, seed=k*77+f)
                    shk += 3
                if 0 <= age < 9:
                    draw_shock(d, strike_x[k], 440, age/30, 0.35, 105, (170,205,255), 6)
            for i, s in enumerate(shots):  # crossing tracers
                age = f - s*F
                if 0 <= age < 8:
                    y0 = 140 + i*36
                    draw_tracer(d, -20, y0, W+20, y0+40, age/8, color=(160,220,255))
        # singularity [0.50, 0.66]
        sing = phase(t, 0.50, 0.56) - phase(t, 0.62, 0.68)
        if sing > 0:
            vr = 84*ease_out(min(sing*1.6, 1))
            img.alpha_composite(glow_alpha(glow_void, 0.7*sing), (5, 5))
            draw_vortex(d, CX, 205, vr, f, seed=3)
            draw_spiral_in(d, CX, 205, 52, phase(t, 0.52, 0.64), f, seed=810, R=230)
            act.x = CX + 30*sing; act.rot = 200*0.48*3 - 9*sing
            shk += 5*sing
        # DETONATION [0.66, 0.74]
        if 0.66 <= t < 0.76:
            q = (t-0.66)/0.10
            fl = explosion_flash(480, q*0.55, life=0.6, tint=(200, 140, 255))
            if fl: img.alpha_composite(fl, (0, 0))
            fl2 = explosion_flash(380, max(0, q*0.55-0.12), life=0.5, tint=(255, 190, 120))
            if fl2: img.alpha_composite(fl2, (50, 60))
            draw_debris(d, debris, q*0.95)
            for k in range(4):
                draw_shock(d, CX, 205, max(0, q*0.5-k*0.07), 0.5, 240-k*35, (200,160,255), 9)
            draw_speedlines(d, CX, 205, f, 30, seed=811)
            act.x = CX + 30 - 74*ease_out(q)
            act.rot = 200*0.48*3 - 9 + 24*ease_out(q)
            act.sx, act.sy = 1+0.10*math.sin(math.pi*q), 1-0.07*math.sin(math.pi*q)
            shk += 17*math.sin(math.pi*min(q*1.25, 1))
        # aftermath embers [0.74, 0.90]
        if 0.74 < t < 0.92:
            q = (t-0.74)/0.18
            rng = random.Random(812)
            for _ in range(26):
                ex = rng.uniform(60, W-60); ey = 440 - q*rng.uniform(120, 300)
                s = rng.uniform(2, 5)
                d.ellipse([ex-s, ey-s, ex+s, ey+s],
                          fill=(255, int(rng.uniform(120,180)), 70, int(200*(1-q))))
            act.x = CX - 44 + 44*ease_in_out(q)
            act.rot = (200*0.48*3 + 15) * (1-q)
        # souls stream the whole time -> absorb glow
        draw_soul_stream(img, d, souls, act.x, act.y - 40, t, F, fps,
                         cycle=1.0, seek_frac=0.60, glow=glow_teal)
        img.alpha_composite(glow_alpha(glow_teal, 0.30 + 0.25*storm + 0.3*sing), (CX-110, 200-110))
        ground_shadow(img, act.x, 452, max(0, 310-act.y))
        act.draw(img)
        fin = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sx, sy = shake_xy(f, F, 2 + min(shk, 18))
        fin.alpha_composite(img, (sx, sy))
        frames.append(fin)
    return frames, fps, "donate_08.gif"


# ================================================================
# Donate Studio — registry, render API, Persian overlay, GIF export
# ================================================================

class _Cancelled(Exception):
    pass


_frame_cb = None
_frame_max = None


def _frame_iter(F):
    total = F if not _frame_max else min(F, _frame_max)
    for f in range(total):
        if _frame_cb is not None:
            try:
                keep = _frame_cb(f, total)
            except Exception:
                keep = True
            if keep is False:
                raise _Cancelled()
        yield f


_FX_FUNCS = {
    "soul_harvest": level1,
    "dash": level2,
    "gunfight": level3,
    "hook": level4,
    "storm": level5,
    "singularity": level6,
    "combo": level7,
    "legendary": level8,
}

# (id, Persian name, native frame count, native fps)
EFFECTS = [
    ("soul_harvest", "برداشت روح", 48, 24),
    ("dash", "داش شانه‌ای", 60, 30),
    ("gunfight", "تیراندازی", 72, 24),
    ("hook", "قلاب", 72, 24),
    ("storm", "فراخوان طوفان", 84, 28),
    ("singularity", "تکینگی", 84, 28),
    ("combo", "کمبوی کامل", 108, 30),
    ("legendary", "افسانه‌ای", 120, 30),
]

EFFECT_IDS = [e[0] for e in EFFECTS]


def effect_info(effect_id):
    for eid, fa, nframes, nfps in EFFECTS:
        if eid == effect_id:
            return {"id": eid, "fa_name": fa, "frames": nframes, "fps": nfps}
    raise ValueError("unknown effect: %r" % (effect_id,))


# ---------------- Persian text ----------------

def _font_path(explicit=None):
    if explicit and os.path.isfile(explicit):
        return explicit
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = os.path.join(meipass, "fonts", "BNazanin.ttf")
        if os.path.isfile(p):
            return p
    if os.path.isfile(DEFAULT_FONT_PATH):
        return DEFAULT_FONT_PATH
    return None


def _shape_fa(text):
    if _HAS_RESHAPER:
        try:
            return get_display(arabic_reshaper.reshape(text))
        except Exception:
            return text
    return text


def _fa_textbbox(d, text, font):
    if _HAS_RAQM:
        return d.textbbox((0, 0), text, font=font, direction="rtl")
    return d.textbbox((0, 0), _shape_fa(text), font=font)


def _fa_text(d, xy, text, font, fill):
    if _HAS_RAQM:
        d.text(xy, text, font=font, fill=fill, anchor="mm", direction="rtl")
    else:
        d.text(xy, _shape_fa(text), font=font, fill=fill, anchor="mm")


def _apply_name_pill(frames, name, amount, font_path=None):
    """Dark rounded pill with donor name/amount at the bottom of each frame."""
    fp = _font_path(font_path)
    size = frames[0].width
    try:
        f_name = (ImageFont.truetype(fp, max(20, size // 12)) if fp
                  else ImageFont.load_default())
        f_amt = (ImageFont.truetype(fp, max(16, size // 16)) if fp
                 else ImageFont.load_default())
    except Exception:
        f_name = f_amt = ImageFont.load_default()
    lines = []
    if name:
        lines.append((name, f_name, (255, 255, 255, 255)))
    if amount:
        lines.append((amount, f_amt, (255, 214, 130, 255)))
    if not lines:
        return
    probe = ImageDraw.Draw(frames[0])
    widths, heights = [], []
    for text, font, _c in lines:
        bb = _fa_textbbox(probe, text, font)
        widths.append(bb[2] - bb[0])
        heights.append(bb[3] - bb[1])
    pad_x, pad_y, gap = size // 24, size // 42, size // 64
    pw = max(widths) + pad_x * 2
    ph = sum(heights) + gap * (len(lines) - 1) + pad_y * 2
    x0 = (size - pw) // 2
    y0 = size - ph - size // 26
    for img in frames:
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=size // 32,
                            fill=(10, 12, 22, 205),
                            outline=(255, 255, 255, 70), width=2)
        cy = y0 + pad_y
        for (text, font, col), lh in zip(lines, heights):
            _fa_text(d, (size // 2, cy + lh // 2), text, font, col)
            cy += lh + gap


# ---------------- public render API ----------------

def render_frames(effect_id, avatar, name="", amount="", size=480, fps=24,
                  seed=11, on_frame=None, max_frames=None, font_path=None):
    """Render transparent RGBA frames for an effect.

    Frames are always composed at 480x480 (the effects' native canvas) and
    downscaled to `size` afterwards, so the look never changes with size.
    `fps` is kept for API compatibility (used by export_gif, not here).
    Returns a list of PIL RGBA images, or None if cancelled via on_frame.
    Not reentrant (uses module-level canvas globals).
    """
    global W, H, CX, AV, asp, _frame_cb, _frame_max
    if effect_id not in _FX_FUNCS:
        raise ValueError("unknown effect: %r" % (effect_id,))
    W = H = 480
    CX = W // 2
    AV = avatar.convert("RGBA")
    asp = AV.width / max(1, AV.height)
    random.seed(seed)
    np.random.seed(seed)
    _frame_cb, _frame_max = on_frame, max_frames
    try:
        frames, _native_fps, _fname = _FX_FUNCS[effect_id]()
    except _Cancelled:
        return None
    finally:
        _frame_cb, _frame_max = None, None
    if name or amount:
        _apply_name_pill(frames, name, amount, font_path)
    size = int(size)
    if size != 480:
        frames = [fr.resize((size, size), Image.LANCZOS) for fr in frames]
    return frames


# ---------------- Pillow-only transparent GIF export ----------------

def export_gif(frames, path, fps=24):
    """Export RGBA frames to a transparent GIF (Pillow only, no ffmpeg).

    Uses one shared 255-color palette sampled across the animation and
    reserves palette index 255 for transparency.
    Returns the output file size in bytes.
    """
    if not frames:
        raise ValueError("no frames to export")
    import math as _math
    w, h = frames[0].size
    step = max(1, len(frames) // 8)
    sample = frames[::step][:8] or frames[:1]
    cols = _math.ceil(_math.sqrt(len(sample)))
    rows = _math.ceil(len(sample) / cols)
    mosaic = Image.new("RGB", (w * cols, h * rows), (0, 0, 0))
    for i, fr in enumerate(sample):
        bg = Image.new("RGBA", fr.size, (0, 0, 0, 255))
        mosaic.paste(Image.alpha_composite(bg, fr).convert("RGB"),
                     ((i % cols) * w, (i // cols) * h))
    palette = mosaic.quantize(colors=255, method=Image.FASTOCTREE)
    pal_frames = []
    for fr in frames:
        transp = fr.getchannel("A").point(lambda v: 255 if v < 128 else 0)
        bg = Image.new("RGBA", fr.size, (0, 0, 0, 255))
        comp = Image.alpha_composite(bg, fr).convert("RGB")
        q = comp.quantize(palette=palette, dither=Image.FLOYDSTEINBERG)
        q.paste(255, transp)
        pal_frames.append(q)
    duration_ms = int(round(1000.0 / max(1, fps)))
    pal_frames[0].save(path, save_all=True, append_images=pal_frames[1:],
                       duration=duration_ms, loop=0, transparency=255,
                       disposal=1)
    return os.path.getsize(path)


__all__ = ["EFFECTS", "EFFECT_IDS", "effect_info", "render_frames",
           "export_gif", "default_avatar", "load_avatar_file",
           "remove_bg_floodfill"]
