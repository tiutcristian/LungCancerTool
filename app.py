import tkinter as tk
from ui.login_frame import LoginFrame
from ui.cases_frame import CasesFrame
from ui.viewer_frame import ViewerFrame
from logic.backend import get_initial_cases
from logic.mongo_db import MongoDB


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Lung Cancer Viewer - MVP")
        self.geometry("1100x650")
        self._db = MongoDB()

        # App state
        self.current_user_role = None
        self.cases = get_initial_cases()
        self.current_case = None

        # Main container that hosts all pages
        container = tk.Frame(self)
        container.pack(fill="both", expand=True)

        # Make the single grid cell stretch to full window
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        # Pages
        self.frames = {}
        for F in (LoginFrame, CasesFrame, ViewerFrame):
            frame = F(parent=container, controller=self)
            self.frames[F.__name__] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame("LoginFrame")

        # Start maximized so login fills the screen
        self.after(50, self._maximize)

    def get_initial_cases(self):
        return self._db.list_cases()

    def _maximize(self):
        try:
            self.state("zoomed")                 # Windows
        except Exception:
            try:
                self.attributes("-zoomed", True)  # some Linux WMs
            except Exception:
                pass

    def show_frame(self, name: str):
        frame = self.frames[name]
        frame.tkraise()
        if hasattr(frame, "on_show"):
            frame.on_show()


if __name__ == "__main__":
    app = App()
    app._db.clean_cache(max_age_seconds=7 * 24 * 60 * 60)
    app.mainloop()
