import tkinter as tk
from tkinter import messagebox


class LoginFrame(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        tk.Label(self, text="Login", font=("Arial", 18)).pack(pady=20)

        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()

        form = tk.Frame(self)
        form.pack()

        tk.Label(form, text="Username:").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        tk.Entry(form, textvariable=self.username_var).grid(row=0, column=1)

        tk.Label(form, text="Password:").grid(row=1, column=0, sticky="e", padx=4, pady=4)
        tk.Entry(form, show="*", textvariable=self.password_var).grid(row=1, column=1)

        tk.Button(self, text="Login", command=self.login).pack(pady=12)

    def login(self):
        username = self.username_var.get().strip()
        if not username:
            messagebox.showerror("Error", "Enter a username")
            return

        if username.lower().startswith("r"):
            role = "Radiologist"
        elif username.lower().startswith("a"):
            role = "Annotator"
        else:
            role = "Admin"

        self.controller.current_user_role = role
        self.controller.show_frame("CasesFrame")
