import os
import json
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import copy
import re
import cv2

IMAGE_DIR = "image"
DATA_FILE = "data.json"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm")

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def scan_images():
    data = load_data()
    changed = False
    for fn in list(data.keys()):
        if "loca" not in data[fn]:
            data[fn]["loca"] = data[fn].get("tags", "")
            data[fn]["tags"] = ""
            changed = True

    # Scan root directory and subdirectories (1 level deep)
    def scan_directory(directory, relative_path=""):
        nonlocal changed
        if not os.path.exists(directory):
            return
        
        try:
            for item in os.listdir(directory):
                item_path = os.path.join(directory, item)
                
                if os.path.isdir(item_path):
                    # Recursively scan subdirectories (1 level deep)
                    if relative_path == "":  # Only go 1 level deep
                        scan_directory(item_path, item)
                elif item.lower().endswith(IMAGE_EXTS + VIDEO_EXTS):
                    # Create relative path for storage
                    if relative_path:
                        relative_fn = os.path.join(relative_path, item)
                    else:
                        relative_fn = item
                    
                    if relative_fn not in data:
                        data[relative_fn] = {"loca": "", "tags": "", "date": "", "cap": ""}
                        changed = True
        except:
            pass
    
    scan_directory(IMAGE_DIR)
    
    if changed:
        save_data(data)
    return data


class ImageManager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("七十年代画像資料")
        self.geometry("1600x1200")

        os.makedirs(IMAGE_DIR, exist_ok=True)
        self.data = scan_images()
        self.images = {}
        self.current = None
        self.selection = set()
        self.anchor = None
        self.current_items = []
        self.image_widgets = {}
        self.history = []
        self.redo_history = []
        self.group_by = "date"

        self.video_cap = None
        self.video_playing = False
        self._video_job = None
        self.video_dragging = False
        
        # Image zoom and pan variables
        self.image_scale = 1.0
        self.image_x = 0
        self.image_y = 0
        self.image_dragging = False
        self.image_drag_start_x = 0
        self.image_drag_start_y = 0

        self.build_ui()
        self.thumbs = {}
        self.check_files()

    #UIデザインするよ

    def build_ui(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        # search
        search_frame = tk.Frame(self)
        search_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        self.search = tk.Entry(search_frame)
        self.search.pack(side="left", fill="x", expand=True)
        self.search.bind("<KeyRelease>", lambda e: self.render())
        
        self.group_btn = tk.Button(search_frame, text="表示: 年代", command=self.toggle_group)
        self.group_btn.pack(side="left", padx=(5, 0))

        # list
        self.canvas = tk.Canvas(self, width=670)
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.frame = tk.Frame(self.canvas)

        self.frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scroll.set)

        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.scroll.grid(row=1, column=0, sticky="nse")
        self.bind_all("<Control-MouseWheel>", self._on_mousewheel)
        self.bind("<Control-z>", self.undo)
        self.bind("<Control-Shift-Z>", self.redo)

        # editor
        edit = tk.Frame(self)
        edit.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=5)
        edit.bind("<Configure>", self.on_edit_resize)

        self.name_label = tk.Label(edit, text="", wraplength=240)
        self.name_label.pack(anchor="w")

        self.preview_label = tk.Label(edit)
        self.preview_label.pack(pady=5)
        self.preview_label.bind("<Button-1>", self.on_image_click)
        self.preview_label.bind("<B1-Motion>", self.on_image_drag)
        self.preview_label.bind("<ButtonRelease-1>", self.on_image_release)
        self.preview_label.bind("<MouseWheel>", self.on_image_wheel)
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        
        # Video progress bar (initially hidden)
        self.video_progress = ttk.Progressbar(edit, mode="determinate")
        self.video_progress.pack(fill="x", pady=2)
        self.video_progress.pack_forget()  # Hide initially
        self.video_progress.bind("<Button-1>", self.seek_video_start)
        self.video_progress.bind("<B1-Motion>", self.seek_video_drag)
        self.video_progress.bind("<ButtonRelease-1>", self.seek_video_end)
        
        # Time label (initially hidden)
        self.time_label = tk.Label(edit, text="00:00 / 00:00")
        self.time_label.pack(pady=2)
        self.time_label.pack_forget()  # Hide initially

        tk.Label(edit, text="場所").pack(anchor="w")
        self.loca = tk.Entry(edit)
        self.loca.pack(fill="x")

        tk.Label(edit, text="年月日").pack(anchor="w")
        self.date = tk.Entry(edit)
        self.date.pack(fill="x")
        
        tk.Label(edit, text="タグ").pack(anchor="w")
        self.tags = tk.Entry(edit)
        self.tags.pack(fill="x")

        tk.Label(edit, text="説明").pack(anchor="w")
        self.cap = tk.Entry(edit)
        self.cap.pack(fill="x")

        self.loca.bind("<Return>", self.update_data)
        self.tags.bind("<Return>", self.update_data)
        self.date.bind("<Return>", self.update_data)
        self.cap.bind("<Return>", self.update_data)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    def on_edit_resize(self, event):
        if hasattr(self, "_resize_timer"):
            self.after_cancel(self._resize_timer)
        self._resize_timer = self.after(100, self.update_editor)
    
    # imageファイルを監視して更新するよ
    def check_files(self):
        current_files = set()
        
        def scan_directory(directory, relative_path=""):
            if not os.path.exists(directory):
                return
            
            try:
                for item in os.listdir(directory):
                    item_path = os.path.join(directory, item)
                    
                    if os.path.isdir(item_path):
                        # Recursively scan subdirectories (1 level deep)
                        if relative_path == "":  # Only go 1 level deep
                            scan_directory(item_path, item)
                    elif item.lower().endswith(IMAGE_EXTS + VIDEO_EXTS):
                        # Create relative path for storage
                        if relative_path:
                            relative_fn = os.path.join(relative_path, item)
                        else:
                            relative_fn = item
                        current_files.add(relative_fn)
            except:
                pass
        
        scan_directory(IMAGE_DIR)

        known_files = set(self.data.keys())
        
        added = current_files - known_files
        removed = known_files - current_files
        
        if added:
            for fn in added:
                self.data[fn] = {"loca": "", "tags": "", "date": "", "cap": ""}
        
        if removed:
            for fn in removed:
                self.data.pop(fn, None)
                self.selection.discard(fn)
                if self.current == fn:
                    self.current = None

        thumbs_updated = False
        for fn in self.data:
            if fn not in self.thumbs:
                path = os.path.join(IMAGE_DIR, fn)
                try:
                    img = None
                    if fn.lower().endswith(VIDEO_EXTS):
                        cap = cv2.VideoCapture(path)
                        ret, frame = cap.read()
                        cap.release()
                        if ret:
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            img = Image.fromarray(frame)
                    else:
                        img = Image.open(path)
                    
                    if img:
                        img.thumbnail((150, 150))
                        self.thumbs[fn] = ImageTk.PhotoImage(img)
                        thumbs_updated = True
                except Exception as e:
                    print(f"Error loading thumbnail for {fn}: {e}")
                    pass
        
        for fn in list(self.thumbs.keys()):
            if fn not in self.data:
                self.thumbs.pop(fn, None)
                thumbs_updated = True

        if added or removed:
            save_data(self.data)

        if added or removed or thumbs_updated:
            self.render()
            self.update_editor()
        
        self.after(2000, self.check_files)

    def toggle_group(self):
        self.group_by = "loca" if self.group_by == "date" else "date"
        self.group_btn.config(text="表示: 場所" if self.group_by == "loca" else "表示: 年代")
        self.render()

    #表示

    def render(self):
        for w in self.frame.winfo_children():
            w.destroy()
        self.image_widgets = {}
        self.current_items = []

        keywords = self.search.get().split()
        
        def get_loca_group(info):
            loca = info.get("loca", "")
            parts = loca.split()
            if not parts:
                return "不明"
            group = parts[0]
            if group == "東京" and len(parts) > 1 and parts[1].endswith("区"):
                group = parts[1]
            return group

        if self.group_by == "loca":
            items = sorted(self.data.items(), key=lambda x: (get_loca_group(x[1]), x[1].get("date", "")))
        else:
            items = sorted(self.data.items(), key=lambda x: x[1].get("date", ""))

        current_group = None
        year_frame = None
        col = 0
        MAX_COLS = 4

        for name, info in items:
            search_target = info.get("loca", "") + " " + info.get("tags", "")
            if keywords and not all(k in search_target for k in keywords):
                continue

            if name not in self.thumbs:
                continue
            
            self.current_items.append(name)

            if self.group_by == "loca":
                group = get_loca_group(info)
            else:
                date_str = info.get("date", "")
                group = date_str[:4] if len(date_str) >= 4 else (date_str if date_str else "No Date")

            if group != current_group:
                current_group = group
                year_frame = tk.LabelFrame(self.frame, text=group)
                year_frame.pack(fill="x", padx=5, pady=5)
                col = 0

            lbl = tk.Label(year_frame, image=self.thumbs[name], bd=3, relief="flat")
            lbl.grid(row=col // MAX_COLS, column=col % MAX_COLS, padx=5, pady=5)
            lbl.bind("<Button-1>", lambda e, n=name: self.select(e, n))
            self.image_widgets[name] = lbl

            col += 1
        
        self.update_selection_visuals()

    def update_selection_visuals(self):
        for name, widget in self.image_widgets.items():
            if name in self.selection:
                widget.config(relief="solid", bg="#00aaff")
            else:
                widget.config(relief="flat", bg="SystemButtonFace")

    #選択して修正するよ

    def select(self, event, name):
        ctrl = (event.state & 0x4) != 0
        shift = (event.state & 0x1) != 0

        if shift and self.anchor and self.anchor in self.current_items and name in self.current_items:
            idx_anchor = self.current_items.index(self.anchor)
            idx_curr = self.current_items.index(name)
            start, end = sorted((idx_anchor, idx_curr))
            subset = set(self.current_items[start : end + 1])
            if ctrl:
                self.selection.update(subset)
            else:
                self.selection = subset
        elif ctrl:
            if name in self.selection:
                self.selection.remove(name)
            else:
                self.selection.add(name)
            self.anchor = name
        else:
            self.selection = {name}
            self.anchor = name

        if not self.selection:
            self.current = None
        elif name in self.selection:
            self.current = name
        else:
            self.current = list(self.selection)[-1]

        self.update_selection_visuals()
        self.update_editor()

    def on_image_click(self, event):
        if self.current and self.current.lower().endswith(VIDEO_EXTS):
            # For videos, toggle play/pause
            self.toggle_video(event)
        else:
            # For images, start dragging (no zoom)
            self.image_dragging = True
            self.image_drag_start_x = event.x
            self.image_drag_start_y = event.y
    
    def on_image_wheel(self, event):
        if self.current and self.current.lower().endswith(VIDEO_EXTS):
            return  # Don't zoom videos
        
        # Prevent the event from propagating to the list
        event.widget.focus_set()
        
        # Zoom with mouse wheel
        if event.delta > 0:
            self.image_scale = min(self.image_scale * 1.1, 5.0)  # Zoom in, max 5x
        else:
            self.image_scale = max(self.image_scale / 1.1, 1.0)  # Zoom out, min 1x
        
        # Reset position when zooming to 1.0
        if abs(self.image_scale - 1.0) < 0.01:
            self.image_x = 0
            self.image_y = 0
        
        self.update_image_display()
        return "break"  # Prevent event propagation
    
    def on_image_drag(self, event):
        if self.image_dragging and not self.current.lower().endswith(VIDEO_EXTS):
            dx = event.x - self.image_drag_start_x
            dy = event.y - self.image_drag_start_y
            
            # Get display area and image dimensions
            canvas_width = self.name_label.master.winfo_width() - 20
            if canvas_width < 100: canvas_width = 240
            canvas_height = 600
            
            # Calculate image dimensions at current scale
            try:
                path = os.path.join(IMAGE_DIR, self.current)
                img = Image.open(path)
                orig_width, orig_height = img.size
                img_width = int(orig_width * self.image_scale)
                img_height = int(orig_height * self.image_scale)
            except Exception as e:
                print(f"Error loading image for drag: {e}")
                return
            
            # Update position with boundary constraints
            new_x = self.image_x + dx
            new_y = self.image_y + dy
            
            # Limit dragging to keep image within canvas bounds
            if img_width > canvas_width:
                new_x = max(canvas_width - img_width, min(0, new_x))
            else:
                new_x = (canvas_width - img_width) // 2  # Center if smaller
                
            if img_height > canvas_height:
                new_y = max(canvas_height - img_height, min(0, new_y))
            else:
                new_y = (canvas_height - img_height) // 2  # Center if smaller
            
            self.image_x = new_x
            self.image_y = new_y
            self.image_drag_start_x = event.x
            self.image_drag_start_y = event.y
            self.update_image_display()
    
    def on_image_release(self, event):
        self.image_dragging = False
    
    def update_image_display(self):
        if not self.current or self.current.lower().endswith(VIDEO_EXTS):
            return
            
        try:
            path = os.path.join(IMAGE_DIR, self.current)
            img = Image.open(path)
            
            # Get original image dimensions
            orig_width, orig_height = img.size
            
            # Get display area size
            canvas_width = self.name_label.master.winfo_width() - 20
            if canvas_width < 100: canvas_width = 240
            canvas_height = 600
            
            # Calculate base scale for fitting at 1.0
            scale_x = canvas_width / orig_width
            scale_y = canvas_height / orig_height
            base_scale = min(scale_x, scale_y, 1.0)  # Don't upscale beyond original
            
            # Apply zoom relative to the fitted size
            actual_scale = base_scale * self.image_scale
            new_width = int(orig_width * actual_scale)
            new_height = int(orig_height * actual_scale)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Create display canvas
            canvas = Image.new('RGB', (canvas_width, canvas_height), 'white')
            
            # Get current image dimensions after zoom
            img_width, img_height = img.size
            
            # Initialize position for first display
            if self.image_x == 0 and self.image_y == 0:
                self.image_x = (canvas_width - img_width) // 2
                self.image_y = (canvas_height - img_height) // 2
            
            # Calculate valid paste position - allow negative for dragging
            paste_x = self.image_x
            paste_y = self.image_y
            
            # Paste image on canvas
            canvas.paste(img, (paste_x, paste_y))
            
            self._preview_img = ImageTk.PhotoImage(canvas)
            self.preview_label.config(image=self._preview_img)
        except Exception as e:
            print(f"Error displaying image: {e}")
            pass
    
    def update_editor(self):
        self.stop_video()
        # Reset image zoom/pan when switching files
        self.image_scale = 1.0
        self.image_x = 0
        self.image_y = 0
        
        if not self.current:
            self.name_label.config(text="")
            self.preview_label.config(image="")
            self.tags.delete(0, tk.END)
            self.date.delete(0, tk.END)
            self.cap.delete(0, tk.END)
            # Hide video controls
            self.video_progress.pack_forget()
            self.time_label.pack_forget()
            return

        text = self.current
        if len(self.selection) > 1:
            text += f" (+{len(self.selection)-1})"
        self.name_label.config(text=text)
        
        target_width = self.name_label.master.winfo_width() - 20
        if target_width < 100: target_width = 240

        try:
            path = os.path.join(IMAGE_DIR, self.current)
            
            if self.current.lower().endswith(VIDEO_EXTS):
                # Show video controls immediately after preview
                self.preview_label.bind("<Button-1>", self.toggle_video)
                self.video_progress.pack(fill="x", pady=2)
                self.time_label.pack(pady=2)
                
                # Start video playback immediately
                self.play_video()
            else:
                # Hide video controls for images
                self.video_progress.pack_forget()
                self.time_label.pack_forget()
                # Update image display with zoom/pan support
                self.update_image_display()
        except Exception as e:
            print(f"Error loading file {self.current}: {e}")
            self.preview_label.config(image="")
            self.video_progress.pack_forget()
            self.time_label.pack_forget()

        self.loca.delete(0, tk.END)
        self.tags.delete(0, tk.END)
        # 複数選択時はタグ欄を空欄にする（追記モードのため）
        if len(self.selection) == 1:
            self.loca.insert(0, self.data[self.current].get("loca", ""))
            self.tags.insert(0, self.data[self.current]["tags"])
        self.date.delete(0, tk.END)
        self.date.insert(0, self.data[self.current]["date"])
        self.cap.delete(0, tk.END)
        self.cap.insert(0, self.data[self.current].get("cap", ""))

    def stop_video(self):
        if self._video_job:
            self.after_cancel(self._video_job)
            self._video_job = None
        if self.video_cap:
            self.video_cap.release()
            self.video_cap = None
        self.video_playing = False
        self.video_progress["value"] = 0
        self.time_label.config(text="00:00 / 00:00")

    def toggle_video(self, event=None):
        if self.video_playing:
            # Pause: keep current position but stop animation
            self.video_playing = False
            if self._video_job:
                self.after_cancel(self._video_job)
                self._video_job = None
        else:
            # Resume from current position
            self.video_playing = True
            self.animate_video()

    def play_video(self):
        path = os.path.join(IMAGE_DIR, self.current)
        self.video_cap = cv2.VideoCapture(path)
        self.video_playing = True
        
        # Get video properties
        self.video_total_frames = int(self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = self.video_cap.get(cv2.CAP_PROP_FPS)
        total_seconds = self.video_total_frames / fps if fps > 0 else 0
        
        # Update time label
        total_time = f"{int(total_seconds//60):02d}:{int(total_seconds%60):02d}"
        self.time_label.config(text=f"00:00 / {total_time}")
        
        # Reset progress to start
        self.video_progress["value"] = 0
        self.video_current_frame = 0
        
        self.animate_video()

    def animate_video(self):
        if not self.video_playing or not self.video_cap.isOpened() or self.video_dragging:
            return
        
        ret, frame = self.video_cap.read()
        if ret:
            target_width = self.name_label.master.winfo_width() - 20
            if target_width < 100: target_width = 240
            
            h, w, _ = frame.shape
            scale = min(target_width / w, target_width / h)
            new_w, new_h = int(w * scale), int(h * scale)
            
            frame = cv2.resize(frame, (new_w, new_h))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame)
            self._preview_img = ImageTk.PhotoImage(img)
            self.preview_label.config(image=self._preview_img)
            
            # Update progress
            self.video_current_frame = int(self.video_cap.get(cv2.CAP_PROP_POS_FRAMES))
            progress = (self.video_current_frame / self.video_total_frames) * 100 if self.video_total_frames > 0 else 0
            self.video_progress["value"] = progress
            
            # Update time label
            fps = self.video_cap.get(cv2.CAP_PROP_FPS)
            current_seconds = self.video_current_frame / fps if fps > 0 else 0
            total_seconds = self.video_total_frames / fps if fps > 0 else 0
            current_time = f"{int(current_seconds//60):02d}:{int(current_seconds%60):02d}"
            total_time = f"{int(total_seconds//60):02d}:{int(total_seconds%60):02d}"
            self.time_label.config(text=f"{current_time} / {total_time}")
            
            self._video_job = self.after(30, self.animate_video)
        else:
            self.stop_video()
            self.update_editor()

    def seek_video_start(self, event):
        if not self.video_cap or not self.video_cap.isOpened():
            return
        self.video_dragging = True
        self.seek_video_update(event)
    
    def seek_video_drag(self, event):
        if self.video_dragging:
            self.seek_video_update(event)
    
    def seek_video_end(self, event):
        self.video_dragging = False
        # Resume animation if video is playing
        if self.video_playing:
            self.animate_video()
    
    def seek_video_update(self, event):
        if not self.video_cap or not self.video_cap.isOpened():
            return
        
        # Calculate click position as percentage
        progress_bar_width = self.video_progress.winfo_width()
        if progress_bar_width <= 0:
            return
            
        # Get the click position relative to the progress bar
        click_x = event.x
        click_percentage = max(0, min(1, click_x / progress_bar_width))
        
        # Seek to the corresponding frame
        target_frame = int(self.video_total_frames * click_percentage)
        self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        
        # Update current frame counter
        self.video_current_frame = target_frame
        
        # Update progress bar
        progress = click_percentage * 100
        self.video_progress["value"] = progress
        
        # Update time label
        fps = self.video_cap.get(cv2.CAP_PROP_FPS)
        current_seconds = target_frame / fps if fps > 0 else 0
        total_seconds = self.video_total_frames / fps if fps > 0 else 0
        current_time = f"{int(current_seconds//60):02d}:{int(current_seconds%60):02d}"
        total_time = f"{int(total_seconds//60):02d}:{int(total_seconds%60):02d}"
        self.time_label.config(text=f"{current_time} / {total_time}")
        
        # If video is playing, don't immediately resume animation (wait for drag end)
        if self.video_playing and not self.video_dragging:
            self.animate_video()
        else:
            # Show frame at new position
            ret, frame = self.video_cap.read()
            if ret:
                target_width = self.name_label.master.winfo_width() - 20
                if target_width < 100: target_width = 240
                
                h, w, _ = frame.shape
                scale = min(target_width / w, target_width / h)
                new_w, new_h = int(w * scale), int(h * scale)
                
                frame = cv2.resize(frame, (new_w, new_h))
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame)
                self._preview_img = ImageTk.PhotoImage(img)
                self.preview_label.config(image=self._preview_img)

    def update_data(self, event=None):
        if not self.selection:
            return
        
        self.save_history()

        input_loca = self.loca.get()
        input_tags = self.tags.get()
        date = self.date.get()

        #dateの変換
        date = re.sub(r'昭和(\d+)', lambda m: str(int(m.group(1)) + 1925), date)
        date = date.replace("年", "-").replace("月", "-").replace("日", "-")
        date = date.rstrip("-")

        cap = self.cap.get()
        
        target_widget = event.widget if event else None

        for name in self.selection:
            if len(self.selection) > 1:
                # 複数選択時は、Enterを押したフィールドのみ更新
                if target_widget == self.loca and input_loca:
                    if self.data[name]["loca"]:
                        self.data[name]["loca"] += " " + input_loca
                    else:
                        self.data[name]["loca"] = input_loca
                elif target_widget == self.tags and input_tags:
                    if self.data[name]["tags"]:
                        self.data[name]["tags"] += " " + input_tags
                    else:
                        self.data[name]["tags"] = input_tags
                elif target_widget == self.date:
                    self.data[name]["date"] = date
                elif target_widget == self.cap:
                    self.data[name]["cap"] = cap
            else:
                # 単一選択時は全て上書き
                self.data[name]["loca"] = input_loca
                self.data[name]["tags"] = input_tags
                self.data[name]["date"] = date
                self.data[name]["cap"] = cap
            
        save_data(self.data)
        self.render()
        self.update_editor()

    def save_history(self):
        self.history.append(copy.deepcopy(self.data))
        self.redo_history.clear()

    #undoとredo

    def undo(self, event=None):
        if not self.history:
            return
        self.redo_history.append(copy.deepcopy(self.data))
        self.data = self.history.pop()
        save_data(self.data)
        self.render()
        self.update_editor()

    def redo(self, event=None):
        if not self.redo_history:
            return
        self.history.append(copy.deepcopy(self.data))
        self.data = self.redo_history.pop()
        save_data(self.data)
        self.render()
        self.update_editor()

if __name__ == "__main__":
    ImageManager().mainloop()


