from tkinter import messagebox

import customtkinter as ctk
import requests

from bouncer import WindowsBouncer
from exam_view import ActiveExamFrame
from login_view import LoginFrame


class ProctorIDEKiosk(ctk.CTk):

    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.title("Proctor IDE Secure Kiosk")

        self.violation_count = 0
        self.is_gui_testing = False
        self.bouncer = WindowsBouncer(logger=print)

        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)

        self.bind("<Escape>", self.debug_close)

        self.bind("<FocusOut>", self.handle_focus_out)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        container = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        container.grid(row=0, column=0, sticky="nsew", padx=24, pady=24)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self.frames = {}

        for frame_class in (LoginFrame, ActiveExamFrame):
            frame = frame_class(parent=container, controller=self)
            self.frames[frame_class.__name__] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame("LoginFrame")

    def show_frame(self, frame_name):
        frame = self.frames[frame_name]
        frame.tkraise()

    def handle_focus_out(self, event):
        if self.is_gui_testing:
            return

        if event.widget != self:
            return

        self.violation_count += 1
        print(
            "VIOLATION DETECTED: User attempted to switch windows! "
            f"Total strikes: {self.violation_count}"
        )

    def debug_close(self, event=None):
        try:
            self.ensure_lockdown_released()
            print("Debug shortcut used: closing Proctor IDE kiosk.")
        finally:
            self.destroy()

    def destroy(self):
        if "ActiveExamFrame" in self.frames:
            self.frames["ActiveExamFrame"].stop_process()
        super().destroy()

    def ensure_lockdown_engaged(self):
        if self.bouncer.engage_lockdown():
            print("Mock lockdown is now active for the exam session.")

    def ensure_lockdown_released(self):
        if self.bouncer.release_lockdown():
            print("Mock lockdown has been released.")

    def authenticate_user(self, subject_code, roll_number, session_pin):
        print(f"Attempting to login with Roll: {roll_number}...")

        api_url = "http://127.0.0.1:8000/api/login/"
        payload = {
            "subject_code": subject_code,
            "roll_number": roll_number,
            "session_pin": session_pin,
        }

        try:
            response = requests.post(api_url, json=payload, timeout=5)

            if response.status_code == 200:
                data = response.json()
                print(f"Login Successful! Welcome {data['student_name']}")

                real_duration = data["exam"]["duration_seconds"]
                self.frames["ActiveExamFrame"].remaining_seconds = real_duration
                self.frames["ActiveExamFrame"].timer_label.configure(
                    text=self.frames["ActiveExamFrame"].format_time(real_duration)
                )

                self.ensure_lockdown_engaged()
                self.show_frame("ActiveExamFrame")

            elif response.status_code == 401:
                messagebox.showerror(
                    "Access Denied",
                    "Invalid Roll Number or Session PIN.",
                )
            elif response.status_code == 404:
                messagebox.showerror("No Exam", "There is no active exam right now.")
            else:
                messagebox.showerror(
                    "Server Error",
                    f"Unexpected error: {response.status_code}",
                )

        except requests.exceptions.ConnectionError:
            messagebox.showerror(
                "Network Error",
                "Could not connect to Proctor IDE Server. Is it running?",
            )
        except requests.exceptions.Timeout:
            messagebox.showerror("Timeout", "The server took too long to respond.")

    def submit_exam(self):
        roll_number = self.frames["LoginFrame"].roll_number_var.get()
        strikes = self.violation_count

        exam_frame = self.frames["ActiveExamFrame"]
        combined_code = ""
        for filename, textbox in exam_frame.files.items():
            file_content = textbox.get("1.0", "end-1c")
            combined_code += f"----- {filename} -----\n{file_content}\n\n"

        print("Uploading multi-file submission to Django server...")

        api_url = "http://127.0.0.1:8000/api/submit/"
        payload = {
            "roll_number": roll_number,
            "code_content": combined_code,
            "violation_count": strikes,
        }

        submitted_successfully = False
        try:
            response = requests.post(api_url, json=payload, timeout=5)

            if response.status_code == 200:
                print("Exam successfully saved to database!")
                submitted_successfully = True
                messagebox.showinfo(
                    "Success",
                    "Your exam has been submitted safely. You may now leave the lab.",
                )
            else:
                messagebox.showerror(
                    "Upload Failed",
                    f"Server responded with: {response.text}",
                )

        except requests.exceptions.RequestException as error:
            messagebox.showerror(
                "Network Error",
                "Failed to upload exam. Please call an invigilator.\n"
                f"Error: {error}",
            )

        if submitted_successfully:
            self.ensure_lockdown_released()
            self.destroy()


if __name__ == "__main__":
    app = ProctorIDEKiosk()
    app.mainloop()
