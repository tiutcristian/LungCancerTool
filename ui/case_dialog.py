import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date
from models import Case
from backend_mock import ASSETS_DIR  # pentru a deschide direct în /assets

STATUSES = ["Unsegmented", "Segmented", "Reported"]

class CaseDialog(tk.Toplevel):
    def __init__(self, parent, title, case=None, default_id=None, existing_ids=None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result = None
        self.existing_ids = set(existing_ids or [])

        # ---- fields
        frm = tk.Frame(self, padx=10, pady=10)
        frm.pack(fill="both", expand=True)

        tk.Label(frm, text="Case ID:").grid(row=0, column=0, sticky="e")
        self.id_var = tk.StringVar(value=(case.case_id if case else (default_id or "")))
        tk.Entry(frm, textvariable=self.id_var, width=22).grid(row=0, column=1, padx=6, pady=4)

        tk.Label(frm, text="Patient:").grid(row=1, column=0, sticky="e")
        self.name_var = tk.StringVar(value=(case.patient_name if case else ""))
        tk.Entry(frm, textvariable=self.name_var, width=22).grid(row=1, column=1, padx=6, pady=4)

        tk.Label(frm, text="Date (YYYY-MM-DD):").grid(row=2, column=0, sticky="e")
        self.date_var = tk.StringVar(value=(case.date if case else str(date.today())))
        tk.Entry(frm, textvariable=self.date_var, width=22).grid(row=2, column=1, padx=6, pady=4)

        tk.Label(frm, text="Status:").grid(row=3, column=0, sticky="e")
        self.status_var = tk.StringVar(value=(case.status if case else STATUSES[0]))
        ttk.Combobox(frm, textvariable=self.status_var, values=STATUSES,
                     state="readonly", width=20).grid(row=3, column=1, padx=6, pady=4)

        # images
        tk.Label(frm, text="Series images:").grid(row=4, column=0, sticky="ne")
        right = tk.Frame(frm)
        right.grid(row=4, column=1, sticky="w")
        self.series_paths = list(case.series_paths) if case else []
        self.lb = tk.Listbox(right, width=40, height=6)
        self.lb.pack(side="left")
        for p in self.series_paths:
            self.lb.insert("end", os.path.basename(p))

        btns = tk.Frame(right)
        btns.pack(side="left", padx=6)
        tk.Button(btns, text="Add...", command=self._add_imgs).pack(fill="x", pady=2)
        tk.Button(btns, text="Remove", command=self._remove_selected).pack(fill="x", pady=2)

        # actions
        a = tk.Frame(self, pady=8)
        a.pack()
        tk.Button(a, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        tk.Button(a, text="Save", command=self._save).pack(side="right", padx=4)

        self.grab_set()
        self.transient(parent)
        self.id_entry_invalid = False

    def _add_imgs(self):
        paths = filedialog.askopenfilenames(
            parent=self, title="Select images",
            initialdir=ASSETS_DIR,
            filetypes=[("Images", "*.png;*.jpg;*.jpeg"), ("All files", "*.*")]
        )
        for p in paths:
            if p and p not in self.series_paths:
                self.series_paths.append(p)
                self.lb.insert("end", os.path.basename(p))

    def _remove_selected(self):
        sel = list(self.lb.curselection())
        if not sel:
            return
        for i in reversed(sel):
            self.lb.delete(i)
            del self.series_paths[i]

    def _save(self):
        cid = self.id_var.get().strip()
        if not cid:
            messagebox.showerror("Validation", "Case ID required.")
            return
        # dacă e add, nu permitem duplicate
        if cid not in [getattr(c, "case_id", None) for c in [self.result]] and cid in self.existing_ids:
            messagebox.showerror("Validation", f"Case ID '{cid}' already exists.")
            return
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Validation", "Patient name required.")
            return
        d = self.date_var.get().strip()
        if len(d) != 10 or d[4] != "-" or d[7] != "-":
            messagebox.showerror("Validation", "Date must be YYYY-MM-DD.")
            return

        self.result = Case(cid, name, d, self.status_var.get(), self.series_paths)
        self.destroy()
