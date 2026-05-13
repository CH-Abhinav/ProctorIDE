from tkinter import messagebox

import customtkinter as ctk
import requests

from bouncer import WindowsBouncer
from exam_view import ActiveExamFrame
from login_view import LoginFrame


class EduSyncKiosk(ctk.CTk):
    """
    Main application window for the EduSync secure exam kiosk.

    The root window owns shared state, screen navigation, API actions,
    and the mock lockdown lifecycle.
    """

    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()

        # Basic window metadata.
        self.title("EduSync Secure Kiosk")

        # Tracks how many times the user attempts to leave the kiosk window.
        self.violation_count = 0
        self.is_gui_testing = False
        self.bouncer = WindowsBouncer(logger=print)

        # Configure the kiosk-like behavior requested in the spec.
        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)

        # Secret debug exit:
        # Pressing Escape will immediately close the app.
        self.bind("<Escape>", self.debug_close)

        # Security tripwire:
        # Whenever this root window loses focus, handle_focus_out will run.
        self.bind("<FocusOut>", self.handle_focus_out)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Container frame:
        # This is where all "screens" live.
        # We stack frames in the same grid cell and raise the one we want.
        container = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        container.grid(row=0, column=0, sticky="nsew", padx=24, pady=24)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        # Dictionary used to store each screen/frame instance.
        self.frames = {}

        # Create all screens up front so they can be swapped instantly.
        for frame_class in (LoginFrame, ActiveExamFrame):
            frame = frame_class(parent=container, controller=self)
            self.frames[frame_class.__name__] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        # Start by showing the login screen.
        self.show_frame("LoginFrame")

    def show_frame(self, frame_name):
        """
        Bring the requested frame to the front.
        """
        frame = self.frames[frame_name]
        frame.tkraise()

    def handle_focus_out(self, event):
        """
        Called automatically when the main window loses focus.
        """
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
        """
        Hidden developer shortcut to exit the kiosk.
        """
        try:
            self.ensure_lockdown_released()
            print("Debug shortcut used: closing EduSync kiosk.")
        finally:
            self.destroy()

    def destroy(self):
        """
        Stop any running student process before tearing down the UI.
        """
        if "ActiveExamFrame" in self.frames:
            self.frames["ActiveExamFrame"].stop_process()
        super().destroy()

    def ensure_lockdown_engaged(self):
        """
        Enter mock lockdown once the exam session begins.
        """
        if self.bouncer.engage_lockdown():
            print("Mock lockdown is now active for the exam session.")

    def ensure_lockdown_released(self):
        """
        Leave mock lockdown before the kiosk exits or returns control.
        """
        if self.bouncer.release_lockdown():
            print("Mock lockdown has been released.")

    def authenticate_user(self, roll_number, session_pin):
        """
        Real API Call: Sends credentials to the Django backend.
        """
        print(f"Attempting to login with Roll: {roll_number}...")

        # The URL of your Django API we just built
        api_url = "http://127.0.0.1:8000/api/login/"
        payload = {
            "roll_number": roll_number,
            "session_pin": session_pin,
        }

        try:
            # Send the data to Django
            response = requests.post(api_url, json=payload, timeout=5)

            # If Django says "200 OK"
            if response.status_code == 200:
                data = response.json()
                print(f"Login Successful! Welcome {data['student_name']}")

                # Grab the real exam duration from the database and update the timer!
                real_duration = data["exam"]["duration_seconds"]
                self.frames["ActiveExamFrame"].remaining_seconds = real_duration
                self.frames["ActiveExamFrame"].timer_label.configure(
                    text=self.frames["ActiveExamFrame"].format_time(real_duration)
                )

                # Lock the system and start the exam
                self.ensure_lockdown_engaged()
                self.show_frame("ActiveExamFrame")

            # Handle the specific errors we wrote in our Django views.py
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

        # Handle cases where the Django server is turned off or crashed
        except requests.exceptions.ConnectionError:
            messagebox.showerror(
                "Network Error",
                "Could not connect to EduSync Server. Is it running?",
            )
        except requests.exceptions.Timeout:
            messagebox.showerror("Timeout", "The server took too long to respond.")

    def submit_exam(self):
        """
        Real API Call: Sends the student's code and violation count back to Django.
        Bundles all open tabs into a single submission string.
        """
        # 1. Gather the data from the UI
        roll_number = self.frames["LoginFrame"].roll_number_var.get()
        strikes = self.violation_count

        # Bundle all files into one formatted string for the backend.
        exam_frame = self.frames["ActiveExamFrame"]
        combined_code = ""
        for filename, textbox in exam_frame.files.items():
            file_content = textbox.get("1.0", "end-1c")
            combined_code += f"----- {filename} -----\n{file_content}\n\n"

        print("Uploading multi-file submission to Django server...")

        # 2. Prepare the payload
        api_url = "http://127.0.0.1:8000/api/submit/"
        payload = {
            "roll_number": roll_number,
            "code_content": combined_code,
            "violation_count": strikes,
        }

        # 3. Send it to the backend
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

        # 4. Release the OS lockdown only after a confirmed submission.
        if submitted_successfully:
            self.ensure_lockdown_released()
            self.destroy()


if __name__ == "__main__":
    app = EduSyncKiosk()
    app.mainloop()
