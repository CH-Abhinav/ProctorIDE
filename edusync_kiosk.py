import os
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from bouncer import WindowsBouncer


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
        self.ensure_lockdown_released()
        print("Debug shortcut used: closing EduSync kiosk.")
        self.destroy()

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
        import requests

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
        import requests
        from tkinter import messagebox

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
        try:
            response = requests.post(api_url, json=payload, timeout=5)

            if response.status_code == 200:
                print("Exam successfully saved to database!")
                messagebox.showinfo(
                    "Success",
                    "Your exam has been submitted safely. You may now leave the lab.",
                )
            else:
                messagebox.showerror(
                    "Upload Failed",
                    f"Server responded with: {response.text}",
                )

        except requests.exceptions.RequestException as e:
            messagebox.showerror(
                "Network Error",
                "Failed to upload exam. Please call an invigilator.\n"
                f"Error: {e}",
            )

        # 4. Release the OS lockdown and kill the app
        self.ensure_lockdown_released()
        self.destroy()


class LoginFrame(ctk.CTkFrame):
    """
    First screen shown to the user.

    This frame is responsible only for collecting login details and asking
    the main controller (EduSyncKiosk) to authenticate.
    """

    def __init__(self, parent, controller):
        super().__init__(parent, corner_radius=20, fg_color="#101826")
        self.controller = controller

        # Tkinter StringVar objects make it easy to read entry values later.
        self.roll_number_var = tk.StringVar()
        self.session_pin_var = tk.StringVar()

        # Center the login card within the frame.
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        card = ctk.CTkFrame(
            self,
            width=520,
            corner_radius=24,
            fg_color="#182235",
            border_width=1,
            border_color="#2a3954",
        )
        card.grid(row=0, column=0, padx=24, pady=24)
        card.grid_columnconfigure(0, weight=1)

        title_label = ctk.CTkLabel(
            card,
            text="EduSync Secure Kiosk",
            font=ctk.CTkFont(family="Segoe UI", size=30, weight="bold"),
            text_color="#f8fafc",
        )
        title_label.grid(row=0, column=0, pady=(32, 10), padx=32, sticky="w")

        subtitle_label = ctk.CTkLabel(
            card,
            text="Authenticate to begin your protected exam session.",
            font=ctk.CTkFont(family="Segoe UI", size=14),
            text_color="#94a3b8",
        )
        subtitle_label.grid(row=1, column=0, pady=(0, 28), padx=32, sticky="w")

        roll_label = ctk.CTkLabel(
            card,
            text="Roll Number",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#cbd5e1",
        )
        roll_label.grid(row=2, column=0, sticky="w", pady=(0, 8), padx=32)

        roll_entry = ctk.CTkEntry(
            card,
            textvariable=self.roll_number_var,
            width=420,
            height=44,
            corner_radius=12,
            font=ctk.CTkFont(family="Segoe UI", size=14),
            placeholder_text="Enter your roll number",
        )
        roll_entry.grid(row=3, column=0, sticky="ew", pady=(0, 18), padx=32)

        pin_label = ctk.CTkLabel(
            card,
            text="Session PIN",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#cbd5e1",
        )
        pin_label.grid(row=4, column=0, sticky="w", pady=(0, 8), padx=32)

        pin_entry = ctk.CTkEntry(
            card,
            textvariable=self.session_pin_var,
            width=420,
            height=44,
            corner_radius=12,
            font=ctk.CTkFont(family="Segoe UI", size=14),
            placeholder_text="Enter the invigilator PIN",
            show="*",
        )
        pin_entry.grid(row=5, column=0, sticky="ew", pady=(0, 28), padx=32)

        login_button = ctk.CTkButton(
            card,
            text="Login",
            height=46,
            corner_radius=14,
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            command=self.on_login_clicked,
        )
        login_button.grid(row=6, column=0, sticky="ew", padx=32, pady=(0, 32))

        # Set initial cursor focus so the user can start typing immediately.
        roll_entry.focus_set()

        # Optional convenience: pressing Enter inside either field triggers login.
        roll_entry.bind("<Return>", lambda event: self.on_login_clicked())
        pin_entry.bind("<Return>", lambda event: self.on_login_clicked())

    def on_login_clicked(self):
        """
        Read the current values from the entry fields and forward them to the
        controller. The frame does not authenticate by itself.
        """
        self.controller.authenticate_user(
            self.roll_number_var.get(),
            self.session_pin_var.get(),
        )


class ActiveExamFrame(ctk.CTkFrame):
    """
    Screen shown after successful login.

    This screen provides a multi-file IDE layout inspired by VS Code while
    preserving the kiosk execution and terminal workflow.
    """

    def __init__(self, parent, controller):
        super().__init__(parent, corner_radius=20, fg_color="#0f172a")
        self.controller = controller
        self.current_process = None
        self.current_temp_dir = None

        # Stores every open file editor textbox.
        # Example: {"main.py": <CTkTextbox>, "utils.py": <CTkTextbox>}
        self.files = {}
        self.file_buttons = {}
        self.active_filename = None
        self.primary_filename = "main.py"
        self.terminal_buffer = ""
        self.is_flushing = False
        self.active_streams = 0
        self.terminal_buffer_lock = threading.Lock()
        self.stream_state_lock = threading.Lock()

        # Glue placeholder:
        # In the real product, this initial duration will eventually come from
        # a Django API payload for the specific exam session.
        self.remaining_seconds = 7200

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        content = ctk.CTkFrame(
            self,
            corner_radius=24,
            fg_color="#111827",
            border_width=1,
            border_color="#23314d",
        )
        content.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(2, weight=1)

        menu_bar = ctk.CTkFrame(content, fg_color="transparent", height=28)
        menu_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        menu_bar.grid_propagate(False)

        self.file_menu = tk.Menu(
            self,
            tearoff=0,
            bg="#1e293b",
            fg="white",
            bd=0,
            activebackground="#2563eb",
            activeforeground="white",
        )
        self.file_menu.add_command(label="New File", command=self.prompt_new_file)
        self.file_menu.add_command(
            label="Submit Exam",
            command=self.controller.submit_exam,
        )

        self.edit_menu = tk.Menu(
            self,
            tearoff=0,
            bg="#1e293b",
            fg="white",
            bd=0,
            activebackground="#2563eb",
            activeforeground="white",
        )
        self.edit_menu.add_command(label="Undo", command=self.undo_active_editor)
        self.edit_menu.add_command(label="Redo", command=self.redo_active_editor)

        file_button = ctk.CTkButton(
            menu_bar,
            text="File",
            width=36,
            height=24,
            corner_radius=6,
            fg_color="transparent",
            hover_color="#182235",
            text_color="#cbd5e1",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            command=lambda: self.post_dropdown_menu(self.file_menu, file_button),
        )
        file_button.pack(side="left", padx=(0, 6))
        file_button.bind(
            "<Button-1>",
            lambda event: self.post_dropdown_menu(self.file_menu, file_button),
        )

        edit_button = ctk.CTkButton(
            menu_bar,
            text="Edit",
            width=36,
            height=24,
            corner_radius=6,
            fg_color="transparent",
            hover_color="#182235",
            text_color="#cbd5e1",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            command=lambda: self.post_dropdown_menu(self.edit_menu, edit_button),
        )
        edit_button.pack(side="left", padx=(0, 6))
        edit_button.bind(
            "<Button-1>",
            lambda event: self.post_dropdown_menu(self.edit_menu, edit_button),
        )

        action_header = ctk.CTkFrame(
            content,
            corner_radius=14,
            fg_color="#0f172a",
            border_width=1,
            border_color="#23314d",
        )
        action_header.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))
        action_header.grid_columnconfigure(0, weight=1)
        action_header.grid_columnconfigure(1, weight=1)
        action_header.grid_columnconfigure(2, weight=1)

        self.student_label = ctk.CTkLabel(
            action_header,
            text="Student: Abhinav",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#cbd5e1",
            anchor="w",
        )
        self.student_label.grid(row=0, column=0, sticky="w", padx=16, pady=12)

        action_center = ctk.CTkFrame(action_header, fg_color="transparent")
        action_center.grid(row=0, column=1)

        run_button = ctk.CTkButton(
            action_center,
            text="\u25b6 Run",
            width=92,
            height=34,
            corner_radius=10,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            command=self.run_code,
        )
        run_button.pack(side="left", padx=(0, 8))

        submit_button = ctk.CTkButton(
            action_center,
            text="Submit Exam",
            width=120,
            height=34,
            corner_radius=10,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self.controller.submit_exam,
        )
        submit_button.pack(side="left")

        action_right = ctk.CTkFrame(action_header, fg_color="transparent")
        action_right.grid(row=0, column=2, sticky="e", padx=16)

        self.timer_label = ctk.CTkLabel(
            action_right,
            text=self.format_time(self.remaining_seconds),
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#e2e8f0",
        )
        self.timer_label.pack(side="left", padx=(0, 12))

        emergency_exit_button = ctk.CTkButton(
            action_right,
            text="Emergency Exit",
            fg_color="transparent",
            border_color="#ef4444",
            border_width=1,
            text_color="#ef4444",
            hover_color="#7f1d1d",
            height=34,
            corner_radius=10,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            command=self.confirm_emergency_exit,
        )
        emergency_exit_button.pack(side="left")

        self.main_paned = tk.PanedWindow(
            content,
            orient="horizontal",
            bg="#0f172a",
            sashwidth=6,
            bd=0,
            relief="flat",
        )
        self.main_paned.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 20))

        sidebar_frame = ctk.CTkFrame(
            self.main_paned,
            corner_radius=16,
            fg_color="#0b1220",
            border_width=1,
            border_color="#22304a",
        )
        sidebar_frame.grid_columnconfigure(0, weight=1)
        sidebar_frame.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkScrollableFrame(
            sidebar_frame,
            width=220,
            corner_radius=12,
            fg_color="transparent",
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.sidebar.grid_columnconfigure(0, weight=1)

        explorer_label = ctk.CTkLabel(
            self.sidebar,
            text="EXPLORER",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#94a3b8",
            anchor="w",
        )
        explorer_label.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 10))

        new_file_button = ctk.CTkButton(
            self.sidebar,
            text="+ New File",
            height=32,
            corner_radius=10,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            command=self.prompt_new_file,
        )
        new_file_button.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 12))

        self.main_paned.add(sidebar_frame, minsize=150)

        self.right_paned = tk.PanedWindow(
            self.main_paned,
            orient="vertical",
            bg="#0f172a",
            sashwidth=6,
            bd=0,
            relief="flat",
        )
        self.main_paned.add(self.right_paned, minsize=360)

        editor_frame = ctk.CTkFrame(
            self.right_paned,
            corner_radius=16,
            fg_color="#0b1220",
            border_width=1,
            border_color="#22304a",
        )
        editor_frame.grid_columnconfigure(0, weight=1)
        editor_frame.grid_rowconfigure(1, weight=1)

        editor_header = ctk.CTkFrame(editor_frame, fg_color="transparent")
        editor_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        editor_header.grid_columnconfigure(1, weight=1)

        editor_label = ctk.CTkLabel(
            editor_header,
            text="EDITOR",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#94a3b8",
            anchor="w",
        )
        editor_label.grid(row=0, column=0, sticky="w")

        self.editor_title_label = ctk.CTkLabel(
            editor_header,
            text=self.primary_filename,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#e2e8f0",
            anchor="w",
        )
        self.editor_title_label.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.editor_surface = ctk.CTkFrame(
            editor_frame,
            fg_color="transparent",
        )
        self.editor_surface.grid(row=1, column=0, sticky="nsew", padx=2, pady=(0, 2))
        self.editor_surface.grid_columnconfigure(0, weight=1)
        self.editor_surface.grid_rowconfigure(0, weight=1)

        self.right_paned.add(editor_frame, minsize=200)

        terminal_frame = ctk.CTkFrame(
            self.right_paned,
            corner_radius=16,
            fg_color="#0b1220",
            border_width=1,
            border_color="#22304a",
        )
        terminal_frame.grid_columnconfigure(0, weight=1)
        terminal_frame.grid_rowconfigure(1, weight=1)

        output_label = ctk.CTkLabel(
            terminal_frame,
            text="Interactive Terminal",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color="#cbd5e1",
            anchor="w",
        )
        output_label.grid(row=0, column=0, sticky="w", padx=14, pady=(12, 8))

        self.terminal_output = ctk.CTkTextbox(
            terminal_frame,
            height=180,
            corner_radius=16,
            font=("Consolas", 12),
            fg_color="#050816",
            text_color="#22c55e",
            border_width=1,
            border_color="#1b3a2f",
        )
        self.terminal_output.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=12,
            pady=(0, 12),
        )
        self.terminal_output.configure(state="disabled")
        self.terminal_output.bind("<Return>", self.handle_terminal_enter)
        self.right_paned.add(terminal_frame, minsize=100)

        self.create_file_tab(
            self.primary_filename,
            (
                "# Write your exam solution here\n\n"
                "def main():\n"
                "    pass\n\n"
                "if __name__ == \"__main__\":\n"
                "    main()\n"
            ),
            select_tab=True,
        )
        self.update_timer()
        self.print_shell_prompt()

    def create_file_tab(self, filename, initial_content="", select_tab=True):
        """
        Create a new file editor and sidebar entry.

        Every new textbox gets the same auto-pair and auto-indent bindings so
        the editing experience stays consistent across all files.
        """
        if filename in self.files:
            if select_tab:
                self.switch_to_file(filename)
                self.files[filename].focus_set()
            return self.files[filename]

        editor = ctk.CTkTextbox(
            self.editor_surface,
            wrap="none",
            corner_radius=0,
            font=("Consolas", 14),
            fg_color="#0b1220",
            text_color="#d4d4d4",
            border_width=0,
            undo=True,
            maxundo=100,
            autoseparators=True,
        )
        editor.grid(row=0, column=0, sticky="nsew")
        editor.insert("1.0", initial_content)
        editor.bind("<KeyPress>", self.handle_editor_autopair)
        editor.bind("<Return>", self.auto_indent)
        editor.bind("<Tab>", self.insert_four_spaces)

        self.files[filename] = editor
        self.file_buttons[filename] = ctk.CTkButton(
            self.sidebar,
            text=filename,
            anchor="w",
            height=34,
            corner_radius=8,
            fg_color="transparent",
            hover_color="#1f2937",
            text_color="#cbd5e1",
            command=lambda name=filename: self.switch_to_file(name),
        )
        self.file_buttons[filename].grid(
            row=len(self.file_buttons) + 1,
            column=0,
            sticky="ew",
            padx=8,
            pady=4,
        )

        if self.active_filename is None:
            self.switch_to_file(filename)
        else:
            editor.grid_remove()
            if select_tab:
                self.switch_to_file(filename)

        if select_tab:
            editor.focus_set()
            editor.mark_set("insert", "1.0")

        return editor

    def switch_to_file(self, filename):
        """
        Hide the current editor and show the requested file editor.
        """
        if filename not in self.files:
            return

        if (
            self.active_filename is not None
            and self.active_filename in self.files
            and self.active_filename != filename
        ):
            self.files[self.active_filename].grid_remove()

        self.files[filename].grid(row=0, column=0, sticky="nsew")
        self.active_filename = filename
        self.editor_title_label.configure(text=filename)

        for file_name, button in self.file_buttons.items():
            if file_name == filename:
                button.configure(
                    fg_color="#1d4ed8",
                    hover_color="#1e40af",
                    text_color="#f8fafc",
                )
            else:
                button.configure(
                    fg_color="transparent",
                    hover_color="#1f2937",
                    text_color="#cbd5e1",
                )

    def prompt_new_file(self):
        """
        Ask the student for a filename and create a new editor entry.
        """
        dialog = ctk.CTkInputDialog(
            text="Enter the new filename (example: utils.py):",
            title="Create New File",
        )
        filename = dialog.get_input()

        if filename is None:
            return

        filename = filename.strip()
        if not filename:
            messagebox.showwarning("Invalid Filename", "Filename cannot be empty.")
            return

        if filename in self.files:
            messagebox.showwarning(
                "Duplicate Filename",
                f"A file named '{filename}' already exists.",
            )
            self.switch_to_file(filename)
            self.files[filename].focus_set()
            return

        self.create_file_tab(filename, "", select_tab=True)

    def get_active_editor(self):
        """
        Return the textbox for the currently visible file.
        """
        if self.active_filename is None:
            return None
        return self.files[self.active_filename]

    def post_dropdown_menu(self, menu, button):
        """
        Show a Tk dropdown menu aligned directly beneath its trigger button.
        """
        x_position = button.winfo_rootx()
        y_position = button.winfo_rooty() + button.winfo_height()
        menu.post(x_position, y_position)
        return "break"

    def undo_active_editor(self):
        """
        Undo the last edit in the active editor if the stack allows it.
        """
        editor = self.get_active_editor()
        if editor is None:
            return

        try:
            editor.edit_undo()
        except tk.TclError:
            pass

    def redo_active_editor(self):
        """
        Redo the last reverted edit in the active editor if possible.
        """
        editor = self.get_active_editor()
        if editor is None:
            return

        try:
            editor.edit_redo()
        except tk.TclError:
            pass

    def flush_terminal_buffer(self):
        """
        Flush accumulated process output to the terminal in timed chunks.
        """
        with self.terminal_buffer_lock:
            chunk = self.terminal_buffer
            self.terminal_buffer = ""

        if chunk:
            self.append_terminal_output(chunk)

        if self.is_flushing or self.terminal_buffer:
            self.after(50, self.flush_terminal_buffer)

    def insert_four_spaces(self, event):
        """
        Replace the default Tab behavior with four literal spaces so pressing
        Tab never jumps focus or inserts inconsistent tab characters.
        """
        event.widget.insert("insert", "    ")
        return "break"

    def format_time(self, total_seconds):
        """
        Convert raw seconds into the MM:SS format requested by the UI.
        """
        minutes, seconds = divmod(max(total_seconds, 0), 60)
        return f"{minutes:02d}:{seconds:02d}"

    def update_timer(self):
        """
        Countdown loop for the exam timer.
        """
        self.timer_label.configure(text=self.format_time(self.remaining_seconds))

        if self.remaining_seconds > 0:
            self.remaining_seconds -= 1
            self.after(1000, self.update_timer)

    def append_terminal_output(self, message):
        """
        Safely write text into the terminal widget from the Tk thread.
        """
        self.terminal_output.configure(state="normal")
        self.terminal_output.insert("end", message)
        self.terminal_output.mark_set("input_start", "end-1c")
        self.terminal_output.mark_gravity("input_start", "left")
        self.terminal_output.see("end")
        if self.current_process is None:
            self.terminal_output.configure(state="disabled")

    def schedule_terminal_append(self, message):
        """
        Marshal terminal writes from worker threads onto the UI thread.
        """
        self.after(0, lambda: self.append_terminal_output(message))

    def print_shell_prompt(self):
        """
        Show the EduSync shell prompt and prepare the terminal for input.
        """
        self.terminal_output.configure(state="normal")
        self.terminal_output.insert("end", "\nedusync> ")
        self.terminal_output.mark_set("input_start", "end-1c")
        self.terminal_output.mark_gravity("input_start", "left")
        self.terminal_output.see("end")

    def process_shell_command(self, command):
        """
        Handle built-in terminal commands when no program is running.
        """
        if command == "run":
            self.run_code()
        elif command in ("clear", "cls"):
            self.terminal_output.configure(state="normal")
            self.terminal_output.delete("1.0", "end")
            self.print_shell_prompt()
        elif command == "submit":
            self.controller.submit_exam()
        elif command == "help":
            self.append_terminal_output(
                "run - Execute editor code\n"
                "clear - Clear terminal\n"
                "submit - Submit exam\n"
            )
            self.print_shell_prompt()
        elif command == "exit":
            self.append_terminal_output(
                "Use the Emergency Exit button to leave the exam.\n"
            )
            self.print_shell_prompt()
        else:
            self.append_terminal_output(
                f"Command not found: {command}. Type 'help' for available commands.\n"
            )
            self.print_shell_prompt()

    def read_process_stream(self, stream):
        """
        Continuously read a process stream and forward each line to the terminal.
        """
        try:
            while True:
                line = stream.readline()
                if not line:
                    break
                self.schedule_terminal_append(line)
        finally:
            stream.close()

    def handle_terminal_enter(self, event=None):
        """
        Route terminal Enter presses either to the running process or the
        built-in EduSync shell.
        """
        process_running = (
            self.current_process is not None
            and self.current_process.poll() is None
        )

        if process_running:
            user_input = self.terminal_output.get("input_start", "end-1c")

            try:
                self.current_process.stdin.write(user_input + "\n")
                self.current_process.stdin.flush()
            except Exception as error:
                self.append_terminal_output(f"\nCRITICAL ERROR: {error}\n")
                return "break"

            self.terminal_output.configure(state="normal")
            self.terminal_output.insert("end", "\n")
            self.terminal_output.mark_set("input_start", "end-1c")
            self.terminal_output.see("end")
            return "break"

        command = self.terminal_output.get("input_start", "end-1c").strip()
        self.terminal_output.configure(state="normal")
        self.terminal_output.insert("end", "\n")
        self.terminal_output.see("end")

        if not command:
            self.print_shell_prompt()
            return "break"

        self.process_shell_command(command)
        return "break"

    def cleanup_temp_dir(self):
        """
        Remove the current sandbox directory after a run finishes.
        """
        if self.current_temp_dir is not None:
            self.current_temp_dir.cleanup()
            self.current_temp_dir = None

    def handle_editor_autopair(self, event):
        """
        Insert matching closing characters and place the caret between them.
        """
        pairs = {
            "(": ")",
            "[": "]",
            "{": "}",
            "\"": "\"",
            "'": "'",
        }
        typed_char = event.char

        if typed_char not in pairs:
            return None

        if event.state & 0x4:
            return None

        editor = event.widget
        editor.insert("insert", typed_char + pairs[typed_char])
        editor.mark_set("insert", "insert-1c")
        return "break"

    def auto_indent(self, event=None):
        """
        Copy the current line's leading whitespace onto the next line.
        """
        editor = event.widget
        current_line_start = editor.index("insert linestart")
        current_line_text = editor.get(current_line_start, "insert lineend")

        leading_whitespace_chars = []
        for char in current_line_text:
            if char in (" ", "\t"):
                leading_whitespace_chars.append(char)
            else:
                break

        indentation = "".join(leading_whitespace_chars)
        editor.insert("insert", "\n" + indentation)
        return "break"

    def confirm_emergency_exit(self):
        """
        Ask for confirmation before leaving the kiosk and forfeiting the exam.
        """
        should_exit = messagebox.askyesno(
            "Emergency Exit",
            "Are you sure you want to exit? This will forfeit your exam.",
        )
        if should_exit:
            self.controller.debug_close()

    def run_code(self):
        """
        Execute the current project inside a temporary sandbox directory.

        Every open tab is written out as a real physical file first, then the
        currently active file determines which runtime or compiler to use.
        """
        import subprocess

        if self.current_process is not None and self.current_process.poll() is None:
            self.append_terminal_output("\nA program is already running.\n")
            return

        active_file = self.active_filename

        if active_file not in self.files:
            self.append_terminal_output("\nNo active file is available to run.\n")
            return

        _, extension = os.path.splitext(active_file)
        extension = extension.lower()

        # Clear the terminal so each run starts with fresh output.
        self.terminal_output.configure(state="normal")
        self.terminal_output.delete("1.0", "end")
        self.terminal_output.insert(
            "end",
            f"Executing {active_file}...\n",
        )
        self.terminal_output.insert("end", "-" * 30 + "\n")
        self.terminal_output.see("end")

        try:
            self.cleanup_temp_dir()
            self.current_temp_dir = tempfile.TemporaryDirectory()
            temp_dir = self.current_temp_dir.name
            with self.terminal_buffer_lock:
                self.terminal_buffer = ""
            self.is_flushing = True
            self.flush_terminal_buffer()

            for filename, textbox in self.files.items():
                file_contents = textbox.get("1.0", "end-1c")
                file_path = os.path.join(temp_dir, filename)
                parent_dir = os.path.dirname(file_path)

                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)

                with open(file_path, "w", encoding="utf-8") as source_file:
                    source_file.write(file_contents)

            compile_cmd = None
            run_cmd = None
            build_target = active_file

            if extension == ".py":
                run_cmd = ["python", "-u", active_file]
            elif extension == ".cpp":
                cpp_files = [
                    file_name for file_name in self.files
                    if file_name.lower().endswith(".cpp")
                ]
                if not cpp_files:
                    self.append_terminal_output("\nNo C++ files found to compile.\n")
                    self.is_flushing = False
                    self.cleanup_temp_dir()
                    self.print_shell_prompt()
                    return
                compile_cmd = ["g++", *cpp_files, "-o", "out.exe"]
                run_cmd = ["out.exe"]
                build_target = active_file
            elif extension == ".java":
                java_files = [
                    file_name for file_name in self.files
                    if file_name.lower().endswith(".java")
                ]
                if not java_files:
                    self.append_terminal_output("\nNo Java files found to compile.\n")
                    self.is_flushing = False
                    self.cleanup_temp_dir()
                    self.print_shell_prompt()
                    return
                compile_cmd = ["javac", *java_files]
                run_cmd = ["java", active_file.replace(".java", "")]
                build_target = active_file
            else:
                self.append_terminal_output(
                    f"\nUnsupported file type: {extension or '[no extension]'}\n"
                )
                self.is_flushing = False
                self.cleanup_temp_dir()
                self.print_shell_prompt()
                return

            # 1. TEMPORARILY DISABLE SECURITY
            # GUI-based student code may open its own window and need focus.
            # We relax the kiosk restrictions while that child process is alive.
            self.controller.attributes("-topmost", False)
            self.controller.is_gui_testing = True

            if compile_cmd is not None:
                self.append_terminal_output(
                    f"Compiling {build_target}...\n"
                )
                compile_result = subprocess.run(
                    compile_cmd,
                    capture_output=True,
                    text=True,
                    cwd=temp_dir,
                )
                if compile_result.stdout:
                    self.append_terminal_output(compile_result.stdout)
                if compile_result.stderr:
                    self.append_terminal_output(compile_result.stderr)
                if compile_result.returncode != 0:
                    self.append_terminal_output(
                        "\nCompilation failed. Program was not started.\n"
                    )
                    self.is_flushing = False
                    self.controller.attributes("-topmost", True)
                    self.controller.is_gui_testing = False
                    self.cleanup_temp_dir()
                    self.print_shell_prompt()
                    return

                self.append_terminal_output("Compilation successful.\n")

            # 2. LAUNCH THE STUDENT CODE IN THE BACKGROUND
            self.current_process = subprocess.Popen(
                run_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=0,
                cwd=temp_dir,
            )
            self.append_terminal_output(
                "Program started. Security temporarily paused...\n"
            )
            with self.stream_state_lock:
                self.active_streams = 2

            def stream_characters(stream):
                """
                Read one character at a time so prompts without trailing newlines
                appear immediately in the interactive terminal.
                """
                try:
                    while True:
                        char = stream.read(1)
                        if not char:
                            break
                        with self.terminal_buffer_lock:
                            self.terminal_buffer += char
                finally:
                    stream.close()
                    with self.stream_state_lock:
                        self.active_streams -= 1

            threading.Thread(
                target=stream_characters,
                args=(self.current_process.stdout,),
                daemon=True,
            ).start()
            threading.Thread(
                target=stream_characters,
                args=(self.current_process.stderr,),
                daemon=True,
            ).start()

            # 3. WATCHDOG LOOP
            # Poll without blocking CustomTkinter. Once the process exits,
            # restore kiosk security and return the terminal to read-only mode.
            def check_process():
                if self.current_process is None:
                    return

                if self.current_process.poll() is None:
                    self.after(150, check_process)
                    return

                with self.stream_state_lock:
                    streams_running = self.active_streams > 0
                with self.terminal_buffer_lock:
                    has_pending_output = bool(self.terminal_buffer)

                if streams_running or has_pending_output:
                    self.after(50, check_process)
                    return

                self.is_flushing = False
                self.append_terminal_output("\nProgram finished.\n")

                # 4. RE-ACTIVATE SECURITY AFTER OUTPUT HAS BEEN SHOWN
                self.controller.attributes("-topmost", True)
                self.controller.is_gui_testing = False
                self.current_process = None
                self.cleanup_temp_dir()
                self.print_shell_prompt()

            check_process()

        except Exception as error:
            self.is_flushing = False
            self.append_terminal_output(f"\nCRITICAL ERROR: {error}\n")
            self.controller.attributes("-topmost", True)
            self.controller.is_gui_testing = False
            self.current_process = None
            self.cleanup_temp_dir()
            self.print_shell_prompt()



if __name__ == "__main__":
    app = EduSyncKiosk()
    app.mainloop()
