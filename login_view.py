import tkinter as tk

import customtkinter as ctk


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
