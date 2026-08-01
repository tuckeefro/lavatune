from __future__ import annotations

import fcntl
import os
import pty
import struct
import subprocess
import sys
import termios
import time
import unittest


def resize(fd: int, rows: int, columns: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))


class RuntimeTests(unittest.TestCase):
    def test_compact_resize_race_does_not_crash_renderer(self) -> None:
        master, slave = pty.openpty()
        resize(slave, 3, 12)
        environment = dict(os.environ)
        environment.update(
            {
                "TERM": "xterm-256color",
                "LAVATUNE_HIDE_DOCK": "1",
            }
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "lavatune",
                "--demo",
                "--compact-tile",
                "--no-stats",
            ],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=environment,
        )
        os.close(slave)
        output = bytearray()
        try:
            time.sleep(0.25)
            self.assertIsNone(process.poll())
            resize(master, 24, 80)
            time.sleep(0.45)
            self.assertIsNone(process.poll())
            os.write(master, b"q")
            self.assertEqual(process.wait(timeout=3), 0)
            while True:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)
            os.close(master)

        self.assertNotIn(b"Traceback", output)


if __name__ == "__main__":
    unittest.main()
