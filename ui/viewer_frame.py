import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from PIL import Image, ImageTk, ImageOps
from pathlib import Path
from pydicom import dcmread

# your existing mock; works unchanged
from logic.backend import run_ai
# Replace Case import with the correct path
from model.models import Case


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
        self._pil_images = []  # list[PIL.Image] for all frames (RGBA)
        self._file_first_index = []  # list[int] listbox idx -> first frame index in _pil_images
        self._display_imgs = []  # list[ImageTk.PhotoImage]
        self._display_sizes = []  # list[(w, h)]
        self._display_offsets = []  # list[int] top Y of each frame in stacked display
        self._total_height = 0
        self._scroll_y = 0
        self._heatmap_src = None
        self._zoom = 1.0
        self._fit_mode = True

        # --- AI progress UI state ---
        self._ai_running = False
        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress_stage = tk.StringVar(value="Idle")
        self._progress_detail = tk.StringVar(value="")
        self._progress_indeterminate = False

        # slice navigation helpers
        self._ignore_slice_scale = False

        # --- styles (match your app) ---
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        PRIMARY = "#0ea5e9";
        BG = "#0b1220";
        CARD_BG = "#0f172a";
        FG = "#e5e7eb";
        MUTED = "#94a3b8";
        FIELD_BG = "#111827";
        BORDER = "#1f2937"
        style.configure("App.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("Toolbar.TFrame", background=BG)
        style.configure("Title.TLabel", background=BG, foreground=FG, font=("Segoe UI", 14, "bold"))
        style.configure("Card.TLabel", background=CARD_BG, foreground=FG)
        style.configure("CardMuted.TLabel", background=CARD_BG, foreground=MUTED)
        style.configure("RightTitle.TLabel", background=CARD_BG, foreground=FG, font=("Segoe UI", 12, "bold"))
        style.configure("Ghost.TButton", background=BG, foreground=MUTED, padding=(12, 8), borderwidth=0)
        style.map("Ghost.TButton", background=[("active", "#111827")], foreground=[("active", FG), ("!active", MUTED)])
        style.configure("Accent.TButton", background=PRIMARY, foreground="#0b1220", padding=(12, 8), borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#22d3ee"), ("!active", PRIMARY)])
        style.configure("Blue.Horizontal.TProgressbar", troughcolor=FIELD_BG,
                        background=PRIMARY, bordercolor=BORDER, lightcolor=PRIMARY, darkcolor=PRIMARY)

        # --- layout ---
        root = ttk.Frame(self, style="App.TFrame");
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root, style="Toolbar.TFrame", padding=(12, 10));
        top.pack(fill="x")
        ttk.Button(top, text="← Back", style="Ghost.TButton",
                   command=lambda: controller.show_frame("CasesFrame")).pack(side="left")
        self.case_label = ttk.Label(top, text="Case: -", style="Title.TLabel");
        self.case_label.pack(side="left", padx=(8, 0))

        content = ttk.Frame(root, style="App.TFrame");
        content.pack(fill="both", expand=True)

        # left list (one entry per file; label shows frame count for DICOM)
        left = ttk.Frame(content, style="Card.TFrame", padding=10);
        left.pack(side="left", fill="y", padx=(12, 6), pady=(0, 12))
        ttk.Label(left, text="Series", style="RightTitle.TLabel").pack(anchor="w")
        self.series_list = tk.Listbox(left, height=10, activestyle="none",
                                      bg=FIELD_BG, fg=FG, highlightthickness=0,
                                      selectbackground="#1f2937", selectforeground=FG)
        self.series_list.pack(fill="y", expand=False, pady=(6, 6))
        self.series_list.bind("<<ListboxSelect>>", lambda e: self._scroll_to_file_selection())

        nav = ttk.Frame(left, style="Card.TFrame");
        nav.pack(fill="x")
        self.prev_btn = ttk.Button(nav, text="← Prev", style="Ghost.TButton", command=self.prev_image)
        self.next_btn = ttk.Button(nav, text="Next →", style="Ghost.TButton", command=self.next_image)
        self.prev_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.next_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))
        # center stacked canvas
        center = ttk.Frame(content, style="Card.TFrame", padding=8)
        center.pack(side="left", fill="both", expand=True, padx=6, pady=(0, 12))

        viewer_area = ttk.Frame(center, style="Card.TFrame")
        viewer_area.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(viewer_area, bg="black", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.vscroll = ttk.Scrollbar(viewer_area, orient="vertical", command=self._on_vscroll)
        self.vscroll.pack(side="right", fill="y")

        self.canvas.bind("<Configure>", lambda e: self._rebuild_and_redraw())

        # slice slider (jump to a specific slice)
        slice_bar = ttk.Frame(center, style="Card.TFrame")
        slice_bar.pack(fill="x", pady=(8, 0))
        ttk.Label(slice_bar, text="Slice", style="Card.TLabel").pack(side="left")
        self.slice_scale = ttk.Scale(slice_bar, from_=0, to=0, orient="horizontal", command=self._on_slice_scale)
        self.slice_scale.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.slice_info = ttk.Label(slice_bar, text="0/0", style="Card.TLabel")
        self.slice_info.pack(side="left")

        viewer_tb = ttk.Frame(center, style="Card.TFrame");
        viewer_tb.pack(fill="x", pady=(8, 0))
        ttk.Label(viewer_tb, text="View", style="Card.TLabel").pack(side="left", padx=(0, 8))
        ttk.Button(viewer_tb, text="Fit width", style="Ghost.TButton", command=self._fit).pack(side="left")
        ttk.Button(viewer_tb, text="1:1", style="Ghost.TButton", command=self._one_to_one).pack(side="left")
        ttk.Button(viewer_tb, text="−", style="Ghost.TButton", command=lambda: self._zoom_step(0.9)).pack(side="left")
        ttk.Button(viewer_tb, text="+", style="Ghost.TButton", command=lambda: self._zoom_step(1.1)).pack(side="left")
        self.zoom_label = ttk.Label(viewer_tb, text="100%", style="Card.TLabel");
        self.zoom_label.pack(side="left", padx=(8, 0))

        # right panel
        right = ttk.Frame(content, style="Card.TFrame", padding=10);
        right.pack(side="left", fill="y", padx=(6, 12), pady=(0, 12))
        ttk.Label(right, text="Biomarkers", style="RightTitle.TLabel").pack(anchor="w")
        self.biomarker_frame = ttk.Frame(right, style="Card.TFrame");
        self.biomarker_frame.pack(fill="x", pady=(6, 6))

        # --- AI progress (live) ---
        ttk.Label(right, text="AI Progress", style="RightTitle.TLabel").pack(anchor="w", pady=(10, 0))
        self.progress_bar = ttk.Progressbar(
            right, maximum=100, variable=self._progress_var,
            style="Blue.Horizontal.TProgressbar", mode="determinate"
        )
        self.progress_bar.pack(fill="x", pady=(6, 2))
        self.progress_stage_lbl = ttk.Label(right, textvariable=self._progress_stage, style="CardMuted.TLabel")
        self.progress_stage_lbl.pack(anchor="w")

        log_row = ttk.Frame(right, style="Card.TFrame")
        log_row.pack(fill="both", expand=False, pady=(6, 10))
        self.log_text = scrolledtext.ScrolledText(
            log_row, height=7, wrap="word",
            bg=FIELD_BG, fg="#e5e7eb", insertbackground="#e5e7eb", relief="flat"
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.configure(state="disabled")
        log_sb = ttk.Scrollbar(log_row, orient="vertical", command=self.log_text.yview)
        log_sb.pack(side="left", fill="y")
        self.log_text.configure(yscrollcommand=log_sb.set)

        ttk.Button(right, text="Clear log", style="Ghost.TButton", command=self._clear_log).pack(fill="x", pady=(0, 10))

        # --- heatmap controls ---
        hm_controls = ttk.Frame(right, style="Card.TFrame");
        hm_controls.pack(fill="x", pady=(4, 10))
        self.heatmap_on = tk.BooleanVar(value=True)
        ttk.Checkbutton(hm_controls, text="Show heatmap", variable=self.heatmap_on,
                        command=self._rebuild_and_redraw).pack(anchor="w")
        ttk.Label(hm_controls, text="Opacity", style="Card.TLabel").pack(anchor="w", pady=(6, 0))
        self.hm_opacity = tk.DoubleVar(value=0.55)
        ttk.Scale(hm_controls, from_=0.0, to=1.0, orient="horizontal",
                  variable=self.hm_opacity, command=lambda _=None: self._rebuild_and_redraw()).pack(fill="x")

        self._ai_btn = ttk.Button(right, text="Run AI", style="Accent.TButton", command=self.run_ai)
        self._ai_btn.pack(fill="x", pady=(8, 8))

        ttk.Label(right, text="Explanation", style="Card.TLabel").pack(anchor="w")
        self.explanation_text = tk.Text(right, width=36, height=9, wrap="word",
                                        bg=FIELD_BG, fg="#e5e7eb", insertbackground="#e5e7eb", relief="flat")
        self.explanation_text.pack(fill="both", expand=True, pady=(4, 0))

        # mouse & keyboard
        self.canvas.bind("<MouseWheel>", self._on_wheel)  # Windows/macOS
        self.canvas.bind("<Button-4>", lambda e: self._scroll(-120))  # X11 up
        self.canvas.bind("<Button-5>", lambda e: self._scroll(+120))  # X11 down
        self.bind_all("+", lambda e: self._zoom_step(1.1))
        self.bind_all("-", lambda e: self._zoom_step(0.9))
        self.bind_all("f", lambda e: self._fit())
        self.bind_all("1", lambda e: self._one_to_one())
        self.bind_all("<Left>", lambda e: self.prev_image())
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

        # Accept both:
        #   - a folder path (ct_series_dir)
        #   - a list of individual files (ct_images)
        dicom_dir = getattr(c, "ct_series_dir", None)
        raw_paths = []
        raw_paths.extend(list(getattr(c, "ct_images", []) or []))

        # If the case only has file paths, try infer the folder
        if (not dicom_dir) and raw_paths:
            for p in raw_paths:
                if p and os.path.isdir(p):
                    dicom_dir = p
                    break
            if (not dicom_dir) and raw_paths and os.path.isfile(raw_paths[0]):
                dicom_dir = os.path.dirname(raw_paths[0])

        if dicom_dir and not os.path.isdir(dicom_dir):
            dicom_dir = None

        # Build a candidate file list
        candidates = []
        for p in raw_paths:
            if p and os.path.isfile(p):
                candidates.append(p)

        if not candidates and dicom_dir:
            # Collect .dcm/.dicom and also DICOM-without-extension (DICM header), recursively
            for root, _, files in os.walk(dicom_dir):
                for fn in sorted(files):
                    fp = os.path.join(root, fn)
                    ext = os.path.splitext(fn)[1].lower()
                    if ext in (".dcm", ".dicom"):
                        candidates.append(fp)
                        continue
                    # quick header check for extensionless DICOM
                    try:
                        with open(fp, "rb") as f:
                            f.seek(128)
                            if f.read(4) == b"DICM":
                                candidates.append(fp)
                    except Exception:
                        pass

        if not candidates:
            messagebox.showerror(
                "Invalid CT data",
                "No CT files found for this case (missing folder and file list)."
            )
            return

        # Sort slices by Z if possible, else by InstanceNumber, else by name
        def _slice_key(path: str):
            try:
                ds = dcmread(path, stop_before_pixels=True, force=True)
                if hasattr(ds, "ImagePositionPatient") and ds.ImagePositionPatient:
                    return float(ds.ImagePositionPatient[2])
                if hasattr(ds, "InstanceNumber"):
                    return float(ds.InstanceNumber)
            except Exception:
                pass
            return 0.0

        dicom_files = sorted(candidates, key=_slice_key)

        first_idx = 0
        for i, dcm_path in enumerate(dicom_files):
            try:
                frames = self._dicom_to_frames(str(dcm_path))
                self._pil_images.extend(frames)
            except Exception as e:
                messagebox.showerror(
                    "DICOM error",
                    f"Could not open:\n{dcm_path}\n\n{e}"
                )
                return

        # listbox: UN SINGUR ENTRY = o serie
        self.series_list.insert(
            "end",
            f"1. {os.path.basename(dicom_dir)}  [{len(self._pil_images)} slices]"
        )
        self._file_first_index.append(0)

        if self._pil_images:
            self.series_list.selection_clear(0, "end");
            self.series_list.selection_set(0)
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
        try:
            arr = apply_modality_lut(arr, ds)
        except Exception:
            pass
        try:
            arr = apply_voi_lut(arr, ds)
        except Exception:
            pass

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
        self.zoom_label.configure(text=f"{int(round(scale * 100))}%")

        padding = 8
        self._display_imgs.clear();
        self._display_sizes.clear();
        self._display_offsets.clear()
        y = 0
        for img in self._pil_images:
            composed = self._apply_heatmap(img.copy())
            w = max(1, int(img.width * scale));
            h = max(1, int(img.height * scale))
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
            self._update_scrollbar()
            self._sync_slice_controls()
            return

        top = self._scroll_y
        bottom = self._scroll_y + ch
        for tkimg, (w, h), y in zip(self._display_imgs, self._display_sizes, self._display_offsets):
            if y > bottom or (y + h) < top:
                continue
            x = (cw - w) // 2
            self.canvas.create_image(x, y - self._scroll_y, anchor="nw", image=tkimg)

        self._update_scrollbar()
        self._sync_slice_controls()

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
            last = self._file_first_index[i + 1] - 1 if i + 1 < len(self._file_first_index) else len(
                self._pil_images) - 1
            if first <= frame_idx <= last:
                file_idx = i;
                break
        self.series_list.selection_clear(0, "end");
        self.series_list.selection_set(file_idx)
        y = self._display_offsets[frame_idx]
        self._scroll_y = max(0, y - 12)
        self._redraw_only()
        self._sync_slice_controls(frame_idx)
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
                    target = i;
                    break
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
                target = max(0, i - 1);
                break
        self._select_and_scroll_frame(target)

    def _update_nav(self):
        has = len(self._display_offsets) > 1
        state = "normal" if has else "disabled"
        self.prev_btn.config(state=state);
        self.next_btn.config(state=state)

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

    def _on_vscroll(self, *args):
        """Scrollbar callback."""
        if not self._display_imgs:
            return
        ch = max(self.canvas.winfo_height(), 1)
        max_scroll = max(0, self._total_height - ch)

        if not args:
            return

        if args[0] == "moveto" and len(args) >= 2:
            try:
                frac = float(args[1])
            except Exception:
                return
            self._scroll_y = int(frac * max_scroll) if max_scroll else 0
            self._redraw_only()
            self._update_nav()
        elif args[0] == "scroll" and len(args) >= 3:
            try:
                amount = int(args[1])
            except Exception:
                amount = 0
            unit = args[2]
            if unit == "units":
                self._scroll(amount * 120)
            elif unit == "pages":
                self._scroll(amount * ch)

    def _update_scrollbar(self):
        """Sync the scrollbar thumb to current scroll position."""
        if not hasattr(self, "vscroll"):
            return
        ch = max(self.canvas.winfo_height(), 1)
        total = max(self._total_height, 1)
        if self._total_height <= ch:
            self.vscroll.set(0.0, 1.0)
            return
        first = self._scroll_y / float(total)
        last = min(1.0, (self._scroll_y + ch) / float(total))
        first = max(0.0, min(first, 1.0))
        self.vscroll.set(first, last)

    def _on_slice_scale(self, val):
        if self._ignore_slice_scale:
            return
        if not self._display_offsets:
            return
        try:
            idx = int(float(val) + 0.5)
        except Exception:
            return
        idx = max(0, min(idx, len(self._display_offsets) - 1))
        self._select_and_scroll_frame(idx)

    def _top_visible_frame_index(self):
        if not self._display_offsets:
            return 0
        for i, (y, (w, h)) in enumerate(zip(self._display_offsets, self._display_sizes)):
            if (y + h) > self._scroll_y:
                return i
        return max(0, len(self._display_offsets) - 1)

    def _sync_slice_controls(self, idx=None):
        """Update slice slider + label without causing feedback loops."""
        if not hasattr(self, "slice_scale") or not hasattr(self, "slice_info"):
            return

        n = len(self._display_offsets)
        if n <= 0:
            self._ignore_slice_scale = True
            try:
                self.slice_scale.config(to=0)
                self.slice_scale.set(0)
                self.slice_info.config(text="0/0")
            finally:
                self._ignore_slice_scale = False
            return

        if idx is None:
            idx = self._top_visible_frame_index()
        idx = max(0, min(int(idx), n - 1))

        self._ignore_slice_scale = True
        try:
            self.slice_scale.config(to=max(0, n - 1))
            self.slice_scale.set(idx)
            self.slice_info.config(text=f"{idx + 1}/{n}")
        finally:
            self._ignore_slice_scale = False

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
            if t < 0.25:
                r, g, b = 0, int(4 * t * 255), 255
            elif t < 0.5:
                r, g, b = 0, 255, int((1 - 4 * (t - 0.25)) * 255)
            elif t < 0.75:
                r, g, b = int(4 * (t - 0.5) * 255), 255, 0
            else:
                r, g, b = 255, int((1 - 4 * (t - 0.75)) * 255), 0
            pal.extend([max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))])
        return pal

    def _colorize_from_luminance(self, lum_img):
        p = lum_img.convert("P");
        p.putpalette(self._palette)
        return p.convert("RGBA")

    # ---------- biomarkers ----------
    def _render_biomarkers(self, biomarkers):
        """Render biomarker bars in the right panel.

        Expected format:
          [{"name": "TTF-1", "value": 0.69}, {"name": "CK7", "value": 0.68}]

        If the list is empty/invalid, we keep the section empty.
        """
        try:
            for w in self.biomarker_frame.winfo_children():
                w.destroy()
        except Exception:
            return

        if not isinstance(biomarkers, list) or not biomarkers:
            return

        for bm in biomarkers:
            try:
                name = str(bm.get("name", ""))
                val = float(bm.get("value", 0.0))
            except Exception:
                continue

            # clamp value to [0, 1]
            if val < 0.0:
                val = 0.0
            if val > 1.0:
                val = 1.0

            row = ttk.Frame(self.biomarker_frame, style="Card.TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=name, style="Card.TLabel").pack(anchor="w")
            pb = ttk.Progressbar(row, maximum=1.0, value=val, style="Blue.Horizontal.TProgressbar")
            pb.pack(fill="x")
            ttk.Label(row, text=f"{int(round(val * 100))}%", style="Card.TLabel").pack(anchor="e")

    # ---------- actions ----------
    def _clear_log(self):
        if not hasattr(self, "log_text"):
            return
        try:
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.configure(state="disabled")
        except Exception:
            pass

    def _append_log(self, line):
        if not hasattr(self, "log_text"):
            return
        try:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", (line or "").rstrip() + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        except Exception:
            pass

    def _set_progress_indeterminate(self, on):
        if not hasattr(self, "progress_bar"):
            return
        if on and not self._progress_indeterminate:
            self._progress_indeterminate = True
            try:
                self.progress_bar.config(mode="indeterminate")
                self.progress_bar.start(12)
            except Exception:
                pass
        elif (not on) and self._progress_indeterminate:
            self._progress_indeterminate = False
            try:
                self.progress_bar.stop()
            except Exception:
                pass
            try:
                self.progress_bar.config(mode="determinate")
            except Exception:
                pass

    def _set_progress(self, pct=None, stage=None, msg=None):
        if stage is not None:
            self._progress_stage.set(stage)
        if msg:
            self._append_log(msg)
        if pct is None:
            self._set_progress_indeterminate(True)
        else:
            self._set_progress_indeterminate(False)
            try:
                self._progress_var.set(float(pct))
            except Exception:
                pass

    def _ui_progress(self, stage, msg="", pct=None):
        """UI-thread progress update (called via after())."""
        self._set_progress(stage=stage, msg=msg, pct=pct)

    def _finish_ai_run(self):
        self._ai_running = False
        self._set_progress_indeterminate(False)
        try:
            self._ai_btn.config(state="normal")
        except Exception:
            pass

    def _on_ai_error(self, title, details=""):
        self._set_progress(stage="Error", msg=title, pct=0)
        if details:
            self._append_log(details)
        try:
            messagebox.showerror("AI error", title)
        except Exception:
            pass
        self._finish_ai_run()

    def run_ai(self):
        """Run the AI pipeline in a background thread and stream progress into the UI."""
        if self._ai_running:
            messagebox.showinfo("AI", "AI is already running for this case.")
            return

        c = self.controller.current_case  # type: Case

        # reset UI
        self._ai_running = True
        self._clear_log()
        self._progress_var.set(0.0)
        self._progress_stage.set("Starting...")
        self._heatmap_src = None

        for w in self.biomarker_frame.winfo_children():
            w.destroy()

        self.explanation_text.delete("1.0", "end")
        self.explanation_text.insert("end", "Running AI... (CPU may take a while)\n")

        try:
            self._ai_btn.config(state="disabled")
        except Exception:
            pass

        self._append_log(f"[START] Case {c.case_id} · {c.patient_name}")

        def progress_cb(stage, msg="", pct=None):
            # called from worker thread → schedule on UI thread
            self.after(0, lambda s=stage, m=msg, p=pct: self._ui_progress(s, m, p))

        def worker():
            import traceback
            try:
                result = run_ai(c, progress_cb=progress_cb)
                self.after(0, lambda r=result: self._apply_ai_result(r))
            except Exception as e:
                tb = traceback.format_exc()
                self.after(0, lambda: self._on_ai_error(str(e), tb))

        self._run_ai_thread = threading.Thread(target=worker, daemon=True)
        self._run_ai_thread.start()

    def _apply_ai_result(self, result):
        # Be tolerant to different backend return shapes.
        # Preferred: {"biomarkers": [{"name":..., "value":...}], "explanation": ...}
        biomarkers = None
        if isinstance(result, dict):
            bms = result.get("biomarkers")
            if isinstance(bms, list) and bms:
                biomarkers = bms
            else:
                # fallback: raw scores (older pipeline style)
                if "Raw_TTF1" in result or "Raw_CK7" in result:
                    try:
                        biomarkers = [
                            {"name": "TTF-1", "value": float(result.get("Raw_TTF1", 0.0))},
                            {"name": "CK7", "value": float(result.get("Raw_CK7", 0.0))},
                        ]
                    except Exception:
                        biomarkers = []
                elif "TTF1" in result or "CK7" in result:
                    # sometimes scores are nested
                    try:
                        biomarkers = [
                            {"name": "TTF-1", "value": float(result.get("TTF1", 0.0))},
                            {"name": "CK7", "value": float(result.get("CK7", 0.0))},
                        ]
                    except Exception:
                        biomarkers = []
        if biomarkers is None:
            biomarkers = []

        self._render_biomarkers(biomarkers)

        # explanation
        explanation = ""
        if isinstance(result, dict):
            explanation = result.get("explanation", "")
            if not explanation and ("TTF1_Class" in result or "CK7_Class" in result):
                try:
                    explanation = (
                        f"Model predicts TTF-1: {result.get('TTF1_Class', '-')} "
                        f"(score={float(result.get('Raw_TTF1', 0.0)):.3f}), "
                        f"CK7: {result.get('CK7_Class', '-')} "
                        f"(score={float(result.get('Raw_CK7', 0.0)):.3f})."
                    )
                except Exception:
                    pass

        self.explanation_text.delete("1.0", "end")
        self.explanation_text.insert("end", explanation)

        self._heatmap_src = result.get("heatmap") if isinstance(result, dict) else None
        self._rebuild_and_redraw()

        self._set_progress(stage="Done", msg="[DONE] Analysis complete.", pct=100)
        self._finish_ai_run()

