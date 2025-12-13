import os
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageOps

# your existing mock; works unchanged
from backend_mock import mock_run_ai
from models import Case


class ViewerFrame(tk.Frame):
    """
    Stacked (concatenated) viewer with direct DICOM support:
      • Accepts PNG/JPG and DICOM paths in case.series_paths
      • DICOM is decoded on the fly (all frames shown)
      • Prev/Next navigation + stacked scrolling, heatmap, zoom, fit width / 1:1
    """
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # --- state ---
        self._pil_images = []                 # list[PIL.Image] for all frames (RGBA)
        self._file_first_index = []           # list[int] listbox idx -> first frame index in _pil_images
        self._display_imgs = []               # list[ImageTk.PhotoImage]
        self._display_sizes = []              # list[(w, h)]
        self._display_offsets = []            # list[int] top Y of each frame in stacked display
        self._total_height = 0
        self._scroll_y = 0
        self._heatmap_src = None
        self._zoom = 1.0
        self._fit_mode = True

        # --- styles (match your app) ---
        style = ttk.Style(self)
        try: style.theme_use("clam")
        except Exception: pass
        PRIMARY = "#0ea5e9"; BG="#0b1220"; CARD_BG="#0f172a"; FG="#e5e7eb"; MUTED="#94a3b8"; FIELD_BG="#111827"; BORDER="#1f2937"
        style.configure("App.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("Toolbar.TFrame", background=BG)
        style.configure("Title.TLabel", background=BG, foreground=FG, font=("Segoe UI", 14, "bold"))
        style.configure("Card.TLabel", background=CARD_BG, foreground=FG)
        style.configure("RightTitle.TLabel", background=CARD_BG, foreground=FG, font=("Segoe UI", 12, "bold"))
        style.configure("Ghost.TButton", background=BG, foreground=MUTED, padding=(12, 8), borderwidth=0)
        style.map("Ghost.TButton", background=[("active", "#111827")], foreground=[("active", FG), ("!active", MUTED)])
        style.configure("Accent.TButton", background=PRIMARY, foreground="#0b1220", padding=(12, 8), borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#22d3ee"), ("!active", PRIMARY)])
        style.configure("Blue.Horizontal.TProgressbar", troughcolor=FIELD_BG,
                        background=PRIMARY, bordercolor=BORDER, lightcolor=PRIMARY, darkcolor=PRIMARY)

        # --- layout ---
        root = ttk.Frame(self, style="App.TFrame"); root.pack(fill="both", expand=True)

        top = ttk.Frame(root, style="Toolbar.TFrame", padding=(12, 10)); top.pack(fill="x")
        ttk.Button(top, text="← Back", style="Ghost.TButton",
                   command=lambda: controller.show_frame("CasesFrame")).pack(side="left")
        self.case_label = ttk.Label(top, text="Case: -", style="Title.TLabel"); self.case_label.pack(side="left", padx=(8, 0))

        content = ttk.Frame(root, style="App.TFrame"); content.pack(fill="both", expand=True)

        # left list (one entry per file; label shows frame count for DICOM)
        left = ttk.Frame(content, style="Card.TFrame", padding=10); left.pack(side="left", fill="y", padx=(12, 6), pady=(0, 12))
        ttk.Label(left, text="Series", style="RightTitle.TLabel").pack(anchor="w")
        self.series_list = tk.Listbox(left, height=10, activestyle="none",
                                      bg=FIELD_BG, fg=FG, highlightthickness=0,
                                      selectbackground="#1f2937", selectforeground=FG)
        self.series_list.pack(fill="y", expand=False, pady=(6, 6))
        self.series_list.bind("<<ListboxSelect>>", lambda e: self._scroll_to_file_selection())

        nav = ttk.Frame(left, style="Card.TFrame"); nav.pack(fill="x")
        self.prev_btn = ttk.Button(nav, text="← Prev", style="Ghost.TButton", command=self.prev_image)
        self.next_btn = ttk.Button(nav, text="Next →", style="Ghost.TButton", command=self.next_image)
        self.prev_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.next_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # center stacked canvas
        center = ttk.Frame(content, style="Card.TFrame", padding=8); center.pack(side="left", fill="both", expand=True, padx=6, pady=(0, 12))
        self.canvas = tk.Canvas(center, bg="black", highlightthickness=0); self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._rebuild_and_redraw())

        viewer_tb = ttk.Frame(center, style="Card.TFrame"); viewer_tb.pack(fill="x", pady=(8, 0))
        ttk.Label(viewer_tb, text="View", style="Card.TLabel").pack(side="left", padx=(0, 8))
        ttk.Button(viewer_tb, text="Fit width", style="Ghost.TButton", command=self._fit).pack(side="left")
        ttk.Button(viewer_tb, text="1:1", style="Ghost.TButton", command=self._one_to_one).pack(side="left")
        ttk.Button(viewer_tb, text="−", style="Ghost.TButton", command=lambda: self._zoom_step(0.9)).pack(side="left")
        ttk.Button(viewer_tb, text="+", style="Ghost.TButton", command=lambda: self._zoom_step(1.1)).pack(side="left")
        self.zoom_label = ttk.Label(viewer_tb, text="100%", style="Card.TLabel"); self.zoom_label.pack(side="left", padx=(8, 0))

        # right panel
        right = ttk.Frame(content, style="Card.TFrame", padding=10); right.pack(side="left", fill="y", padx=(6, 12), pady=(0, 12))
        ttk.Label(right, text="Biomarkers", style="RightTitle.TLabel").pack(anchor="w")
        self.biomarker_frame = ttk.Frame(right, style="Card.TFrame"); self.biomarker_frame.pack(fill="x", pady=(6, 6))
        hm_controls = ttk.Frame(right, style="Card.TFrame"); hm_controls.pack(fill="x", pady=(4, 10))
        self.heatmap_on = tk.BooleanVar(value=True)
        ttk.Checkbutton(hm_controls, text="Show heatmap", variable=self.heatmap_on,
                        command=self._rebuild_and_redraw).pack(anchor="w")
        ttk.Label(hm_controls, text="Opacity", style="Card.TLabel").pack(anchor="w", pady=(6, 0))
        self.hm_opacity = tk.DoubleVar(value=0.55)
        ttk.Scale(hm_controls, from_=0.0, to=1.0, orient="horizontal",
                  variable=self.hm_opacity, command=lambda _=None: self._rebuild_and_redraw()).pack(fill="x")
        ttk.Button(right, text="Run AI", style="Accent.TButton", command=self.run_ai).pack(fill="x", pady=(8, 8))
        ttk.Label(right, text="Explanation", style="Card.TLabel").pack(anchor="w")
        self.explanation_text = tk.Text(right, width=36, height=12, wrap="word",
                                        bg=FIELD_BG, fg="#e5e7eb", insertbackground="#e5e7eb", relief="flat")
        self.explanation_text.pack(fill="both", expand=True, pady=(4, 0))

        # mouse & keyboard
        self.canvas.bind("<MouseWheel>", self._on_wheel)               # Windows/macOS
        self.canvas.bind("<Button-4>", lambda e: self._scroll(-120))   # X11 up
        self.canvas.bind("<Button-5>", lambda e: self._scroll(+120))   # X11 down
        self.bind_all("+", lambda e: self._zoom_step(1.1))
        self.bind_all("-", lambda e: self._zoom_step(0.9))
        self.bind_all("f", lambda e: self._fit())
        self.bind_all("1", lambda e: self._one_to_one())
        self.bind_all("<Left>",  lambda e: self.prev_image())
        self.bind_all("<Right>", lambda e: self.next_image())

        self._palette = self._build_palette()

    # ---------- lifecycle ----------
    def on_show(self):
        c = self.controller.current_case  # type: Case
        self.case_label.config(text=f"Case: {c.case_id}  ·  {c.patient_name}")

        self._heatmap_src = None
        self.explanation_text.delete("1.0", "end")
        for w in self.biomarker_frame.winfo_children(): w.destroy()

        # load all paths (PNG/JPG or DICOM) into frames
        self._pil_images.clear()
        self._file_first_index.clear()
        self.series_list.delete(0, "end")

        for i, path in enumerate(c.series_paths):
            try:
                frames = self._load_any_to_frames(path)  # list of PIL RGBA
                first_idx = len(self._pil_images)
                self._pil_images.extend(frames)
                # label shows frame count for DICOM
                label = os.path.basename(path)
                if len(frames) > 1: label += f"  [{len(frames)}]"
                self.series_list.insert("end", f"{i+1}. {label}")
                self._file_first_index.append(first_idx)
            except Exception as e:
                messagebox.showerror("Image error", f"Could not open:\n{path}\n\n{e}")

        if self._pil_images:
            self.series_list.selection_clear(0, "end"); self.series_list.selection_set(0)
        self._fit()
        self._update_nav()

    # ---------- loading ----------
    def _is_dicom(self, path):
        try:
            with open(path, "rb") as f:
                f.seek(128)
                if f.read(4) == b"DICM":
                    return True
        except Exception:
            pass
        # fallback: try reading header quickly
        try:
            from pydicom import dcmread
            dcmread(path, stop_before_pixels=True, force=True)
            return True
        except Exception:
            return False

    def _load_any_to_frames(self, path):
        """Return list[PIL.Image (RGBA)] for a PNG/JPG or DICOM file."""
        ext = os.path.splitext(path)[1].lower()
        if ext in (".png", ".jpg", ".jpeg"):
            from PIL import Image
            img = Image.open(path).convert("RGBA")
            return [img]
        if self._is_dicom(path):
            return self._dicom_to_frames(path)
        # unknown → let PIL try
        from PIL import Image
        img = Image.open(path).convert("RGBA")
        return [img]

    def _dicom_to_frames(self, path):
        """Decode DICOM (supports multi-frame, VOI/MOD LUT, MONOCHROME1) -> list of PIL RGBA."""
        import numpy as np
        try:
            from pydicom import dcmread
            from pydicom.pixel_data_handlers.util import apply_modality_lut, apply_voi_lut
        except Exception as e:
            raise RuntimeError("DICOM support requires: pydicom, numpy, pillow") from e

        ds = dcmread(path, force=True)
        try:
            arr = ds.pixel_array  # uses installed pixel handlers
        except Exception as e:
            raise RuntimeError(
                "Cannot decode DICOM pixel data. Install plugins:\n"
                "pip install pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg\n"
                "or: pip install gdcm"
            ) from e

        # modality/voi LUTs
        try: arr = apply_modality_lut(arr, ds)
        except Exception: pass
        try: arr = apply_voi_lut(arr, ds)
        except Exception: pass

        # MONOCHROME1 inversion
        try:
            if str(getattr(ds, "PhotometricInterpretation", "")).upper() == "MONOCHROME1":
                arr = arr.max() - arr
        except Exception:
            pass

        def to_uint8(a):
            a = a.astype("float32")
            if a.size >= 16:
                lo, hi = np.percentile(a, (1, 99))
            else:
                lo, hi = float(a.min()), float(a.max())
            if hi <= lo:
                lo, hi = float(a.min()), float(a.max())
            if hi <= lo:
                return (a * 0).astype("uint8")
            a = np.clip(a, lo, hi)
            a = (a - lo) / (hi - lo)
            return (a * 255.0 + 0.5).astype("uint8")

        imgs = []
        from PIL import Image

        # handle shapes
        if arr.ndim == 2:
            g = to_uint8(arr)
            pil = Image.fromarray(g, mode="L").convert("RGBA")
            imgs.append(pil)
        elif arr.ndim == 3:
            # grayscale multi-frame OR color single frame (rows, cols, 3)
            if arr.shape[-1] in (3, 4):  # color
                if arr.dtype != "uint8":
                    arr = np.clip(arr, 0, 255).astype("uint8")
                pil = Image.fromarray(arr[..., :3], mode="RGB").convert("RGBA")
                imgs.append(pil)
            else:
                for i in range(arr.shape[0]):
                    g = to_uint8(arr[i])
                    pil = Image.fromarray(g, mode="L").convert("RGBA")
                    imgs.append(pil)
        elif arr.ndim == 4 and arr.shape[-1] in (3, 4):  # (frames, rows, cols, 3)
            for i in range(arr.shape[0]):
                frame = arr[i]
                if frame.dtype != "uint8":
                    frame = np.clip(frame, 0, 255).astype("uint8")
                pil = Image.fromarray(frame[..., :3], mode="RGB").convert("RGBA")
                imgs.append(pil)
        else:
            # fallback: first slice
            g = to_uint8(arr if arr.ndim == 2 else arr[0])
            pil = Image.fromarray(g, mode="L").convert("RGBA")
            imgs.append(pil)

        return imgs

    # ---------- heatmap ----------
    def _apply_heatmap(self, base):
        if not (self._heatmap_src and self.heatmap_on.get()):
            return base
        hm = self._heatmap_src.resize(base.size, Image.LANCZOS)
        if hm.mode != "RGBA": hm = hm.convert("RGBA")
        alpha = hm.split()[3]
        alpha = ImageOps.autocontrast(alpha, cutoff=2)
        colored = self._colorize_from_luminance(alpha)
        op = max(0.0, min(float(self.hm_opacity.get()), 1.0))
        a_scaled = alpha.point(lambda p: int(p * op))
        colored.putalpha(a_scaled)
        return Image.alpha_composite(base, colored)

    # ---------- build + render ----------
    def _rebuild_and_redraw(self):
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        if cw <= 1 or not self._pil_images:
            self.canvas.delete("all")
            self.canvas.create_text(cw // 2, ch // 2, text="[CT slice placeholder]", fill="white")
            self._update_nav()
            return

        widest = max(img.width for img in self._pil_images)
        base_scale = cw / widest if self._fit_mode else 1.0
        scale = max(0.05, min(base_scale * self._zoom, 8.0))
        self.zoom_label.configure(text=f"{int(round(scale*100))}%")

        padding = 8
        self._display_imgs.clear(); self._display_sizes.clear(); self._display_offsets.clear()
        y = 0
        for img in self._pil_images:
            composed = self._apply_heatmap(img.copy())
            w = max(1, int(img.width * scale)); h = max(1, int(img.height * scale))
            disp = composed.resize((w, h), Image.LANCZOS)
            tkimg = ImageTk.PhotoImage(disp)
            self._display_imgs.append(tkimg)
            self._display_sizes.append((w, h))
            self._display_offsets.append(y)
            y += h + padding

        self._total_height = max(0, y - padding)
        self._scroll_y = max(0, min(self._scroll_y, max(0, self._total_height - ch)))
        self._redraw_only()
        self._update_nav()

    def _redraw_only(self):
        self.canvas.delete("all")
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        if not self._display_imgs:
            self.canvas.create_text(cw // 2, ch // 2, text="[CT slice placeholder]", fill="white")
            return
        top = self._scroll_y; bottom = self._scroll_y + ch
        for tkimg, (w, h), y in zip(self._display_imgs, self._display_sizes, self._display_offsets):
            if y > bottom or (y + h) < top: continue
            x = (cw - w) // 2
            self.canvas.create_image(x, y - self._scroll_y, anchor="nw", image=tkimg)

    # ---------- navigation ----------
    def _current_index(self):
        sel = self.series_list.curselection()
        if not sel: return None
        return int(sel[0])

    def _scroll_to_file_selection(self):
        idx = self._current_index()
        if idx is None or idx >= len(self._file_first_index): return
        first = self._file_first_index[idx]
        if not self._display_offsets: return
        y = self._display_offsets[first]
        self._scroll_y = max(0, y - 12)
        self._redraw_only()
        self._update_nav()

    def _select_and_scroll_frame(self, frame_idx):
        frame_idx = max(0, min(frame_idx, len(self._display_offsets) - 1))
        # also select the owning file in the left list
        file_idx = 0
        for i, first in enumerate(self._file_first_index):
            last = self._file_first_index[i+1] - 1 if i+1 < len(self._file_first_index) else len(self._pil_images)-1
            if first <= frame_idx <= last:
                file_idx = i; break
        self.series_list.selection_clear(0, "end"); self.series_list.selection_set(file_idx)
        y = self._display_offsets[frame_idx]
        self._scroll_y = max(0, y - 12)
        self._redraw_only()
        self._update_nav()

    def next_image(self):
        if not self._display_offsets: return
        # find first frame whose top is below current scroll
        ch = max(self.canvas.winfo_height(), 1)
        bottom = self._scroll_y + ch
        # current visible frames
        visible = [i for i, y in enumerate(self._display_offsets)
                   if not (y > bottom or (y + self._display_sizes[i][1]) < self._scroll_y)]
        if visible:
            target = visible[-1] + 1
        else:
            # jump to next frame after current top
            target = 0
            for i, y in enumerate(self._display_offsets):
                if y > self._scroll_y:
                    target = i; break
        if target < len(self._display_offsets):
            self._select_and_scroll_frame(target)
        else:
            self.bell()

    def prev_image(self):
        if not self._display_offsets: return
        # find first frame whose top is at/above current scroll
        target = 0
        for i, y in enumerate(self._display_offsets):
            if y >= self._scroll_y:
                target = max(0, i - 1); break
        self._select_and_scroll_frame(target)

    def _update_nav(self):
        has = len(self._display_offsets) > 1
        state = "normal" if has else "disabled"
        self.prev_btn.config(state=state); self.next_btn.config(state=state)

    # ---------- interactions ----------
    def _on_wheel(self, event):
        delta = -1 if event.delta > 0 else 1
        self._scroll(delta * 120)

    def _scroll(self, pixels):
        if not self._display_imgs: return
        ch = max(self.canvas.winfo_height(), 1)
        max_scroll = max(0, self._total_height - ch)
        self._scroll_y = max(0, min(self._scroll_y + pixels, max_scroll))
        self._redraw_only()

    # ---------- zoom & modes ----------
    def _fit(self):
        self._fit_mode = True
        self._rebuild_and_redraw()

    def _one_to_one(self):
        self._fit_mode = False
        self._zoom = 1.0
        self._rebuild_and_redraw()

    def _zoom_step(self, factor):
        ch = max(self.canvas.winfo_height(), 1)
        before_total = max(1, self._total_height)
        before_ratio = self._scroll_y / before_total if before_total else 0.0
        self._fit_mode = False
        self._zoom = max(0.05, min(self._zoom * factor, 8.0))
        self._rebuild_and_redraw()
        after_total = max(1, self._total_height)
        self._scroll_y = max(0, min(int(after_total * before_ratio), max(0, self._total_height - ch)))
        self._redraw_only()

    # ---------- colormap ----------
    def _build_palette(self):
        pal = []
        for i in range(256):
            t = i / 255.0
            if t < 0.25:    r, g, b = 0, int(4*t*255), 255
            elif t < 0.5:   r, g, b = 0, 255, int((1-4*(t-0.25))*255)
            elif t < 0.75:  r, g, b = int(4*(t-0.5)*255), 255, 0
            else:           r, g, b = 255, int((1-4*(t-0.75))*255), 0
            pal.extend([max(0,min(255,r)), max(0,min(255,g)), max(0,min(255,b))])
        return pal

    def _colorize_from_luminance(self, lum_img):
        p = lum_img.convert("P"); p.putpalette(self._palette)
        return p.convert("RGBA")

    # ---------- actions ----------
    def run_ai(self):
        c = self.controller.current_case  # type: Case
        result = mock_run_ai(c)

        # biomarkers
        for w in self.biomarker_frame.winfo_children(): w.destroy()
        for bm in result["biomarkers"]:
            row = ttk.Frame(self.biomarker_frame, style="Card.TFrame"); row.pack(fill="x", pady=4)
            ttk.Label(row, text=bm["name"], style="Card.TLabel").pack(anchor="w")
            pb = ttk.Progressbar(row, maximum=1.0, value=bm["value"], style="Blue.Horizontal.TProgressbar"); pb.pack(fill="x")
            ttk.Label(row, text=f"{int(round(bm['value']*100))}%", style="Card.TLabel").pack(anchor="e")

        self.explanation_text.delete("1.0", "end")
        self.explanation_text.insert("end", result.get("explanation", ""))

        self._heatmap_src = result.get("heatmap")
        self._rebuild_and_redraw()
