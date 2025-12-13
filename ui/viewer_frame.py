from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageOps

from logic.backend import run_ai
from model.models import Case


class ViewerFrame(tk.Frame):
    """
    Dark, modern viewer with corrected heatmap enhancement:
      • Heatmap intensity taken from overlay alpha -> auto-contrasted
      • Colored with a jet-like colormap (blue→green→yellow→red)
      • Per-pixel alpha scaled by user opacity (slider)
    """
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # ---------- State ----------
        self._pil_base: Image.Image | None = None   # current series image (RGBA)
        self._heatmap: Image.Image | None = None    # AI heatmap (RGBA or anything with alpha)
        self._tk_img = None
        self._zoom = 1.0
        self._fit_mode = True

        # ---------- Styles ----------
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        PRIMARY = "#0ea5e9"
        BG       = "#0b1220"
        CARD_BG  = "#0f172a"
        FG       = "#e5e7eb"
        MUTED    = "#94a3b8"
        FIELD_BG = "#111827"
        BORDER   = "#1f2937"

        style.configure("App.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("Toolbar.TFrame", background=BG)
        style.configure("Title.TLabel", background=BG, foreground=FG, font=("Segoe UI", 14, "bold"))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("RightTitle.TLabel", background=CARD_BG, foreground=FG, font=("Segoe UI", 12, "bold"))
        style.configure("Card.TLabel", background=CARD_BG, foreground=FG)

        style.configure("Ghost.TButton", background=BG, foreground=MUTED,
                        padding=(12, 8), borderwidth=0)
        style.map("Ghost.TButton",
                  background=[("active", "#111827")],
                  foreground=[("active", FG), ("!active", MUTED)])

        style.configure("Accent.TButton", background=PRIMARY, foreground="#0b1220",
                        padding=(12, 8), borderwidth=0)
        style.map("Accent.TButton",
                  background=[("active", "#22d3ee"), ("!active", PRIMARY)])

        style.configure("Blue.Horizontal.TProgressbar", troughcolor=FIELD_BG,
                        background=PRIMARY, bordercolor=BORDER, lightcolor=PRIMARY, darkcolor=PRIMARY)

        # ---------- Root Layout ----------
        root = ttk.Frame(self, style="App.TFrame")
        root.pack(fill="both", expand=True)

        # Top bar
        top = ttk.Frame(root, style="Toolbar.TFrame", padding=(12, 10))
        top.pack(fill="x")
        ttk.Button(top, text="← Back", style="Ghost.TButton",
                   command=lambda: controller.show_frame("CasesFrame")).pack(side="left")
        self.case_label = ttk.Label(top, text="Case: -", style="Title.TLabel")
        self.case_label.pack(side="left", padx=(8, 0))

        # Content area
        content = ttk.Frame(root, style="App.TFrame")
        content.pack(fill="both", expand=True)

        # Left: series list
        left = ttk.Frame(content, style="Card.TFrame", padding=10)
        left.pack(side="left", fill="y", padx=(12, 6), pady=(0, 12))
        ttk.Label(left, text="Series", style="RightTitle.TLabel").pack(anchor="w")

        self.series_list = tk.Listbox(
            left, height=8, activestyle="none",
            bg=FIELD_BG, fg=FG, highlightthickness=0,
            selectbackground="#1f2937", selectforeground=FG
        )
        self.series_list.pack(fill="y", expand=False, pady=(6, 0))
        self.series_list.bind("<<ListboxSelect>>", lambda e: self._load_selected_series())

        # Center: viewer card
        center = ttk.Frame(content, style="Card.TFrame", padding=8)
        center.pack(side="left", fill="both", expand=True, padx=6, pady=(0, 12))

        self.canvas = tk.Canvas(center, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._redraw())

        viewer_tb = ttk.Frame(center, style="Card.TFrame")
        viewer_tb.pack(fill="x", pady=(8, 0))
        ttk.Label(viewer_tb, text="View", style="Card.TLabel").pack(side="left", padx=(0, 8))
        ttk.Button(viewer_tb, text="Fit", style="Ghost.TButton",
                   command=self._fit).pack(side="left")
        ttk.Button(viewer_tb, text="1:1", style="Ghost.TButton",
                   command=self._one_to_one).pack(side="left")
        ttk.Button(viewer_tb, text="−", style="Ghost.TButton",
                   command=lambda: self._zoom_step(0.9)).pack(side="left")
        ttk.Button(viewer_tb, text="+", style="Ghost.TButton",
                   command=lambda: self._zoom_step(1.1)).pack(side="left")
        self.zoom_label = ttk.Label(viewer_tb, text="100%", style="Card.TLabel")
        self.zoom_label.pack(side="left", padx=(8, 0))

        # Right: results
        right = ttk.Frame(content, style="Card.TFrame", padding=10)
        right.pack(side="left", fill="y", padx=(6, 12), pady=(0, 12))

        ttk.Label(right, text="Biomarkers", style="RightTitle.TLabel").pack(anchor="w")
        self.biomarker_frame = ttk.Frame(right, style="Card.TFrame")
        self.biomarker_frame.pack(fill="x", pady=(6, 6))

        # Heatmap controls
        controls = ttk.Frame(right, style="Card.TFrame")
        controls.pack(fill="x", pady=(4, 10))
        self.heatmap_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="Show heatmap overlay",
                        variable=self.heatmap_var,
                        command=self._redraw).pack(anchor="w")
        ttk.Label(controls, text="Opacity", style="Card.TLabel").pack(anchor="w", pady=(6, 0))
        self.hm_opacity = tk.DoubleVar(value=0.55)
        self.hm_opacity_scale = ttk.Scale(
            controls, from_=0.0, to=1.0, orient="horizontal",
            variable=self.hm_opacity, command=lambda _=None: self._redraw()
        )
        self.hm_opacity_scale.pack(fill="x")

        ttk.Button(right, text="Run AI", style="Accent.TButton", command=self.run_ai)\
            .pack(fill="x", pady=(8, 8))

        ttk.Label(right, text="Explanation", style="Card.TLabel").pack(anchor="w")
        self.explanation_text = tk.Text(
            right, width=36, height=12, wrap="word",
            bg=FIELD_BG, fg="#e5e7eb", insertbackground="#e5e7eb", relief="flat"
        )
        self.explanation_text.pack(fill="both", expand=True, pady=(4, 0))

        # Mouse & keyboard
        self.canvas.bind("<MouseWheel>", self._on_wheel)         # Windows/macOS
        self.canvas.bind("<Button-4>", lambda e: self._zoom_step(1.1))  # X11
        self.canvas.bind("<Button-5>", lambda e: self._zoom_step(0.9))

        self.bind_all("+", lambda e: self._zoom_step(1.1))
        self.bind_all("-", lambda e: self._zoom_step(0.9))
        self.bind_all("f", lambda e: self._fit())
        self.bind_all("1", lambda e: self._one_to_one())
        self.bind_all("r", lambda e: self.run_ai())

        # Precompute colormap palette (jet-like)
        self._palette = self._build_palette()

    # ---------- lifecycle ----------
    def on_show(self):
        c: Case = self.controller.current_case
        self.case_label.config(text=f"Case: {c.case_id}  ·  {c.patient_name}")

        self._heatmap = None
        self.explanation_text.delete("1.0", "end")
        for w in self.biomarker_frame.winfo_children():
            w.destroy()

        self.series_list.delete(0, "end")
        for i, p in enumerate(c.ct_images):
            name = os.path.basename(p)
            self.series_list.insert("end", f"{i+1}. {name}")

        if c.ct_images:
            self.series_list.selection_clear(0, "end")
            self.series_list.selection_set(0)
            self._load_selected_series()
        else:
            self._pil_base = None
            self._fit()
            self.canvas.delete("all")
            self.canvas.create_text(
                self.canvas.winfo_width() // 2,
                self.canvas.winfo_height() // 2,
                text="No series available",
                fill="white",
            )

    # ---------- helpers ----------
    def _load_selected_series(self):
        c: Case = self.controller.current_case
        if not c.ct_images:
            return
        idx = self.series_list.curselection()
        if not idx:
            return
        img_path = c.ct_images[int(idx[0])]
        try:
            self._pil_base = Image.open(img_path).convert("RGBA")
        except Exception as e:
            self._pil_base = None
            messagebox.showerror("Image error", f"Could not open image:\n{img_path}\n\n{e}")
        self._fit()

    def _compose(self) -> Image.Image | None:
        """Return base image with optional colored heatmap overlay."""
        base = self._pil_base
        if base is None:
            return None

        img = base.copy().convert("RGBA")
        if self._heatmap and self.heatmap_var.get():
            # Use heatmap's alpha channel as intensity (0..255)
            hm = self._heatmap.resize(base.size, Image.LANCZOS)
            if hm.mode != "RGBA":
                hm = hm.convert("RGBA")
            alpha = hm.split()[3]  # take transparency as intensity

            # Stretch contrast for better dynamic range
            alpha = ImageOps.autocontrast(alpha, cutoff=2)

            # Colorize with our palette (blue->green->yellow->red)
            colored = self._colorize_from_luminance(alpha)

            # Scale per-pixel alpha by user opacity
            opacity = max(0.0, min(float(self.hm_opacity.get()), 1.0))
            a_scaled = alpha.point(lambda p: int(p * opacity))
            colored.putalpha(a_scaled)

            # Composite onto base
            img = Image.alpha_composite(img, colored)

        return img

    def _fit_to_canvas(self, img: Image.Image) -> Image.Image:
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        iw, ih = img.size
        scale = min(cw / iw, ch / ih)
        new_size = (max(1, int(iw * scale)), max(1, int(ih * scale)))
        return img.resize(new_size, Image.LANCZOS)

    def _redraw(self):
        self.canvas.delete("all")
        img = self._compose()
        if img is None:
            self.canvas.create_text(
                self.canvas.winfo_width() // 2,
                self.canvas.winfo_height() // 2,
                text="[CT slice placeholder]",
                fill="white",
            )
            return

        if self._fit_mode:
            display = self._fit_to_canvas(img)
            self._zoom = display.width / img.width
        else:
            z = max(0.05, min(self._zoom, 8.0))
            w = max(1, int(img.width * z))
            h = max(1, int(img.height * z))
            display = img.resize((w, h), Image.LANCZOS)

        self._tk_img = ImageTk.PhotoImage(display)
        cx = (self.canvas.winfo_width() - display.width) // 2
        cy = (self.canvas.winfo_height() - display.height) // 2
        self.canvas.create_image(cx, cy, anchor="nw", image=self._tk_img)
        self._update_zoom_label()

    def _update_zoom_label(self):
        self.zoom_label.configure(text=f"{int(round(self._zoom * 100))}%")

    # ---------- zoom & view ----------
    def _fit(self):
        self._fit_mode = True
        self._redraw()

    def _one_to_one(self):
        self._fit_mode = False
        self._zoom = 1.0
        self._redraw()

    def _zoom_step(self, factor: float):
        self._fit_mode = False
        self._zoom = max(0.05, min(self._zoom * factor, 8.0))
        self._redraw()

    def _on_wheel(self, event):
        if event.delta > 0:
            self._zoom_step(1.1)
        else:
            self._zoom_step(0.9)

    # ---------- colormap utils ----------
    def _build_palette(self):
        """Return a 256*3 list for a jet-like palette."""
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
            pal.extend([max(0, min(255, r)),
                        max(0, min(255, g)),
                        max(0, min(255, b))])
        return pal

    def _colorize_from_luminance(self, lum_img: Image.Image) -> Image.Image:
        """Map L image -> RGBA using the precomputed palette."""
        p = lum_img.convert("P")
        p.putpalette(self._palette)
        return p.convert("RGBA")

    # ---------- actions ----------
    def run_ai(self):
        c: Case = self.controller.current_case
        try:
            result = run_ai(c)
        except Exception as e:
            messagebox.showerror("AI / DB error", f"Could not load AI result for {c.case_id}:\n{e}")
            result = {"biomarkers": [], "explanation": "", "heatmap": None}

        # biomarkers
        for w in self.biomarker_frame.winfo_children():
            w.destroy()
        for bm in result["biomarkers"]:
            row = ttk.Frame(self.biomarker_frame, style="Card.TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=bm["name"], style="Card.TLabel").pack(anchor="w")
            pb = ttk.Progressbar(row, maximum=1.0, value=bm["value"], style="Blue.Horizontal.TProgressbar")
            pb.pack(fill="x")
            pct = int(round(bm["value"] * 100))
            ttk.Label(row, text=f"{pct}%", style="Card.TLabel").pack(anchor="e")

        # explanation
        self.explanation_text.delete("1.0", "end")
        self.explanation_text.insert("end", result["explanation"])

        # store heatmap and redraw
        self._heatmap = result.get("heatmap")
        self._redraw()
