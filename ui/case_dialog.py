import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date
from model.models import Case

STATUSES = ["Unsegmented", "Segmented", "Reported"]



def _default_initialdir() -> str:
    """Choose a sensible default folder for picking images."""
    here = os.path.dirname(os.path.abspath(__file__))

    # Common layouts:
    #  - project_root/assets
    #  - ui/assets (if you keep assets next to UI code)
    candidates = [
        os.path.join(here, "assets"),
        os.path.abspath(os.path.join(here, "..", "assets")),
        os.getcwd(),
    ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    return os.getcwd()



class CaseDialog(tk.Toplevel):
    """Styled Add/Edit dialog with dark theme and keyboard shortcuts."""
    def __init__(self, parent, title, case=None, default_id=None, existing_ids=None):
        super().__init__(parent)
        self.title(title)
        self.result = None
        self.existing_ids = set(existing_ids or [])
        self.transient(parent)
        self.grab_set()

        # ---------- Styles (align with app palette) ----------
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

        self.configure(bg=BG)
        style.configure("Dialog.TFrame", background=CARD_BG)
        style.configure("DialogTitle.TLabel", background=CARD_BG, foreground=FG, font=("Segoe UI", 14, "bold"))
        style.configure("DialogMuted.TLabel", background=CARD_BG, foreground=MUTED)
        style.configure("DialogLabel.TLabel", background=CARD_BG, foreground=FG, font=("Segoe UI", 10, "bold"))

        style.configure("TEntry",
                        fieldbackground=FIELD_BG, foreground=FG,
                        insertcolor=FG, bordercolor=BORDER, padding=6)
        style.map("TEntry",
                  fieldbackground=[("disabled", "#1f2937"), ("!disabled", FIELD_BG)],
                  bordercolor=[("focus", PRIMARY), ("!focus", BORDER)])

        style.configure("Accent.TButton", background=PRIMARY, foreground="#0b1220",
                        padding=(14, 8), borderwidth=0)
        style.map("Accent.TButton",
                  background=[("active", "#22d3ee"), ("!active", PRIMARY)])
        style.configure("Ghost.TButton", background=CARD_BG, foreground=MUTED,
                        padding=(12, 8), borderwidth=0)
        style.map("Ghost.TButton",
                  background=[("active", "#111827")],
                  foreground=[("active", FG), ("!active", MUTED)])

        # ---------- Layout ----------
        outer = ttk.Frame(self, style="Dialog.TFrame", padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=title, style="DialogTitle.TLabel").pack(anchor="w", pady=(0, 8))
        form = ttk.Frame(outer, style="Dialog.TFrame")
        form.pack(fill="x")

        # Case ID
        ttk.Label(form, text="Case ID", style="DialogLabel.TLabel").grid(row=0, column=0, sticky="w", pady=(2, 2))
        self.id_var = tk.StringVar(value=(case.case_id if case else (default_id or "")))
        id_entry = ttk.Entry(form, textvariable=self.id_var)
        id_entry.grid(row=1, column=0, sticky="ew")
        form.grid_columnconfigure(0, weight=1)

        # Patient
        ttk.Label(form, text="Patient", style="DialogLabel.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 2))
        self.name_var = tk.StringVar(value=(case.patient_name if case else ""))
        ttk.Entry(form, textvariable=self.name_var).grid(row=3, column=0, sticky="ew")

        # Date
        ttk.Label(form, text="Date (YYYY-MM-DD)", style="DialogLabel.TLabel").grid(row=4, column=0, sticky="w", pady=(12, 2))
        self.date_var = tk.StringVar(value=(case.date if case else str(date.today())))
        ttk.Entry(form, textvariable=self.date_var).grid(row=5, column=0, sticky="ew")

        # Status
        ttk.Label(form, text="Status", style="DialogLabel.TLabel").grid(row=6, column=0, sticky="w", pady=(12, 2))
        self.status_var = tk.StringVar(value=(case.segmentation_status if case else STATUSES[0]))
        ttk.Combobox(form, textvariable=self.status_var, values=STATUSES,
                     state="readonly").grid(row=7, column=0, sticky="ew")

        # Series list with buttons
        ttk.Label(form, text="Series images", style="DialogLabel.TLabel").grid(row=8, column=0, sticky="w", pady=(12, 2))
        list_row = ttk.Frame(form, style="Dialog.TFrame")
        list_row.grid(row=9, column=0, sticky="nsew")
        form.grid_rowconfigure(9, weight=1)

        self.image_paths = list(case.ct_images) if case else []

        # Use tk.Listbox but style colors to match
        self.lb = tk.Listbox(list_row, height=6, activestyle="none",
                             bg=FIELD_BG, fg=FG, highlightthickness=0,
                             selectbackground="#1f2937", selectforeground=FG)
        self.lb.pack(side="left", fill="both", expand=True)
        for p in self.image_paths:
            self.lb.insert("end", os.path.basename(p))

        sb = ttk.Scrollbar(list_row, orient="vertical", command=self.lb.yview)
        sb.pack(side="left", fill="y")
        self.lb.configure(yscrollcommand=sb.set)

        btns = ttk.Frame(list_row, style="Dialog.TFrame")
        btns.pack(side="left", padx=8, fill="y")
        ttk.Button(btns, text="Add…", style="Ghost.TButton", command=self._add_imgs).pack(fill="x", pady=2)
        ttk.Button(btns, text="Remove", style="Ghost.TButton", command=self._remove_selected).pack(fill="x", pady=2)

        # Actions
        actions = ttk.Frame(outer, style="Dialog.TFrame")
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Cancel", style="Ghost.TButton", command=self._cancel).pack(side="right", padx=6)
        ttk.Button(actions, text="Save", style="Accent.TButton", command=self._save).pack(side="right")

        # ---------- Behavior ----------
        self.bind("<Escape>", lambda e: self._cancel())
        self.bind("<Control-s>", lambda e: self._save())

        # Focus + center on parent
        self.after(50, lambda: id_entry.focus_set())
        self._center_on_parent(parent)

        # Fixed min size; allow manual widen
        self.minsize(560, 420)

    # ---------- Helpers ----------
    def _center_on_parent(self, parent):
        try:
            self.update_idletasks()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _add_imgs(self):
        paths = filedialog.askopenfilenames(
            parent=self, title="Select images",
            initialdir=_default_initialdir(),
            filetypes=[("Images", "*.png;*.jpg;*.jpeg"), ("All files", "*.*")]
        )
        for p in paths:
            if p and p not in self.image_paths:
                self.image_paths.append(p)
                self.lb.insert("end", os.path.basename(p))

    def _remove_selected(self):
        sel = list(self.lb.curselection())
        if not sel:
            return
        for i in reversed(sel):
            self.lb.delete(i)
            del self.image_paths[i]

    def _cancel(self):
        self.result = None
        self.destroy()

    def _save(self):
        cid = (self.id_var.get() or "").strip()
        if not cid:
            messagebox.showerror("Validation", "Case ID required.")
            return
        if cid in self.existing_ids:
            messagebox.showerror("Validation", f"Case ID '{cid}' already exists.")
            return
        name = (self.name_var.get() or "").strip()
        if not name:
            messagebox.showerror("Validation", "Patient name required.")
            return
        d = (self.date_var.get() or "").strip()
        if len(d) != 10 or d[4] != "-" or d[7] != "-":
            messagebox.showerror("Validation", "Date must be YYYY-MM-DD.")
            return

        self.result = Case(cid, name, d, self.status_var.get(), self.image_paths)
        self.destroy()
