import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock, call, patch


def import_bouncer_module():
    fake_ctypes = types.ModuleType("ctypes")
    fake_winreg = types.ModuleType("winreg")

    with patch.dict(sys.modules, {"ctypes": fake_ctypes, "winreg": fake_winreg}):
        sys.modules.pop("bouncer", None)
        return importlib.import_module("bouncer")


class WindowsBouncerTests(unittest.TestCase):
    def setUp(self):
        self.bouncer_module = import_bouncer_module()

    def make_bouncer(self, registry_client=None, os_controller=None):
        return self.bouncer_module.WindowsBouncer(
            logger=None,
            registry_client=registry_client,
            os_controller=os_controller,
        )

    def test_engage_lockdown_attempts_registry_disable_and_updates_state(self):
        registry_client = MagicMock()
        os_controller = MagicMock()
        bouncer = self.make_bouncer(
            registry_client=registry_client,
            os_controller=os_controller,
        )

        result = bouncer.engage_lockdown()

        self.assertTrue(result)
        registry_client.set_disable_taskmgr.assert_called_once_with(1)
        os_controller.stop_explorer.assert_called_once_with()
        self.assertTrue(bouncer.lockdown_active)
        self.assertFalse(bouncer.explorer_running)
        self.assertFalse(bouncer.task_manager_enabled)

    def test_release_lockdown_reverts_registry_value_and_restores_state(self):
        registry_client = MagicMock()
        os_controller = MagicMock()
        bouncer = self.make_bouncer(
            registry_client=registry_client,
            os_controller=os_controller,
        )
        self.assertTrue(bouncer.engage_lockdown())

        result = bouncer.release_lockdown()

        self.assertTrue(result)
        registry_client.set_disable_taskmgr.assert_has_calls([call(1), call(0)])
        os_controller.start_explorer.assert_called_once_with()
        self.assertFalse(bouncer.lockdown_active)
        self.assertTrue(bouncer.explorer_running)
        self.assertTrue(bouncer.task_manager_enabled)

    def test_engage_lockdown_handles_registry_permission_error(self):
        registry_client = MagicMock()
        registry_client.set_disable_taskmgr.side_effect = PermissionError(
            "Access denied"
        )
        os_controller = MagicMock()
        bouncer = self.make_bouncer(
            registry_client=registry_client,
            os_controller=os_controller,
        )

        result = bouncer.engage_lockdown()

        self.assertFalse(result)
        self.assertFalse(bouncer.lockdown_active)
        self.assertTrue(bouncer.explorer_running)
        self.assertTrue(bouncer.task_manager_enabled)
        os_controller.stop_explorer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
