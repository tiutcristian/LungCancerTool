import tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import dataclass
import random

# ---------- Models & mock backend ----------

@dataclass
class Case:
    case_id: str
    patient_name: str
    date: str
    status: str

def get_initial_cases():
    return [
        Case("LC-001", "John Doe", "2025-10-01", "Unsegmented"),
        Case("LC-002", "Jane Smith", "2025-10-03", "Segmented"),
    ]

def mock_run_ai(case: Case):
    biomarkers = [
        {"name": "Malignancy probability", "value": random.uniform(0.3, 0.95)},
        {"name": "Lymph node involvement", "value": random.uniform(0.1, 0.8)},
        {"name": "Metastasis risk", "value": random.uniform(0.05, 0.7)},
    ]
    explanation = (
        f"(Mock) For case {case.case_id}, higher malignancy probability "
        "is driven by nodule size, upper-lobe location and spiculation."
    )
    return {"biomarkers": biomarkers, "explanation": explanation, "has_heatmap": True}

# ---------- Tkinter app ----------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Lung Cancer Viewer - MVP")
        self.geometry("1000x600")

        self.current_user_role = None
        self.cases = get_initial_cases()
        self.current_case = None

        container = tk.Frame(self)
        container.pack(fill="both", expand=True)

        self.frames = {}
        for F in (LoginFrame, CasesFrame, ViewerFrame):
            frame = F(parent=container, controller=self)
            self.frames[F.__name__] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame("LoginFrame")

    def show_frame(self, name):
        frame = self.frames[name]
        frame.tkraise()
        if hasattr(frame, "on_show"):
            frame.on_show()

class LoginFrame(tk.Frame):
    def __init__(self, parent, controller: App):
        super().__init__(parent)
        self.controller = controller

        tk.Label(self, text="Login", font=("Arial", 18)).pack(pady=20)

        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()

        form = tk.Frame(self)
        form.pack()

        tk.Label(form, text="Username:").grid(row=0, column=0, sticky="e")
        tk.Entry(form, textvariable=self.username_var).grid(row=0, column=1)

        tk.Label(form, text="Password:").grid(row=1, column=0, sticky="e")
        tk.Entry(form, show="*", textvariable=self.password_var).grid(row=1, column=1)

        tk.Button(self, text="Login", command=self.login).pack(pady=10)

    def login(self):
        username = self.username_var.get().strip()
        if not username:
            messagebox.showerror("Error", "Enter a username")
            return
        # Mock: if username starts with 'r' -> Radiologist, etc.
        if username.lower().startswith("r"):
            role = "Radiologist"
        elif username.lower().startswith("a"):
            role = "Annotator"
        else:
            role = "Admin"

        self.controller.current_user_role = role
        self.controller.show_frame("CasesFrame")

class CasesFrame(tk.Frame):
    def __init__(self, parent, controller: App):
        super().__init__(parent)
        self.controller = controller

        top = tk.Frame(self)
        top.pack(fill="x", pady=5)

        self.role_label = tk.Label(top, text="Role: ?")
        self.role_label.pack(side="left", padx=10)

        tk.Label(top, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        tk.Entry(top, textvariable=self.search_var).pack(side="left")
        tk.Button(top, text="Apply", command=self.refresh_table).pack(side="left", padx=5)

        btns = tk.Frame(self)
        btns.pack(fill="x", pady=5)
        tk.Button(btns, text="Add Case", command=self.add_case).pack(side="left")
        tk.Button(btns, text="Edit Case", command=self.edit_case).pack(side="left")
        tk.Button(btns, text="Delete Case", command=self.delete_case).pack(side="left")
        tk.Button(btns, text="Open Viewer", command=self.open_viewer).pack(side="left")

        columns = ("id", "patient", "date", "status")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=col.capitalize())
        self.tree.pack(fill="both", expand=True)

    def on_show(self):
        self.role_label.config(text=f"Role: {self.controller.current_user_role}")
        self.refresh_table()

    def get_filtered_cases(self):
        q = self.search_var.get().lower().strip()
        if not q:
            return self.controller.cases
        return [
            c for c in self.controller.cases
            if q in c.case_id.lower() or q in c.patient_name.lower()
        ]

    def refresh_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for case in self.get_filtered_cases():
            self.tree.insert("", "end", values=(case.case_id, case.patient_name, case.date, case.status))

    def add_case(self):
        new_id = f"LC-{len(self.controller.cases)+1:03d}"
        case = Case(new_id, "New Patient", "2025-11-05", "Unsegmented")
        self.controller.cases.append(case)
        self.refresh_table()

    def get_selected_case(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select a case first")
            return None
        values = self.tree.item(sel[0], "values")
        case_id = values[0]
        for c in self.controller.cases:
            if c.case_id == case_id:
                return c
        return None

    def edit_case(self):
        case = self.get_selected_case()
        if not case:
            return
        # Simple: toggle status for now
        case.status = "Segmented" if case.status != "Segmented" else "Reported"
        self.refresh_table()

    def delete_case(self):
        case = self.get_selected_case()
        if not case:
            return
        self.controller.cases.remove(case)
        self.refresh_table()

    def open_viewer(self):
        case = self.get_selected_case()
        if not case:
            return
        self.controller.current_case = case
        self.controller.show_frame("ViewerFrame")

class ViewerFrame(tk.Frame):
    def __init__(self, parent, controller: App):
        super().__init__(parent)
        self.controller = controller

        top = tk.Frame(self)
        top.pack(fill="x")
        self.case_label = tk.Label(top, text="Case: -")
        self.case_label.pack(side="left", padx=10)

        tk.Button(top, text="Back", command=lambda: controller.show_frame("CasesFrame")).pack(side="right")

        middle = tk.Frame(self)
        middle.pack(fill="both", expand=True)

        # Left: fake series list
        left = tk.Frame(middle)
        left.pack(side="left", fill="y", padx=5, pady=5)
        tk.Label(left, text="Series").pack()
        self.series_list = tk.Listbox(left, height=5)
        self.series_list.insert("end", "Series 1", "Series 2")
        self.series_list.pack()

        # Center: placeholder viewer
        center = tk.Frame(middle, bg="black")
        center.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        self.viewer_label = tk.Label(center, text="[CT slice placeholder]", fg="white", bg="black")
        self.viewer_label.pack(expand=True)

        # Right: results panel
        right = tk.Frame(middle)
        right.pack(side="left", fill="y", padx=5, pady=5)

        tk.Label(right, text="Biomarkers", font=("Arial", 12, "bold")).pack(pady=5)
        self.biomarker_frame = tk.Frame(right)
        self.biomarker_frame.pack()

        tk.Button(right, text="Run AI", command=self.run_ai).pack(pady=5)

        tk.Label(right, text="Explanation").pack()
        self.explanation_text = tk.Text(right, width=30, height=10)
        self.explanation_text.pack()

    def on_show(self):
        c = self.controller.current_case
        self.case_label.config(text=f"Case: {c.case_id} | {c.patient_name}")
        self.explanation_text.delete("1.0", "end")
        for w in self.biomarker_frame.winfo_children():
            w.destroy()

    def run_ai(self):
        case = self.controller.current_case
        result = mock_run_ai(case)

        # Update biomarkers
        for w in self.biomarker_frame.winfo_children():
            w.destroy()
        for bm in result["biomarkers"]:
            row = tk.Frame(self.biomarker_frame)
            row.pack(fill="x")
            tk.Label(row, text=bm["name"]).pack(anchor="w")
            pb = ttk.Progressbar(row, maximum=1.0)
            pb["value"] = bm["value"]
            pb.pack(fill="x")

        # Update explanation
        self.explanation_text.delete("1.0", "end")
        self.explanation_text.insert("end", result["explanation"])

        # Simulate heatmap: change label text
        self.viewer_label.config(text="[CT slice + heatmap overlay (mock)]")

if __name__ == "__main__":
    app = App()
    app.mainloop()