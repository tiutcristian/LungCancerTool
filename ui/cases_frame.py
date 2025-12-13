import tkinter as tk
from tkinter import ttk, messagebox
from ui.case_dialog import CaseDialog


class CasesFrame(tk.Frame):
    """Cases list with dark UI, toolbar, zebra rows, and handy shortcuts."""
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # ---------- Styles (match login palette) ----------
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        PRIMARY = "#0ea5e9"   # cyan-500
        BG       = "#0b1220"  # slate-950
        CARD_BG  = "#0f172a"  # slate-900
        FG       = "#e5e7eb"  # gray-200
        MUTED    = "#94a3b8"  # gray-400
        FIELD_BG = "#111827"  # gray-900
        BORDER   = "#1f2937"  # slate-800
        DANGER   = "#ef4444"  # red-500
        ROW_EVEN = "#0b1220"  # background
        ROW_ODD  = "#0e1627"  # slightly lighter

        style.configure("App.TFrame", background=BG)
        style.configure("Toolbar.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("H1.TLabel", background=BG, foreground=FG, font=("Segoe UI", 18, "bold"))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Role.TLabel", background=BG, foreground=FG, font=("Segoe UI", 10, "bold"))
        style.configure("CardMuted.TLabel", background=CARD_BG, foreground=MUTED)

        style.configure("TEntry",
                        fieldbackground=FIELD_BG, foreground=FG,
                        insertcolor=FG, bordercolor=BORDER, padding=8)
        style.map("TEntry",
                  fieldbackground=[("disabled", "#1f2937"), ("!disabled", FIELD_BG)],
                  bordercolor=[("focus", PRIMARY), ("!focus", BORDER)])

        style.configure("Accent.TButton", background=PRIMARY, foreground="#0b1220",
                        padding=(14, 8), borderwidth=0)
        style.map("Accent.TButton",
                  background=[("active", "#22d3ee"), ("!active", PRIMARY)])

        style.configure("Ghost.TButton", background=BG, foreground=MUTED,
                        padding=(12, 8), borderwidth=0)
        style.map("Ghost.TButton",
                  background=[("active", "#111827")],
                  foreground=[("active", FG), ("!active", MUTED)])

        style.configure("Danger.TButton", background=DANGER, foreground="#0b1220",
                        padding=(12, 8), borderwidth=0)
        style.map("Danger.TButton",
                  background=[("active", "#f87171"), ("!active", DANGER)])

        style.configure("Treeview",
                        background=CARD_BG, fieldbackground=CARD_BG, foreground=FG,
                        bordercolor=BORDER, rowheight=28)
        style.configure("Treeview.Heading",
                        background=BG, foreground=FG, bordercolor=BORDER,
                        font=("Segoe UI", 10, "bold"))

        # ---------- Root ----------
        root = ttk.Frame(self, style="App.TFrame")
        root.pack(fill="both", expand=True)

        # Top bar: title + role
        topbar = ttk.Frame(root, style="Toolbar.TFrame", padding=(16, 12))
        topbar.pack(fill="x")
        ttk.Label(topbar, text="Cases", style="H1.TLabel").pack(side="left")
        self.role_label = ttk.Label(topbar, text="Role: ?", style="Role.TLabel")
        self.role_label.pack(side="right")

        # Controls: search + buttons
        controls = ttk.Frame(root, style="Toolbar.TFrame", padding=(16, 0))
        controls.pack(fill="x")

        left = ttk.Frame(controls, style="Toolbar.TFrame")
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="🔎 Search", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(left, textvariable=self.search_var, width=28)
        self.search_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(left, text="Clear", style="Ghost.TButton",
                   command=lambda: (self.search_var.set(""), self.refresh_table())).pack(side="left", padx=(8, 0))

        right = ttk.Frame(controls, style="Toolbar.TFrame")
        right.pack(side="right")
        self.btn_add  = ttk.Button(right, text="Add Case", style="Ghost.TButton", command=self.add_case)
        self.btn_edit = ttk.Button(right, text="Edit",     style="Ghost.TButton", command=self.edit_case)
        self.btn_del  = ttk.Button(right, text="Delete",   style="Danger.TButton", command=self.delete_case)
        self.btn_open = ttk.Button(right, text="Open Viewer", style="Accent.TButton", command=self.open_viewer)
        for b in (self.btn_add, self.btn_edit, self.btn_del, self.btn_open):
            b.pack(side="left", padx=6)

        # Table card
        card = ttk.Frame(root, style="Card.TFrame", padding=12)
        card.pack(fill="both", expand=True, padx=16, pady=12)

        columns = ("id", "patient", "date", "status", "series")
        self.tree = ttk.Treeview(card, columns=columns, show="headings", selectmode="browse")
        headers = {"id": "ID", "patient": "Patient", "date": "Date", "status": "Status", "series": "#Series"}
        widths = {"id": 120, "patient": 260, "date": 130, "status": 140, "series": 90}
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, stretch=True, width=widths[col])

        # zebra rows
        self.tree.tag_configure("evenrow", background=ROW_EVEN)
        self.tree.tag_configure("oddrow", background=ROW_ODD)

        # scrollbars
        yscroll = ttk.Scrollbar(card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        # bindings
        self.search_var.trace_add("write", lambda *_: self.refresh_table())
        self.tree.bind("<Double-1>", lambda e: self.open_viewer())
        self.tree.bind("<Return>",   lambda e: self.open_viewer())
        self.tree.bind("<Delete>",   lambda e: self.delete_case())
        self.bind_all("<Control-n>", lambda e: self.add_case())
        self.bind_all("<Control-e>", lambda e: self.edit_case())

    # ---------- lifecycle ----------
    def on_show(self):
        self.role_label.config(text=f"Role: {self.controller.current_user_role}")
        self.refresh_table()
        self.search_entry.focus_set()

    # ---------- helpers ----------
    def _existing_ids(self):
        return {c.case_id for c in self.controller.cases}

    def _next_id(self):
        maxnum = 0
        for c in self.controller.cases:
            try:
                n = int(str(c.case_id).split("-")[-1])
                maxnum = max(maxnum, n)
            except Exception:
                pass
        return f"LC-{maxnum+1:03d}"

    def get_filtered_cases(self):
        q = self.search_var.get().lower().strip()
        if not q:
            return self.controller.cases
        return [c for c in self.controller.cases
                if q in c.case_id.lower() or q in c.patient_name.lower()]

    def refresh_table(self):
        # clear
        for row in self.tree.get_children():
            self.tree.delete(row)
        # fill with zebra striping
        for i, case in enumerate(self.get_filtered_cases()):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.tree.insert(
                "", "end",
                values=(case.case_id, case.patient_name, case.date, case.status, len(case.series_paths)),
                tags=(tag,)
            )

    # ---------- actions ----------
    def add_case(self):
        new_id = self._next_id()
        dlg = CaseDialog(self, title="Add Case", default_id=new_id, existing_ids=self._existing_ids())
        self.wait_window(dlg)
        if dlg.result:
            self.controller.cases.append(dlg.result)
            self.refresh_table()

    def _get_selected_case(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select a case first")
            return None
        case_id = self.tree.item(sel[0], "values")[0]
        for c in self.controller.cases:
            if c.case_id == case_id:
                return c
        return None

    def edit_case(self):
        case = self._get_selected_case()
        if not case:
            return
        ids = self._existing_ids() - {case.case_id}
        dlg = CaseDialog(self, title="Edit Case", case=case, existing_ids=ids)
        self.wait_window(dlg)
        if dlg.result:
            case.case_id = dlg.result.case_id
            case.patient_name = dlg.result.patient_name
            case.date = dlg.result.date
            case.status = dlg.result.status
            case.series_paths = dlg.result.series_paths
            self.refresh_table()

    def delete_case(self):
        case = self._get_selected_case()
        if not case:
            return
        if messagebox.askyesno("Confirm delete",
                               f"Delete case {case.case_id} - {case.patient_name}?"):
            self.controller.cases.remove(case)
            self.refresh_table()

    def open_viewer(self):
        case = self._get_selected_case()
        if not case:
            return
        self.controller.current_case = case
        self.controller.show_frame("ViewerFrame")
