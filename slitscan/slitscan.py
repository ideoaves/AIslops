import sys
import cv2
import numpy as np
from collections import deque

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton,
    QSlider, QFileDialog, QVBoxLayout, QHBoxLayout,
    QProgressDialog, QMessageBox, QComboBox, QCheckBox,
    QStyle, QStyleOptionSlider
)

# 書き出しサイズ
EXPORT_W = 1920
EXPORT_H = 1080

RANGE_COLOR = QColor(60, 130, 246, 150)


class PosSlider(QSlider):

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.in_frame = 0
        self.out_frame = 0

    def set_marks(self, in_frame, out_frame):
        self.in_frame = in_frame
        self.out_frame = out_frame
        self.update()

    def _value_x(self, value, groove, handle_w):
        span = groove.width() - handle_w
        offset = QStyle.sliderPositionFromValue(
            self.minimum(), self.maximum(), value, span
        )
        return groove.x() + offset + handle_w / 2

    def paintEvent(self, event):
        super().paintEvent(event)

        if self.maximum() <= self.minimum() or self.out_frame <= self.in_frame:
            return

        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        style = self.style()
        groove = style.subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
        handle = style.subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)

        x0 = self._value_x(self.in_frame, groove, handle.width())
        x1 = self._value_x(self.out_frame, groove, handle.width())

        h = 6.0
        band = QRectF(x0, groove.center().y() - h / 2 + 1, max(1.0, x1 - x0), h)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(RANGE_COLOR)
        p.drawRoundedRect(band, 2, 2)


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.cap = None
        self.path = None
        self.frame_count = 0
        self.width = 0
        self.height = 0
        self.fps = 30

        self.in_frame = 0
        self.out_frame = 0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)

        self.preview = QLabel("動画開いてください")
        self.preview.setAlignment(Qt.AlignCenter)

        self.play_btn = QPushButton("再生")
        self.play_btn.setEnabled(False)
        
        self.open_btn = QPushButton("動画選択")
        self.export_btn = QPushButton("書き出し")
        self.export_btn.setEnabled(False)

        self.set_in_btn = QPushButton("In")
        self.set_out_btn = QPushButton("Out")
        self.reset_range_btn = QPushButton("Reset")
        for b in (self.set_in_btn, self.set_out_btn, self.reset_range_btn):
            b.setEnabled(False)
        self.range_lbl = QLabel()


        self.mode = QComboBox()
        self.mode.addItems(["ディスプレイスモード", "スリットモード"])

        self.slitpos = QSlider(Qt.Horizontal)
        self.slitpos.setRange(0, 1000)
        self.slitpos.setValue(500)
        self.slitpos.setEnabled(False)
        self.slitpos_end = QSlider(Qt.Horizontal)
        self.slitpos_end.setRange(0, 1000)
        self.slitpos_end.setValue(500)
        self.slitpos_end.setEnabled(False)
        self.slitpos_anim = QCheckBox("アニメーション")
        self.slitpos_anim.setEnabled(False)
        self.slitpos_lbl = QLabel("スリットの位置")

        self.direction = QComboBox()
        self.direction.addItems(["縦", "横"])

        self.subframe = QCheckBox("低フレーム動画用の補完")
        self.subframe.setChecked(True)

        self.pos = PosSlider()

        self.maxoff = QSlider(Qt.Horizontal)
        self.maxoff.setRange(0, 600)
        self.maxoff.setValue(120)
        self.maxoff_end = QSlider(Qt.Horizontal)
        self.maxoff_end.setRange(0, 600)
        self.maxoff_end.setValue(120)
        self.maxoff_end.setEnabled(False)
        self.maxoff_anim = QCheckBox("アニメーション")
        self.maxoff_lbl = QLabel("最大ズレ")

        self.strength = QSlider(Qt.Horizontal)
        self.strength.setRange(1, 200)
        self.strength.setValue(0)

        lay = QVBoxLayout(self)
        lay.addWidget(self.preview)
        lay.addWidget(self.pos)
        
        btn_lay = QHBoxLayout()
        btn_lay.addWidget(self.play_btn)
        btn_lay.addWidget(self.open_btn)
        btn_lay.addWidget(self.export_btn)
        lay.addLayout(btn_lay)

        range_lay = QHBoxLayout()
        range_lay.addWidget(self.set_in_btn)
        range_lay.addWidget(self.set_out_btn)
        range_lay.addWidget(self.reset_range_btn)
        range_lay.addWidget(self.range_lbl, 1)
        lay.addLayout(range_lay)

        mode_lay = QHBoxLayout()
        mode_lay.addWidget(QLabel("モード"))
        mode_lay.addWidget(self.mode)
        mode_lay.addWidget(QLabel("スリット方向"))
        mode_lay.addWidget(self.direction)
        mode_lay.addWidget(self.subframe)
        mode_lay.addStretch(1)
        lay.addLayout(mode_lay)

        sp_head = QHBoxLayout()
        sp_head.addWidget(self.slitpos_lbl)
        sp_head.addWidget(self.slitpos_anim)
        sp_head.addStretch(1)
        lay.addLayout(sp_head)
        lay.addWidget(self.slitpos)
        lay.addWidget(self.slitpos_end)

        mo_head = QHBoxLayout()
        mo_head.addWidget(self.maxoff_lbl)
        mo_head.addWidget(self.maxoff_anim)
        mo_head.addStretch(1)
        lay.addLayout(mo_head)
        lay.addWidget(self.maxoff)
        lay.addWidget(self.maxoff_end)

        lay.addWidget(QLabel("カーブ"))
        lay.addWidget(self.strength)

        self.open_btn.clicked.connect(self.open_video)
        self.play_btn.clicked.connect(self.toggle_play)
        self.export_btn.clicked.connect(self.export_video)
        self.set_in_btn.clicked.connect(self.set_in)
        self.set_out_btn.clicked.connect(self.set_out)
        self.reset_range_btn.clicked.connect(self.reset_range)
        self.pos.valueChanged.connect(self.update_preview)
        self.strength.valueChanged.connect(self.update_preview)
        self.direction.currentIndexChanged.connect(self.update_preview)
        self.subframe.toggled.connect(self.update_preview)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.maxoff.valueChanged.connect(self.update_preview)
        self.maxoff_end.valueChanged.connect(self.update_preview)
        self.slitpos.valueChanged.connect(self.update_preview)
        self.slitpos_end.valueChanged.connect(self.update_preview)
        self.maxoff_anim.toggled.connect(self.anim_changed)
        self.slitpos_anim.toggled.connect(self.anim_changed)

    def is_vertical(self):
        return self.direction.currentIndex() == 0

    def is_strip(self):
        return self.mode.currentIndex() == 1

    def axis_len(self):
        return self.width if self.is_vertical() else self.height

    def anim_t(self, idx):
        span = self.out_frame - self.in_frame
        if span <= 0:
            return 0.0
        t = (idx - self.in_frame) / span
        return float(min(1.0, max(0.0, t)))

    def anim_value(self, slider, end_slider, check, idx):
        v0 = float(slider.value())
        if not check.isChecked():
            return v0
        v1 = float(end_slider.value())
        return v0 + (v1 - v0) * self.anim_t(idx)

    def maxoff_at(self, idx):
        return self.anim_value(self.maxoff, self.maxoff_end, self.maxoff_anim, idx)

    def slitpos_at(self, idx):
        return self.anim_value(self.slitpos, self.slitpos_end, self.slitpos_anim, idx)

    def slit_index(self, n, idx):
        if n <= 0:
            return 0
        return int(round(self.slitpos_at(idx) / 1000 * (n - 1)))

    def mode_changed(self):
        strip = self.is_strip()
        self.slitpos.setEnabled(strip)
        self.slitpos_anim.setEnabled(strip)
        self.slitpos_end.setEnabled(strip and self.slitpos_anim.isChecked())
        self.update_preview()

    def anim_changed(self):
        self.maxoff_end.setEnabled(self.maxoff_anim.isChecked())
        self.slitpos_end.setEnabled(self.is_strip() and self.slitpos_anim.isChecked())
        self.update_preview()

    def update_param_labels(self, idx):
        axis = "x" if self.is_vertical() else "y"
        px = self.slit_index(self.axis_len(), idx)
        sp = f"スリット位置 ({axis} = {px} px)"
        if self.slitpos_anim.isChecked():
            sp += f"   In {self.slitpos.value()} → Out {self.slitpos_end.value()}  /1000"
        self.slitpos_lbl.setText(sp)

        mo = f"最大の時間差 ({self.maxoff_at(idx):.1f} F)"
        if self.maxoff_anim.isChecked():
            mo += f"   In {self.maxoff.value()} → Out {self.maxoff_end.value()}"
        self.maxoff_lbl.setText(mo)

    def offsets(self, idx):
        n = self.axis_len()
        x = np.linspace(0, 1, n)
        s = self.strength.value() / 10
        c = 1 / (1 + np.exp(-s * (x - 0.5)))
        span = c.max() - c.min()
        if span > 0:
            c = (c - c.min()) / span
        return (c * self.maxoff_at(idx)).astype(np.float32)

    def ring_size(self):
        m = float(self.maxoff.value())
        if self.maxoff_anim.isChecked():
            m = max(m, float(self.maxoff_end.value()))
        return int(np.ceil(m)) + 2

    def open_video(self):
        p, _ = QFileDialog.getOpenFileName(self, "", "", "Video (*.mp4 *.mov *.mkv *.avi)")
        if not p:
            return

        self.timer.stop()
        self.play_btn.setText("再生")

        self.path = p
        self.cap = cv2.VideoCapture(p)
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        
        self.pos.setMaximum(max(0, self.frame_count - 1))
        self.pos.setValue(0)

        self.reset_range()
        self.mode_changed()

        self.play_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        self.set_in_btn.setEnabled(True)
        self.set_out_btn.setEnabled(True)
        self.reset_range_btn.setEnabled(True)
        self.update_preview()

    def frame_to_tc(self, f):
        t = f / (self.fps or 30)
        m, s = divmod(t, 60)
        return f"{int(m):02d}:{s:06.3f}"

    def update_range_label(self):
        n = self.out_frame - self.in_frame + 1
        self.range_lbl.setText(
            f"In {self.frame_to_tc(self.in_frame)} (F {self.in_frame})  /  "
            f"Out {self.frame_to_tc(self.out_frame)} (F {self.out_frame})  /  "
            f"F {n}"
        )

    def set_in(self):
        self.in_frame = self.pos.value()
        if self.out_frame < self.in_frame:
            self.out_frame = self.in_frame
        self.range_changed()

    def set_out(self):
        self.out_frame = self.pos.value()
        if self.in_frame > self.out_frame:
            self.in_frame = self.out_frame
        self.range_changed()

    def reset_range(self):
        self.in_frame = 0
        self.out_frame = max(0, self.frame_count - 1)
        self.range_changed()

    def range_changed(self):
        self.pos.set_marks(self.in_frame, self.out_frame)
        self.update_range_label()
        self.update_preview()

    def toggle_play(self):
        if self.timer.isActive():
            self.timer.stop()
            self.play_btn.setText("再生")
        else:
            interval = int(1000 / self.fps)
            self.timer.start(interval)
            self.play_btn.setText("停止")

    def next_frame(self):
        current = self.pos.value()
        if self.in_frame <= current < self.out_frame:
            self.pos.setValue(current + 1)
        else:
            self.pos.setValue(self.in_frame)

    def update_preview(self):
        if self.cap is None:
            return

        idx = self.pos.value()
        self.update_param_labels(idx)
        offs = self.offsets(idx)

        start = max(0, idx - (self.ring_size() - 1))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, start)

        ring = []
        for _ in range(idx - start + 1):
            ok, f = self.cap.read()
            if not ok:
                break
            ring.append(f)

        if not ring:
            return

        out = self.compose(ring, offs, idx)

        rgb = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
        q = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888)
        self.preview.setPixmap(QPixmap.fromImage(q).scaled(
            900, 600, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def compose(self, ring, offs, idx):
        n = len(ring)

        if self.subframe.isChecked():
            base = np.floor(offs).astype(np.int32)
            alpha = (offs - base).astype(np.float32)
        else:
            base = np.rint(offs).astype(np.int32)
            alpha = np.zeros(offs.shape, np.float32)

        base = np.clip(base, 0, n - 1)

        out = np.empty_like(ring[-1])
        vertical = self.is_vertical()
        out_v = out.transpose(1, 0, 2) if vertical else out

        def view(frame):
            return frame.transpose(1, 0, 2) if vertical else frame

        strip = self.is_strip()
        slit = self.slit_index(len(offs), idx)

        for o in np.unique(base):
            sel = np.flatnonzero(base == o)
            o_next = min(o + 1, n - 1)

            src = slit if strip else sel
            s0 = view(ring[-1 - o])[src]

            a = alpha[sel]
            if o_next == o or not a.any():
                out_v[sel] = s0
                continue

            s1 = view(ring[-1 - o_next])[src]

            w = a[:, None, None]
            blended = s0.astype(np.float32) * (1.0 - w) + s1.astype(np.float32) * w
            out_v[sel] = blended.round().astype(np.uint8)

        return out

    def fit_to_export_size(self, img):
        h, w = img.shape[:2]
        if (w, h) == (EXPORT_W, EXPORT_H):
            return img

        scale = min(EXPORT_W / w, EXPORT_H / h)
        nw = max(1, int(round(w * scale)))
        nh = max(1, int(round(h * scale)))
        interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
        resized = cv2.resize(img, (nw, nh), interpolation=interp)

        canvas = np.zeros((EXPORT_H, EXPORT_W, 3), np.uint8)
        y = (EXPORT_H - nh) // 2
        x = (EXPORT_W - nw) // 2
        canvas[y:y + nh, x:x + nw] = resized
        return canvas

    def export_video(self):
        if self.path is None:
            return

        self.timer.stop()
        self.play_btn.setText("Play")

        if self.out_frame < self.in_frame:
            return

        save, _ = QFileDialog.getSaveFileName(self, "", "", "MP4 (*.mp4)")
        if not save:
            return

        ring_size = self.ring_size()

        read_start = max(0, self.in_frame - (ring_size - 1))

        cap = cv2.VideoCapture(self.path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, read_start)

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(save, fourcc, self.fps, (EXPORT_W, EXPORT_H))
        if not writer.isOpened():
            cap.release()
            QMessageBox.critical(self, "", "書き出し先を開けませんでした。")
            return

        total = self.out_frame - self.in_frame + 1
        progress = QProgressDialog("書き出し中...", "キャンセル", 0, total, self)
        progress.setWindowModality(Qt.WindowModal)

        ring = deque(maxlen=ring_size)
        idx = read_start
        written = 0

        while idx <= self.out_frame:
            ok, frame = cap.read()
            if not ok:
                break
            ring.append(frame)

            if idx >= self.in_frame:
                offs = self.offsets(idx)
                writer.write(self.fit_to_export_size(self.compose(ring, offs, idx)))
                written += 1
                progress.setValue(written)
                if progress.wasCanceled():
                    break

            idx += 1

        cap.release()
        writer.release()
        progress.close()

        if written:
            QMessageBox.information(
                self, "", f"{written} フレームを書き出しました。\n{save}"
            )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = App()
    w.resize(1000, 800)
    w.show()
    sys.exit(app.exec())