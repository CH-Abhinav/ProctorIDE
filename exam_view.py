import os
import re
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import tkinter.ttk as ttk
from bisect import bisect_right
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image
import requests
import shutil

from proctor_ai import AIProctor


FOLDER_ICON = "\U0001F4C1"
FILE_ICON = "\U0001F4C4"


class TerminalTab(ctk.CTkFrame):

    def __init__(self, parent, parent_exam_frame):
        super().__init__(parent, corner_radius=0, fg_color="#1F1F1F")
        self.exam_frame = parent_exam_frame
        self.WORKSPACE_DIR = getattr(
            parent_exam_frame,
            "WORKSPACE_DIR",
            os.path.abspath("./proctor_workspace"),
        )
        os.makedirs(self.WORKSPACE_DIR, exist_ok=True)
        self.current_dir = self.WORKSPACE_DIR
        self.prompt_text = "proctorIDE> "
        self.current_process = None
        self.terminal_buffer = ""
        self.command_history = []
        self.history_index = 0
        self.is_flushing = False
        self.active_streams = 0
        self.cleanup_temp_dir_on_stop = False
        self.terminal_buffer_lock = threading.Lock()
        self.stream_state_lock = threading.Lock()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        best_font = parent_exam_frame.get_best_monospace_font(13)
        self.terminal_output = ctk.CTkTextbox(
            self,
            height=180,
            corner_radius=0,
            font=best_font,
            fg_color="#181818",
            text_color="#cccccc",
            border_width=0,
        )
        self.terminal_output.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=12,
            pady=(0, 12),
        )
        if hasattr(self.terminal_output, "_textbox"):
            self.terminal_output._textbox.configure(
                padx=12,
                pady=12,
                spacing1=2,
                font=best_font,
            )
            self.terminal_output._textbox.tag_config("prompt", foreground="#4facf7")
        self.terminal_output.configure(state="disabled")
        self.terminal_output.bind("<Return>", self.handle_terminal_enter)
        self.terminal_output.bind("<Up>", self.handle_terminal_up)
        self.terminal_output.bind("<Down>", self.handle_terminal_down)
        self.terminal_output.bind("<BackSpace>", self.prevent_prompt_deletion)
        self.terminal_output.bind("<Left>", self.prevent_prompt_deletion)
        self.print_shell_prompt()

    def append_terminal_output(self, message):
        self.terminal_output.configure(state="normal")
        self.terminal_output.insert("end", message)
        self.terminal_output.mark_set("input_start", "end-1c")
        self.terminal_output.mark_gravity("input_start", "left")
        self.terminal_output.see("end")
        if self.current_process is None:
            self.terminal_output.configure(state="disabled")

    def schedule_terminal_append(self, message):
        self.after(0, lambda: self.append_terminal_output(message))

    def _is_within_workspace(self, candidate_path):
        try:
            workspace_root = os.path.normcase(os.path.abspath(self.WORKSPACE_DIR))
            candidate_root = os.path.normcase(os.path.abspath(candidate_path))
            return (
                os.path.commonpath([workspace_root, candidate_root])
                == workspace_root
            )
        except ValueError:
            return False

    def flush_terminal_buffer(self):
        with self.terminal_buffer_lock:
            chunk = self.terminal_buffer
            self.terminal_buffer = ""

        if chunk:
            self.append_terminal_output(chunk)

        if self.is_flushing or self.terminal_buffer:
            self.after(50, self.flush_terminal_buffer)

    def get_process_cwd(self):
        return self.current_dir

    def begin_streaming_process(self):
        with self.terminal_buffer_lock:
            self.terminal_buffer = ""
        self.is_flushing = True
        self.flush_terminal_buffer()

    def attach_process_watchdog(
        self,
        started_message="Program started.\n",
        finished_message="\nProgram finished.\n",
        cleanup_temp_dir=False,
    ):
        self.cleanup_temp_dir_on_stop = cleanup_temp_dir
        self.append_terminal_output(started_message)
        self.exam_frame.run_button.configure(
            text="Stop",
            fg_color="#2A2D2E",
            hover_color="#4A2D2D",
            text_color="#F48771",
            command=self.stop_process,
        )
        with self.stream_state_lock:
            self.active_streams = 2

        def stream_characters(stream):
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
            self.append_terminal_output(finished_message)
            self.current_process = None
            if cleanup_temp_dir:
                self.exam_frame.cleanup_temp_dir()
            self.cleanup_temp_dir_on_stop = False
            self.exam_frame.reset_run_button()
            self.exam_frame.refresh_workspace_tree()
            self.print_shell_prompt()

        check_process()

    def print_shell_prompt(self):
        self.terminal_output.configure(state="normal")
        if hasattr(self.terminal_output, "_textbox"):
            self.terminal_output._textbox.insert(
                "end",
                f"\n{self.prompt_text}",
                "prompt",
            )
        else:
            self.terminal_output.insert("end", f"\n{self.prompt_text}")
        self.terminal_output.mark_set("input_start", "end-1c")
        self.terminal_output.mark_gravity("input_start", "left")
        self.terminal_output.see("end")

    def prevent_prompt_deletion(self, event):
        if self.terminal_output.compare("insert", "<=", "input_start"):
            self.terminal_output.mark_set("insert", "input_start")
            return "break"
        return None

    def process_shell_command(self, command):
        command = command.strip()
        if hasattr(self.exam_frame, 'sync_files_to_workspace'):
            self.exam_frame.sync_files_to_workspace()
        
        if command.startswith("cd "):
            target_dir = command[3:].strip()
            
            if not hasattr(self, 'current_dir'):
                self.current_dir = os.path.abspath(self.WORKSPACE_DIR)
            
            new_dir = os.path.abspath(os.path.join(self.current_dir, target_dir))

            if self._is_within_workspace(new_dir):
                if os.path.isdir(new_dir):
                    self.current_dir = new_dir
                    self.append_terminal_output(
                        f"\nChanged directory to {self.current_dir}\n"
                    )
                else:
                    self.append_terminal_output(f"\nDirectory not found: {new_dir}\n")
            else:
                self.append_terminal_output(
                    f"\nAccess Denied: Cannot navigate outside exam workspace.\n"
                )

            self.print_shell_prompt()
            return
            
        if command == "run":
            self.exam_frame.run_code()
        elif command in ("clear", "cls"):
            self.terminal_output.configure(state="normal")
            self.terminal_output.delete("1.0", "end")
            self.print_shell_prompt()
        elif command == "submit":
            self.exam_frame.controller.submit_exam()
        elif command.startswith("search "):
            target_url = command.split(None, 1)[1].strip()
            self.exam_frame.launch_browser(target_url, terminal=self)
            self.print_shell_prompt()
            
        else:
            try:
                if not hasattr(self, 'current_dir'):
                    self.current_dir = os.getcwd()

                self.begin_streaming_process()
                
                self.current_process = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=self.current_dir,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=0,
                )
                
                self.attach_process_watchdog(
                    started_message=f"Running shell command: {command}\n",
                    finished_message="\nShell command finished.\n",
                    cleanup_temp_dir=False,
                )
                
                if hasattr(self.exam_frame, 'refresh_workspace_tree'):
                    self.after(1000, self.exam_frame.refresh_workspace_tree)
                    
            except Exception as error:
                self.is_flushing = False
                self.current_process = None
                self.append_terminal_output(f"\nCRITICAL ERROR: {error}\n")
                self.print_shell_prompt()

    def submit_exam(self):
        self.exam_frame.submit_exam()

    def handle_terminal_enter(self, event=None):
        user_input = self.terminal_output.get("input_start", "end-1c").strip()

        built_in_commands = ("search", "clear", "cls", "submit", "help", "exit", "cd")
        is_built_in = any(
            user_input == command or user_input.startswith(f"{command} ")
            for command in built_in_commands
        )

        if is_built_in:
            self.terminal_output.configure(state="normal")
            self.terminal_output.insert("end", "\n")
            self.terminal_output.see("end")

            if user_input:
                self.command_history.append(user_input)
                self.history_index = len(self.command_history)
                self.process_shell_command(user_input)
            else:
                self.print_shell_prompt()
            return "break"

        process_running = (
            self.current_process is not None
            and self.current_process.poll() is None
        )

        if process_running:
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

        self.terminal_output.configure(state="normal")
        self.terminal_output.insert("end", "\n")
        self.terminal_output.see("end")

        if not user_input:
            self.print_shell_prompt()
            return "break"

        self.command_history.append(user_input)
        self.history_index = len(self.command_history)
        self.process_shell_command(user_input)
        return "break"

    def handle_terminal_up(self, event):
        if not self.command_history or self.history_index == 0:
            return "break"

        self.history_index -= 1
        self.terminal_output.delete("input_start", "end-1c")
        self.terminal_output.insert(
            "input_start",
            self.command_history[self.history_index],
        )
        self.terminal_output.see("end")
        return "break"

    def handle_terminal_down(self, event):
        if self.history_index >= len(self.command_history):
            return "break"

        self.history_index += 1
        self.terminal_output.delete("input_start", "end-1c")

        if self.history_index < len(self.command_history):
            self.terminal_output.insert(
                "input_start",
                self.command_history[self.history_index],
            )

        self.terminal_output.see("end")
        return "break"

    def stop_process(self):
        if self.current_process is not None and self.current_process.poll() is None:
            self.current_process.kill()
            self.append_terminal_output("\n[Process forcibly terminated]\n")

        self.is_flushing = False
        self.exam_frame.controller.attributes("-topmost", True)
        self.exam_frame.controller.is_gui_testing = False
        self.current_process = None
        if self.cleanup_temp_dir_on_stop:
            self.exam_frame.cleanup_temp_dir()
        self.cleanup_temp_dir_on_stop = False
        self.print_shell_prompt()
        self.exam_frame.reset_run_button()


class ActiveExamFrame(ctk.CTkFrame):

    def __init__(self, parent, controller):
        super().__init__(parent, corner_radius=0, fg_color="#181818")
        self.controller = controller
        self.WORKSPACE_DIR = os.path.abspath("./proctor_workspace")
        if os.path.exists(self.WORKSPACE_DIR):
            shutil.rmtree(self.WORKSPACE_DIR, ignore_errors=True)
        os.makedirs(self.WORKSPACE_DIR, exist_ok=True)
        self.current_temp_dir = None
        self.proctor = AIProctor()
        self.ai_proctor = self.proctor
        self.camera_image = None

        self.files = {}
        self.tree_nodes = {}
        self.tree_item_paths = {}
        self.selected_tree_node = ""
        self.active_filename = None
        self.primary_filename = "main.py"
        self.highlight_timer = None

        self.remaining_seconds = 7200

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        content = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color="#181818",
            border_width=0,
        )
        content.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(2, weight=1)

        menu_bar = ctk.CTkFrame(
            content,
            corner_radius=0,
            fg_color="#181818",
            border_width=0,
            height=28,
        )
        menu_bar.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        menu_bar.grid_propagate(False)

        self.file_menu = tk.Menu(
            self,
            tearoff=0,
            bg="#1F1F1F",
            fg="#CCCCCC",
            bd=0,
            activebackground="#007ACC",
            activeforeground="#FFFFFF",
        )
        self.file_menu.add_command(label="New File", command=self.prompt_new_file)
        self.file_menu.add_command(
            label="Submit Exam",
            command=self.controller.submit_exam,
        )

        self.edit_menu = tk.Menu(
            self,
            tearoff=0,
            bg="#1F1F1F",
            fg="#CCCCCC",
            bd=0,
            activebackground="#007ACC",
            activeforeground="#FFFFFF",
        )
        self.edit_menu.add_command(label="Undo", command=self.undo_active_editor)
        self.edit_menu.add_command(label="Redo", command=self.redo_active_editor)

        self.terminal_menu = tk.Menu(
            self,
            tearoff=0,
            bg="#1F1F1F",
            fg="#CCCCCC",
            bd=0,
            activebackground="#007ACC",
            activeforeground="#FFFFFF",
        )
        self.terminal_menu.add_command(
            label="New Terminal",
            command=self.add_terminal,
        )
        self.terminal_menu.add_command(
            label="Close Active Terminal",
            command=self.close_terminal,
        )
        self.terminal_menu.add_separator()
        self.terminal_menu.add_command(
            label="Close All Terminals",
            command=self.close_all_terminals,
        )

        file_button = ctk.CTkButton(
            menu_bar,
            text="File",
            width=44,
            height=24,
            corner_radius=4,
            fg_color="transparent",
            hover_color="#1F1F1F",
            text_color="#CCCCCC",
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
            width=44,
            height=24,
            corner_radius=4,
            fg_color="transparent",
            hover_color="#1F1F1F",
            text_color="#CCCCCC",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            command=lambda: self.post_dropdown_menu(self.edit_menu, edit_button),
        )
        edit_button.pack(side="left", padx=(0, 6))
        edit_button.bind(
            "<Button-1>",
            lambda event: self.post_dropdown_menu(self.edit_menu, edit_button),
        )

        terminal_button = ctk.CTkButton(
            menu_bar,
            text="Terminal",
            width=60,
            height=24,
            corner_radius=4,
            fg_color="transparent",
            hover_color="#1F1F1F",
            text_color="#CCCCCC",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            command=lambda: self.post_dropdown_menu(self.terminal_menu, terminal_button),
        )
        terminal_button.pack(side="left", padx=(0, 6))
        terminal_button.bind(
            "<Button-1>",
            lambda event: self.post_dropdown_menu(self.terminal_menu, terminal_button),
        )

        action_header = ctk.CTkFrame(
            content,
            corner_radius=0,
            fg_color="#1F1F1F",
            border_width=0,
        )
        action_header.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        action_header.grid_columnconfigure(0, weight=1)
        action_header.grid_columnconfigure(1, weight=1)
        action_header.grid_columnconfigure(2, weight=1)

        self.student_label = ctk.CTkLabel(
            action_header,
            text="Student: Abhinav",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#CCCCCC",
            anchor="w",
        )
        self.student_label.grid(row=0, column=0, sticky="w", padx=16, pady=12)

        action_center = ctk.CTkFrame(
            action_header,
            corner_radius=0,
            fg_color="transparent",
            border_width=0,
        )
        action_center.grid(row=0, column=1)

        self.run_button = ctk.CTkButton(
            action_center,
            text="Run",
            width=92,
            height=30,
            corner_radius=4,
            fg_color="#2A2D2E",
            hover_color="#37373D",
            text_color="#CCCCCC",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            command=self.run_code,
        )
        self.run_button.pack(side="left", padx=(0, 8))

        submit_button = ctk.CTkButton(
            action_center,
            text="Submit Exam",
            width=120,
            height=30,
            corner_radius=4,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color="#007ACC",
            hover_color="#1493FF",
            text_color="#FFFFFF",
            command=self.controller.submit_exam,
        )
        submit_button.pack(side="left")

        action_right = ctk.CTkFrame(
            action_header,
            corner_radius=0,
            fg_color="transparent",
            border_width=0,
        )
        action_right.grid(row=0, column=2, sticky="e", padx=16)

        self.timer_label = ctk.CTkLabel(
            action_right,
            text=self.format_time(self.remaining_seconds),
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#CCCCCC",
        )
        self.timer_label.pack(side="left", padx=(0, 12))



        emergency_exit_button = ctk.CTkButton(
            action_right,
            text="Emergency Exit",
            fg_color="#2A2D2E",
            hover_color="#3A1F1F",
            border_width=0,
            text_color="#F48771",
            height=30,
            corner_radius=4,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            command=self.confirm_emergency_exit,
        )
        emergency_exit_button.pack(side="left")

        self.main_paned = tk.PanedWindow(
            content,
            orient="horizontal",
            bg="#181818",
            sashwidth=6,
            bd=0,
            relief="flat",
        )
        self.main_paned.configure(
            background="#181818",
            sashrelief="flat",
            sashpad=0,
            showhandle=False,
        )
        self.main_paned.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

        sidebar_frame = ctk.CTkFrame(
            self.main_paned,
            corner_radius=0,
            fg_color="#1F1F1F",
            border_width=0,
        )
        sidebar_frame.grid_columnconfigure(0, weight=1)
        sidebar_frame.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(
            sidebar_frame,
            corner_radius=0,
            fg_color="transparent",
            border_width=0,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(1, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "VSCode.Treeview",
            background="#1F1F1F",
            foreground="#CCCCCC",
            fieldbackground="#1F1F1F",
            borderwidth=0,
            relief="flat",
            rowheight=24,
        )
        style.map(
            "VSCode.Treeview",
            background=[("selected", "#007ACC")],
            foreground=[("selected", "#FFFFFF")],
        )
        style.layout("VSCode.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

        explorer_label = ctk.CTkLabel(
            self.sidebar,
            text="EXPLORER",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#A0A0A0",
            anchor="w",
        )
        explorer_label.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 10))

        tree_container = ctk.CTkFrame(
            self.sidebar,
            corner_radius=0,
            fg_color="#1F1F1F",
            border_width=0,
        )
        tree_container.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        tree_container.grid_columnconfigure(0, weight=1)
        tree_container.grid_rowconfigure(0, weight=1)

        self.file_tree = ttk.Treeview(
            tree_container,
            show="tree",
            style="VSCode.Treeview",
            selectmode="browse",
        )
        self.file_tree.grid(row=0, column=0, sticky="nsew")

        tree_scrollbar = ttk.Scrollbar(
            tree_container,
            orient="vertical",
            command=self.file_tree.yview,
        )
        tree_scrollbar.grid(row=0, column=1, sticky="ns")
        self.file_tree.configure(yscrollcommand=tree_scrollbar.set)
        self.file_tree.bind("<Double-1>", self.on_tree_double_click)
        self.file_tree.bind("<Button-3>", self.show_tree_context_menu)

        self.tree_context_menu = tk.Menu(
            self,
            bg="#1F1F1F",
            fg="#CCCCCC",
            bd=0,
            activebackground="#007ACC",
            activeforeground="#FFFFFF",
            tearoff=0,
        )
        self.tree_context_menu.add_command(
            label="New File",
            command=self.on_new_file_click,
        )
        self.tree_context_menu.add_command(
            label="New Folder",
            command=self.on_new_folder_click,
        )
        self.tree_context_menu.add_command(
            label="Delete",
            command=self.on_delete_click,
        )

        self.camera_container = ctk.CTkFrame(
            self.sidebar,
            corner_radius=8,
            fg_color="#181818",
            height=140,
            border_width=1,
            border_color="#2A2D2E",
        )
        self.camera_container.grid(
            row=2,
            column=0,
            sticky="ew",
            padx=8,
            pady=(0, 8),
        )
        self.camera_container.grid_columnconfigure(0, weight=1)
        self.camera_container.grid_rowconfigure(1, weight=1)
        self.camera_container.grid_propagate(False)

        camera_title = ctk.CTkLabel(
            self.camera_container,
            text="AI PROCTOR",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#A0A0A0",
            anchor="w",
        )
        camera_title.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))

        self.camera_label = ctk.CTkLabel(
            self.camera_container,
            text="Initializing AI...",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color="#CCCCCC",
        )
        self.camera_label.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        self.main_paned.add(sidebar_frame, minsize=150)

        self.right_paned = tk.PanedWindow(
            self.main_paned,
            orient="vertical",
            bg="#181818",
            sashwidth=6,
            bd=0,
            relief="flat",
        )
        self.right_paned.configure(
            background="#181818",
            sashrelief="flat",
            sashpad=0,
            showhandle=False,
        )
        self.main_paned.add(self.right_paned, minsize=360)

        editor_frame = ctk.CTkFrame(
            self.right_paned,
            corner_radius=0,
            fg_color="#1F1F1F",
            border_width=0,
        )
        editor_frame.grid_columnconfigure(0, weight=1)
        editor_frame.grid_rowconfigure(1, weight=1)

        editor_header = ctk.CTkFrame(
            editor_frame,
            corner_radius=0,
            fg_color="#1F1F1F",
            border_width=0,
        )
        editor_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        editor_header.grid_columnconfigure(1, weight=1)

        editor_label = ctk.CTkLabel(
            editor_header,
            text="EDITOR",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#A0A0A0",
            anchor="w",
        )
        editor_label.grid(row=0, column=0, sticky="w")

        self.editor_title_label = ctk.CTkLabel(
            editor_header,
            text=self.primary_filename,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#CCCCCC",
            anchor="w",
        )
        self.editor_title_label.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.editor_surface = ctk.CTkFrame(
            editor_frame,
            corner_radius=0,
            fg_color="#1F1F1F",
            border_width=0,
        )
        self.editor_surface.grid(row=1, column=0, sticky="nsew", padx=2, pady=(0, 2))
        self.editor_surface.grid_columnconfigure(0, weight=1)
        self.editor_surface.grid_rowconfigure(0, weight=1)

        self.right_paned.add(editor_frame, minsize=200)

        terminal_frame = ctk.CTkFrame(
            self.right_paned,
            corner_radius=0,
            fg_color="#1F1F1F",
            border_width=0,
        )
        terminal_frame.grid_columnconfigure(0, weight=1)
        terminal_frame.grid_rowconfigure(1, weight=1)

        terminal_header = ctk.CTkFrame(
            terminal_frame,
            corner_radius=0,
            fg_color="transparent",
        )
        terminal_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        terminal_header.grid_columnconfigure(0, weight=1)

        output_label = ctk.CTkLabel(
            terminal_header,
            text="Interactive Terminal",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color="#CCCCCC",
            anchor="w",
        )
        output_label.grid(row=0, column=0, sticky="w")

        add_term_btn = ctk.CTkButton(
            terminal_header,
            text="+",
            width=28,
            height=24,
            fg_color="#2A2D2E",
            hover_color="#007ACC",
            text_color="#FFF",
            command=self.add_terminal,
        )
        add_term_btn.grid(row=0, column=2, padx=(0, 5))

        close_term_btn = ctk.CTkButton(
            terminal_header,
            text="×",
            width=28,
            height=24,
            fg_color="#2A2D2E",
            hover_color="#D32F2F",
            text_color="#FFF",
            command=self.close_terminal,
        )
        close_term_btn.grid(row=0, column=3)

        self.terminal_tabview = ctk.CTkTabview(
            terminal_frame,
            corner_radius=0,
            fg_color="#1F1F1F",
            segmented_button_fg_color="#181818",
            segmented_button_selected_color="#007ACC",
            segmented_button_selected_hover_color="#1493FF",
            segmented_button_unselected_color="#2A2D2E",
            segmented_button_unselected_hover_color="#37373D",
            text_color="#CCCCCC",
        )
        self.terminal_tabview.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=12,
            pady=(0, 12),
        )

        self.terminals = {}
        self.add_terminal()
        self.right_paned.add(terminal_frame, minsize=100)

        self.create_file_tab(
            self.primary_filename,
            (
                "def main():\n"
                "    pass\n\n"
                "if __name__ == \"__main__\":\n"
                "    main()\n"
            ),
            select_tab=True,
        )
        self.update_timer()
        self.proctor.start_monitoring()
        self.update_webcam_feed()

    def get_best_monospace_font(self, size):
        import tkinter.font as tkfont
        available_families = tkfont.families()
        candidates = ["Cascadia Code", "Fira Code", "JetBrains Mono", "Consolas", "Courier New"]
        for candidate in candidates:
            if candidate in available_families:
                return (candidate, size)
        return ("monospace", size)

    def create_file_tab(self, filename, initial_content="", select_tab=True):
        filename = self.normalize_path(filename)
        if filename in self.files:
            if select_tab:
                self.switch_to_file(filename)
                self.files[filename].focus_set()
            return self.files[filename]

        best_font = self.get_best_monospace_font(14)
        editor = ctk.CTkTextbox(
            self.editor_surface,
            wrap="none",
            corner_radius=0,
            font=best_font,
            fg_color="#1e1e1e",
            text_color="#d4d4d4",
            border_width=0,
            undo=True,
            maxundo=100,
            autoseparators=True,
        )
        self.setup_syntax_tags(editor)
        editor.grid(row=0, column=0, sticky="nsew")
        editor.insert("1.0", initial_content)
        editor.bind("<KeyPress>", self.handle_editor_autopair)
        editor.bind("<Return>", self.auto_indent)
        editor.bind("<Tab>", self.insert_four_spaces)
        editor.bind("<Control-s>", lambda event: self.sync_files_to_workspace() or "break")
        editor.bind(
            "<KeyRelease>",
            lambda event, name=filename: self.on_key_release(event, name),
        )

        if hasattr(editor, "_textbox"):
            editor._textbox.configure(
                padx=16,
                pady=16,
                spacing1=4,
                spacing3=4,
                font=best_font,
                relief="flat",
                borderwidth=0,
                highlightthickness=0,
                insertbackground="#d4d4d4",
            )

        if hasattr(editor, "_scrollbar") and editor._scrollbar is not None:
            editor._scrollbar.grid_remove()

        self.files[filename] = editor
        self.insert_path_into_tree(filename)

        if self.active_filename is None:
            self.switch_to_file(filename)
        else:
            editor.grid_remove()
            if select_tab:
                self.switch_to_file(filename)

        if select_tab:
            editor.focus_set()
            editor.mark_set("insert", "1.0")

        self.highlight_syntax(editor, filename, line_only=False)
        return editor

    def normalize_path(self, path):
        return path.replace("\\", "/").strip().strip("/")

    def get_selected_tree_path(self):
        if not self.selected_tree_node:
            return ""
        return self.tree_item_paths.get(self.selected_tree_node, "")

    def insert_path_into_tree(self, filepath):
        filepath = self.normalize_path(filepath)
        parts = [part for part in filepath.split("/") if part]
        if not parts:
            return None

        parent_item = ""
        current_path_parts = []

        for folder_name in parts[:-1]:
            current_path_parts.append(folder_name)
            folder_path = "/".join(current_path_parts)
            if folder_path not in self.tree_nodes:
                item_id = self.file_tree.insert(
                    parent_item,
                    "end",
                    text=f"{FOLDER_ICON} {folder_name}",
                    open=True,
                )
                self.tree_nodes[folder_path] = item_id
                self.tree_item_paths[item_id] = folder_path
            parent_item = self.tree_nodes[folder_path]

        file_path = "/".join(parts)
        if file_path not in self.tree_nodes:
            item_id = self.file_tree.insert(
                parent_item,
                "end",
                text=f"{FILE_ICON} {parts[-1]}",
                open=False,
            )
            self.tree_nodes[file_path] = item_id
            self.tree_item_paths[item_id] = file_path
        return self.tree_nodes[file_path]

    def ensure_folder_path_in_tree(self, folder_path):
        folder_path = self.normalize_path(folder_path)
        if not folder_path:
            return ""

        if folder_path in self.tree_nodes:
            return self.tree_nodes[folder_path]

        parts = [part for part in folder_path.split("/") if part]
        parent_item = ""
        current_path_parts = []

        for folder_name in parts:
            current_path_parts.append(folder_name)
            current_path = "/".join(current_path_parts)
            if current_path not in self.tree_nodes:
                item_id = self.file_tree.insert(
                    parent_item,
                    "end",
                    text=f"{FOLDER_ICON} {folder_name}",
                    open=True,
                )
                self.tree_nodes[current_path] = item_id
                self.tree_item_paths[item_id] = current_path
            parent_item = self.tree_nodes[current_path]

        return parent_item

    def show_tree_context_menu(self, event):
        item = self.file_tree.identify_row(event.y)
        if item:
            self.file_tree.selection_set(item)
        self.selected_tree_node = item
        self.tree_context_menu.tk_popup(event.x_root, event.y_root)

    def get_insertion_parent(self):
        selected_path = self.get_selected_tree_path()
        if not selected_path:
            return "", ""

        if selected_path in self.files:
            parent_path = os.path.dirname(selected_path).replace("\\", "/")
            if not parent_path or parent_path == ".":
                return "", ""
            return self.tree_nodes.get(parent_path, ""), parent_path

        return self.selected_tree_node, selected_path

    def on_new_folder_click(self):
        dialog = ctk.CTkInputDialog(
            text="Enter the new folder name:",
            title="Create New Folder",
        )
        folder_name = dialog.get_input()
        if folder_name is None:
            return

        folder_name = self.normalize_path(folder_name)
        if not folder_name:
            messagebox.showwarning("Invalid Folder", "Folder name cannot be empty.")
            return

        parent_item, parent_path = self.get_insertion_parent()
        full_folder_path = self.normalize_path(
            f"{parent_path}/{folder_name}" if parent_path else folder_name
        )

        if full_folder_path in self.tree_nodes:
            messagebox.showwarning(
                "Duplicate Folder",
                f"A folder named '{full_folder_path}' already exists.",
            )
            return

        folder_node = self.ensure_folder_path_in_tree(full_folder_path)
        if folder_node:
            self.file_tree.selection_set(folder_node)
            self.file_tree.focus(folder_node)
            self.file_tree.see(folder_node)
            self.selected_tree_node = folder_node

    def on_new_file_click(self):
        dialog = ctk.CTkInputDialog(
            text="Enter the new filename:",
            title="Create New File",
        )
        filename = dialog.get_input()
        if filename is None:
            return

        filename = self.normalize_path(filename)
        if not filename:
            messagebox.showwarning("Invalid Filename", "Filename cannot be empty.")
            return

        parent_item, parent_path = self.get_insertion_parent()
        full_path = self.normalize_path(
            f"{parent_path}/{filename}" if parent_path else filename
        )

        if "/" in filename:
            nested_parent = os.path.dirname(full_path).replace("\\", "/")
            parent_item = self.ensure_folder_path_in_tree(nested_parent)

        if full_path in self.files:
            messagebox.showwarning(
                "Duplicate Filename",
                f"A file named '{full_path}' already exists.",
            )
            self.switch_to_file(full_path)
            self.files[full_path].focus_set()
            return

        self.create_file_tab(full_path, "", select_tab=True)
        file_node = self.tree_nodes.get(full_path)
        if file_node:
            self.file_tree.selection_set(file_node)
            self.file_tree.focus(file_node)
            self.file_tree.see(file_node)
            self.selected_tree_node = file_node

    def on_delete_click(self):
        node = self.selected_tree_node
        if not node:
            return

        target_path = self.tree_item_paths.get(node, "")
        if not target_path:
            return

        should_delete = messagebox.askyesno(
            "Delete",
            f"Are you sure you want to delete '{target_path}'?",
        )
        if not should_delete:
            return

        def collect_tree_nodes(item_id):
            collected = [item_id]
            for child_id in self.file_tree.get_children(item_id):
                collected.extend(collect_tree_nodes(child_id))
            return collected

        descendant_nodes = collect_tree_nodes(node)
        descendant_paths = [
            self.tree_item_paths[item_id]
            for item_id in descendant_nodes
            if item_id in self.tree_item_paths
        ]

        active_deleted = False
        for path in descendant_paths:
            if path in self.files:
                editor = self.files.pop(path)
                if path == self.active_filename:
                    editor.grid_remove()
                    active_deleted = True
                editor.destroy()
            self.tree_nodes.pop(path, None)

        for item_id in descendant_nodes:
            self.tree_item_paths.pop(item_id, None)

        self.file_tree.delete(node)
        self.selected_tree_node = ""

        if active_deleted:
            self.active_filename = None
            self.editor_title_label.configure(text="")

    def on_tree_double_click(self, event):
        selected_items = self.file_tree.selection()
        if not selected_items:
            return

        selected_item = selected_items[0]
        selected_path = self.tree_item_paths.get(selected_item)
        if not selected_path:
            return

        if selected_path in self.files:
            self.switch_to_file(selected_path)
            self.files[selected_path].focus_set()
            return

        disk_path = os.path.abspath(os.path.join(self.WORKSPACE_DIR, selected_path))
        if not self._is_within_workspace(disk_path) or not os.path.isfile(disk_path):
            return

        try:
            with open(disk_path, "r", encoding="utf-8", errors="replace") as file_handle:
                disk_content = file_handle.read()
        except OSError as error:
            messagebox.showerror("Open File Failed", f"Could not open '{selected_path}': {error}")
            return

        self.create_file_tab(selected_path, initial_content=disk_content, select_tab=True)

    def refresh_workspace_tree(self):
        workspace_root = os.path.abspath(self.WORKSPACE_DIR)
        os.makedirs(workspace_root, exist_ok=True)

        for item_id in self.file_tree.get_children():
            self.file_tree.delete(item_id)

        self.tree_nodes.clear()
        self.tree_item_paths.clear()
        self.selected_tree_node = ""

        for root, dirs, files in os.walk(workspace_root):
            dirs.sort()
            files.sort()

            relative_root = os.path.relpath(root, workspace_root)
            relative_root = "" if relative_root in (".", os.curdir) else relative_root

            if relative_root:
                self.ensure_folder_path_in_tree(relative_root)

            for folder_name in dirs:
                folder_path = os.path.normpath(
                    os.path.join(relative_root, folder_name)
                ).replace("\\", "/")
                self.ensure_folder_path_in_tree(folder_path)

            for file_name in files:
                file_path = os.path.normpath(
                    os.path.join(relative_root, file_name)
                ).replace("\\", "/")
                self.insert_path_into_tree(file_path)

        if self.active_filename and self.active_filename in self.tree_nodes:
            tree_item = self.tree_nodes[self.active_filename]
            self.file_tree.selection_set(tree_item)
            self.file_tree.focus(tree_item)
            self.file_tree.see(tree_item)
            self.selected_tree_node = tree_item

    def launch_browser(self, target_url="http://127.0.0.1:8080", terminal=None):
        terminal = terminal or self.get_active_terminal()
        blocker_js = (
            "document.addEventListener('click', function(e) { "
            "var t = e.target.closest('a'); "
            "if(t && t.href && !t.href.includes('localhost') && !t.href.includes('127.0.0.1')) { "
            "e.preventDefault(); "
            "alert('External navigation blocked.'); "
            "} "
            "});"
        )
        browser_script = (
            "import webview\n"
            f"TARGET_URL = {target_url!r}\n"
            f"BLOCKER_JS = {blocker_js!r}\n"
            "def on_loaded():\n"
            "    try:\n"
            "        window.evaluate_js(BLOCKER_JS)\n"
            "    except Exception as error:\n"
            "        print(f'[Browser Injection Error] {error}')\n"
            "window = webview.create_window(\n"
            "    'Proctor IDE Web Viewer',\n"
            "    TARGET_URL,\n"
            "    width=900,\n"
            "    height=700,\n"
            "    on_top=True,\n"
            ")\n"
            "window.events.loaded += on_loaded\n"
            "webview.start()\n"
        )

        try:
            terminal.append_terminal_output(
                f"\n[Booting Secure Browser at {target_url}...]\n"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", browser_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            def watch_browser():
                stdout, stderr = process.communicate()
                if process.returncode != 0:
                    if stdout:
                        terminal.schedule_terminal_append(stdout)
                    terminal.schedule_terminal_append(
                        f"\n[Browser Crashed!] Error details:\n{stderr}\n"
                    )

            threading.Thread(target=watch_browser, daemon=True).start()

        except Exception as error:
            terminal.append_terminal_output(
                f"\nBrowser launch failed: {error}\n"
            )

    def setup_syntax_tags(self, editor):
        best_font = self.get_best_monospace_font(14)
        italic_font = (best_font[0], best_font[1], "italic")

        editor.tag_config("keyword", foreground="#569cd6")
        editor.tag_config("string", foreground="#ce9178")
        if hasattr(editor, "_textbox"):
            editor._textbox.tag_config("comment", foreground="#6A9955", font=italic_font)
        else:
            editor.tag_config("comment", foreground="#6A9955")
        editor.tag_config("number", foreground="#b5cea8")
        editor.tag_raise("keyword")
        editor.tag_raise("string")
        editor.tag_raise("comment")
        editor.tag_raise("number")

    def on_key_release(self, event, filename):
        if self.highlight_timer is not None:
            self.after_cancel(self.highlight_timer)

        self.highlight_timer = self.after(
            300,
            lambda: self.highlight_syntax(event.widget, filename, line_only=True),
        )

    def get_language_keywords(self, extension):
        keyword_map = {
            ".py": [
                "def",
                "class",
                "import",
                "return",
                "if",
                "else",
                "elif",
                "for",
                "while",
                "try",
                "except",
                "with",
                "from",
                "as",
                "pass",
            ],
            ".js": [
                "const",
                "let",
                "var",
                "function",
                "return",
                "if",
                "else",
                "for",
                "while",
                "class",
                "import",
                "export",
            ],
            ".ts": [
                "const",
                "let",
                "var",
                "function",
                "return",
                "if",
                "else",
                "for",
                "while",
                "class",
                "import",
                "export",
                "interface",
                "type",
            ],
            ".cpp": [
                "int",
                "void",
                "return",
                "if",
                "include",
                "else",
                "class",
                "public",
                "private",
                "for",
                "while",
            ],
            ".c": [
                "int",
                "void",
                "return",
                "if",
                "include",
                "else",
                "for",
                "while",
                "struct",
            ],
            ".java": [
                "class",
                "public",
                "private",
                "static",
                "void",
                "return",
                "if",
                "else",
                "import",
                "new",
            ],
            ".rb": [
                "def",
                "class",
                "module",
                "end",
                "if",
                "else",
                "elsif",
                "return",
                "require",
            ],
            ".pl": [
                "sub",
                "my",
                "if",
                "else",
                "elsif",
                "return",
                "use",
                "package",
            ],
            ".rs": [
                "fn",
                "let",
                "mut",
                "pub",
                "struct",
                "impl",
                "return",
                "if",
                "else",
                "match",
                "use",
            ],
        }
        return keyword_map.get(extension, [])

    def offset_to_index(self, offset, line_offsets):
        line_number = bisect_right(line_offsets, offset) - 1
        column = offset - line_offsets[line_number]
        return f"{line_number + 1}.{column}"

    def add_matches_for_pattern(
        self,
        editor,
        content,
        line_offsets,
        pattern,
        tag_name,
        start_index="1.0",
    ):
        for match in re.finditer(pattern, content, re.MULTILINE):
            start_offset, end_offset = match.span()
            if start_offset == end_offset:
                continue
            editor.tag_add(
                tag_name,
                editor.index(f"{start_index}+{start_offset}c"),
                editor.index(f"{start_index}+{end_offset}c"),
            )

    def highlight_syntax(self, editor, filename, line_only=False):
        self.highlight_timer = None

        extension = os.path.splitext(filename)[1].lower()
        keywords = self.get_language_keywords(extension)

        if line_only:
            start_index = editor.index("insert linestart")
            end_index = editor.index("insert lineend")
        else:
            start_index = "1.0"
            end_index = "end-1c"

        editor.tag_remove("keyword", start_index, end_index)
        editor.tag_remove("string", start_index, end_index)
        editor.tag_remove("comment", start_index, end_index)
        editor.tag_remove("number", start_index, end_index)

        content = editor.get(start_index, end_index)
        if not content:
            return

        line_offsets = [0]
        for match in re.finditer(r"\n", content):
            line_offsets.append(match.end())

        string_pattern = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
        number_pattern = r"\b\d+(?:\.\d+)?\b"

        if extension in {".py", ".rb", ".pl"}:
            comment_pattern = r"#.*"
        else:
            comment_pattern = r"//.*"

        if keywords:
            keyword_pattern = r"\b(?:%s)\b" % "|".join(
                re.escape(keyword) for keyword in keywords
            )
            self.add_matches_for_pattern(
                editor,
                content,
                line_offsets,
                keyword_pattern,
                "keyword",
                start_index=start_index,
            )

        self.add_matches_for_pattern(
            editor,
            content,
            line_offsets,
            string_pattern,
            "string",
            start_index=start_index,
        )
        self.add_matches_for_pattern(
            editor,
            content,
            line_offsets,
            comment_pattern,
            "comment",
            start_index=start_index,
        )
        self.add_matches_for_pattern(
            editor,
            content,
            line_offsets,
            number_pattern,
            "number",
            start_index=start_index,
        )

    def switch_to_file(self, filename):
        filename = self.normalize_path(filename)
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
        self.highlight_syntax(self.files[filename], filename, line_only=False)
        tree_item = self.tree_nodes.get(filename)
        if tree_item:
            self.file_tree.selection_set(tree_item)
            self.file_tree.focus(tree_item)
            self.file_tree.see(tree_item)

    def prompt_new_file(self):
        dialog = ctk.CTkInputDialog(
            text="Enter the new filename (example: utils.py):",
            title="Create New File",
        )
        filename = dialog.get_input()

        if filename is None:
            return

        filename = self.normalize_path(filename)
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
        if self.active_filename is None:
            return None
        return self.files[self.active_filename]

    def post_dropdown_menu(self, menu, button):
        x_position = button.winfo_rootx()
        y_position = button.winfo_rooty() + button.winfo_height()
        menu.post(x_position, y_position)
        return "break"

    def undo_active_editor(self):
        editor = self.get_active_editor()
        if editor is None:
            return

        try:
            editor.edit_undo()
        except tk.TclError:
            pass

    def redo_active_editor(self):
        editor = self.get_active_editor()
        if editor is None:
            return

        try:
            editor.edit_redo()
        except tk.TclError:
            pass

    def insert_four_spaces(self, event):
        event.widget.insert("insert", "    ")
        return "break"

    def format_time(self, total_seconds):
        minutes, seconds = divmod(max(total_seconds, 0), 60)
        return f"{minutes:02d}:{seconds:02d}"

    def update_timer(self):
        self.timer_label.configure(text=self.format_time(self.remaining_seconds))

        if self.remaining_seconds > 0:
            self.remaining_seconds -= 1
            self.after(1000, self.update_timer)

    def update_webcam_feed(self):
        frame, strikes = self.proctor.get_latest_frame_and_strikes()

        if frame is not None:
            pil_image = Image.fromarray(frame)
            ctk_image = ctk.CTkImage(light_image=pil_image, size=(180, 120))
            self.camera_image = ctk_image
            self.camera_label.configure(image=ctk_image, text="")

        if self.proctor.is_running:
            self.after(33, self.update_webcam_feed)
        else:
            self.after(250, self.update_webcam_feed)

    def cleanup_temp_dir(self):
        if self.current_temp_dir is not None:
            try:
                self.current_temp_dir.cleanup()
            except Exception as error:
                print(f"Temp directory cleanup failed: {error}")
            self.current_temp_dir = None

    def reset_run_button(self):
        self.run_button.configure(
            text="Run",
            fg_color="#2A2D2E",
            hover_color="#37373D",
            text_color="#CCCCCC",
            command=self.run_code,
        )

    def get_active_terminal(self):
        active_tab_name = self.terminal_tabview.get()
        return self.terminals[active_tab_name]

    def get_running_terminal(self):
        for terminal in self.terminals.values():
            if (
                terminal.current_process is not None
                and terminal.current_process.poll() is None
            ):
                return terminal
        return None

    def stop_process(self):
        self.proctor.is_running = False
        for terminal in self.terminals.values():
            if (
                terminal.current_process is not None
                and terminal.current_process.poll() is None
            ):
                terminal.stop_process()

    def _is_within_workspace(self, candidate_path):
        try:
            workspace_root = os.path.normcase(os.path.abspath(self.WORKSPACE_DIR))
            candidate_root = os.path.normcase(os.path.abspath(candidate_path))
            return (
                os.path.commonpath([workspace_root, candidate_root])
                == workspace_root
            )
        except ValueError:
            return False

    def add_terminal(self):
        base_name = "Terminal"
        tab_name = base_name
        spaces = ""
        while tab_name in self.terminals:
            spaces += " "
            tab_name = base_name + spaces

        tab = self.terminal_tabview.add(tab_name)
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        terminal = TerminalTab(tab, self)
        terminal.grid(row=0, column=0, sticky="nsew")

        self.terminals[tab_name] = terminal
        self.terminal_tabview.set(tab_name)

    def close_terminal(self):
        active_tab_name = self.terminal_tabview.get()
        if not active_tab_name or active_tab_name not in self.terminals:
            return

        terminal_to_close = self.terminals[active_tab_name]
        if (
            terminal_to_close.current_process is not None
            and terminal_to_close.current_process.poll() is None
        ):
            terminal_to_close.stop_process()

        self.terminal_tabview.delete(active_tab_name)
        del self.terminals[active_tab_name]

    def close_all_terminals(self):
        for tab_name in list(self.terminals.keys()):
            terminal = self.terminals[tab_name]
            if (
                terminal.current_process is not None
                and terminal.current_process.poll() is None
            ):
                terminal.stop_process()
            self.terminal_tabview.delete(tab_name)
            del self.terminals[tab_name]

    def submit_exam(self):
        self.sync_files_to_workspace()
        zip_path = shutil.make_archive("submission", "zip", self.WORKSPACE_DIR)
        roll_number = self.controller.frames["LoginFrame"].roll_number_var.get().strip()
        violation_count = getattr(
            self.ai_proctor,
            "violation_count",
            getattr(self.ai_proctor, "violation_strikes", 0),
        )

        try:
            with open(zip_path, "rb") as zip_file:
                files = {
                    "file": (os.path.basename(zip_path), zip_file, "application/zip")
                }
                payload = {
                    "roll_number": roll_number or "R001",
                    "violation_count": violation_count,
                }
                response = requests.post(
                    "http://127.0.0.1:8000/api/submit-zip/",
                    data=payload,
                    files=files,
                    timeout=5,
                )

            if response.status_code == 200:
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
                os.remove(zip_path)
            except OSError:
                pass

    def sync_files_to_workspace(self):
        """Mirror the in-memory editors onto the physical workspace."""
        os.makedirs(self.WORKSPACE_DIR, exist_ok=True)

        for filename, textbox in self.files.items():
            relative_path = os.path.normpath(filename)
            workspace_path = os.path.abspath(
                os.path.join(self.WORKSPACE_DIR, relative_path)
            )

            try:
                if (
                    os.path.commonpath(
                        [os.path.normcase(self.WORKSPACE_DIR), os.path.normcase(workspace_path)]
                    )
                    != os.path.normcase(self.WORKSPACE_DIR)
                ):
                    continue
            except ValueError:
                continue

            parent_dir = os.path.dirname(workspace_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            file_contents = textbox.get("1.0", "end-1c")
            with open(workspace_path, "w", encoding="utf-8") as workspace_file:
                workspace_file.write(file_contents)

    def handle_editor_autopair(self, event):
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
        should_exit = messagebox.askyesno(
            "Emergency Exit",
            "Are you sure you want to exit? This will forfeit your exam.",
        )
        if should_exit:
            self.controller.debug_close()

    def run_code(self):
        active_tab_name = self.terminal_tabview.get()
        active_terminal = self.terminals[active_tab_name]
        running_terminal = self.get_running_terminal()

        if running_terminal is not None:
            if running_terminal is active_terminal:
                active_terminal.append_terminal_output(
                    "\nA program is already running in this terminal.\n"
                )
            else:
                active_terminal.append_terminal_output(
                    "\nAnother terminal already has a running process. "
                    "Stop it before starting a new run.\n"
                )
            return

        active_file = self.active_filename

        if active_file not in self.files:
            active_terminal.append_terminal_output(
                "\nNo active file is available to run.\n"
            )
            return

        _, extension = os.path.splitext(active_file)
        extension = extension.lower()

        active_terminal.terminal_output.configure(state="normal")
        active_terminal.terminal_output.delete("1.0", "end")
        active_terminal.terminal_output.insert(
            "end",
            f"Executing {active_file}...\n",
        )
        active_terminal.terminal_output.insert("end", "-" * 30 + "\n")
        active_terminal.terminal_output.see("end")

        try:
            self.sync_files_to_workspace()
            self.cleanup_temp_dir()
            self.current_temp_dir = tempfile.TemporaryDirectory()
            temp_dir = self.current_temp_dir.name
            active_terminal.begin_streaming_process()

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

            if active_file.endswith("manage.py"):
                run_cmd = ["python", "-u", active_file, "runserver", "--noreload"]
            elif extension == ".py":
                run_cmd = ["python", "-u", active_file]
            elif extension in {".html", ".htm"}:
                run_cmd = ["python", "-u", "-m", "http.server", "8080"]
                build_target = "Local Web Server (Port 8080)"
            elif extension == ".c":
                compile_cmd = ["gcc", active_file, "-o", "out.exe"]
                run_cmd = [os.path.join(temp_dir, "out.exe")]
            elif extension == ".js":
                run_cmd = ["node", active_file]
            elif extension == ".rb":
                run_cmd = ["ruby", active_file]
            elif extension == ".pl":
                run_cmd = ["perl", active_file]
            elif extension == ".rs":
                compile_cmd = ["rustc", active_file]
                run_cmd = [
                    os.path.join(
                        temp_dir,
                        os.path.splitext(active_file)[0] + ".exe",
                    )
                ]
            elif extension == ".cpp":
                cpp_files = [
                    file_name for file_name in self.files
                    if file_name.lower().endswith(".cpp")
                ]
                if not cpp_files:
                    active_terminal.append_terminal_output(
                        "\nNo C++ files found to compile.\n"
                    )
                    active_terminal.is_flushing = False
                    self.cleanup_temp_dir()
                    active_terminal.print_shell_prompt()
                    return
                compile_cmd = ["g++", *cpp_files, "-o", "out.exe"]
                run_cmd = [os.path.join(temp_dir, "out.exe")]
                build_target = active_file
            elif extension == ".java":
                java_files = [
                    file_name for file_name in self.files
                    if file_name.lower().endswith(".java")
                ]
                if not java_files:
                    active_terminal.append_terminal_output(
                        "\nNo Java files found to compile.\n"
                    )
                    active_terminal.is_flushing = False
                    self.cleanup_temp_dir()
                    active_terminal.print_shell_prompt()
                    return
                compile_cmd = ["javac", *java_files]
                run_cmd = ["java", active_file.replace(".java", "")]
                build_target = active_file
            else:
                active_terminal.append_terminal_output(
                    f"\nRunning files with the extension '{extension}' is not supported yet.\n"
                )
                active_terminal.is_flushing = False
                self.cleanup_temp_dir()
                active_terminal.print_shell_prompt()
                return

            if compile_cmd is not None:
                active_terminal.append_terminal_output(
                    f"Compiling {build_target}...\n"
                )
                compile_result = subprocess.run(
                    compile_cmd,
                    capture_output=True,
                    text=True,
                    cwd=temp_dir,
                )
                if compile_result.stdout:
                    active_terminal.append_terminal_output(compile_result.stdout)
                if compile_result.stderr:
                    active_terminal.append_terminal_output(compile_result.stderr)
                if compile_result.returncode != 0:
                    active_terminal.append_terminal_output(
                        "\nCompilation failed. Program was not started.\n"
                    )
                    active_terminal.is_flushing = False
                    self.cleanup_temp_dir()
                    self.reset_run_button()
                    active_terminal.print_shell_prompt()
                    return

                active_terminal.append_terminal_output("Compilation successful.\n")

            active_terminal.current_process = subprocess.Popen(
                run_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=0,
                cwd=temp_dir,
            )

            if extension in {".html", ".htm"}:
                self.launch_browser(
                    f"http://127.0.0.1:8080/{os.path.basename(active_file)}",
                    terminal=active_terminal,
                )

            active_terminal.attach_process_watchdog(
                started_message=(
                    "Program started.\n"
                    "Use 'search http://127.0.0.1:8080' to open local web apps.\n"
                    if extension in {".html", ".htm"}
                    else "Program started.\n"
                ),
                finished_message="\nProgram finished.\n",
                cleanup_temp_dir=True,
            )

        except Exception as error:
            active_terminal.is_flushing = False
            active_terminal.append_terminal_output(
                f"\nCRITICAL ERROR: {error}\n"
            )
            active_terminal.current_process = None
            self.cleanup_temp_dir()
            self.reset_run_button()
            active_terminal.print_shell_prompt()
