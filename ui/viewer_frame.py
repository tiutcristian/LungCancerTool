import os
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from backend_mock import mock_run_ai
from models import Case


class ViewerFrame(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        self._pil_base = None   # PIL.Image pentru seria curentă
        self._tk_img = None     # ImageTk.PhotoImage referință (evită GC)

        top = tk.Frame(self)
        top.pack(fill="x")
        self.case_label = tk.Label(top, text="Case: -")
        self.case_label.pack(side="left", padx=10)

        tk.Button(top, text="Back", command=lambda: controller.show_frame("CasesFrame")).pack(side="right", padx=6)

        middle = tk.Frame(self)
        middle.pack(fill="both", expand=True)

        # stânga: lista de serii (imagini din assets)
        left = tk.Frame(middle)
        left.pack(side="left", fill="y", padx=6, pady=6)
        tk.Label(left, text="Series").pack(anchor="w")
        self.series_list = tk.Listbox(left, height=6)
        self.series_list.pack(fill="y")
        self.series_list.bind("<<ListboxSelect>>", lambda e: self._load_selected_series())

        # centru: canvas pentru imagine
        center = tk.Frame(middle)
        center.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        self.canvas = tk.Canvas(center, bg="black")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._redraw())

        # dreapta: rezultate
        right = tk.Frame(middle)
        right.pack(side="left", fill="y", padx=6, pady=6)

        tk.Label(right, text="Biomarkers", font=("Arial", 12, "bold")).pack(pady=(0, 6))
        self.biomarker_frame = tk.Frame(right)
        self.biomarker_frame.pack(fill="x")

        tk.Button(right, text="Run AI", command=self.run_ai).pack(pady=8, fill="x")

        tk.Label(right, text="Explanation").pack(anchor="w")
        self.explanation_text = tk.Text(right, width=32, height=12)
        self.explanation_text.pack()

    # ---------- lifecycle ----------
    def on_show(self):
        c: Case = self.controller.current_case
        self.case_label.config(text=f"Case: {c.case_id} | {c.patient_name}")

        self.explanation_text.delete("1.0", "end")
        for w in self.biomarker_frame.winfo_children():
            w.destroy()

        # populate series list
        self.series_list.delete(0, "end")
        for i, p in enumerate(c.series_paths):
            name = os.path.basename(p)
            self.series_list.insert("end", f"{i+1}. {name}")

        # open first series if available
        if c.series_paths:
            self.series_list.selection_clear(0, "end")
            self.series_list.selection_set(0)
            self._load_selected_series()
        else:
            self._pil_base = None
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
        if not c.series_paths:
            return
        idx = self.series_list.curselection()
        if not idx:
            return
        img_path = c.series_paths[int(idx[0])]
        try:
            self._pil_base = Image.open(img_path).convert("RGBA")
        except Exception:
            self._pil_base = None
        self._redraw()

    def _fit_to_canvas(self, img):
        if img is None:
            return None
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        iw, ih = img.size
        scale = min(cw / iw, ch / ih)
        new_size = (max(1, int(iw * scale)), max(1, int(ih * scale)))
        return img.resize(new_size, Image.LANCZOS)

    def _redraw(self, overlay=None):
        self.canvas.delete("all")
        base = self._pil_base
        if base is None:
            self.canvas.create_text(
                self.canvas.winfo_width() // 2,
                self.canvas.winfo_height() // 2,
                text="[CT slice placeholder]",
                fill="white",
            )
            return

        display = base.copy()
        if overlay is not None:
            # resize overlay la aceeași dimensiune cu baza
            overlay = overlay.resize(base.size, Image.LANCZOS)
            display = Image.alpha_composite(display, overlay)

        display = self._fit_to_canvas(display)
        self._tk_img = ImageTk.PhotoImage(display)
        cx = (self.canvas.winfo_width() - display.width) // 2
        cy = (self.canvas.winfo_height() - display.height) // 2
        self.canvas.create_image(cx, cy, anchor="nw", image=self._tk_img)

    # ---------- actions ----------
    def run_ai(self):
        c: Case = self.controller.current_case
        result = mock_run_ai(c)

        # biomarkers
        for w in self.biomarker_frame.winfo_children():
            w.destroy()
        for bm in result["biomarkers"]:
            row = tk.Frame(self.biomarker_frame)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=bm["name"]).pack(anchor="w")
            pb = ttk.Progressbar(row, maximum=1.0)
            pb["value"] = bm["value"]
            pb.pack(fill="x")

        # explanation
        self.explanation_text.delete("1.0", "end")
        self.explanation_text.insert("end", result["explanation"])

        # heatmap overlay
        self._redraw(overlay=result.get("heatmap"))
