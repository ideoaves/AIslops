import os
import sys
import io
import sqlite3
import json
import time
import tempfile
from string import Template
from datetime import datetime
from collections import OrderedDict, Counter
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageOps
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRectF, QMimeData, QUrl, QSize, QFile, QVariantAnimation, QSettings
from PySide6.QtGui import QColor, QPixmap, QImage, QPen, QDrag, QImageReader, QPainter
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QSplitter, QTreeWidget, QTreeWidgetItem,
                               QLabel, QVBoxLayout, QHBoxLayout, QSlider, QGraphicsView, QAbstractButton,
                               QGraphicsScene, QGraphicsItem, QMenu, QMessageBox, QPushButton, QFileDialog, QLineEdit)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.sqlite")
EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff")
WORKERS = 2
THUMB_PX = 128
GRID = 8
LIGHT_WEIGHT = 1.0
COLOR_WEIGHT = 1.5
GLOBAL_WEIGHT = 4.0
WEIGHTS = dict(color=1.0, time=1.5, lens=1.2, model=0.5, focal=0.8, gps=1.2)
CATEGORY_TOP = 30
SIZE_MIN, SIZE_MAX, SIZE_DEFAULT = 8, 800, 40
SPREAD = 60
UNIFORM = 0.6
GAP = 0.75
SPACE_ITERS = 150
ZOOM_STEP = 1.2
THUMB_SHOW_MAX = 1500
LOAD_MS = 60
LOAD_MAX_PX = 128
CACHE_MB = 300
PREVIEW_PX = 240
HOVER_PX = 320
HOVER_DELAY_MS = 120
CLIP_MODEL, CLIP_PRETRAINED = "xlm-roberta-base-ViT-B-32", "laion5b_s13b_b90k"
CLIP_BATCH = 256
SEARCH_TOP = 300
SAME_PERIOD_DAYS = 3
DIM_OPACITY = 0.2
THEME = "dark"
FONT_SIZE = 12
PAD = 4
CONTROL_H = 16
BAR_H = 32
BUTTON_W, BUTTON_H = 64, 24
DARK = dict(bg="#111", panel="#000", surface="#333", border="#ddd", hover="#555",
            text="#ddd", sub="#888", accent="#BBB", accentText="#111", danger="#f44",
            checkOff="#111", checkOn="#BBB")
LIGHT = dict(bg="#DDD", panel="#EEE", surface="#ccc", border="#222", hover="#CCC",
             text="#222", sub="#777", accent="#444", accentText="#eee", danger="#c22",
             checkOff="#EEE", checkOn="#ccc")


QSS = Template("""
QWidget { background: $panel; color: $text; font-size: ${font}px; }
QMainWindow, QDialog { background: $bg; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: ${pad}px; }

QPushButton, QToolButton { background: $surface; border: 1px solid $border; padding: 0 ${pad2}px; min-width: ${bw}px; min-height: ${bh}px; max-height: ${bh}px; }
QPushButton:hover, QToolButton:hover { background: $hover; }
QPushButton:pressed, QToolButton:pressed, QToolButton:checked { border-color: $accent; }
QPushButton:disabled, QToolButton:disabled { color: $sub; }
QPushButton[accent="true"] { background: $accent; color: $accentText; border-color: $accent; }

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: $bg; border: 1px solid $border; padding: ${pad}px; selection-background-color: $accent; selection-color: $accentText; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: $accent; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox::down-arrow { image: url($arrow); width: 10px; height: 10px; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border; selection-background-color: $accent; selection-color: $accentText; }

QCheckBox::indicator, QRadioButton::indicator { width: ${ind}px; height: ${ind}px; border: 1px solid $border; background: $checkOff; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: $checkOn; border-color: $border; image: url($check); }

QSlider::groove:horizontal { height: 4px; background: $bg; border: 1px solid $border; }
QSlider::sub-page:horizontal { background: $accent; }
QSlider::handle:horizontal { width: 12px; margin: -${hm}px 0; background: $accent; }
QProgressBar { background: $bg; border: 1px solid $border; text-align: center; color: $bg; }
QProgressBar::chunk { background: $accent; }

QScrollBar:vertical { width: 10px; background: transparent; }
QScrollBar:horizontal { height: 10px; background: transparent; }
QScrollBar::handle { background: $border; margin: 2px; }
QScrollBar::handle:hover { background: $sub; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { background: none; border: none; width: 0; height: 0; }

QTreeView, QListView, QTableView { background: $bg; border: 1px solid $border; alternate-background-color: $panel; outline: none; }
QTreeView::item:hover, QListView::item:hover, QTableView::item:hover { background: $hover; }
QTreeView::item:selected, QListView::item:selected, QTableView::item:selected { background: $accent; color: $accentText; }
QHeaderView::section { background: $surface; border: none; border-right: 1px solid $border; padding: ${pad}px; }

QMenuBar { background: $panel; }
QMenuBar::item:selected, QMenu::item:selected { background: $accent; color: $accentText; }
QMenu { background: $surface; border: 1px solid $border; padding: ${pad}px 0; }
QMenu::item { padding: ${pad}px ${pad3}px; }
QMenu::separator { height: 1px; background: $border; margin: ${pad}px 0; }
QSplitter::handle { background: $bg; }
""")
ARROW_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M1 3l4 4 4-4" fill="none" stroke="{}" stroke-width="1.6"/></svg>'
CHECK_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14"><path d="M0 0L14 14M14 0L0 14" fill="none" stroke="{}" stroke-width="1"/></svg>'


class theme:
    current = dict(DARK)

    @staticmethod
    def apply(app, mode="dark"):
        theme.current = dict(DARK if mode == "dark" else LIGHT)
        cur = theme.current
        paths = {}
        for name, svg, col in (("arrow", ARROW_SVG, cur["sub"]), ("check", CHECK_SVG, cur["border"])):
            paths[name] = os.path.join(tempfile.gettempdir(), f"imagemap_{name}_{mode}.svg").replace("\\", "/")
            with open(paths[name], "w", encoding="utf-8") as f:
                f.write(svg.format(col))
        app.setStyleSheet(QSS.substitute(cur, **paths, font=FONT_SIZE, pad=PAD, pad2=PAD * 2, pad3=PAD * 3, ind=CONTROL_H - 2,
                                         bw=BUTTON_W - PAD * 4 - 2, bh=BUTTON_H - 2, hm=(CONTROL_H - 4) // 2))

    @staticmethod
    def color(name):
        return QColor(theme.current[name])

    @staticmethod
    def mix(a, b, t):
        a, b = theme.color(a), theme.color(b)
        return QColor(*(round(x + (y - x) * t) for x, y in zip(a.getRgb()[:3], b.getRgb()[:3])))


SWITCH_W, SWITCH_H = 34, CONTROL_H


class RangeSlider(QWidget):
    changed = Signal(float, float)

    def __init__(self, lo=0.0, hi=1.0, parent=None):
        super().__init__(parent)
        self.lo, self.hi, self.held = lo, hi, None
        self.setMinimumWidth(120)
        self.setFixedHeight(22)

    def sizeHint(self):
        return QSize(200, 22)

    def x_of(self, v):
        return 6 + v * (self.width() - 12)

    def paintEvent(self, e):
        p = QPainter(self)
        y, xl, xh = self.height() / 2, self.x_of(self.lo), self.x_of(self.hi)
        p.fillRect(QRectF(0, y - 3, self.width(), 6), theme.color("border"))
        p.fillRect(QRectF(1, y - 2, self.width() - 2, 4), theme.color("bg"))
        p.fillRect(QRectF(xl, y - 2, xh - xl, 4), theme.color("accent"))
        for x in (xl, xh):
            p.fillRect(QRectF(x - 6, y - SWITCH_H / 2, 12, SWITCH_H), theme.color("accent"))

    def mousePressEvent(self, e):
        x, xl, xh = e.position().x(), self.x_of(self.lo), self.x_of(self.hi)
        self.held = "lo" if abs(x - xl) < abs(x - xh) or (xl == xh and x < xl) else "hi"
        self.mouseMoveEvent(e)

    def mouseMoveEvent(self, e):
        v = min(max((e.position().x() - 6) / (self.width() - 12), 0.0), 1.0)
        if self.held == "lo":
            self.lo = min(v, self.hi)
        else:
            self.hi = max(v, self.lo)
        self.update()
        self.changed.emit(self.lo, self.hi)


class ToggleSwitch(QAbstractButton):
    def __init__(self, text="", checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.knob = 1.0 if checked else 0.0
        self.anim = QVariantAnimation(self, duration=120)
        self.anim.valueChanged.connect(self.set_knob)
        self.toggled.connect(self.slide)

    def sizeHint(self):
        return QSize(SWITCH_W + (self.fontMetrics().horizontalAdvance(self.text()) + 8 if self.text() else 0), SWITCH_H + 4)

    def set_knob(self, v):
        self.knob = v
        self.update()

    def slide(self, on):
        self.anim.stop()
        self.anim.setStartValue(self.knob)
        self.anim.setEndValue(1.0 if on else 0.0)
        self.anim.start()

    def paintEvent(self, e):
        p = QPainter(self)
        y = (self.height() - SWITCH_H) / 2
        p.setPen(theme.color("border"))
        p.setBrush(theme.mix("bg", "panel", self.knob))
        p.drawRect(QRectF(0, y, SWITCH_W - 1, SWITCH_H - 1))
        p.setBrush(theme.color("border"))
        p.drawRect(QRectF(3 + self.knob * (SWITCH_W - SWITCH_H), y + 3, SWITCH_H - 7, SWITCH_H - 7))
        p.setPen(theme.color("text" if self.isEnabled() else "sub"))
        p.drawText(QRectF(SWITCH_W + 8, 0, self.width(), self.height()), Qt.AlignVCenter, self.text())


def to_lab(rgb):
    c = np.where(rgb > 0.04045, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.9505, 1.0, 1.089])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def analyze(path):
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            w, h = im.size if exif.get(274) not in (5, 6, 7, 8) else im.size[::-1]
            stamp = exif.get_ifd(0x8769).get(36867) or exif.get(306)
            im.draft("RGB", (THUMB_PX, THUMB_PX))
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((THUMB_PX, THUMB_PX))
        try:
            ts = datetime.strptime(str(stamp).strip("\x00 ")[:19], "%Y:%m:%d %H:%M:%S").timestamp()
        except ValueError:
            ts = os.path.getmtime(path)
        lab = to_lab(np.asarray(im.resize((GRID, GRID), Image.BOX), np.float64) / 255)
        lab *= np.array([LIGHT_WEIGHT, COLOR_WEIGHT, COLOR_WEIGHT])
        feat = np.concatenate([lab.ravel(), lab.mean((0, 1)) * GLOBAL_WEIGHT]).astype(np.float32)
        r, g, b = map(int, np.asarray(im).reshape(-1, 3).mean(0))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        return path, ts, w, h, (r << 16) | (g << 8) | b, feat.tobytes(), buf.getvalue()
    except Exception:
        return path, None, 0, 0, 0, None, None


def read_exif(path):
    try:
        with Image.open(path) as im:
            e = im.getexif()
            sub, g = e.get_ifd(0x8769), e.get_ifd(0x8825)
        try:
            dms = lambda v, ref: (float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600) * (-1 if ref in ("S", "W") else 1)
            lat, lon = dms(g[2], g.get(1)), dms(g[4], g.get(3))
        except (KeyError, ZeroDivisionError, TypeError, ValueError, IndexError):
            lat = lon = None
        focal = float(sub.get(37386) or 0) or None
        return path, str(e.get(272) or "").strip("\x00 "), str(sub.get(42036) or "").strip("\x00 "), focal, lat, lon
    except Exception:
        return path, "", "", None, None, None


def normalize(block):
    block = block - block.mean(0)
    return block / max(np.sqrt((block ** 2).sum(1).mean()), 1e-9)


def one_hot(values):
    cats = {c: k for k, (c, _) in enumerate(Counter(values).most_common(CATEGORY_TOP))}
    out = np.zeros((len(values), len(cats) + 1))
    out[np.arange(len(values)), [cats.get(v, len(cats)) for v in values]] = 1
    return out


def fill_mean(block):
    return np.where(np.isnan(block), np.nanmean(block, 0), block)


def combine_features(rows, exif):
    ex = [exif.get(r[0], ("", "", None, None, None)) for r in rows]
    lat = np.radians(np.array([e[3] if e[3] is not None else np.nan for e in ex]))
    lon = np.radians(np.array([e[4] if e[4] is not None else np.nan for e in ex]))
    blocks = dict(
        color=np.stack([np.frombuffer(r[5], np.float32) for r in rows]),
        time=np.array([[r[1] / 86400] for r in rows]),
        lens=one_hot([e[1] for e in ex]),
        model=one_hot([e[0] for e in ex]),
        focal=fill_mean(np.log(np.array([[e[2] or np.nan] for e in ex]))),
        gps=fill_mean(np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])),
    )
    return np.hstack([normalize(np.nan_to_num(blocks[k])) * w for k, w in WEIGHTS.items() if w > 0])


def space_out(coords):
    from scipy.spatial import cKDTree
    n = len(coords)
    c = (coords - coords.min(0)) / np.maximum(np.ptp(coords, 0), 1e-9)
    c = c * (1 - UNIFORM) + np.argsort(np.argsort(c, 0), 0) / max(n - 1, 1) * UNIFORM
    gap = GAP / np.sqrt(max(n, 1))
    c = c + np.random.default_rng(0).normal(0, gap * 0.01, c.shape)

    def relax(c, left):
        p = cKDTree(c).query_pairs(gap, output_type="ndarray")
        if left == 0 or not len(p):
            return c
        v = c[p[:, 1]] - c[p[:, 0]]
        dist = np.maximum(np.linalg.norm(v, axis=1), 1e-12)
        push = v / dist[:, None] * ((gap - dist) / 2)[:, None]
        move = np.column_stack([np.bincount(p[:, 1], push[:, i], n) - np.bincount(p[:, 0], push[:, i], n) for i in (0, 1)])
        return relax(c + move, left - 1)

    return relax(c, SPACE_ITERS)


def true_case(path):
    path = os.path.normpath(path)
    parent, name = os.path.split(path)
    if not name:
        return path[:1].upper() + path[1:]
    parent = true_case(parent)
    try:
        name = next((n for n in os.listdir(parent) if n.lower() == name.lower()), name)
    except OSError:
        pass
    return os.path.join(parent, name)


def dir_key(d):
    return os.path.normcase(d.rstrip("\\") + "\\")


def scan(folder, out):
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return
    for e in entries:
        if e.is_dir(follow_symlinks=False):
            scan(e.path, out)
        elif e.name.lower().endswith(EXTS):
            st = e.stat()
            out[e.path] = (st.st_mtime, st.st_size)


class Worker(QThread):
    progress = Signal(str)
    loaded = Signal(object)
    laidout = Signal(object)

    def __init__(self, root, parent):
        super().__init__(parent)
        self.root = root

    def run(self):
        db = sqlite3.connect(DB_PATH)
        db.execute("pragma journal_mode=wal")
        db.execute("create table if not exists img(path text primary key, mtime real, size int, ts real, w int, h int, color int, feat blob, thumb blob)")
        db.execute("create table if not exists layouts(root text, path text, x real, y real, primary key(root, path))")
        db.execute("create table if not exists meta(k text primary key, v text)")
        db.execute("create table if not exists clip(path text primary key, emb blob)")
        db.execute("create table if not exists exif(path text primary key, model text, lens text, focal real, lat real, lon real)")
        self.progress.emit("走査中…")
        files = {}
        scan(self.root, files)
        inside = lambda p: os.path.normcase(p).startswith(dir_key(self.root))
        known = {p: (m, s) for p, m, s in db.execute("select path, mtime, size from img") if inside(p)}
        db.executemany("delete from img where path=?", [(p,) for p in known if p not in files])
        todo = [p for p, v in files.items() if known.get(p) != v]
        db.executemany("delete from exif where path=?", [(p,) for p in todo])
        db.execute("delete from exif where path not in (select path from img)")
        with Pool(WORKERS) as pool:
            self.pour(db, pool, analyze, todo, "insert or replace into img values(?,?,?,?,?,?,?,?,?)", lambda r: (r[0], *files[r[0]], *r[1:]), "解析中")
            need = [p for (p,) in db.execute("select path from img where path not in (select path from exif)")]
            self.pour(db, pool, read_exif, need, "insert or replace into exif values(?,?,?,?,?,?)", lambda r: r, "EXIF読み込み中")
        if self.isInterruptionRequested():
            return
        rows = [r for r in db.execute("select path, ts, w, h, color, feat from img where feat is not null order by path") if inside(r[0])]
        self.loaded.emit(rows)
        if not rows:
            self.progress.emit("0枚")
            return
        layout = {p: (x, y) for p, x, y in db.execute("select path, x, y from layouts where root=?", (dir_key(self.root),))}
        params = json.dumps([WEIGHTS, CATEGORY_TOP])
        if all(r[0] in layout for r in rows) and db.execute("select v from meta where k=?", ('layoutParams:' + dir_key(self.root),)).fetchone() == (params,):
            self.laidout.emit(space_out(np.array([layout[r[0]] for r in rows])))
            self.progress.emit(f"{len(rows)}枚")
            return
        from sklearn.decomposition import PCA
        from sklearn.manifold import TSNE
        exif = {r[0]: r[1:] for r in db.execute("select path, model, lens, focal, lat, lon from exif")}
        feats = combine_features(rows, exif)
        pca = PCA(n_components=min(50, *feats.shape)).fit_transform(feats)
        self.laidout.emit(space_out(pca[:, :2]))
        self.progress.emit(f"{len(rows)}枚　配置計算中（t-SNE）…")
        coords = TSNE(2, init=pca[:, :2] / pca[:, 0].std() * 1e-4, perplexity=min(30, len(rows) - 1), n_jobs=WORKERS).fit_transform(pca)
        db.executemany("insert or replace into layouts values(?,?,?,?)", [(dir_key(self.root), r[0], float(x), float(y)) for r, (x, y) in zip(rows, coords)])
        db.execute("insert or replace into meta values(?, ?)", ('layoutParams:' + dir_key(self.root), params))
        db.commit()
        self.laidout.emit(space_out(coords))
        self.progress.emit(f"{len(rows)}枚")


    def pour(self, db, pool, func, paths, sql, to_row, label):
        for i, r in enumerate(pool.imap_unordered(func, paths, chunksize=8), 1):
            db.execute(sql, to_row(r))
            if self.isInterruptionRequested():
                break
            if i % 200 == 0:
                db.commit()
                self.progress.emit(f"{label} {i}/{len(paths)}")
        db.commit()


class ClipWorker(QThread):
    progress = Signal(str)
    ready = Signal(object)
    model = None

    def __init__(self, paths, parent):
        super().__init__(parent)
        self.paths = paths

    def run(self):
        try:
            import torch
            import open_clip
        except ImportError:
            self.progress.emit("タグ検索なし")
            return
        if ClipWorker.model is None:
            self.progress.emit("タグモデル読み込み中…")
            model, _, prep = open_clip.create_model_and_transforms(CLIP_MODEL, pretrained=CLIP_PRETRAINED)
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            ClipWorker.model = ((model.half() if dev == "cuda" else model).to(dev).eval(), prep, open_clip.get_tokenizer(CLIP_MODEL), dev, torch)
        model, prep, _, dev, torch = ClipWorker.model
        db = sqlite3.connect(DB_PATH)
        db.execute("create table if not exists clip(path text primary key, emb blob)")
        done = {p for (p,) in db.execute("select path from clip")}
        todo = [p for p in self.paths if p not in done]
        for i in range(0, len(todo), CLIP_BATCH):
            if self.isInterruptionRequested():
                return
            chunk = todo[i:i + CLIP_BATCH]
            thumbs = dict(db.execute(f"select path, thumb from img where path in ({','.join('?' * len(chunk))})", chunk))
            x = torch.stack([prep(Image.open(io.BytesIO(thumbs[p])).convert("RGB")) for p in chunk]).to(dev)
            with torch.no_grad():
                e = model.encode_image(x.half() if dev == "cuda" else x).float()
            e = torch.nn.functional.normalize(e, dim=-1).cpu().numpy().astype(np.float16)
            db.executemany("insert or replace into clip values(?,?)", [(p, v.tobytes()) for p, v in zip(chunk, e)])
            db.commit()
            self.progress.emit(f"タグ解析 {i + len(chunk)}/{len(todo)}")
        embs = dict(db.execute("select path, emb from clip"))
        self.ready.emit(np.stack([np.frombuffer(embs[p], np.float16) for p in self.paths]).astype(np.float32))
        self.progress.emit("")

    @staticmethod
    def encode_text(q):
        model, _, tok, dev, torch = ClipWorker.model
        with torch.no_grad():
            t = model.encode_text(tok([q]).to(dev)).float()
        return torch.nn.functional.normalize(t, dim=-1).cpu().numpy()[0]


class ThumbStore:
    def __init__(self):
        self.db = None
        self.cache = OrderedDict()
        self.bytes = 0
        self.px = 0
        self.deadline = 0
        self.pending = self.evicted = False

    def set_size(self, size, dpr):
        px = min(-(-int(size * dpr) // 16) * 16, LOAD_MAX_PX)
        if px != self.px:
            self.px, self.bytes = px, 0
            self.cache.clear()

    def get(self, path):
        if path in self.cache:
            self.cache.move_to_end(path)
            return self.cache[path]
        if time.perf_counter() > self.deadline:
            self.pending = True
            return None
        self.db = self.db or sqlite3.connect(DB_PATH)
        row = self.db.execute("select thumb from img where path=?", (path,)).fetchone()
        pm = QPixmap.fromImage(QImage.fromData(row[0]).scaled(self.px, self.px, Qt.KeepAspectRatio, Qt.SmoothTransformation)) if row else QPixmap()
        self.cache[path] = pm
        self.bytes += pm.width() * pm.height() * 4
        while self.bytes > CACHE_MB * 1048576:
            old = self.cache.popitem(last=False)[1]
            self.bytes -= old.width() * old.height() * 4
            self.evicted = True
        return pm


class Thumb(QGraphicsItem):
    size = drawn = SIZE_DEFAULT
    store = ThumbStore()

    def __init__(self, path, ts, w, h, color):
        super().__init__()
        self.path, self.ts, self.w, self.h, self.color = path, ts, w, h, color
        self.key = os.path.normcase(path)
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIgnoresTransformations | QGraphicsItem.ItemHasNoContents)

    def boundingRect(self):
        s = Thumb.drawn
        return QRectF(-s / 2, -s / 2, s, s)

    def paint(self, *args):
        pass

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.setZValue(1 if value else 0)
        return super().itemChange(change, value)


class HoverLoader(QThread):
    done = Signal(str, object)

    def __init__(self, path, size, parent):
        super().__init__(parent)
        self.path, self.size = path, size

    def run(self):
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        reader.setScaledSize(reader.size().scaled(HOVER_PX, HOVER_PX, Qt.KeepAspectRatio))
        img = reader.read()
        if not img.isNull():
            self.done.emit(self.path, img)


class MapView(QGraphicsView):
    menuRequested = Signal(object, object)

    def __init__(self, scene):
        super().__init__(scene)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.items, self.colors, self.selected = [], [], []
        self.xy = self.shown = self.half = self.aspect = self.near = None
        self.pressItem = None
        self.collapseItem = None
        self.panFrom = None
        self.setMouseTracking(True)
        self.hoverItem = None
        self.hoverLabel = QLabel(self.viewport())
        self.hoverLabel.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hoverLabel.setStyleSheet(f"border: 1px solid {theme.current['border']}; background: {theme.current['bg']};")
        self.hoverLabel.hide()
        self.hoverTimer = QTimer(singleShot=True, interval=HOVER_DELAY_MS, timeout=self.show_hover)

    def track_hover(self, pos):
        item = self.itemAt(pos)
        self.hoverPos = pos
        if item is not self.hoverItem:
            self.hoverItem = item
            self.hoverLabel.hide()
            if item:
                self.hoverTimer.start()
        elif self.hoverLabel.isVisible():
            self.place_hover()

    def show_hover(self):
        item = self.hoverItem
        if not item:
            return
        s = HOVER_PX / max(item.w, item.h, 1)
        size = QSize(max(int(item.w * s), 1), max(int(item.h * s), 1))
        Thumb.store.db = Thumb.store.db or sqlite3.connect(DB_PATH)
        row = Thumb.store.db.execute("select thumb from img where path=?", (item.path,)).fetchone()
        self.set_hover(item.path, QImage.fromData(row[0]).scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation) if row else QImage(size, QImage.Format_RGB32))
        loader = HoverLoader(item.path, size, self)
        loader.done.connect(self.set_hover)
        loader.finished.connect(loader.deleteLater)
        loader.start()

    def set_hover(self, path, img):
        if not self.hoverItem or self.hoverItem.path != path:
            return
        self.hoverLabel.setPixmap(QPixmap.fromImage(img))
        self.hoverLabel.adjustSize()
        self.place_hover()
        self.hoverLabel.show()
        self.hoverLabel.raise_()

    def place_hover(self):
        w, h, p = self.hoverLabel.width(), self.hoverLabel.height(), self.hoverPos
        x = p.x() + 16 if p.x() + 16 + w <= self.viewport().width() else p.x() - 16 - w
        y = p.y() + 16 if p.y() + 16 + h <= self.viewport().height() else p.y() - 16 - h
        self.hoverLabel.move(max(x, 0), max(y, 0))

    def hide_hover(self):
        self.hoverTimer.stop()
        self.hoverItem = None
        self.hoverLabel.hide()

    def leaveEvent(self, e):
        self.hide_hover()
        super().leaveEvent(e)

    def paintEvent(self, e):
        store = Thumb.store
        store.set_size(Thumb.drawn, self.devicePixelRatioF())
        store.deadline, store.pending, store.evicted = time.perf_counter() + LOAD_MS / 1000, False, False
        super().paintEvent(e)
        if store.pending and not store.evicted:
            QTimer.singleShot(15, self.viewport().update)

    def drawBackground(self, p, rect):
        p.fillRect(rect, theme.color("bg"))

    def drawForeground(self, p, rect):
        if self.xy is None or not self.items:
            return
        t = self.viewportTransform()
        v = self.xy * (t.m11(), t.m22()) + (t.dx(), t.dy())
        s, w, h = Thumb.drawn, self.viewport().width(), self.viewport().height()
        on = np.nonzero(self.shown & (v[:, 0] > -s) & (v[:, 0] < w + s) & (v[:, 1] > -s) & (v[:, 1] < h + s))[0]
        useThumb = len(on) <= THUMB_SHOW_MAX and s >= 12
        sel = [i for i in self.selected if self.shown[i]]
        p.save()
        p.resetTransform()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        pen = QPen(theme.color("accent"), 2)
        near = self.near
        groups = [(on, 1.0)] if near is None else [(on[~near[on]], DIM_OPACITY), (on[near[on]], 1.0)]
        groups.append((np.array(sel, int), 1.0))
        for g, (idx, opacity) in enumerate(groups):
            p.setOpacity(opacity)
            for i in idx.tolist():
                (x, y), (hw, hh) = v[i], self.half[i]
                r = QRectF(x - hw, y - hh, hw * 2, hh * 2)
                pm = Thumb.store.get(self.items[i].path) if useThumb else None
                if pm and not pm.isNull():
                    p.drawPixmap(r, pm, QRectF(pm.rect()))
                else:
                    p.fillRect(r, self.colors[i])
                if g == len(groups) - 1:
                    p.setPen(pen)
                    p.drawRect(r)
        p.restore()

    def update_size(self):
        if self.aspect is None:
            return
        s = min(GAP * SPREAD * 0.8 * self.transform().m11(), SIZE_DEFAULT) * Thumb.size / SIZE_DEFAULT
        if s != Thumb.drawn:
            for item in self.items:
                item.prepareGeometryChange()
            Thumb.drawn = s
        r = self.aspect
        self.half = np.column_stack([np.where(r >= 1, s / 2, s * r / 2), np.where(r >= 1, s / 2 / r, s / 2)])
        self.viewport().update()

    def wheelEvent(self, e):
        f = ZOOM_STEP ** (e.angleDelta().y() / 120)
        self.scale(f, f)
        self.update_size()
        self.track_hover(e.position().toPoint())

    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        self.hide_hover()
        if e.button() in (Qt.RightButton, Qt.MiddleButton):
            self.panFrom = self.panStart = pos
            return
        item = self.itemAt(pos)
        if item and e.button() == Qt.LeftButton:
            self.pressItem, self.pressPos = item, pos
            if e.modifiers() & Qt.ControlModifier:
                item.setSelected(not item.isSelected())
            elif not item.isSelected():
                self.scene().clearSelection()
                item.setSelected(True)
            return
        if e.button() == Qt.LeftButton and not e.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier):
            self.panFrom = self.panStart = pos
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if e.buttons() == Qt.NoButton:
            self.track_hover(pos)
        if self.panFrom is not None:
            d = pos - self.panFrom
            self.panFrom = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
            return
        if self.pressItem and (pos - self.pressPos).manhattanLength() > 5:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(i.path) for i in self.scene().selectedItems()])
            drag = QDrag(self)
            drag.setMimeData(mime)
            pm = Thumb.store.cache.get(self.pressItem.path)
            if pm and not pm.isNull():
                drag.setPixmap(pm.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.pressItem = None
            drag.exec(Qt.CopyAction | Qt.MoveAction, Qt.CopyAction)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        pos = e.position().toPoint()
        if e.button() == Qt.RightButton and self.panFrom is not None and (pos - self.panStart).manhattanLength() <= 5 and self.itemAt(pos):
            self.menuRequested.emit(self.itemAt(pos), e.globalPosition().toPoint())
        if e.button() == Qt.LeftButton and self.panFrom is not None and (pos - self.panStart).manhattanLength() <= 5:
            self.scene().clearSelection()
        self.panFrom = None
        item = self.pressItem
        if item and not e.modifiers() & Qt.ControlModifier and len(self.scene().selectedItems()) > 1:
            self.collapseItem = item
            QTimer.singleShot(QApplication.doubleClickInterval(), lambda: self.collapse(item))
        self.pressItem = None
        super().mouseReleaseEvent(e)

    def collapse(self, item):
        if self.collapseItem is item:
            self.scene().clearSelection()
            item.setSelected(True)

    def mouseDoubleClickEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        self.collapseItem = None
        if item:
            for i in (self.scene().selectedItems() if item.isSelected() else [item]):
                os.startfile(i.path)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ImageMap")
        self.resize(1500, 900)
        self.items, self.coords = [], None
        self.scene = QGraphicsScene()
        self.view = MapView(self.scene)
        self.view.menuRequested.connect(self.image_menu)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemSelectionChanged.connect(self.filter_folder)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.folder_menu)
        self.hidden = set()
        self.preview = QLabel(alignment=Qt.AlignCenter)
        self.preview.setFixedHeight(PREVIEW_PX)
        self.info = QLabel(wordWrap=True, alignment=Qt.AlignTop | Qt.AlignLeft)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.slider = QSlider(Qt.Horizontal, minimum=SIZE_MIN, maximum=SIZE_MAX, value=SIZE_DEFAULT)
        self.slider.setFixedWidth(220)
        self.slider.valueChanged.connect(self.resize_thumbs)
        self.timeSort = ToggleSwitch("時間ソート")
        self.timeSort.toggled.connect(self.apply_layout)
        self.dateRange = RangeSlider()
        self.dateRange.setFixedWidth(260)
        self.dateRange.changed.connect(self.apply_filter)
        self.dateLabel = QLabel()
        self.search = QLineEdit(placeholderText="タグ検索")
        self.search.setFixedWidth(200)
        self.search.setEnabled(False)
        self.search.returnPressed.connect(self.run_search)
        self.clipStatus = QLabel()
        self.clip = None
        self.clipEmb = self.searchMask = None
        self.settings = QSettings("ImageMap", "ImageMap")
        self.root = self.settings.value("root", "")
        self.root = true_case(self.root) if self.root and os.path.isdir(self.root) else self.root
        self.folderPrefix = ""
        self.status = QLabel()
        pick = QPushButton("フォルダ選択")
        pick.clicked.connect(self.choose_folder)

        self.slider.setFixedHeight(CONTROL_H)
        self.dateRange.setFixedHeight(CONTROL_H)
        bars = []
        for lefts, rights in (([pick], []), ([QLabel("サムネ"), self.slider, self.timeSort, QLabel("撮影日"), self.dateRange, self.dateLabel], [self.clipStatus, self.search, self.status])):
            bar = QWidget()
            bar.setFixedHeight(BAR_H)
            lay = QHBoxLayout(bar)
            lay.setContentsMargins(PAD * 2, 0, PAD * 2, 0)
            lay.setSpacing(PAD * 3)
            for w in lefts:
                lay.addWidget(w, 0, Qt.AlignVCenter)
            lay.addStretch()
            for w in rights:
                lay.addWidget(w, 0, Qt.AlignVCenter)
            bars.append(bar)
        infoBox = QWidget()
        infoLay = QVBoxLayout(infoBox)
        infoLay.addWidget(self.preview)
        infoLay.addWidget(self.info, 1)
        treeBox = QWidget()
        treeLay = QVBoxLayout(treeBox)
        treeLay.setContentsMargins(0, 0, 0, 0)
        treeLay.setSpacing(0)
        treeLay.addWidget(bars[0])
        treeLay.addWidget(self.tree, 1)
        left = QSplitter(Qt.Vertical)
        left.addWidget(treeBox)
        left.addWidget(infoBox)
        left.setSizes([500, 400])
        right = QWidget()
        rightLay = QVBoxLayout(right)
        rightLay.setContentsMargins(0, 0, 0, 0)
        rightLay.setSpacing(0)
        rightLay.addWidget(bars[1])
        rightLay.addWidget(self.view, 1)
        main = QSplitter(Qt.Horizontal)
        main.addWidget(left)
        main.addWidget(right)
        main.setSizes([320, 1180])
        self.setCentralWidget(main)

        self.infoTimer = QTimer(singleShot=True, interval=60, timeout=self.show_info)
        self.scene.selectionChanged.connect(self.selection_changed)
        self.worker = None
        if self.root and os.path.isdir(self.root):
            self.load_root()
        else:
            self.status.setText("フォルダを選択してください")
            QTimer.singleShot(0, self.choose_folder)

    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "画像フォルダを選択", self.root or os.path.expanduser("~/Pictures"))
        if d:
            self.save_view()
            self.root = true_case(d)
            self.settings.setValue("root", self.root)
            self.load_root()

    def load_root(self):
        if self.worker:
            for sig in (self.worker.progress, self.worker.loaded, self.worker.laidout):
                sig.disconnect()
            self.worker.requestInterruption()
        if self.clip:
            for sig in (self.clip.progress, self.clip.ready):
                sig.disconnect()
            self.clip.requestInterruption()
            self.clip = None
        self.search.setEnabled(False)
        self.clipEmb = self.searchMask = None
        self.setWindowTitle(f"ImageMap - {self.root}")
        self.scene.clear()
        self.tree.clear()
        self.items, self.coords = [], None
        self.view.items, self.view.colors, self.view.selected, self.view.xy = [], [], [], None
        self.view.hide_hover()
        self.folderPrefix = dir_key(self.root)
        self.worker = Worker(self.root, self)
        self.worker.progress.connect(self.status.setText)
        self.worker.loaded.connect(self.build)
        self.worker.laidout.connect(self.set_coords)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def build(self, rows):
        self.db = sqlite3.connect(DB_PATH)
        saved = self.db.execute("select v from meta where k='hidden'").fetchone()
        self.hidden = set(json.loads(saved[0])) if saved else set()
        self.items = [Thumb(p, ts, w, h, QColor((c >> 16) & 255, (c >> 8) & 255, c & 255)) for p, ts, w, h, c, _ in rows]
        for item in self.items:
            self.scene.addItem(item)
        self.sync_view()
        self.sceneSize = np.sqrt(len(rows)) * SPREAD
        m = self.sceneSize * 0.5
        self.scene.setSceneRect(-m, -m, self.sceneSize + 2 * m, self.sceneSize + 2 * m)
        counts, children = {}, {}
        for item in self.items:
            self.count_dirs(os.path.dirname(item.path), counts, children)
        self.tree.clear()
        self.add_node(self.tree, self.root, counts, children)
        self.tree.topLevelItem(0).setExpanded(True)
        self.clip = ClipWorker([i.path for i in self.items], self)
        self.clip.progress.connect(self.clipStatus.setText)
        self.clip.ready.connect(self.clip_ready)
        self.clip.finished.connect(self.clip.deleteLater)
        self.clip.start()

    def clip_ready(self, emb):
        self.clipEmb = emb
        self.search.setEnabled(True)
        self.run_search()

    def run_search(self):
        q = self.search.text().strip()
        self.searchMask = None
        if q and self.clipEmb is not None:
            self.searchMask = np.zeros(len(self.items), bool)
            self.searchMask[np.argsort(-(self.clipEmb @ ClipWorker.encode_text(q)))[:SEARCH_TOP]] = True
        self.apply_filter()

    def sync_view(self):
        for k, item in enumerate(self.items):
            item.index = k
        ts = self.tsArr = np.array([i.ts for i in self.items])
        self.timeRank = np.argsort(np.argsort(ts)) / max(len(ts) - 1, 1)
        self.sortedTs = np.sort(ts)
        for item, r in zip(self.items, self.timeRank):
            item.rank = r
        self.view.items, self.view.colors = self.items, [i.color for i in self.items]
        self.view.aspect = np.array([i.w / max(i.h, 1) for i in self.items])
        self.resize_thumbs(Thumb.size)
        self.apply_layout()
        self.apply_filter()
        self.selection_changed()

    def count_dirs(self, d, counts, children):
        counts[d] = counts.get(d, 0) + 1
        if os.path.normcase(d) != os.path.normcase(self.root) and os.path.dirname(d) != d:
            children.setdefault(os.path.dirname(d), set()).add(d)
            self.count_dirs(os.path.dirname(d), counts, children)

    def add_node(self, parent, d, counts, children):
        node = QTreeWidgetItem(parent, [f"{os.path.basename(d) or d}  ({counts.get(d, 0)})"])
        node.setData(0, Qt.UserRole, d)
        node.setForeground(0, theme.color("sub" if dir_key(d) in self.hidden else "text"))
        for c in sorted(children.get(d, ()), key=str.lower):
            self.add_node(node, c, counts, children)

    def relabel(self, node, counts):
        d = node.data(0, Qt.UserRole)
        for i in reversed(range(node.childCount())):
            self.relabel(node.child(i), counts)
        if counts.get(d) or not node.parent():
            node.setText(0, f"{os.path.basename(d) or d}  ({counts.get(d, 0)})")
        else:
            node.parent().removeChild(node)

    def folder_menu(self, pos):
        node = self.tree.itemAt(pos)
        if not node:
            return
        d = node.data(0, Qt.UserRole)
        key = dir_key(d)
        menu = QMenu(self)
        hide = menu.addAction("再表示" if key in self.hidden else "非表示")
        delete = menu.addAction("削除")
        hide.setEnabled(node.parent() is not None)
        delete.setEnabled(node.parent() is not None)
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is hide:
            self.hidden ^= {key}
            self.db.execute("insert or replace into meta values('hidden', ?)", (json.dumps(sorted(self.hidden)),))
            self.db.commit()
            node.setForeground(0, theme.color("sub" if key in self.hidden else "text"))
            self.apply_filter()
        elif chosen is delete and QMessageBox.question(
                self, "フォルダの削除", f"{d}\nをフォルダごとごみ箱へ移しますか？\n画像以外のファイル（RAW・動画など）も一緒に移ります。") == QMessageBox.Yes:
            if QFile.moveToTrash(d)[0]:
                self.remove_items([i for i in self.items if i.key.startswith(key)])
            else:
                QMessageBox.warning(self, "フォルダの削除", "ごみ箱へ移せませんでした。使用中のファイルがないか確認してください。")

    def image_menu(self, item, pos):
        targets = self.scene.selectedItems() if item.isSelected() else [item]
        menu = QMenu(self)
        delete = menu.addAction(f"削除（{len(targets)}枚）" if len(targets) > 1 else "削除")
        if menu.exec(pos) is delete:
            self.remove_items([t for t in targets if QFile.moveToTrash(t.path)[0]])

    def remove_items(self, gone):
        goneIds = {id(i) for i in gone}
        keep = np.array([id(i) not in goneIds for i in self.items], bool)
        for table in ("img", "layouts", "exif", "clip"):
            self.db.executemany(f"delete from {table} where path=?", [(i.path,) for i in gone])
        self.db.commit()
        self.items = [i for i, k in zip(self.items, keep) if k]
        if self.coords is not None:
            self.coords = self.coords[keep]
        if self.clipEmb is not None:
            self.clipEmb = self.clipEmb[keep]
        if self.searchMask is not None:
            self.searchMask = self.searchMask[keep]
        self.sync_view()
        for i in gone:
            self.scene.removeItem(i)
        counts = {}
        for item in self.items:
            self.count_dirs(os.path.dirname(item.path), counts, {})
        self.relabel(self.tree.topLevelItem(0), counts)
        self.status.setText(f"{len(self.items)}枚")

    def selection_changed(self):
        sel = self.view.selected = [i.index for i in self.scene.selectedItems() if i.index < len(self.items) and self.items[i.index] is i]
        self.view.near = np.abs(self.tsArr - self.tsArr[sel[0]]) <= SAME_PERIOD_DAYS * 86400 if len(sel) == 1 else None
        self.view.viewport().update()
        self.infoTimer.start()

    def filter_folder(self):
        sel = self.tree.selectedItems()
        self.folderPrefix = dir_key(sel[0].data(0, Qt.UserRole) if sel else self.root)
        self.apply_filter()

    def apply_filter(self, *_):
        if not self.items:
            return
        lo, hi = self.dateRange.lo, self.dateRange.hi
        n = len(self.sortedTs) - 1
        self.dateLabel.setText(f"{datetime.fromtimestamp(self.sortedTs[round(lo * n)]):%Y-%m-%d} 〜 "
                               f"{datetime.fromtimestamp(self.sortedTs[round(hi * n)]):%Y-%m-%d}")
        hid = [h for h in self.hidden if not self.folderPrefix.startswith(h)]
        mask = self.searchMask
        shown = [lo <= i.rank <= hi and i.key.startswith(self.folderPrefix) and not any(i.key.startswith(h) for h in hid) and (mask is None or mask[k]) for k, i in enumerate(self.items)]
        for item, on in zip(self.items, shown):
            item.setVisible(on)
        self.view.shown = np.array(shown, bool)
        self.view.viewport().update()

    def set_coords(self, coords):
        if not len(coords):
            return
        first = self.coords is None
        self.coords = (coords - coords.min(0)) / np.maximum(np.ptp(coords, 0), 1e-9)
        self.apply_layout()
        if not first:
            return
        saved = json.loads(self.settings.value("views", "{}")).get(dir_key(self.root))
        if saved:
            size, zoom, cx, cy = saved
            self.slider.setValue(size)
            self.view.resetTransform()
            self.view.scale(zoom / self.sceneSize, zoom / self.sceneSize)
            self.view.centerOn(cx * self.sceneSize, cy * self.sceneSize)
        else:
            self.slider.setValue(SIZE_DEFAULT)
            self.view.fitInView(QRectF(0, 0, self.sceneSize, self.sceneSize), Qt.KeepAspectRatio)
        self.view.update_size()

    def save_view(self):
        if self.coords is None:
            return
        views = json.loads(self.settings.value("views", "{}"))
        c = self.view.mapToScene(self.view.viewport().rect().center())
        views[dir_key(self.root)] = [self.slider.value(), self.view.transform().m11() * self.sceneSize, c.x() / self.sceneSize, c.y() / self.sceneSize]
        self.settings.setValue("views", json.dumps(views))

    def apply_layout(self):
        if self.coords is None or len(self.coords) != len(self.items):
            return
        xy = np.column_stack([self.coords[:, 0], self.timeRank if self.timeSort.isChecked() else self.coords[:, 1]]) * self.sceneSize
        for item, (x, y) in zip(self.items, xy.tolist()):
            item.setPos(x, y)
        self.view.xy = xy
        self.view.viewport().update()

    def resize_thumbs(self, v):
        Thumb.size = v
        self.view.update_size()

    def show_info(self):
        sel = self.scene.selectedItems()
        if not sel:
            self.preview.clear()
            self.info.setText("")
            return
        item = sel[0]
        reader = QImageReader(item.path)
        reader.setAutoTransform(True)
        reader.setScaledSize(reader.size().scaled(PREVIEW_PX, PREVIEW_PX, Qt.KeepAspectRatio))
        self.preview.setPixmap(QPixmap.fromImage(reader.read()))
        head = f"<b>{len(sel)}枚選択</b><br>" if len(sel) > 1 else ""
        self.info.setText(head + f"<b>{os.path.basename(item.path)}</b><br>{os.path.dirname(item.path)}<br>"
                          f"{item.w} × {item.h} px<br>{os.path.getsize(item.path) / 1048576:.2f} MB<br>"
                          f"{datetime.fromtimestamp(item.ts):%Y-%m-%d %H:%M:%S}")

    def closeEvent(self, e):
        self.save_view()
        self.worker.requestInterruption()
        self.worker.wait(3000)
        os._exit(0)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    theme.apply(app, THEME)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
