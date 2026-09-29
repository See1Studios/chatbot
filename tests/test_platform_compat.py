"""PLATFORM_COMPAT_v1 (platform-portability pp/D, #397): file locks and the /proc check behave the same on every OS.
Run on FIREBAT (Windows) and here (Linux). Run: python3 -m unittest tests.test_platform_compat  (from services/chatbot)
"""
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import platform_compat as pc  # noqa: E402

HOLD = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, sys.argv[2])
    import platform_compat as pc
    fh = open(sys.argv[1], "a")
    pc.lock_file(fh)
    print("held", flush=True)
    time.sleep(3)
""")


class FileLock(unittest.TestCase):
    def test_a_second_process_cannot_take_a_held_lock(self):
        path = Path(tempfile.mkdtemp()) / "x.lock"
        holder = subprocess.Popen([sys.executable, "-c", HOLD, str(path), str(ROOT)], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            with open(str(path), "a") as fh:
                self.assertFalse(pc.lock_file(fh, blocking=False))
        finally:
            holder.kill()
            holder.wait()
        with open(str(path), "a") as fh:                      # the holder is gone: free again
            deadline = time.time() + 5                        # Windows lets go of a dead process's lock a little later
            got = pc.lock_file(fh, blocking=False)            # once per handle: a Windows lock is not re-entrant
            while not got and time.time() < deadline:
                time.sleep(0.1)
                got = pc.lock_file(fh, blocking=False)
            self.assertTrue(got)
            pc.unlock_file(fh)

    def test_without_any_locking_it_fails_open(self):
        with mock.patch.object(pc, "fcntl", None), mock.patch.object(pc, "msvcrt", None):
            with tempfile.TemporaryFile("a+") as fh:
                self.assertTrue(pc.lock_file(fh, blocking=False))


class NamesAndText(unittest.TestCase):
    def test_a_name_is_found_as_spelled_on_disk(self):
        # #405: on a case-insensitive disk (Windows, macOS) is_file() says yes to ROLE.md when only role.md is there
        d = Path(tempfile.mkdtemp())
        (d / "role.md").write_bytes(b"x")
        self.assertEqual(Path(pc.named_file(d, ("ROLE.md", "role.md"))).name, "role.md")
        (d / "role.md").unlink()
        (d / "ROLE.md").write_bytes(b"x")
        self.assertEqual(Path(pc.named_file(d, ("ROLE.md", "role.md"))).name, "ROLE.md")
        self.assertIsNone(pc.named_file(d, ("PROCEDURE.md",)))
        self.assertIsNone(pc.named_file(d / "missing", ("ROLE.md",)))

    def test_text_is_written_with_lf_everywhere(self):
        f = Path(tempfile.mkdtemp()) / "card.json"
        pc.write_text(f, "a\nb\n")
        self.assertEqual(f.read_bytes(), b"a\nb\n")


class HttpServer(unittest.TestCase):
    def test_no_second_socket_can_share_the_port(self):
        # #409: with SO_REUSEADDR a Windows socket may bind a port another socket already holds
        import socket
        from http.server import BaseHTTPRequestHandler
        srv = pc.http_server(("127.0.0.1", 0), BaseHTTPRequestHandler)
        try:
            port = srv.server_address[1]
            other = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                with self.assertRaises(OSError):
                    other.bind(("127.0.0.1", port))
            finally:
                other.close()
        finally:
            srv.server_close()


class ProcScan(unittest.TestCase):
    def test_no_proc_means_an_empty_scan_not_a_crash(self):
        from providers import accounts
        with mock.patch.object(pc, "has_proc", return_value=False):
            self.assertEqual(accounts._scan_procs(), {p: [] for p in accounts.PROVIDERS})


if __name__ == "__main__":
    unittest.main()
