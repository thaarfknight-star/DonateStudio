#!/usr/bin/env python3
"""Donate Studio — desktop generator for transparent donation-alert GIFs.

Persian RTL UI, dark streamer theme. Renders with donate_engine (Pillow-only,
no ffmpeg) in a background thread and exports transparent GIFs for OBS /
Streamlabs overlays.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QImage, QPixmap, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QLineEdit, QListWidget, QListWidgetItem, QComboBox,
    QSlider, QProgressBar, QFileDialog, QMessageBox, QGroupBox,
)

import donate_engine as eng
import donate_pro as proeng

OUT_DIR = os.path.expanduser("~/workspace/your_files/donate-gifs")

STYLESHEET = """
QWidget { background: #1b1e26; color: #e8eaf0; font-size: 14px; }
QGroupBox { border: 1px solid #3d465c; border-radius: 8px; margin-top: 14px;
            font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top right;
                  right: 12px; padding: 0 6px; color: #9fd8c9; }
QPushButton { background: #2d3342; border: 1px solid #3d465c; border-radius: 8px;
              padding: 8px 14px; }
QPushButton:hover { background: #3a4257; }
QPushButton:disabled { color: #6b7280; background: #232833; }
QPushButton#primary { background: #2f6f5e; border-color: #3f8f78; font-weight: bold; }
QPushButton#primary:hover { background: #38846f; }
QLineEdit, QComboBox, QListWidget, QSlider { background: #242936;
    border: 1px solid #3d465c; border-radius: 6px; padding: 6px; }
QListWidget::item { padding: 8px; }
QListWidget::item:selected { background: #4a5a8a; border-radius: 4px; }
QProgressBar { border: 1px solid #3d465c; border-radius: 6px; text-align: center;
               background: #242936; }
QProgressBar::chunk { background: #2f6f5e; border-radius: 4px; }
QLabel#preview { border: 1px dashed #3d465c; border-radius: 8px; }
QLabel#status { color: #9aa3b2; }
"""


def pil_to_pixmap(im):
    im = im.convert("RGBA")
    raw = im.tobytes("raw", "RGBA")
    qimg = QImage(raw, im.width, im.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


class RenderWorker(QThread):
    """Render and/or export in the background. Cancel-safe via on_frame hook."""
    progress = Signal(int)
    done = Signal(object)
    error = Signal(str)

    def __init__(self, mode, **kw):
        super().__init__()
        self.mode = mode
        self.kw = kw
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            kw = dict(self.kw)
            out_path = kw.pop("out_path", None)
            frames = kw.pop("frames", None)
            engine = kw.pop("engine", eng)
            if frames is None:
                def cb(i, n):
                    self.progress.emit(int(100 * i / max(1, n)))
                    return not self._cancel

                kw["on_frame"] = cb
                frames = engine.render_frames(**kw)
                if frames is None or self._cancel:
                    return  # cancelled quietly
            if self.mode == "render":
                self.done.emit(("frames", frames))
            else:
                size = eng.export_gif(frames, out_path, fps=kw.get("fps", 24))
                self.done.emit(("file", out_path, size))
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("دونیت استودیو — Donate Studio")
        self.resize(1060, 730)
        self.frames = None
        self.params_key = None
        self.avatar = eng.default_avatar()
        self.worker = None
        self.frame_idx = 0
        self.playing = False
        self._build_ui()
        self._refresh_default_path()

    # ---------------- UI ----------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setSpacing(12)

        # ---- settings panel (right side in RTL) ----
        box = QGroupBox("تنظیمات")
        box.setFixedWidth(330)
        v = QVBoxLayout(box)

        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(140, 140)
        self.avatar_label.setAlignment(Qt.AlignCenter)
        self.avatar_label.setStyleSheet(
            "border: 1px solid #3d465c; border-radius: 8px;")
        v.addWidget(self.avatar_label, alignment=Qt.AlignCenter)
        self._update_avatar_thumb()

        btn_avatar = QPushButton("انتخاب آواتار")
        btn_avatar.clicked.connect(self.pick_avatar)
        v.addWidget(btn_avatar)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("مثلاً: علی")
        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("مثلاً: ۵۰٬۰۰۰ تومان")
        form.addRow("نام دونیت‌کننده", self.name_edit)
        form.addRow("مبلغ", self.amount_edit)
        v.addLayout(form)

        v.addWidget(QLabel("افکت"))
        self.effect_list = QListWidget()
        self._effect_entries = []  # ("header", None) | ("classic"|"pro", eid)

        def _add_header(text):
            it = QListWidgetItem(text)
            it.setFlags(Qt.NoItemFlags)
            fnt = it.font()
            fnt.setBold(True)
            it.setFont(fnt)
            it.setForeground(QColor("#9fd8c9"))
            self.effect_list.addItem(it)
            self._effect_entries.append(("header", None))

        def _add_fx(kind, eid, fa):
            self.effect_list.addItem(fa)
            self._effect_entries.append((kind, eid))

        _add_header("━━ پک کلاسیک ━━")
        for _eid, fa, _n, _f in eng.EFFECTS:
            _add_fx("classic", _eid, fa)
        _add_header("━━ پک حرفه‌ای ━━")
        for _eid, fa, _n, _f in proeng.EFFECTS:
            _add_fx("pro", _eid, fa)
        self.effect_list.setCurrentRow(1)
        self.effect_list.currentRowChanged.connect(self._on_effect_changed)
        v.addWidget(self.effect_list)

        row2 = QHBoxLayout()
        self.size_combo = QComboBox()
        self.size_combo.addItems(["240", "360", "480", "720×720", "1280×720"])
        self.size_combo.setCurrentText("480")
        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["15", "24", "30"])
        row2.addWidget(QLabel("اندازه"))
        row2.addWidget(self.size_combo)
        row2.addWidget(QLabel("فریم‌ریت"))
        row2.addWidget(self.fps_combo)
        v.addLayout(row2)

        v.addStretch(1)
        root.addWidget(box)

        # ---- preview panel ----
        pbox = QGroupBox("پیش‌نمایش")
        pv = QVBoxLayout(pbox)

        self.preview = QLabel("هنوز رندر نشده")
        self.preview.setObjectName("preview")
        self.preview.setFixedSize(430, 430)
        self.preview.setAlignment(Qt.AlignCenter)
        pv.addWidget(self.preview, alignment=Qt.AlignCenter)

        ctrl = QHBoxLayout()
        self.btn_play = QPushButton("▶ پخش")
        self.btn_play.setEnabled(False)
        self.btn_play.clicked.connect(self.toggle_play)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._on_scrub)
        ctrl.addWidget(self.btn_play)
        ctrl.addWidget(self.slider)
        pv.addLayout(ctrl)

        brow = QHBoxLayout()
        self.btn_render = QPushButton("رندر پیش‌نمایش")
        self.btn_render.setObjectName("primary")
        self.btn_render.clicked.connect(self.start_render)
        self.btn_export = QPushButton("خروجی گیف شفاف")
        self.btn_export.clicked.connect(self.start_export)
        self.btn_cancel = QPushButton("لغو")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_work)
        brow.addWidget(self.btn_render)
        brow.addWidget(self.btn_export)
        brow.addWidget(self.btn_cancel)
        pv.addLayout(brow)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        pv.addWidget(self.progress)

        pathrow = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(40)
        btn_browse.clicked.connect(self.browse_path)
        pathrow.addWidget(QLabel("مسیر خروجی"))
        pathrow.addWidget(self.path_edit)
        pathrow.addWidget(btn_browse)
        pv.addLayout(pathrow)

        self.status = QLabel("آماده")
        self.status.setObjectName("status")
        pv.addWidget(self.status)
        pv.addStretch(1)
        root.addWidget(pbox, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._on_effect_changed(1)  # default fps per effect + default path

    # ---------------- params ----------------

    def _effect_meta(self, kind, eid):
        src = proeng.EFFECTS if kind == "pro" else eng.EFFECTS
        for e in src:
            if e[0] == eid:
                return e
        return None

    def _current_params(self):
        row = max(0, self.effect_list.currentRow())
        kind, payload = self._effect_entries[row]
        if kind == "header":  # shouldn't happen; fall back to first classic
            kind, payload = "classic", eng.EFFECTS[0][0]
        eid = payload
        if kind == "pro":
            engine = proeng
            st = self.size_combo.currentText()
            if "×" in st:
                ww, hh = st.split("×")
                size = (int(ww), int(hh))
            else:
                size = int(st)
        else:
            engine = eng
            size = int(self.size_combo.currentText())
        return {
            "engine": engine,
            "effect_id": eid,
            "avatar": self.avatar,
            "name": self.name_edit.text().strip(),
            "amount": self.amount_edit.text().strip(),
            "size": size,
            "fps": int(self.fps_combo.currentText()),
            "seed": 11,
        }

    def _params_key(self, p):
        return (p["effect_id"], p["size"], p["name"], p["amount"],
                id(p["avatar"]))

    def _on_effect_changed(self, row):
        if 0 <= row < len(self._effect_entries):
            kind, payload = self._effect_entries[row]
            if kind != "header":
                meta = self._effect_meta(kind, payload)
                if meta:
                    self.fps_combo.setCurrentText(str(meta[3]))
                    if kind == "pro":
                        self.size_combo.setCurrentText("1280×720")
                    else:
                        self.size_combo.setCurrentText("480")
        self._refresh_default_path()

    def _refresh_default_path(self):
        row = max(0, self.effect_list.currentRow())
        kind, payload = self._effect_entries[row]
        eid = payload if kind != "header" else eng.EFFECTS[0][0]
        ts = time.strftime("%Y%m%d_%H%M%S")
        os.makedirs(OUT_DIR, exist_ok=True)
        self.path_edit.setText(
            os.path.join(OUT_DIR, "studio_%s_%s.gif" % (eid, ts)))

    def browse_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "ذخیره گیف", self.path_edit.text(),
            "GIF (*.gif)")
        if path:
            if not path.lower().endswith(".gif"):
                path += ".gif"
            self.path_edit.setText(path)

    def pick_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "انتخاب آواتار", os.path.expanduser("~"),
            "تصویر (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        try:
            self.avatar = eng.load_avatar_file(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "خطا", "آواتار باز نشد:\n%s" % e)
            return
        self._update_avatar_thumb()
        self.frames = None
        self.params_key = None
        self.status.setText("آواتار عوض شد — دوباره رندر بگیرید")

    def _update_avatar_thumb(self):
        thumb = self.avatar.copy()
        thumb.thumbnail((132, 132), Image.LANCZOS)
        self.avatar_label.setPixmap(pil_to_pixmap(thumb))

    # ---------------- render / export ----------------

    def _set_working(self, working, label):
        for w in (self.btn_render, self.btn_export, self.effect_list,
                  self.size_combo, self.fps_combo, self.name_edit,
                  self.amount_edit):
            w.setEnabled(not working)
        self.btn_cancel.setEnabled(working)
        if working:
            self.progress.setValue(0)
        self.status.setText(label)

    def start_render(self):
        if self.worker and self.worker.isRunning():
            return
        params = self._current_params()
        self.worker = RenderWorker("render", **params)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.done.connect(self._on_render_done)
        self.worker.error.connect(self._on_error)
        self._set_working(True, "در حال رندر…")
        self.worker.start()

    def start_export(self):
        if self.worker and self.worker.isRunning():
            return
        params = self._current_params()
        out = self.path_edit.text().strip()
        if not out:
            self._refresh_default_path()
            out = self.path_edit.text().strip()
        kw = dict(params)
        kw["out_path"] = out
        if self.frames and self.params_key == self._params_key(params):
            kw["frames"] = self.frames  # reuse cached render
        self.worker = RenderWorker("export", **kw)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.done.connect(self._on_export_done)
        self.worker.error.connect(self._on_error)
        self._set_working(True, "در حال ساخت گیف…")
        self.worker.start()

    def cancel_work(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status.setText("در حال لغو…")

    def _on_render_done(self, payload):
        _kind, frames = payload
        self.frames = frames
        self.params_key = self._params_key(self._current_params())
        self._set_working(False, "رندر شد: %d فریم" % len(frames))
        self.progress.setValue(100)
        self.frame_idx = 0
        self.slider.setEnabled(True)
        self.slider.setRange(0, len(frames) - 1)
        self.slider.setValue(0)
        self.btn_play.setEnabled(True)
        self._show_frame(0)
        self.playing = True
        self.btn_play.setText("⏸ توقف")
        self.timer.start(1000 // max(1, int(self.fps_combo.currentText())))

    def _on_export_done(self, payload):
        _kind, path, size = payload
        self._set_working(False, "آماده")
        self.progress.setValue(100)
        self._refresh_default_path()
        QMessageBox.information(
            self, "خروجی گیف",
            "فایل ساخته شد:\n%s\nحجم: %d کیلوبایت" % (path, size // 1024))

    def _on_error(self, msg):
        self._set_working(False, "آماده")
        QMessageBox.warning(self, "خطا", "خطا رخ داد:\n%s" % msg)

    # ---------------- preview playback ----------------

    def _show_frame(self, i):
        if not self.frames:
            return
        pm = pil_to_pixmap(self.frames[i]).scaled(
            410, 410, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(pm)

    def _tick(self):
        if not self.frames or not self.playing:
            return
        self.frame_idx = (self.frame_idx + 1) % len(self.frames)
        self.slider.blockSignals(True)
        self.slider.setValue(self.frame_idx)
        self.slider.blockSignals(False)
        self._show_frame(self.frame_idx)

    def _on_scrub(self, v):
        if self.frames and 0 <= v < len(self.frames):
            self.frame_idx = v
            self._show_frame(v)

    def toggle_play(self):
        if not self.frames:
            return
        self.playing = not self.playing
        self.btn_play.setText("⏸ توقف" if self.playing else "▶ پخش")
        if self.playing:
            self.timer.start(1000 // max(1, int(self.fps_combo.currentText())))
        else:
            self.timer.stop()


def main():
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    app.setStyleSheet(STYLESHEET)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
