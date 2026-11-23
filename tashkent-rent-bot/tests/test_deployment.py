import contextlib
import io
import subprocess
import traceback
import unittest
from unittest.mock import patch

from deployment import install as installer


class DeploymentTests(unittest.TestCase):
    def test_windows_install_and_check_stop_before_any_system_actions(self):
        for action in ("--install", "--check"):
            with self.subTest(action=action), patch.object(installer.sys, "platform", "win32"), \
                    patch.object(installer, "install") as install, \
                    patch.object(installer, "check") as check, \
                    patch.object(installer.subprocess, "run") as execute, \
                    contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(installer.main([action]), 1)
                self.assertIn("Ubuntu server", output.getvalue())
                install.assert_not_called()
                check.assert_not_called()
                execute.assert_not_called()

    def test_failed_command_does_not_disclose_output_or_command_arguments(self):
        secret = "https://user:fake-secret@example.invalid/package"
        result = subprocess.CompletedProcess(["pip", secret], 1, stdout=secret)
        with patch.object(installer.subprocess, "run", return_value=result):
            with self.assertRaises(installer.InstallError) as raised:
                installer.run_command(["pip", secret], "install dependencies")
        self.assertIn("install dependencies", str(raised.exception))
        self.assertNotIn(secret, str(raised.exception))

    def test_subprocess_exception_does_not_disclose_its_context(self):
        secret = "https://user:fake-secret@example.invalid/"
        with patch.object(installer.subprocess, "run", side_effect=OSError(secret)):
            try:
                installer.run_command(["pip"], "install dependencies")
            except installer.InstallError as error:
                self.assertNotIn(secret, "".join(traceback.format_exception(error)))
            else:
                self.fail("Expected a sanitized installation failure")

    def test_unexpected_failure_prints_only_exception_type(self):
        secret = "credential-value-in-original-error"
        with patch.object(installer, "require_host", side_effect=ValueError(secret)), \
                contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(installer.main(["--check"]), 1)
        self.assertIn("ValueError", output.getvalue())
        self.assertNotIn(secret, output.getvalue())


if __name__ == "__main__":
    unittest.main()
