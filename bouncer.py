"""
Safe mock Windows lockdown controller for local integration testing.

WARNING:
This module does not modify the operating system.
It does not kill explorer.exe, edit the registry, or disable Task Manager.
It only simulates those actions in memory so the kiosk UI can be integrated
and tested without touching the host machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional


EventCallback = Callable[[str], None]


@dataclass
class WindowsBouncer:
    """
    Test-friendly mock of a Windows kiosk lockdown service.

    The public API intentionally mirrors what a real OS-level controller might
    expose, so it can be swapped later with a production implementation.
    """

    logger: Optional[EventCallback] = print
    lockdown_active: bool = False
    explorer_running: bool = True
    task_manager_enabled: bool = True
    history: List[str] = field(default_factory=list)

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _record(self, message: str) -> None:
        entry = f"[{self._timestamp()}] {message}"
        self.history.append(entry)
        if self.logger is not None:
            self.logger(entry)

    def engage_lockdown(self) -> bool:
        """
        Simulate engaging a kiosk lockdown.

        Returns True when the state changed, or False if lockdown was already
        active. This makes UI integrations easy to reason about.
        """
        if self.lockdown_active:
            self._record("Lockdown request ignored: lockdown already active.")
            return False

        self._record("Engaging mock lockdown.")
        self._record("Simulating explorer.exe termination.")
        self.explorer_running = False

        self._record("Simulating Task Manager policy disable.")
        self.task_manager_enabled = False

        self.lockdown_active = True
        self._record("Mock lockdown engaged successfully.")
        return True

    def release_lockdown(self) -> bool:
        """
        Simulate releasing a kiosk lockdown.

        Returns True when the state changed, or False if lockdown was already
        inactive.
        """
        if not self.lockdown_active:
            self._record("Release request ignored: lockdown already inactive.")
            return False

        self._record("Releasing mock lockdown.")
        self._record("Simulating explorer.exe restart.")
        self.explorer_running = True

        self._record("Simulating Task Manager policy re-enable.")
        self.task_manager_enabled = True

        self.lockdown_active = False
        self._record("Mock lockdown released successfully.")
        return True

    def get_status(self) -> Dict[str, bool]:
        """
        Return a snapshot of the current simulated OS state.
        """
        return {
            "lockdown_active": self.lockdown_active,
            "explorer_running": self.explorer_running,
            "task_manager_enabled": self.task_manager_enabled,
        }

    def status_text(self) -> str:
        """
        Human-readable state summary for terminal or Tkinter display.
        """
        status = self.get_status()
        return (
            "Lockdown active: {lockdown_active}\n"
            "Explorer running: {explorer_running}\n"
            "Task Manager enabled: {task_manager_enabled}"
        ).format(**status)


def run_terminal_demo() -> None:
    """
    Minimal terminal menu for testing the mock bouncer by hand.
    """

    def menu_logger(message: str) -> None:
        print(message)

    bouncer = WindowsBouncer(logger=menu_logger)

    while True:
        print("\nMock Windows Bouncer")
        print("1. Engage lockdown")
        print("2. Release lockdown")
        print("3. Show status")
        print("4. Show event history")
        print("5. Exit")

        choice = input("Choose an option: ").strip()

        if choice == "1":
            changed = bouncer.engage_lockdown()
            if not changed:
                print("No state change was needed.")
        elif choice == "2":
            changed = bouncer.release_lockdown()
            if not changed:
                print("No state change was needed.")
        elif choice == "3":
            print("\n" + bouncer.status_text())
        elif choice == "4":
            print("\nEvent history:")
            if not bouncer.history:
                print("No events recorded yet.")
            else:
                for entry in bouncer.history:
                    print(entry)
        elif choice == "5":
            print("Exiting mock bouncer.")
            break
        else:
            print("Invalid choice. Please select 1, 2, 3, 4, or 5.")


if __name__ == "__main__":
    run_terminal_demo()
