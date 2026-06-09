import os
import shutil
import tempfile

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
            workspace_dir = self.frames["ActiveExamFrame"].WORKSPACE_DIR
            if os.path.exists(workspace_dir):
                try:
                    shutil.rmtree(workspace_dir)
                    print("Workspace completely wiped.")
                except OSError as error:
                    print(f"Failed to wipe workspace: {error}")
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
                self.session_token = data.get("session_token", "")

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
        session_token = getattr(self, "session_token", "")

        exam_frame = self.frames["ActiveExamFrame"]

        exam_frame.sync_files_to_workspace()

        print("Uploading multi-file submission to Django server...")

        workspace_dir = os.path.abspath(exam_frame.WORKSPACE_DIR)
        archive_base = os.path.join(tempfile.gettempdir(), "submission")
        archive_path = shutil.make_archive(archive_base, "zip", workspace_dir)
        submitted_successfully = False

        try:
            api_url = "http://127.0.0.1:8000/api/submit/"
            data = {
                "roll_number": roll_number,
                "violation_count": strikes,
                "session_token": session_token,
            }

            with open(archive_path, "rb") as archive_file:
                files = {"file": ("submission.zip", archive_file, "application/zip")}
                response = requests.post(
                    api_url,
                    data=data,
                    files=files,
                    timeout=5,
                )

            if response.status_code == 200:
                print("Exam successfully saved to database!")
                submitted_successfully = True
                try:
                    if os.path.isdir(workspace_dir):
                        shutil.rmtree(workspace_dir)
                    os.makedirs(workspace_dir, exist_ok=True)
                except OSError as cleanup_error:
                    print(f"Workspace cleanup failed: {cleanup_error}")
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

        finally:
            try:
                os.remove(archive_path)
            except OSError:
                pass

        if submitted_successfully:
            self.ensure_lockdown_released()
            self.destroy()


if __name__ == "__main__":
    app = ProctorIDEKiosk()
    app.mainloop()
