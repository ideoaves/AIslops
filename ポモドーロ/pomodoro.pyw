import ctypes
import math
import time
import tkinter as tk
import winsound
from pathlib import Path

WORK_MIN = 25
SHORT_BREAK_MIN = 5
LONG_BREAK_MIN = 30
TIMES_PER_CYCLE = 4

WIDTH = 340
HEIGHT = 172
FACE = "#c0c0c0"
TITLE_BG = "#000080"
WORK_COLOR = "#000080"
BREAK_COLOR = "#008080"
FONT = ("Microsoft Sans Serif", 9)
TITLE_FONT = ("Microsoft Sans Serif", 9, "bold")
CLOCK_FONT = ("MS Gothic", 30)
GLYPH_FONT = ("Marlett", 8)
BLOCK_WIDTH = 8
POS_FILE = Path(__file__).with_name("position.txt")


class Pomodoro:
    def __init__(self, root):
        self.root = root
        self.cycle = 1
        self.time_no = 1
        self.phase = "work"
        self.running = False
        self.remaining = WORK_MIN * 60
        self.phase_end = 0
        self.buttons = {}
        self.pressed_tag = None

        root.title("Pomodoro")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        if POS_FILE.exists():
            x, y = POS_FILE.read_text().split()
        else:
            x = (root.winfo_screenwidth() - WIDTH) // 2
            y = (root.winfo_screenheight() - HEIGHT) // 2
        root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")

        c = self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, bg=FACE, highlightthickness=0)
        c.pack()
        c.bind("<ButtonRelease-1>", self.release)
        self.bevel(0, 0, WIDTH, HEIGHT, True, "frame")
        c.create_rectangle(3, 3, WIDTH - 4, 21, fill=TITLE_BG, outline="", tags="titlebar")
        c.create_text(8, 12, text="Pomodoro", anchor="w", fill="white", font=TITLE_FONT, tags="titlebar")
        c.tag_bind("titlebar", "<ButtonPress-1>", self.drag_start)
        c.tag_bind("titlebar", "<B1-Motion>", self.drag_move)
        self.bevel(12, 84, WIDTH - 12, 106, False, "frame")

        self.add_button("minimize", WIDTH - 41, 5, 16, 14, "0", GLYPH_FONT, self.minimize)
        self.add_button("close", WIDTH - 21, 5, 16, 14, "r", GLYPH_FONT, self.close)
        self.add_button("start", WIDTH // 2 - 96, 136, 88, 24, "Start", FONT, self.start)
        self.add_button("stop", WIDTH // 2 + 8, 136, 88, 24, "Stop", FONT, self.stop, False)

        root.after(10, self.show_in_taskbar)
        self.tick()

    # Win95風の立体枠を4本の線で描く
    def bevel(self, x0, y0, x1, y1, raised, tag):
        colors = ("white", "black", "#dfdfdf", "#808080") if raised else ("#808080", "white", "black", "#dfdfdf")
        for i, (light, dark) in enumerate([colors[0:2], colors[2:4]]):
            l, t, r, b = x0 + i, y0 + i, x1 - 1 - i, y1 - 1 - i
            self.canvas.create_line(l, b, l, t, r, t, fill=light, tags=tag)
            self.canvas.create_line(l, b, r, b, r, t - 1, fill=dark, tags=tag)

    # ボタンを登録し、押下と離した時の処理を結びつける
    def add_button(self, tag, x, y, w, h, text, font, command, enabled=True):
        self.buttons[tag] = dict(rect=(x, y, x + w, y + h), text=text, font=font,
                                 command=command, enabled=enabled, pressed=False)
        self.canvas.tag_bind(tag, "<ButtonPress-1>", lambda e: self.press(tag))
        self.draw_button(tag)

    # ボタンを状態（押下・無効）に合わせて描き直す
    def draw_button(self, tag):
        b = self.buttons[tag]
        x0, y0, x1, y1 = b["rect"]
        c = self.canvas
        c.delete(tag)
        c.create_rectangle(x0, y0, x1 - 1, y1 - 1, fill=FACE, outline="", tags=tag)
        self.bevel(x0, y0, x1, y1, not b["pressed"], tag)
        cx, cy = (x0 + x1) // 2 + b["pressed"], (y0 + y1) // 2 + b["pressed"]
        if b["enabled"]:
            c.create_text(cx, cy, text=b["text"], font=b["font"], tags=tag)
        else:
            c.create_text(cx + 1, cy + 1, text=b["text"], font=b["font"], fill="white", tags=tag)
            c.create_text(cx, cy, text=b["text"], font=b["font"], fill="#808080", tags=tag)

    def set_button(self, tag, **kw):
        self.buttons[tag].update(kw)
        self.draw_button(tag)

    def press(self, tag):
        if self.buttons[tag]["enabled"]:
            self.pressed_tag = tag
            self.set_button(tag, pressed=True)

    # 押されていたボタンを戻し、ボタン上で離された時だけコマンドを実行する
    def release(self, e):
        tag, self.pressed_tag = self.pressed_tag, None
        if tag is None:
            return
        b = self.buttons[tag]
        self.set_button(tag, pressed=False)
        x0, y0, x1, y1 = b["rect"]
        if x0 <= e.x < x1 and y0 <= e.y < y1:
            b["command"]()

    def drag_start(self, e):
        self.drag_offset = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self.drag_offset[0]}+{e.y_root - self.drag_offset[1]}")

    # 次回起動用に位置を保存して終了する
    def close(self):
        POS_FILE.write_text(f"{self.root.winfo_x()} {self.root.winfo_y()}")
        self.root.destroy()

    # 枠なしウィンドウをタスクバーに表示させ、最小化できるスタイルを足す
    def show_in_taskbar(self):
        user32 = ctypes.windll.user32
        self.hwnd = user32.GetParent(self.root.winfo_id())
        user32.SetWindowLongW(self.hwnd, -20, (user32.GetWindowLongW(self.hwnd, -20) & ~0x80) | 0x40000)
        user32.SetWindowLongW(self.hwnd, -16, user32.GetWindowLongW(self.hwnd, -16) | 0x20000)
        self.root.withdraw()
        self.root.after(10, self.show_topmost)

    # スタイル変更で外れた最前面指定を、表示し直した後にかけ直す
    def show_topmost(self):
        self.root.deiconify()
        ctypes.windll.user32.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0, 0x3)

    def minimize(self):
        ctypes.windll.user32.ShowWindow(self.hwnd, 6)

    def phase_seconds(self):
        if self.phase == "work":
            return WORK_MIN * 60
        return (LONG_BREAK_MIN if self.time_no == TIMES_PER_CYCLE else SHORT_BREAK_MIN) * 60

    # 今のタイムを作業の頭から始める
    def start(self):
        self.phase = "work"
        self.phase_end = time.monotonic() + self.phase_seconds()
        self.running = True
        self.set_button("start", enabled=False)
        self.set_button("stop", enabled=True)

    def stop(self):
        self.running = False
        self.set_button("start", enabled=True, text="Resume")
        self.set_button("stop", enabled=False)

    # 作業→休憩→次のタイムへ進め、音とウィンドウ前面化で知らせる
    def advance(self):
        if self.phase == "work":
            self.phase = "break"
        else:
            self.phase = "work"
            self.time_no += 1
            if self.time_no > TIMES_PER_CYCLE:
                self.time_no = 1
                self.cycle += 1
        self.phase_end += self.phase_seconds()
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
        ctypes.windll.user32.ShowWindow(self.hwnd, 9)

    # 残り時間を進めて、カウンタと時間バーを描き直す
    def tick(self):
        if self.running:
            self.remaining = self.phase_end - time.monotonic()
            if self.remaining <= 0:
                self.advance()
                self.remaining = self.phase_end - time.monotonic()
        c = self.canvas
        c.delete("status")
        state = ("Working..." if self.phase == "work" else "Resting...") if self.running else "Stopped"
        c.create_text(14, 120, text=f"{state}  {self.cycle} ({self.time_no}/{TIMES_PER_CYCLE})",
                      anchor="w", font=FONT, tags="status")
        m, s = divmod(max(0, math.ceil(self.remaining)), 60)
        c.create_text(WIDTH // 2, 54, text=f"{m:02d}:{s:02d}", font=CLOCK_FONT, tags="status")

        left, right = 16, WIDTH - 16
        filled = (right - left) * (1 - self.remaining / self.phase_seconds())
        color = WORK_COLOR if self.phase == "work" else BREAK_COLOR
        x = left
        while x + BLOCK_WIDTH <= left + filled:
            c.create_rectangle(x, 88, x + BLOCK_WIDTH - 1, 101, fill=color, outline="", tags="status")
            x += BLOCK_WIDTH + 2
        self.root.after(200, self.tick)


root = tk.Tk()
Pomodoro(root)
root.mainloop()
