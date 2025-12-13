import tkinter as tk
from tkinter import ttk, messagebox


class LoginFrame(tk.Frame):
    """
    Dark, modern login with a centered, responsive card.
    The card stays perfectly centered and its width adapts to window size.
    """
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        # ---------- Styles ----------
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Palette
        PRIMARY = "#0ea5e9"   # cyan-500
        BG       = "#0b1220"  # slate-950
        CARD_BG  = "#0f172a"  # slate-900
        FG       = "#e5e7eb"  # gray-200
        MUTED    = "#94a3b8"  # gray-400
        FIELD_BG = "#111827"  # gray-900
        BORDER   = "#1f2937"  # slate-800

        style.configure("App.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("Title.TLabel", background=CARD_BG, foreground=FG, font=("Segoe UI", 22, "bold"))
        style.configure("Sub.TLabel",   background=CARD_BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("Field.TLabel", background=CARD_BG, foreground=FG, font=("Segoe UI", 10, "bold"))

        # ttk.Entry styling (clam supports these options)
        style.configure("TEntry",
                        fieldbackground=FIELD_BG, foreground=FG,
                        insertcolor=FG, bordercolor=BORDER, padding=8)
        style.map("TEntry",
                  fieldbackground=[("disabled", "#1f2937"), ("!disabled", FIELD_BG)],
                  bordercolor=[("focus", PRIMARY), ("!focus", BORDER)])

        # Buttons
        style.configure("Accent.TButton", background=PRIMARY, foreground="#0b1220",
                        padding=10, borderwidth=0)
        style.map("Accent.TButton",
                  background=[("active", "#22d3ee"), ("!active", PRIMARY)],
                  foreground=[("disabled", "#cbd5e1"), ("!disabled", "#0b1220")])

        style.configure("Ghost.TButton", background=CARD_BG, foreground=MUTED,
                        padding=(12, 8), borderwidth=0)
        style.map("Ghost.TButton",
                  background=[("active", "#111827")],
                  foreground=[("active", FG), ("!active", MUTED)])

        # ---------- Root layout (fills entire page) ----------
        root = ttk.Frame(self, style="App.TFrame")
        root.pack(fill="both", expand=True)

        # Responsive, centered card
        self.card = ttk.Frame(root, style="Card.TFrame", padding=24)
        # Start centered; width will be updated in _on_resize
        self.card.place(relx=0.5, rely=0.5, anchor="c", width=520)

        # Keep card centered & responsive on window resize
        root.bind("<Configure>", self._on_resize)
        self.after(10, self._on_resize)  # run once after initial draw

        # ---------- Card content ----------
        ttk.Label(self.card, text="Lung Cancer Viewer", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.card, text="Sign in to continue", style="Sub.TLabel").pack(anchor="w", pady=(0, 12))

        form = ttk.Frame(self.card, style="Card.TFrame")
        form.pack(fill="x")

        # Username
        ttk.Label(form, text="Username", style="Field.TLabel").grid(row=0, column=0, sticky="w", pady=(2, 2))
        self.username_var = tk.StringVar()
        self.username_entry = ttk.Entry(form, textvariable=self.username_var)
        self.username_entry.grid(row=1, column=0, sticky="ew")
        form.grid_columnconfigure(0, weight=1)

        # Password with better eye toggle
        ttk.Label(form, text="Password", style="Field.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 2))

        pw_row = ttk.Frame(form, style="Card.TFrame")
        pw_row.grid(row=3, column=0, sticky="ew")
        pw_row.grid_columnconfigure(0, weight=1)

        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(pw_row, textvariable=self.password_var, show="•")
        self.password_entry.grid(row=0, column=0, sticky="ew")

        # Flat eye toggle that visually aligns with the entry
        self._pw_hidden = True
        self.eye_btn = ttk.Button(pw_row, text="👁  Show", width=10,
                                  style="Ghost.TButton", command=self._toggle_pw)
        self.eye_btn.grid(row=0, column=1, padx=(8, 0), sticky="e")

        # Login button
        ttk.Button(self.card, text="Log in", style="Accent.TButton", command=self.login)\
            .pack(fill="x", pady=(16, 8))

        # Hint
        ttk.Label(
            self.card,
            text="Tip: usernames starting with 'r' or 'a' map to Radiologist/Annotator.",
            style="Sub.TLabel",
        ).pack(anchor="w")

        # Keyboard: Enter submits; focus username
        self.bind_all("<Return>", lambda e: self.login())
        self.after(100, lambda: self.username_entry.focus_set())

    # ---------- Responsive behavior ----------
    def _on_resize(self, event=None):
        """Keep the card perfectly centered and scale width with window size."""
        w = max(self.winfo_width(), 380)
        # target width ≈ 40% of window; clamp for readability
        target_w = max(380, min(int(w * 0.40), 760))
        self.card.place_configure(relx=0.5, rely=0.5, anchor="c", width=target_w)

    # ---------- UI actions ----------
    def _toggle_pw(self):
        self._pw_hidden = not self._pw_hidden
        self.password_entry.configure(show="•" if self._pw_hidden else "")
        self.eye_btn.configure(text=("👁  Show" if self._pw_hidden else "🙈  Hide"))

    def login(self):
        username = self.username_var.get().strip()
        if not username:
            messagebox.showerror("Error", "Enter a username")
            self.username_entry.focus_set()
            return

        if username.lower().startswith("r"):
            role = "Radiologist"
        elif username.lower().startswith("a"):
            role = "Annotator"
        else:
            role = "Admin"

        self.controller.current_user_role = role
        self.controller.show_frame("CasesFrame")
