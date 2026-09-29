#!/usr/bin/env python3
"""Headless smoke test for Donate Studio (classic + PRO packs).

- Renders a few frames of every effect with a sample Persian name/amount.
- Exports one 240px GIF through the app's export path and asserts it is a
  valid GIF with preserved transparency.
- PRO pack: 3 structural frames + gold-text presence over 60 frames at
  640x360, one Pillow export, and a native 1280x720 render sanity check.
- Instantiates the MainWindow offscreen and checks the effect list.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image

import donate_engine as eng
import donate_pro as proeng

NAME = "علی رضایی"
AMOUNT = "۵۰٬۰۰۰ تومان"


def main():
    avatar = eng.default_avatar()
    assert avatar.mode == "RGBA" and avatar.size[0] > 0
    print("avatar OK:", avatar.size)

    # ---- classic pack (v1, unchanged) ----
    assert len(eng.EFFECTS) == 8, len(eng.EFFECTS)
    for eid, fa, nframes, nfps in eng.EFFECTS:
        frames = eng.render_frames(eid, avatar, NAME, AMOUNT, size=240,
                                   seed=11, max_frames=4)
        assert frames is not None and len(frames) == 4, (eid, frames)
        for fr in frames:
            assert fr.mode == "RGBA" and fr.size == (240, 240), (eid, fr.size)
        # pill drawn: bottom-center must be opaque; a corner stays transparent
        assert frames[0].getpixel((120, 215))[3] > 200, eid
        assert frames[0].getpixel((5, 5))[3] == 0, eid
        print("effect OK: %-12s (%s) 4 frames" % (eid, fa))

    # export one GIF through the engine's export function
    frames = eng.render_frames("legendary", avatar, NAME, AMOUNT, size=240,
                               seed=11, max_frames=12)
    out = "/tmp/donate_studio_smoke.gif"
    size = eng.export_gif(frames, out, fps=15)
    assert os.path.isfile(out) and size > 1000, size
    g = Image.open(out)
    assert g.format == "GIF", g.format
    assert g.n_frames == 12, g.n_frames
    assert "transparency" in g.info, g.info
    alpha = g.convert("RGBA").getchannel("A")
    lo, hi = alpha.getextrema()
    assert lo < 128 and hi > 200, (lo, hi)  # transparency preserved
    print("export OK: %s (%d KB), %d frames, transparency preserved"
          % (out, size // 1024, g.n_frames))

    # ---- PRO pack ----
    assert len(proeng.EFFECTS) == 5, len(proeng.EFFECTS)
    corners = [(5, 5), (634, 5), (5, 354), (634, 354)]
    for eid, fa, nframes, nfps in proeng.EFFECTS:
        frames = proeng.render_frames(eid, avatar, NAME, AMOUNT,
                                      size=(640, 360), seed=11, max_frames=60)
        assert frames is not None and len(frames) == 60, (eid, frames)
        for fr in frames[:3]:
            assert fr.mode == "RGBA" and fr.size == (640, 360), (eid, fr.size)
        for cx, cy in corners:
            a = frames[0].getpixel((cx, cy))[3]
            assert a < 64, (eid, (cx, cy), a)  # corners stay transparent
        # gold text drawn somewhere in the first 2 seconds
        gold = 0
        for fr in frames[::6]:
            px = np.asarray(fr)
            mask = ((px[..., 0] > 200) & (px[..., 1] > 150)
                    & (px[..., 2] < 150) & (px[..., 3] > 128))
            gold += int(mask.sum())
        assert gold > 300, (eid, gold)
        print("pro OK: %-14s (%s) 60 frames, gold px=%d" % (eid, fa, gold))

    # native 1280x720 render sanity (3 frames)
    frames = proeng.render_frames("pro_jackpot", avatar, NAME, AMOUNT,
                                  size=(1280, 720), seed=11, max_frames=3)
    assert frames and frames[0].size == (1280, 720), "720p render"
    print("pro 720p OK: pro_jackpot renders natively at 1280x720")

    # square canvas sanity
    frames = proeng.render_frames("pro_vortex", avatar, NAME, AMOUNT,
                                  size=(720, 720), seed=11, max_frames=3)
    assert frames and frames[0].size == (720, 720), "square render"
    print("pro square OK: pro_vortex renders natively at 720x720")

    # export one PRO GIF through the Pillow path
    frames = proeng.render_frames("pro_fountain", avatar, NAME, AMOUNT,
                                  size=(320, 180), seed=11, max_frames=24)
    out2 = "/tmp/donate_studio_smoke_pro.gif"
    size2 = eng.export_gif(frames, out2, fps=15)
    g2 = Image.open(out2)
    assert g2.format == "GIF", g2.format
    # Pillow merges consecutive identical frames (adds their durations), so
    # the stored count can be slightly below the rendered count.
    assert 22 <= g2.n_frames <= 24, g2.n_frames
    assert "transparency" in g2.info, g2.info
    print("pro export OK: %s (%d KB), %d frames (Pillow dedup aware)"
          % (out2, size2 // 1024, g2.n_frames))

    # ---- offscreen GUI ----
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import app as appmod
    w = appmod.MainWindow()
    # 2 group headers + 8 classic + 5 pro
    assert w.effect_list.count() == 15, w.effect_list.count()
    assert w.preview is not None and w.btn_export is not None
    # select the first PRO effect and check param dispatch
    w.effect_list.setCurrentRow(10)
    p = w._current_params()
    assert p["effect_id"] == "pro_fountain", p["effect_id"]
    assert p["size"] == (1280, 720), p["size"]
    assert p["engine"] is proeng, p["engine"]
    w.effect_list.setCurrentRow(1)
    p = w._current_params()
    assert p["effect_id"] == "soul_harvest", p["effect_id"]
    assert p["size"] == 480 and p["engine"] is eng, (p["size"], p["engine"])
    w.close()
    print("MainWindow OK (offscreen, 15 rows, pro dispatch works)")

    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
