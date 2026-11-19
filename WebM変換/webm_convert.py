from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

HERE = Path(__file__).resolve().parent

EXTENSIONS = {
    ".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".flv", ".f4v", ".mpg",
    ".mpeg", ".mpe", ".m1v", ".m2v", ".ts", ".m2ts", ".mts", ".tod", ".vob", ".3gp",
    ".3g2", ".ogv", ".ogm", ".asf", ".rm", ".rmvb", ".divx", ".dv", ".mxf", ".amv",
    ".mpv",
}

FORMATS = ("webm", "mp4")
EXT = {"webm": ".webm", "mp4": ".mp4"}

PROGRESS_RE = re.compile(r"out_time_(?:us|ms)=(\d+)")


class Cancelled(Exception):
    pass


def echo(message: str, _level: str = "info") -> None:
    if sys.stdout:
        print(message, flush=True)

def ffmpeg_paths() -> tuple[str, str]:
    found = [shutil.which(name) for name in ("ffmpeg", "ffprobe")]
    if not all(found):
        raise RuntimeError("ffmpegがないよ")
    return found[0], found[1]  # type: ignore[return-value]


def hidden() -> dict:
    if os.name != "nt":
        return {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": info, "creationflags": 0x08000000}  # CREATE_NO_WINDOW


@dataclass
class Info:
    width: int
    height: int
    duration: float
    fps: float = 30.0


def probe(path: Path) -> Optional[Info]:
    args = [ffmpeg_paths()[1], "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate:format=duration",
            "-of", "default=noprint_wrappers=1:nokey=0", "--", str(path)]
    try:
        out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", **hidden())
    except OSError:
        return None
    if out.returncode:
        return None

    values = dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)
    try:
        width, height = int(values["width"]), int(values["height"])
    except (KeyError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    try:
        duration = float(values.get("duration") or 0)
    except ValueError:
        duration = 0.0
    return Info(width, height, duration, parse_fps(values.get("r_frame_rate", "")))


def parse_fps(raw: str) -> float:
    try:
        num, den = (float(part) for part in raw.split("/", 1))
    except ValueError:
        return 30.0
    return num / den if num > 0 and den > 0 else 30.0

def corner_color(src: Path, duration: float, offset: float = 0.0) -> Optional[str]:
    ffmpeg = ffmpeg_paths()[0]
    chain = r"crop=w=max(2\,iw/32):h=max(2\,ih/32):x=0:y=0,scale=1:1:flags=area"
    raw = Path(tempfile.gettempdir()) / f"corner_{uuid.uuid4().hex}.raw"
    inside = offset + (min(duration * 0.1, 10.0) if duration > 0 else 0.0)

    try:
        for seek in dict.fromkeys((inside, offset)):
            args = [ffmpeg, "-hide_banner", "-nostats", "-loglevel", "error", "-y"]
            if seek > 0.05:
                args += ["-ss", f"{seek:.3f}"]
            args += ["-i", str(src), "-vf", chain, "-frames:v", "1", "-an", "-sn", "-dn",
                     "-f", "rawvideo", "-pix_fmt", "rgb24", str(raw)]
            try:
                done = subprocess.run(args, capture_output=True, **hidden())
            except OSError:
                return None
            if done.returncode == 0 and raw.exists():
                data = raw.read_bytes()
                if len(data) >= 3:
                    return f"0x{data[0]:02X}{data[1]:02X}{data[2]:02X}"
        return None
    finally:
        raw.unlink(missing_ok=True)


def normalize_color(value: str) -> str:
    text = value.strip().lstrip("#")
    text = text[2:] if text[:2].lower() == "0x" else text
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", text):
        raise ValueError(f"余白色は #RRGGBB 形式で: {value}")
    return f"0x{text.upper()}"

def even(value: int) -> int:
    return 0 if value <= 0 else value - (value % 2)


def stamp(ms: float) -> str:
    ms = max(0, int(ms))
    return f"{ms // 60000:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def resolve_size(info: Info, width: int, height: int, max_size: int) -> tuple[int, int]:
    if max_size > 0:
        return (0, max_size) if info.height > info.width else (max_size, 0)
    return width, height


def scale_filter(width: int, height: int, pad: str = "0x000000") -> str:
    if width > 0 and height > 0:
        return (f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={pad},setsar=1")
    if width > 0:
        return f"scale={width}:-2:flags=lanczos,setsar=1"
    if height > 0:
        return f"scale=-2:{height}:flags=lanczos,setsar=1"
    # サイズ指定なし: 元のまま。yuv420p 用に奇数サイズだけ切り詰める
    return "scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos,setsar=1"

def target_size(info: Info, width: int, height: int) -> tuple[int, int]:
    if width > 0 and height > 0:
        return width, height
    if width > 0:
        return width, even(round(info.height * width / info.width))
    if height > 0:
        return even(round(info.width * height / info.height)), height
    return even(info.width), even(info.height)


def x264_crf(crf: int) -> int:
    """VP9 の CRF (0-63) を x264 の CRF (0-51) の同等品質へ寄せる。"""
    return max(0, min(51, crf - 9))


def encode_args(fmt: str, crf: int, audio_kbps: int, mute: bool) -> list[str]:
    """コーデック・音声・コンテナの指定をまとめて返す。"""
    if fmt == "mp4":
        audio = ["-an"] if mute else ["-map", "0:a:0?",
                                      "-c:a", "aac", "-b:a", f"{audio_kbps}k"]
        return ["-c:v", "libx264", "-preset", "medium", "-crf", str(x264_crf(crf)),
                *audio, "-movflags", "+faststart", "-f", "mp4"]
    audio = ["-an"] if mute else ["-map", "0:a:0?",
                                  "-c:a", "libopus", "-b:a", f"{audio_kbps}k"]
    return ["-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0", "-row-mt", "1",
            "-deadline", "good", "-cpu-used", "2", *audio, "-f", "webm"]

@dataclass
class Settings:
    source: Path
    output_dir: Path
    width: int = 0
    height: int = 0
    max_size: int = 0
    pad_color: Optional[str] = None
    crf: int = 32
    audio_kbps: int = 128
    mute: bool = False
    fmt: str = "webm"
    start: float = 0.0   # カット開始 (秒)
    end: float = 0.0     # カット終了 (秒)。0 なら終端まで

    def trim(self, duration: float) -> tuple[float, float]:
        """(開始秒, 長さ秒) を返す。長さ 0 は「終端まで」。"""
        start = max(0.0, self.start)
        if self.end <= start:
            return start, 0.0
        end = min(self.end, duration) if duration > 0 else self.end
        return start, max(0.0, end - start)

    def dest(self) -> Path:
        path = self.output_dir / (self.source.stem + EXT[self.fmt])
        if path.resolve() == self.source.resolve():  # 入力を上書きしない
            path = path.with_name(f"{path.stem}_converted{path.suffix}")
        return path

    def label(self) -> str:
        if self.max_size:
            return f"長辺 {self.max_size}px"
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        if self.width:
            return f"横幅 {self.width}px"
        if self.height:
            return f"縦幅 {self.height}px"
        return "元のサイズ"

    def check(self) -> None:
        if self.fmt not in FORMATS:
            raise ValueError(f"出力形式が不正です: {self.fmt}")
        if not self.source.is_file():
            raise ValueError(f"動画ファイルが見つかりません: {self.source}")
        if self.start < 0:
            raise ValueError("カット開始は 0 秒以上にしてください")
        if self.end and self.end <= self.start:
            raise ValueError("カット終了は開始より後にしてください")


@dataclass
class Result:
    dest: Optional[Path] = None
    cancelled: bool = False
    error: str = ""
    elapsed: float = 0.0

    def summary(self) -> str:
        if self.cancelled:
            return f"中断しました  ({self.elapsed:.1f} 秒)"
        if self.dest is None:
            return f"失敗  {self.error}".rstrip()
        size = self.dest.stat().st_size / 1048576 if self.dest.exists() else 0.0
        return f"完了  {self.dest.name}  ({size:.2f} MB / {self.elapsed:.1f} 秒)"


class Converter:
    def __init__(self, settings: Settings,
                 log: Callable[[str, str], None] = echo,
                 status: Callable[[str], None] = lambda t: None,
                 progress: Callable[[float], None] = lambda p: None):
        self.st = settings
        self.log, self.status, self.progress = log, status, progress
        self.stop = threading.Event()
        self._proc: Optional[subprocess.Popen] = None

    def cancel(self) -> None:
        self.stop.set()
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except OSError:
                pass

    def run(self) -> Result:
        st = self.st
        st.check()
        st.output_dir.mkdir(parents=True, exist_ok=True)
        result = Result()
        started = time.monotonic()

        for line in (f"入力  : {st.source}", f"出力  : {st.output_dir}",
                     f"形式  : {st.fmt.upper()}", f"サイズ: {st.label()}",
                     f"音声  : {'無音化' if st.mute else f'{st.audio_kbps} kbps'}", ""):
            self.log(line, "muted")

        try:
            self._convert(result)
        except Cancelled:
            result.cancelled = True
            self.log("  キャンセルされました", "warn")

        result.elapsed = time.monotonic() - started
        return result

    def _convert(self, result: Result) -> None:
        st = self.st
        dest = st.dest()
        dest.parent.mkdir(parents=True, exist_ok=True)

        info = probe(st.source)
        if info is None:
            result.error = "映像ストリームを読み取れませんでした"
            self.log(f"  {result.error}", "warn")
            return

        start, length = st.trim(info.duration)
        encoded = length if length > 0 else max(0.0, info.duration - start)
        if start > 0 or length > 0:
            self.log(f"  カット : {stamp(start * 1000)} → "
                     f"{stamp((start + encoded) * 1000)} ({encoded:.2f} 秒)")

        width, height = resolve_size(info, st.width, st.height, st.max_size)

        pad = "0x000000"
        if width and height:
            if st.pad_color:
                pad = st.pad_color
                self.log(f"  余白色 : {pad} (固定)")
            else:
                self.status("隅の色を取得中...")
                picked = corner_color(st.source, encoded, start)
                if self.stop.is_set():
                    raise Cancelled
                pad = picked or pad
                self.log(f"  余白色 : {pad} (動画の左上)" if picked
                         else "  余白色 : 取得できなかったため黒で塗ります",
                         "info" if picked else "warn")

        out_w, out_h = target_size(info, width, height)
        self.log(f"  変換   : {info.width}x{info.height} -> {out_w}x{out_h}")
        self.status(f"{st.source.name} を {st.fmt.upper()} に変換中...")

        seek = ["-ss", f"{start:.3f}"] if start > 0 else []
        limit = ["-t", f"{length:.3f}"] if length > 0 else []
        args = [ffmpeg_paths()[0], "-hide_banner", "-nostats", "-loglevel", "error", "-y",
                *seek, "-i", str(st.source), *limit, "-map", "0:v:0",
                "-vf", scale_filter(width, height, pad), "-pix_fmt", "yuv420p",
                *encode_args(st.fmt, st.crf, st.audio_kbps, st.mute),
                "-progress", "pipe:1", str(dest)]
        code, err = self._encode(args, encoded)

        if self.stop.is_set():
            dest.unlink(missing_ok=True)
            raise Cancelled

        if code != 0:
            lines = [ln for ln in err.splitlines() if ln.strip()]
            result.error = lines[0] if lines else f"ffmpeg が {code} で終了しました"
            self.log("  変換に失敗しました", "error")
            for line in lines[:6]:
                self.log(f"    {line}", "error")
            dest.unlink(missing_ok=True)
            return

        self.progress(100.0)
        self.log(f"  完了   : {dest.name} ({dest.stat().st_size / 1048576:.2f} MB)", "ok")
        result.dest = dest

    def _encode(self, args: list[str], duration: float) -> tuple[int, str]:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace",
                                bufsize=1, **hidden())
        self._proc = proc
        errors: list[str] = []
        reader = threading.Thread(target=lambda: errors.extend(proc.stderr), daemon=True)
        reader.start()

        for line in proc.stdout:
            if self.stop.is_set():
                break
            found = PROGRESS_RE.search(line)
            if found and duration > 0:
                percent = float(found.group(1)) / 1e6 / duration * 100
                self.progress(max(0.0, min(100.0, percent)))

        proc.wait()
        reader.join(timeout=2)
        self._proc = None
        return proc.returncode, "".join(errors)

def ask(label: str) -> int:
    raw = input(f"{label}: ").strip().rstrip("pxPX").strip()
    if not raw:
        return 0
    if not raw.isdigit():
        raise SystemExit(f"{label} の値が数値ではありません")
    return int(raw)


def run_cli(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description="動画 1 本を WebM (VP9 + Opus) / MP4 (H.264 + AAC) に変換します。"
                    " 引数なしで起動するとプレビュー付きのウィンドウが開きます。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("source", nargs="?", help="変換する動画ファイル")
    parser.add_argument("--input", "-i", dest="alt_source", help="変換する動画ファイル")
    parser.add_argument("--output", "-o", default=str(HERE / "output"), help="出力フォルダ")
    parser.add_argument("--format", "-f", dest="fmt", choices=FORMATS, default="webm",
                        help="出力形式")
    parser.add_argument("--width", "-W", type=int, default=0, help="横幅 (px)")
    parser.add_argument("--height", "-H", type=int, default=0, help="縦幅 (px)")
    parser.add_argument("--max", "-M", dest="max_size", type=int, default=0,
                        help="長辺 (px)。--width / --height より優先")
    parser.add_argument("--start", type=float, default=0.0, help="カット開始 (秒)")
    parser.add_argument("--end", type=float, default=0.0, help="カット終了 (秒)。0 で終端まで")
    parser.add_argument("--pad-color", default=None,
                        help="余白色を固定する (#RRGGBB)。省略時は動画の左上の色")
    parser.add_argument("--crf", type=int, default=32, help="VP9 の品質 (0-63)")
    parser.add_argument("--audio", type=int, default=128, help="音声ビットレート (kbps)")
    parser.add_argument("--mute", action="store_true", help="音声を入れない (無音化)")
    args = parser.parse_args(argv)

    source = args.source or args.alt_source
    if not source:
        parser.error("変換する動画ファイルを指定してください")

    try:
        ffmpeg_paths()
    except RuntimeError as exc:
        print(exc)
        return 1

    width, height, max_size = args.width, args.height, args.max_size
    if not (width or height or max_size):
        print("\n変換サイズを px で入力してください。")
        print("  横幅と縦幅の両方 -> 比率を保って内接させ、余白を動画の隅の色で塗りつぶす")
        print("  どちらか片方     -> 比率はそのまま、もう片方も同倍率")
        print("  長辺のみ         -> 横長は横幅・縦長は縦幅がその値になる (比率維持)")
        print("  空 Enter         -> 元のサイズのまま\n")
        max_size = ask("長辺 (px) ※使わない場合は空 Enter")
        if not max_size:
            width, height = ask("横幅 (px)"), ask("縦幅 (px)")
        print()

    for name, value in (("横幅", width), ("縦幅", height), ("長辺", max_size)):
        if even(value) != value:
            print(f"  ! {name} {value}px は偶数 {even(value)}px に丸めました")
    width, height, max_size = (even(v) for v in (width, height, max_size))
    if max_size:
        width = height = 0

    def bar(percent: float) -> None:
        filled = int(30 * percent / 100)
        print(f"\r  [{'#' * filled}{'-' * (30 - filled)}] {percent:5.1f}%",
              end="\n" if percent >= 100 else "", flush=True)

    try:
        settings = Settings(
            source=Path(source).expanduser().resolve(),
            output_dir=Path(args.output).expanduser().resolve(),
            width=width, height=height, max_size=max_size,
            pad_color=normalize_color(args.pad_color) if args.pad_color else None,
            crf=args.crf, audio_kbps=args.audio, mute=args.mute, fmt=args.fmt,
            start=args.start, end=args.end)
        settings.check()
    except ValueError as exc:
        print(exc)
        return 1

    converter = Converter(settings, log=echo, progress=bar)
    try:
        result = converter.run()
    except KeyboardInterrupt:
        converter.cancel()
        print("\n中断しました")
        return 130

    print("\n" + result.summary())
    return 0 if result.dest else 1

def run_gui() -> None:
    try:
        from PySide6.QtCore import QObject, Qt, QUrl, Signal
        from PySide6.QtGui import QColor, QPainter, QPen
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget
        from PySide6.QtWidgets import (
            QApplication, QCheckBox, QColorDialog, QFileDialog, QFrame, QGridLayout,
            QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar,
            QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)
    except ImportError:
        print("GUI には PySide6 が必要です:  pip install PySide6")
        print("コマンドラインで使う場合は  python webm_convert.py --help")
        return

    SETTINGS = HERE / "gui_settings.json"
    GREEN, RED = QColor(0, 200, 0), QColor(220, 50, 50)

    def button(text: str, slot, width: int = 0) -> QPushButton:
        widget = QPushButton(text)
        widget.clicked.connect(slot)
        if width:
            widget.setFixedWidth(width)
        return widget

    class TrimSlider(QSlider):
        """再生位置に加えて開始/終了マーカーを持つシークバー。"""

        seeked = Signal(int)
        trimmed = Signal()

        GRAB_PX = 6

        def __init__(self) -> None:
            super().__init__(Qt.Horizontal)
            self.start_ms = 0
            self.end_ms = 0
            self.selected = "playhead"
            self._grabbed: Optional[str] = None
            self.setMinimumHeight(28)

        def reset(self, duration: int) -> None:
            self.setRange(0, max(0, duration))
            self.start_ms, self.end_ms = 0, max(0, duration)
            self.selected = "playhead"
            self.update()

        def _to_ms(self, x: float) -> int:
            width = max(1, self.width())
            return int(max(0.0, min(float(width), x)) / width * self.maximum())

        def _to_x(self, ms: int) -> int:
            return int(ms / self.maximum() * self.width()) if self.maximum() else 0

        def set_marker(self, kind: str, ms: int) -> None:
            if kind == "start":
                self.start_ms = max(0, min(ms, self.end_ms))
            elif kind == "end":
                self.end_ms = max(self.start_ms, min(ms, self.maximum()))
            self.trimmed.emit()
            self.update()

        def nudge(self, delta: int) -> None:
            if self.selected in ("start", "end"):
                current = self.start_ms if self.selected == "start" else self.end_ms
                self.set_marker(self.selected, current + delta)
            else:
                self.seeked.emit(max(self.start_ms,
                                     min(self.value() + delta, self.end_ms)))

        def _drag(self, x: float) -> None:
            ms = self._to_ms(x)
            if self._grabbed in ("start", "end"):
                self.set_marker(self._grabbed, ms)
            else:
                self.setValue(ms)
                self.seeked.emit(ms)

        def mousePressEvent(self, event) -> None:
            if self.maximum() <= 0:
                return
            x = event.position().x()
            near = sorted(((abs(x - self._to_x(ms)), kind)
                           for ms, kind in ((self.start_ms, "start"),
                                            (self.end_ms, "end"))))
            self._grabbed = near[0][1] if near[0][0] <= self.GRAB_PX else "playhead"
            self.selected = self._grabbed
            self._drag(x)

        def mouseMoveEvent(self, event) -> None:
            if self._grabbed:
                self._drag(event.position().x())

        def mouseReleaseEvent(self, event) -> None:
            self._grabbed = None

        def paintEvent(self, event) -> None:
            super().paintEvent(event)
            if self.maximum() <= 0:
                return
            painter = QPainter(self)
            height, width = self.height(), self.width()
            left, right = self._to_x(self.start_ms), self._to_x(self.end_ms)
            shade = QColor(0, 0, 0, 70)
            painter.fillRect(0, 0, left, height, shade)
            painter.fillRect(right, 0, width - right, height, shade)
            for x, color, kind in ((left, GREEN, "start"), (right, RED, "end")):
                painter.setPen(QPen(color, 5 if self.selected == kind else 3))
                painter.drawLine(x, 0, x, height)

    class Bridge(QObject):
        status = Signal(str)
        progress = Signal(float)
        finished = Signal(object)

    class App(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("video 2 WebM / MP4")
            self.setAcceptDrops(True)
            self.converter: Optional[Converter] = None
            self.running = False
            self.video_path: Optional[Path] = None
            self.fps = 30.0
            self.last_dir = str(HERE)

            self.error = ""
            try:
                ffmpeg_paths()
            except RuntimeError as exc:
                self.error = str(exc)

            self._build()
            self.bridge = Bridge()
            self.bridge.status.connect(self.status.setText)
            self.bridge.progress.connect(lambda p: self.bar.setValue(int(p)))
            self.bridge.finished.connect(self._finish)

            self._load()
            self._swatch()
            self._mute()
            self._info()

            if self.error:
                echo(self.error)
                self.status.setText("ffmpeg が見つかりません")
            else:
                echo(f"ffmpeg: {ffmpeg_paths()[0]}")
            self._enable_buttons()

        # ---------- 組み立て ----------

        def _build(self) -> None:
            self.player = QMediaPlayer()
            self.audio_out = QAudioOutput()
            self.player.setAudioOutput(self.audio_out)

            root = QVBoxLayout(self)

            row = QHBoxLayout()
            row.addWidget(QLabel("入力ファイル"))
            self.file_edit = QLineEdit()
            self.file_edit.setReadOnly(True)
            self.file_edit.setPlaceholderText("ウィンドウに動画をドロップするか「開く...」")
            row.addWidget(self.file_edit, 1)
            row.addWidget(button("開く...", self._open_video, 90))
            root.addLayout(row)

            self.video = QVideoWidget()
            self.video.setMinimumHeight(280)
            self.video.setStyleSheet("background:#111;")
            self.player.setVideoOutput(self.video)
            root.addWidget(self.video, 1)

            self.slider = TrimSlider()
            self.slider.seeked.connect(self.player.setPosition)
            self.slider.trimmed.connect(self._trim_changed)
            root.addWidget(self.slider)

            row = QHBoxLayout()
            for text, delta in (("-10秒", -10000), ("-1秒", -1000), ("-1f", None)):
                row.addWidget(button(text, self._jumper(delta)))
            self.play_btn = button("▶", self._toggle_play, 56)
            row.addWidget(self.play_btn)
            for text, delta in (("+1f", None), ("+1秒", 1000), ("+10秒", 10000)):
                row.addWidget(button(text, self._jumper(delta, forward=True)))
            root.addLayout(row)

            row = QHBoxLayout()
            row.addWidget(button("開始をここに (S)", lambda: self._set_here("start")))
            row.addWidget(button("終了をここに (E)", lambda: self._set_here("end")))
            row.addWidget(button("カット解除", self._clear_trim))
            row.addStretch(1)
            root.addLayout(row)

            self.info = QLabel()
            self.info.setFrameShape(QFrame.StyledPanel)
            root.addWidget(self.info)

            self.player.positionChanged.connect(self._on_position)
            self.player.durationChanged.connect(self._on_duration)
            self.player.playbackStateChanged.connect(
                lambda state: self.play_btn.setText(
                    "⏸" if state == QMediaPlayer.PlayingState else "▶"))

            row = QHBoxLayout()
            row.addWidget(QLabel("出力フォルダ"))
            self.out_dir = QLineEdit(str(HERE / "output"))
            row.addWidget(self.out_dir, 1)
            row.addWidget(button("参照...", self._browse_output, 90))
            root.addLayout(row)

            row = QHBoxLayout()
            row.addWidget(self._size_box(), 1)
            row.addWidget(self._encode_box(), 1)
            root.addLayout(row)

            self.status = QLabel("待機中")
            root.addWidget(self.status)
            self.bar = QProgressBar()
            self.bar.setRange(0, 100)
            self.bar.setTextVisible(False)
            self.bar.setFixedHeight(12)
            root.addWidget(self.bar)

            row = QHBoxLayout()
            self.webm_btn = button("WebM で変換", lambda: self._start("webm"), 150)
            self.mp4_btn = button("MP4 で変換", lambda: self._start("mp4"), 150)
            self.cancel_btn = button("キャンセル", self._cancel, 110)
            self.cancel_btn.setEnabled(False)
            row.addWidget(self.webm_btn)
            row.addWidget(self.mp4_btn)
            row.addWidget(self.cancel_btn)
            row.addStretch(1)
            row.addWidget(button("出力フォルダを開く", self._open_output, 150))
            root.addLayout(row)

        def _size_box(self) -> QWidget:
            box = QGroupBox("サイズ指定 (px)  ※空なら元のサイズ")
            grid = QGridLayout(box)
            grid.addWidget(QLabel("横×縦"), 0, 0)
            holder = QHBoxLayout()
            self.w_edit, self.h_edit = QLineEdit(), QLineEdit()
            for edit in (self.w_edit, self.h_edit):
                edit.setFixedWidth(70)
            holder.addWidget(self.w_edit)
            holder.addWidget(QLabel("×"))
            holder.addWidget(self.h_edit)
            holder.addStretch(1)
            grid.addLayout(holder, 0, 1)

            grid.addWidget(QLabel("長辺"), 1, 0)
            self.max_edit = QLineEdit("1080")
            self.max_edit.setFixedWidth(70)
            grid.addWidget(self.max_edit, 1, 1)

            grid.addWidget(QLabel("余白色"), 2, 0)
            holder = QHBoxLayout()
            self.pad_edit = QLineEdit()
            self.pad_edit.setFixedWidth(90)
            self.pad_edit.textChanged.connect(lambda _: self._swatch())
            self.chip = QLabel()
            self.chip.setFixedSize(26, 20)
            self.chip.setFrameShape(QFrame.Box)
            holder.addWidget(self.pad_edit)
            holder.addWidget(self.chip)
            holder.addWidget(button("選ぶ...", self._pick_color, 70))
            holder.addStretch(1)
            grid.addLayout(holder, 2, 1)
            return box

        def _encode_box(self) -> QWidget:
            box = QGroupBox("エンコード設定")
            grid = QGridLayout(box)
            grid.addWidget(QLabel("画質 CRF"), 0, 0)
            self.crf = QSpinBox()
            self.crf.setRange(0, 63)
            self.crf.setValue(32)
            self.crf.setFixedWidth(70)
            grid.addWidget(self.crf, 0, 1)
            grid.addWidget(QLabel("(MP4 は x264 換算)"), 0, 2)

            grid.addWidget(QLabel("音声"), 1, 0)
            self.audio = QSpinBox()
            self.audio.setRange(6, 510)
            self.audio.setValue(128)
            self.audio.setFixedWidth(70)
            grid.addWidget(self.audio, 1, 1)
            grid.addWidget(QLabel("kbps"), 1, 2)

            self.mute = QCheckBox("無音化")
            self.mute.stateChanged.connect(lambda _: self._mute())
            grid.addWidget(self.mute, 2, 0, 1, 3)
            grid.setColumnStretch(3, 1)
            return box

        # ---------- プレビュー ----------

        def _open_video(self) -> None:
            patterns = " ".join(f"*{ext}" for ext in sorted(EXTENSIONS))
            path, _ = QFileDialog.getOpenFileName(
                self, "動画を開く", self.last_dir,
                f"動画ファイル ({patterns});;すべてのファイル (*)")
            if path:
                self.load_video(Path(path))

        def load_video(self, path: Path) -> None:
            self.video_path = path
            self.last_dir = str(path.parent)
            self.file_edit.setText(str(path))
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            info = probe(path)
            self.fps = info.fps if info else 30.0
            self.status.setText("待機中")
            self.bar.setValue(0)
            self._enable_buttons()
            self.player.play()

        def _on_duration(self, duration: int) -> None:
            self.slider.reset(duration)
            self._info()

        def _on_position(self, pos: int) -> None:
            if self.slider.maximum() and pos > self.slider.end_ms:
                self.player.setPosition(self.slider.start_ms)
                return
            self.slider.blockSignals(True)
            self.slider.setValue(pos)
            self.slider.blockSignals(False)
            self.slider.update()
            self._info()

        def _trim_changed(self) -> None:
            pos = self.player.position()
            if pos < self.slider.start_ms:
                self.player.setPosition(self.slider.start_ms)
            elif pos > self.slider.end_ms:
                self.player.setPosition(self.slider.end_ms)
            self._info()

        def _frame_ms(self) -> int:
            return max(1, round(1000 / self.fps)) if self.fps > 0 else 33

        def _jumper(self, delta: Optional[int], forward: bool = False):
            def go() -> None:
                step = delta if delta is not None else (
                    self._frame_ms() if forward else -self._frame_ms())
                self._jump(step)
            return go

        def _jump(self, delta: int) -> None:
            target = self.player.position() + delta
            self.player.setPosition(max(self.slider.start_ms,
                                        min(target, self.slider.end_ms)))

        def _toggle_play(self) -> None:
            if self.player.playbackState() == QMediaPlayer.PlayingState:
                self.player.pause()
            else:
                self.player.play()

        def _set_here(self, kind: str) -> None:
            self.slider.selected = kind
            self.slider.set_marker(kind, self.player.position())

        def _clear_trim(self) -> None:
            self.slider.start_ms = 0
            self.slider.end_ms = self.slider.maximum()
            self.slider.selected = "playhead"
            self.slider.update()
            self._info()

        def _info(self) -> None:
            if not self.video_path:
                self.info.setText("どうがを　つっこめ！  (ここに動画をドロップ)")
                return
            length = max(0, self.slider.end_ms - self.slider.start_ms)
            self.info.setText(
                f"[{self.slider.selected}]  開始 {stamp(self.slider.start_ms)} / "
                f"終了 {stamp(self.slider.end_ms)} / 現在 {stamp(self.player.position())}"
                f"   書き出す長さ {stamp(length)}   {self.fps:.2f} fps")

        def keyPressEvent(self, event) -> None:
            key = event.key()
            if not self.video_path or key not in (
                    Qt.Key_Left, Qt.Key_Right, Qt.Key_S, Qt.Key_E, Qt.Key_P, Qt.Key_Space):
                super().keyPressEvent(event)
                return
            if key == Qt.Key_Left:
                self.slider.nudge(-self._frame_ms())
            elif key == Qt.Key_Right:
                self.slider.nudge(self._frame_ms())
            elif key == Qt.Key_S:
                self._set_here("start")
            elif key == Qt.Key_E:
                self._set_here("end")
            elif key == Qt.Key_P:
                self.slider.selected = "playhead"
            else:
                self._toggle_play()
            self.slider.update()
            self._info()

        def dragEnterEvent(self, event) -> None:
            urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
            if urls and Path(urls[0].toLocalFile()).suffix.lower() in EXTENSIONS:
                event.acceptProposedAction()

        def dropEvent(self, event) -> None:
            path = Path(event.mimeData().urls()[0].toLocalFile())
            if path.is_file():
                self.load_video(path)

        # ---------- 設定 ----------

        def _swatch(self) -> None:
            raw = self.pad_edit.text().strip()
            try:
                color = "#" + normalize_color(raw)[2:] if raw else "transparent"
            except ValueError:
                color = "transparent"
            self.chip.setStyleSheet(f"background:{color}; border:1px solid #888;")

        def _mute(self) -> None:
            self.audio.setEnabled(not self.mute.isChecked())

        def _browse_output(self) -> None:
            path = QFileDialog.getExistingDirectory(self, "出力フォルダ",
                                                    self.out_dir.text() or str(HERE))
            if path:
                self.out_dir.setText(os.path.normpath(path))

        def _pick_color(self) -> None:
            try:
                initial = QColor("#" + normalize_color(self.pad_edit.text())[2:])
            except ValueError:
                initial = QColor("#000000")
            chosen = QColorDialog.getColor(initial, self, "余白色を選ぶ")
            if chosen.isValid():
                self.pad_edit.setText(chosen.name().upper())

        def _open_output(self) -> None:
            folder = Path(self.out_dir.text().strip())
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open",
                                  str(folder)])

        def _size(self, edit: QLineEdit, label: str) -> int:
            raw = edit.text().strip().rstrip("pxPX").strip()
            if not raw:
                return 0
            if not raw.isdigit():
                raise ValueError(f"{label} には数値 (px) を入力してください。")
            return int(raw)

        def _settings(self, fmt: str) -> Optional[Settings]:
            if not self.video_path:
                QMessageBox.information(self, "確認", "先に動画を開いてください。")
                return None
            try:
                width = self._size(self.w_edit, "横幅")
                height = self._size(self.h_edit, "縦幅")
                max_size = self._size(self.max_edit, "長辺")
                raw = self.pad_edit.text().strip()
                pad = normalize_color(raw) if raw else None
            except ValueError as exc:
                QMessageBox.warning(self, "確認", str(exc))
                return None

            if max_size:
                width = height = 0
            for label, value in (("横幅", width), ("縦幅", height), ("長辺", max_size)):
                if even(value) != value:
                    echo(f"! {label} {value}px は偶数 {even(value)}px に丸めました")
            width, height, max_size = (even(v) for v in (width, height, max_size))

            start = self.slider.start_ms / 1000
            end = (0.0 if self.slider.end_ms >= self.slider.maximum()
                   else self.slider.end_ms / 1000)
            if end and end - start < 0.05:
                QMessageBox.warning(self, "確認", "カット範囲が短すぎます。")
                return None

            settings = Settings(
                source=self.video_path, output_dir=Path(self.out_dir.text().strip()),
                width=width, height=height, max_size=max_size, pad_color=pad,
                crf=self.crf.value(), audio_kbps=self.audio.value(),
                mute=self.mute.isChecked(), fmt=fmt, start=start, end=end)
            try:
                settings.check()
            except ValueError as exc:
                QMessageBox.warning(self, "確認", str(exc))
                return None
            return settings

        # ---------- 変換 ----------

        def _enable_buttons(self) -> None:
            ready = bool(self.video_path) and not self.error and not self.running
            self.webm_btn.setEnabled(ready)
            self.mp4_btn.setEnabled(ready)
            self.cancel_btn.setEnabled(self.running)

        def _start(self, fmt: str) -> None:
            if self.running or self.error:
                return
            settings = self._settings(fmt)
            if settings is None:
                return

            self.running = True
            self._enable_buttons()
            self.bar.setValue(0)

            self.converter = Converter(
                settings, log=echo,
                status=self.bridge.status.emit,
                progress=self.bridge.progress.emit)

            def work() -> None:
                try:
                    result = self.converter.run()  # type: ignore[union-attr]
                except Exception as exc:  # noqa: BLE001 -- コンソールにも出す
                    echo(f"エラー: {exc}")
                    result = Result(error=str(exc))
                self.bridge.finished.emit(result)

            threading.Thread(target=work, daemon=True).start()

        def _cancel(self) -> None:
            if self.converter:
                self.converter.cancel()
            self.status.setText("キャンセルしています...")
            self.cancel_btn.setEnabled(False)

        def _finish(self, result: Result) -> None:
            self.running = False
            self.converter = None
            self._enable_buttons()
            self.bar.setValue(100 if result.dest else 0)
            echo("")
            echo(result.summary())
            self.status.setText(result.summary())

        # ---------- 保存/復元 ----------

        def _state(self) -> dict:
            return {"output": self.out_dir.text(), "width": self.w_edit.text(),
                    "height": self.h_edit.text(), "max": self.max_edit.text(),
                    "pad": self.pad_edit.text(), "crf": self.crf.value(),
                    "audio": self.audio.value(), "mute": self.mute.isChecked(),
                    "last_dir": self.last_dir}

        def _save(self) -> None:
            try:
                SETTINGS.write_text(json.dumps(self._state(), ensure_ascii=False, indent=2),
                                    encoding="utf-8")
            except OSError:
                pass

        def _load(self) -> None:
            try:
                data = json.loads(SETTINGS.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            edits = {"output": self.out_dir, "width": self.w_edit, "height": self.h_edit,
                     "max": self.max_edit, "pad": self.pad_edit}
            for key, edit in edits.items():
                if key in data:
                    edit.setText(str(data[key]))
            for key, spin in (("crf", self.crf), ("audio", self.audio)):
                try:
                    spin.setValue(int(data[key]))
                except (KeyError, TypeError, ValueError):
                    pass
            self.mute.setChecked(bool(data.get("mute", False)))
            folder = str(data.get("last_dir") or data.get("input") or HERE)
            self.last_dir = folder if Path(folder).is_dir() else str(HERE)

        def closeEvent(self, event) -> None:
            if self.running:
                if QMessageBox.question(self, "確認", "変換中です。中断して閉じますか？") \
                        != QMessageBox.Yes:
                    event.ignore()
                    return
                if self.converter:
                    self.converter.cancel()
            self.player.stop()
            self._save()
            event.accept()

    app = QApplication(sys.argv[:1])
    window = App()
    window.resize(940, 780)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(run_cli(sys.argv[1:]))
    run_gui()
