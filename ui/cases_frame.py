import tkinter as tk
from tkinter import ttk, messagebox
from ui.case_dialog import CaseDialog
from logic.backend import get_initial_cases, add_case, update_case, delete_case


class CasesFrame(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # ---------- Styles ----------
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        PRIMARY = "#0ea5e9"
        BG = "#0b1220"
        CARD_BG = "#0f172a"
        FG = "#e5e7eb"
        MUTED = "#94a3b8"
        BORDER = "#1f2937"
        DANGER = "#ef4444"
        ROW_EVEN = "#0b1220"
        ROW_ODD = "#0e1627"

        style.configure("App.TFrame", background=BG)
        style.configure("Toolbar.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("H1.TLabel", background=BG, foreground=FG, font=("Segoe UI", 18, "bold"))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Role.TLabel", background=BG, foreground=FG, font=("Segoe UI", 10, "bold"))

        style.configure("Accent.TButton", background=PRIMARY, foreground="#0b1220", padding=(14, 8))
        style.configure("Ghost.TButton", background=BG, foreground=MUTED, padding=(12, 8))
        style.configure("Danger.TButton", background=DANGER, foreground="#0b1220", padding=(12, 8))

        style.configure(
            "Treeview",
            background=CARD_BG,
            fieldbackground=CARD_BG,
            foreground=FG,
            bordercolor=BORDER,
            rowheight=28,
        )
        style.configure(
            "Treeview.Heading",
            background=BG,
            foreground=FG,
            bordercolor=BORDER,
            font=("Segoe UI", 10, "bold"),
        )

        # ---------- Layout ----------
        root = ttk.Frame(self, style="App.TFrame")
        root.pack(fill="both", expand=True)

        topbar = ttk.Frame(root, style="Toolbar.TFrame", padding=(16, 12))
        topbar.pack(fill="x")
        ttk.Label(topbar, text="Cases", style="H1.TLabel").pack(side="left")
        self.role_label = ttk.Label(topbar, text="Role: ?", style="Role.TLabel")
        self.role_label.pack(side="right")

        controls = ttk.Frame(root, style="Toolbar.TFrame", padding=(16, 0))
        controls.pack(fill="x")

        left = ttk.Frame(controls, style="Toolbar.TFrame")
        left.pack(side="left", fill="x", expand=True)

        ttk.Label(left, text="🔎 Search", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        self.search_var = tk.StringVar()
        ttk.Entry(left, textvariable=self.search_var, width=28).pack(side="left", fill="x", expand=True)

        ttk.Button(
            left,
            text="Clear",
            style="Ghost.TButton",
            command=lambda: (self.search_var.set(""), self.refresh_table()),
        ).pack(side="left", padx=(8, 0))

        right = ttk.Frame(controls, style="Toolbar.TFrame")
        right.pack(side="right")

        ttk.Button(right, text="Add Case", style="Ghost.TButton", command=self.add_case).pack(side="left", padx=6)
        ttk.Button(right, text="Edit", style="Ghost.TButton", command=self.edit_case).pack(side="left", padx=6)
        ttk.Button(right, text="Delete", style="Danger.TButton", command=self.delete_case).pack(side="left", padx=6)
        ttk.Button(right, text="Open Viewer", style="Accent.TButton", command=self.open_viewer).pack(side="left", padx=6)

        # ---------- Table ----------
        card = ttk.Frame(root, style="Card.TFrame", padding=12)
        card.pack(fill="both", expand=True, padx=16, pady=12)

        columns = ("id", "patient", "date", "status", "ct")
        headers = {
            "id": "ID",
            "patient": "Patient",
            "date": "Date",
            "status": "Status",
            "ct": "CT Series (DICOM folder)",
        }

        self.tree = ttk.Treeview(card, columns=columns, show="headings", selectmode="browse")
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, stretch=True)

        self.tree.tag_configure("evenrow", background=ROW_EVEN)
        self.tree.tag_configure("oddrow", background=ROW_ODD)

        yscroll = ttk.Scrollbar(card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        self.search_var.trace_add("write", lambda *_: self.refresh_table())
        self.tree.bind("<Double-1>", lambda e: self.open_viewer())
        self.tree.bind("<Return>", lambda e: self.open_viewer())
        self.tree.bind("<Delete>", lambda e: self.delete_case())

        self.on_show()

    # ---------- Data ----------
    def on_show(self):
        self.role_label.config(text=f"Role: {self.controller.current_user_role}")
        try:
            self.controller.cases = get_initial_cases()
        except Exception as e:
            messagebox.showerror("Database error", str(e))
            self.controller.cases = []
        self.refresh_table()

    def refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        for i, case in enumerate(self.controller.cases):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.tree.insert(
                "",
                "end",
                values=(
                    case.case_id,
                    case.patient_name,
                    case.date,
                    case.segmentation_status,
                    case.ct_series_dir,
                ),
                tags=(tag,),
            )

    # ---------- Actions ----------
    def add_case(self):
        dlg = CaseDialog(self, title="Add Case")
        self.wait_window(dlg)
        if dlg.result:
            add_case(dlg.result)
            self.controller.cases = get_initial_cases()
            self.refresh_table()

    def _get_selected_case(self):
        sel = self.tree.selection()
        if not sel:
            return None
        case_id = self.tree.item(sel[0], "values")[0]
        return next((c for c in self.controller.cases if c.case_id == case_id), None)

    def edit_case(self):
        case = self._get_selected_case()
        if not case:
            return
        dlg = CaseDialog(self, title="Edit Case", case=case)
        self.wait_window(dlg)
        if dlg.result:
            update_case(dlg.result)
            self.controller.cases = get_initial_cases()
            self.refresh_table()

    def delete_case(self):
        case = self._get_selected_case()
        if not case:
            return
        if messagebox.askyesno("Confirm delete", f"Delete case {case.case_id}?"):
            delete_case(case.case_id)
            self.controller.cases = get_initial_cases()
            self.refresh_table()

    def open_viewer(self):
        case = self._get_selected_case()
        if not case:
            return
        self.controller.current_case = case
        self.controller.show_frame("ViewerFrame")
