import sys
import os
import subprocess
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QSlider, QLabel, QPushButton
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtGui import QPainter, QPen, QColor


class ClickableSlider(QSlider):
    def __init__(self, parent):
        super().__init__(Qt.Horizontal)
        self.parent_ref = parent
        self.dragging_marker = None

    def pos_to_ms(self, x):
        if self.width() == 0:
            return 0
        return int((x / self.width()) * self.maximum())

    def mousePressEvent(self, e):
        if not self.parent_ref.video_path:
            return

        x = e.position().x()
        click_ms = self.pos_to_ms(x)

        # どのマーカーを掴むか判定
        if abs(click_ms - self.parent_ref.start_ms) < 1000:
            self.dragging_marker = "start"
        elif abs(click_ms - self.parent_ref.end_ms) < 1000:
            self.dragging_marker = "end"
        else:
            self.dragging_marker = "playhead"
            self.parent_ref.player.setPosition(click_ms)

        self.parent_ref.selected_marker = self.dragging_marker
        self.parent_ref.update_info()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if not self.parent_ref.video_path:
            return

        if self.dragging_marker is None:
            return

        x = e.position().x()
        ms = self.pos_to_ms(x)

        if self.dragging_marker == "playhead":
            self.parent_ref.player.setPosition(ms)

        elif self.dragging_marker == "start":
            self.parent_ref.start_ms = max(0, min(ms, self.parent_ref.end_ms))
            if self.parent_ref.player.position() < self.parent_ref.start_ms:
                self.parent_ref.player.setPosition(self.parent_ref.start_ms)

        elif self.dragging_marker == "end":
            self.parent_ref.end_ms = max(self.parent_ref.start_ms, ms)
            if self.parent_ref.player.position() > self.parent_ref.end_ms:
                self.parent_ref.player.setPosition(self.parent_ref.end_ms)

        self.parent_ref.update_info()
        self.update()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self.dragging_marker = None
        super().mouseReleaseEvent(e)

    def paintEvent(self, event):
        super().paintEvent(event)

        if self.maximum() == 0:
            return

        painter = QPainter(self)
        h = self.height()

        def pos_to_x(ms):
            return int((ms / self.maximum()) * self.width())

        # START
        painter.setPen(QPen(QColor(0, 200, 0), 3))
        x = pos_to_x(self.parent_ref.start_ms)
        painter.drawLine(x, 0, x, h)

        # END
        painter.setPen(QPen(QColor(220, 50, 50), 3))
        x = pos_to_x(self.parent_ref.end_ms)
        painter.drawLine(x, 0, x, h)


class DroppableVideoWidget(QVideoWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()

    def dropEvent(self, event):
        self.parent().dropEvent(event)


class VideoTrimmer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("videoccut")
        self.resize(900, 500)
        self.setAcceptDrops(True)

        self.video_path = None
        self.fps = 30
        self.start_ms = 0
        self.end_ms = 0
        self.selected_marker = "playhead"

        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)

        self.video_widget = QVideoWidget()
        self.video_widget = DroppableVideoWidget(self)
        self.player.setVideoOutput(self.video_widget)
        self.video_widget.setMinimumHeight(500)
        self.video_widget.setAcceptDrops(False)

        self.slider = ClickableSlider(self)
        self.slider.sliderMoved.connect(self.seek)

        self.info = QLabel("どうがを　つっこめ！")

        controls = QHBoxLayout()
        controls.addWidget(self.btn("-10秒", lambda: self.jump(-10000)))
        controls.addWidget(self.btn("-1秒", lambda: self.jump(-1000)))
        controls.addWidget(self.btn("-1f", lambda: self.jump(-self.frame_ms())))
        controls.addWidget(self.btn("▶", self.toggle_play))
        controls.addWidget(self.btn("+1f", lambda: self.jump(self.frame_ms())))
        controls.addWidget(self.btn("+1秒", lambda: self.jump(1000)))
        controls.addWidget(self.btn("+10秒", lambda: self.jump(10000)))

        saves = QHBoxLayout()
        saves.addWidget(self.btn("セーブ", self.save_av))
        saves.addWidget(self.btn("音声", self.save_audio))
        saves.addWidget(self.btn("動画", self.save_video))

        layout = QVBoxLayout()
        layout.addWidget(self.video_widget)
        layout.addWidget(self.slider)
        layout.addLayout(controls)
        layout.addLayout(saves)
        layout.addWidget(self.info)
        self.setLayout(layout)

        self.player.positionChanged.connect(self.update_slider)
        self.player.durationChanged.connect(self.set_duration)

    def btn(self, text, fn):
        b = QPushButton(text)
        b.clicked.connect(fn)
        return b

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()

    def dropEvent(self, event):
        path = event.mimeData().urls()[0].toLocalFile()
        if path.lower().endswith((".mp4", ".mov")):
            self.load_video(path)

    def load_video(self, path):
        self.video_path = path
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

        try:
            result = subprocess.check_output(
                ["ffprobe","-v","0","-select_streams","v:0",
                 "-show_entries","stream=r_frame_rate",
                 "-of","default=noprint_wrappers=1:nokey=1", path]
            ).decode().strip()
            num, den = result.split("/")
            self.fps = float(num) / float(den)
        except:
            self.fps = 30

    def set_duration(self, d):
        self.slider.setRange(0, d)
        self.start_ms = 0
        self.end_ms = d
        self.slider.update()

    def update_slider(self, pos):
        if pos > self.end_ms:
            self.player.setPosition(self.start_ms)
            return

        self.slider.blockSignals(True)
        self.slider.setValue(pos)
        self.slider.blockSignals(False)
        self.slider.update()
        self.update_info()

    def seek(self, pos):
        self.player.setPosition(pos)

    def frame_ms(self):
        return int(1000 / self.fps)

    def jump(self, delta):
        new_pos = self.player.position() + delta
        new_pos = max(self.start_ms, min(new_pos, self.end_ms))
        self.player.setPosition(new_pos)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Left:
            self.move_marker(-self.frame_ms())
        elif e.key() == Qt.Key_Right:
            self.move_marker(self.frame_ms())

        elif e.key() == Qt.Key_S:
            self.selected_marker = "start"
            self.start_ms = self.player.position()

        elif e.key() == Qt.Key_E:
            self.selected_marker = "end"
            self.end_ms = self.player.position()

        elif e.key() == Qt.Key_P:
            self.selected_marker = "playhead"

        elif e.key() == Qt.Key_Space:
            self.toggle_play()

        self.slider.update()
        self.update_info()

    def move_marker(self, delta):
        if self.selected_marker == "playhead":
            self.jump(delta)

        elif self.selected_marker == "start":
            self.start_ms = max(0, min(self.start_ms + delta, self.end_ms))

        elif self.selected_marker == "end":
            self.end_ms = max(self.start_ms, self.end_ms + delta)

    def update_info(self):
        self.info.setText(
            f"[{self.selected_marker}] START:{int(self.start_ms)} "
            f"END:{int(self.end_ms)} POS:{int(self.player.position())}"
        )

    def base_out(self, ext=None):
        base, old_ext = os.path.splitext(self.video_path)
        return base + "_edited" + (ext if ext else old_ext)

    def save_audio(self):
        self.run_ffmpeg(["-vn", "-acodec", "libmp3lame"], self.base_out(".mp3"))

    def save_video(self):
        self.run_ffmpeg(["-an", "-vcodec", "copy"], self.base_out(".mp4"))

    def save_av(self):
        self.run_ffmpeg(["-c", "copy"], self.base_out(".mp4"))

    def run_ffmpeg(self, extra, out):
        ss = str(self.start_ms / 1000)
        to = str(self.end_ms / 1000)

        cmd = [
            "ffmpeg","-y",
            "-ss", ss,
            "-to", to,
            "-i", self.video_path,
            *extra,
            out
        ]
        subprocess.run(cmd)
        self.info.setText(f"セーブ：{out}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = VideoTrimmer()
    w.show()
    sys.exit(app.exec())
