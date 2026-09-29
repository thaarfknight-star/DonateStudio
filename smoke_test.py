#!/usr/bin/env python3
"""Headless smoke test for Donate Studio.

- Renders a few frames of every effect with a sample Persian name/amount.
- Exports one 240px GIF through the app's export path and asserts it is a
  valid GIF with preserved transparency.
- Instantiates the MainWindow offscreen and checks the effect list.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image

import donate_engine as eng

NAME = "علی رضایی"
AMOUNT = "۵۰٬۰۰۰ تومان"


def main():
    avatar = eng.default_avatar()
    assert avatar.mode == "RGBA" and avatar.size[0] > 0
    print("avatar OK:", avatar.size)

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

    # offscreen GUI
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import app as appmod
    w = appmod.MainWindow()
    assert w.effect_list.count() == 8, w.effect_list.count()
    assert w.preview is not None and w.btn_export is not None
    w.close()
    print("MainWindow OK (offscreen, 8 effects listed)")

    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
