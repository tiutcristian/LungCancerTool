import os
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date
from models import Case
from ui.case_dialog import CaseDialog


class CasesFrame(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        top = tk.Frame(self)
        top.pack(fill="x", pady=5)

        self.role_label = tk.Label(top, text="Role: ?")
        self.role_label.pack(side="left", padx=10)

        tk.Label(top, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        tk.Entry(top, textvariable=self.search_var, width=24).pack(side="left")
        tk.Button(top, text="Apply", command=self.refresh_table).pack(side="left", padx=6)

        btns = tk.Frame(self)
        btns.pack(fill="x", pady=6)
        self.btn_add = tk.Button(btns, text="Add Case", command=self.add_case)
        self.btn_edit = tk.Button(btns, text="Edit Case", command=self.edit_case)
        self.btn_del = tk.Button(btns, text="Delete Case", command=self.delete_case)
        self.btn_open = tk.Button(btns, text="Open Viewer", command=self.open_viewer)
        for b in (self.btn_add, self.btn_edit, self.btn_del, self.btn_open):
            b.pack(side="left", padx=2)

        columns = ("id", "patient", "date", "status", "series")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=18)
        headers = {"id": "ID", "patient": "Patient", "date": "Date", "status": "Status", "series": "#Series"}
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, stretch=True, width=100)
        self.tree.pack(fill="both", expand=True, padx=6, pady=4)

    def on_show(self):
        # butoanele NU mai sunt dezactivate; funcționează pentru toate rolurile
        self.role_label.config(text=f"Role: {self.controller.current_user_role}")
        self.refresh_table()

    # --- helpers ---
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
        return [c for c in self.controller.cases if q in c.case_id.lower() or q in c.patient_name.lower()]

    def refresh_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for case in self.get_filtered_cases():
            self.tree.insert("", "end", values=(case.case_id, case.patient_name, case.date, case.status, len(case.series_paths)))

    # --- actions ---
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
        # trimite „existing_ids” fără ID-ul curent (poate rămâne la fel)
        ids = self._existing_ids() - {case.case_id}
        dlg = CaseDialog(self, title="Edit Case", case=case, existing_ids=ids)
        self.wait_window(dlg)
        if dlg.result:
            # updatăm în loc
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
