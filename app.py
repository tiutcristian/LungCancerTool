import tkinter as tk
from ui.login_frame import LoginFrame
from ui.cases_frame import CasesFrame
from ui.viewer_frame import ViewerFrame
from backend_mock import get_initial_cases


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Lung Cancer Viewer - MVP")
        self.geometry("1100x650")

        self.current_user_role = None
        self.cases = get_initial_cases()   # list[Case]
        self.current_case = None

        container = tk.Frame(self)
        container.pack(fill="both", expand=True)

        self.frames = {}
        for F in (LoginFrame, CasesFrame, ViewerFrame):
            frame = F(parent=container, controller=self)
            self.frames[F.__name__] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame("LoginFrame")

    def show_frame(self, name: str):
        frame = self.frames[name]
        frame.tkraise()
        if hasattr(frame, "on_show"):
            frame.on_show()


if __name__ == "__main__":
    app = App()
    app.mainloop()
