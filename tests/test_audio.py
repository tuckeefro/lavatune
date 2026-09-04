from __future__ import annotations

import math
import os
import select
import struct
import subprocess
import unittest
from collections import deque
from unittest.mock import patch

from lavatune.audio import CAPTURE_BINARIES, AudioCapture, AudioFrame
from lavatune.config import BACKEND_NAMES, AudioConfig


def capture_shell(backend: str = "pipewire", source: str | None = None) -> AudioCapture:
    capture = AudioCapture.__new__(AudioCapture)
    capture.backend = backend
    capture.source = source
    capture.config = AudioConfig()
    capture._proc = None
    capture._stderr_tail = bytearray()
    return capture


def atlas_analyzer() -> AudioCapture:
    capture = AudioCapture.__new__(AudioCapture)
    capture.config = AudioConfig(analysis="atlas", sample_rate=16000, frame_size=1024)
    capture._atlas_history = deque([0.0] * 8, maxlen=8)
    capture._atlas_last = 0.0
    capture._atlas_lowpass = 0.0
    capture._atlas_midpass = 0.0
    capture._level_floor = 0.01
    capture._level_ceiling = 0.18
    capture._level_drive = 0.0
    return capture


def sine_chunk(frequency: float, sample_rate: int = 16000, size: int = 1024) -> bytes:
    samples = [
        int(math.sin(math.tau * frequency * index / sample_rate) * 12000)
        for index in range(size)
    ]
    return struct.pack("<" + "h" * size, *samples)


class FakeProcess:
    def __init__(self, timeout_once: bool = False) -> None:
        self.timeout_once = timeout_once
        self.terminated = False
        self.killed = False
        self.waits = 0

    def poll(self):
        return None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float):
        self.waits += 1
        if self.timeout_once and self.waits == 1:
            raise subprocess.TimeoutExpired("audio-backend", timeout)
        return 0


class AudioProcessTests(unittest.TestCase):
    def test_backend_binary_mapping_matches_public_backend_names(self) -> None:
        self.assertEqual(tuple(CAPTURE_BINARIES), BACKEND_NAMES[1:])

    @patch("lavatune.audio.platform.system", return_value="Linux")
    def test_capture_queue_is_bounded_sequenced_and_wakes_a_waiter(self, _system) -> None:
        with patch("lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"):
            capture = AudioCapture(AudioConfig())
        try:
            for sequence in range(12):
                capture._publish(
                    AudioFrame(0.1, [0.1] * 8, 0.0, 0.0, float(sequence + 1)),
                    0.001,
                )

            readable, _, _ = select.select([capture.fileno()], [], [], 0.05)
            frames = capture.drain_after(0)

            self.assertEqual(readable, [capture.fileno()])
            self.assertEqual(len(frames), 8)
            self.assertEqual([item.sequence for item in frames], list(range(5, 13)))
            frames_seen, analysis_seconds = capture.analysis_metrics()
            self.assertEqual(frames_seen, 12)
            self.assertAlmostEqual(analysis_seconds, 0.012)
            capture.consume_signal()
            with self.assertRaises(BlockingIOError):
                os.read(capture.fileno(), 1)
        finally:
            capture.stop()

    def test_atlas_single_pass_analysis_retains_coarse_tonal_contrast(self) -> None:
        low_capture = atlas_analyzer()
        high_capture = atlas_analyzer()

        for _ in range(4):
            low = low_capture._analyze_atlas(struct.unpack("<1024h", sine_chunk(120.0)))
            high = high_capture._analyze_atlas(struct.unpack("<1024h", sine_chunk(4200.0)))

        self.assertGreater(sum(low.bands[:3]), sum(low.bands[5:]) * 1.35)
        self.assertGreater(sum(high.bands[5:]), sum(high.bands[:3]) * 1.35)

    def test_source_is_one_subprocess_argument(self) -> None:
        source = "monitor; touch /tmp/not-executed"
        capture = capture_shell(source=source)

        command = capture._command()

        self.assertEqual(command[command.index("--target") + 1], source)

    @patch("lavatune.audio.platform.system", return_value="Linux")
    def test_linux_microphone_route_uses_backend_default_input(self, _system) -> None:
        cases = {
            "pipewire": "@DEFAULT_AUDIO_SOURCE@",
            "pulse": "@DEFAULT_SOURCE@",
            "ffmpeg": "default",
        }
        for backend, expected in cases.items():
            with self.subTest(backend=backend):
                capture = AudioCapture.__new__(AudioCapture)
                capture.backend = backend
                capture.config = AudioConfig(capture_route="microphone")
                self.assertEqual(capture._resolve_source(None), expected)

    def test_explicit_source_overrides_microphone_route(self) -> None:
        capture = AudioCapture.__new__(AudioCapture)
        capture.backend = "pipewire"
        capture.config = AudioConfig(capture_route="microphone")

        self.assertEqual(capture._resolve_source("my-input"), "my-input")

    @patch("lavatune.audio.platform.system", return_value="Darwin")
    def test_darwin_system_route_raises_runtime_error(self, _system) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            AudioCapture(AudioConfig(capture_route="system"))

        self.assertIn("Live system audio output capture is not supported on macOS", str(ctx.exception))

    @patch("lavatune.audio.platform.system", return_value="Darwin")
    @patch("lavatune.audio.shutil.which")
    def test_darwin_microphone_route_resolves_ffmpeg_source(self, which, _system) -> None:
        which.side_effect = lambda binary: f"/usr/bin/{binary}" if binary == "ffmpeg" else None

        capture = AudioCapture(AudioConfig(capture_route="microphone"))

        self.assertEqual(capture.backend, "ffmpeg")
        self.assertEqual(capture.source, ":default")

    @patch("lavatune.audio.platform.system", return_value="Darwin")
    @patch("lavatune.audio.shutil.which", return_value="/usr/bin/backend")
    def test_darwin_microphone_rejects_linux_only_explicit_backends(self, _which, _system) -> None:
        for backend in ("pipewire", "pulse"):
            with self.subTest(backend=backend):
                with self.assertRaises(RuntimeError) as ctx:
                    AudioCapture(AudioConfig(backend=backend, capture_route="microphone"))
                self.assertIn("is not supported on macOS", str(ctx.exception))

    @patch("lavatune.audio.platform.system", return_value="Linux")
    def test_linux_system_auto_does_not_fall_back_to_sox(self, _system) -> None:
        with patch(
            "lavatune.audio.shutil.which",
            side_effect=lambda binary: "/usr/bin/rec" if binary == "rec" else None,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                AudioCapture(AudioConfig(backend="auto", capture_route="system"))

        self.assertIn("system-output capture backend", str(ctx.exception))

    @patch("lavatune.audio.platform.system", return_value="Linux")
    def test_sox_backend_system_route_raises_runtime_error(self, _system) -> None:
        with patch("lavatune.audio.shutil.which", return_value="/usr/bin/rec"):
            with self.assertRaises(RuntimeError) as ctx:
                AudioCapture(AudioConfig(backend="sox", capture_route="system"))

            self.assertIn("sox' does not support system output capture", str(ctx.exception))

    def test_sox_backend_microphone_route_resolves_default_source(self) -> None:
        with patch("lavatune.audio.shutil.which", return_value="/usr/bin/rec"):
            capture = AudioCapture(AudioConfig(backend="sox", capture_route="microphone"))

            self.assertEqual(capture.backend, "sox")
            self.assertEqual(capture.source, "default")
            self.assertIn("rec", capture._command())

    def test_backend_status_and_diagnostics_are_sanitized(self) -> None:
        capture = capture_shell(source="monitor\x1b]0;spoof\x07")
        capture._stderr_tail.extend(b"failed\x1b]0;spoof\x07")

        self.assertEqual(capture.status(), "pipewire:monitor ]0;spoof :atlas")
        self.assertEqual(capture._backend_message(), "failed ]0;spoof")

    def test_stubborn_backend_is_killed_and_reaped(self) -> None:
        capture = capture_shell()
        process = FakeProcess(timeout_once=True)
        capture._proc = process

        capture._terminate_process()

        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertEqual(process.waits, 2)


def _get_open_fd_count() -> int:
    if os.path.exists("/proc/self/fd"):
        try:
            return len(os.listdir("/proc/self/fd"))
        except OSError:
            pass
    count = 0
    for fd in range(1024):
        try:
            dup_fd = os.dup(fd)
            os.close(dup_fd)
            count += 1
        except OSError:
            pass
    return count


CHILD_FIXTURE_SCRIPT = """
import sys, time, signal

args = sys.argv[1:]
if '--ignore-sigterm' in args:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

if '--fail-stderr' in args:
    sys.stderr.write("FATAL: Device or resource busy\\n")
    sys.stderr.flush()
    sys.exit(2)

if '--exit-early' in args:
    sys.stdout.buffer.write(b"12345")
    sys.stdout.buffer.flush()
    sys.exit(1)

try:
    while True:
        sys.stdout.buffer.write(b"\\0" * 4096)
        sys.stdout.buffer.flush()
        time.sleep(0.01)
except Exception:
    pass
"""


class AdversarialLifecycleTests(unittest.TestCase):
    def test_1_successful_start_stop(self) -> None:
        with patch("lavatune.audio.platform.system", return_value="Linux"), patch(
            "lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"
        ):
            capture = AudioCapture(AudioConfig())
        with patch.object(
            capture, "_command", return_value=[__import__("sys").executable, "-c", CHILD_FIXTURE_SCRIPT]
        ):
            capture.start()
            import time
            time.sleep(0.05)
            self.assertGreaterEqual(capture.frames_received(), 0)
            proc = capture._proc
            pid = proc.pid if proc else None
            capture.stop()

            self.assertIsNone(capture._proc)
            self.assertIsNone(capture._thread)
            self.assertIsNone(capture._stderr_thread)
            self.assertEqual(capture.fileno(), None)
            if pid is not None:
                with self.assertRaises(ChildProcessError):
                    os.waitpid(pid, os.WNOHANG)

    def test_2_stop_called_twice(self) -> None:
        with patch("lavatune.audio.platform.system", return_value="Linux"), patch(
            "lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"
        ):
            capture = AudioCapture(AudioConfig())
        with patch.object(
            capture, "_command", return_value=[__import__("sys").executable, "-c", CHILD_FIXTURE_SCRIPT]
        ):
            capture.start()
            capture.stop()
            fd_before = _get_open_fd_count()
            capture.stop()
            fd_after = _get_open_fd_count()
            self.assertEqual(fd_before, fd_after)

    def test_3_backend_spawn_failure(self) -> None:
        with patch("lavatune.audio.platform.system", return_value="Linux"), patch(
            "lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"
        ):
            capture = AudioCapture(AudioConfig())
        with patch(
            "subprocess.Popen", side_effect=FileNotFoundError(2, "No such file or directory", "pw-cat")
        ):
            with self.assertRaises(RuntimeError) as ctx:
                capture.start()
            self.assertIn("Missing executable", str(ctx.exception))
            self.assertEqual(capture._state, "STOPPED")
            self.assertIsNone(capture.fileno())

    def test_4_popen_succeeds_but_initialization_fails_afterward(self) -> None:
        with patch("lavatune.audio.platform.system", return_value="Linux"), patch(
            "lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"
        ):
            capture = AudioCapture(AudioConfig())
        with patch.object(
            capture, "_command", return_value=[__import__("sys").executable, "-c", CHILD_FIXTURE_SCRIPT]
        ), patch(
            "threading.Thread.start", side_effect=RuntimeError("Thread allocation limit reached")
        ):
            with self.assertRaises(RuntimeError):
                capture.start()
            self.assertEqual(capture._state, "STOPPED")
            self.assertIsNone(capture._proc)
            self.assertIsNone(capture.fileno())

    def test_5_backend_exits_unexpectedly(self) -> None:
        with patch("lavatune.audio.platform.system", return_value="Linux"), patch(
            "lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"
        ):
            capture = AudioCapture(AudioConfig())
        with patch.object(
            capture,
            "_command",
            return_value=[__import__("sys").executable, "-c", CHILD_FIXTURE_SCRIPT, "--exit-early"],
        ):
            capture.start()
            import time
            for _ in range(50):
                if capture.error():
                    break
                time.sleep(0.02)
            self.assertIsNotNone(capture.error())
            self.assertIn("Audio capture stopped for backend", capture.error())
            capture.stop()

    def test_6_backend_ignores_terminate_and_requires_kill(self) -> None:
        with patch("lavatune.audio.platform.system", return_value="Linux"), patch(
            "lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"
        ):
            capture = AudioCapture(AudioConfig())
        with patch.object(
            capture,
            "_command",
            return_value=[__import__("sys").executable, "-c", CHILD_FIXTURE_SCRIPT, "--ignore-sigterm"],
        ):
            capture.start()
            import time
            time.sleep(0.05)
            proc = capture._proc
            pid = proc.pid if proc else None
            capture.stop()

            self.assertIsNone(capture._proc)
            if pid is not None:
                with self.assertRaises(ChildProcessError):
                    os.waitpid(pid, os.WNOHANG)

    def test_7_stderr_producing_backend_failure(self) -> None:
        with patch("lavatune.audio.platform.system", return_value="Linux"), patch(
            "lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"
        ):
            capture = AudioCapture(AudioConfig())
        with patch.object(
            capture,
            "_command",
            return_value=[__import__("sys").executable, "-c", CHILD_FIXTURE_SCRIPT, "--fail-stderr"],
        ):
            capture.start()
            import time
            for _ in range(50):
                if capture.error():
                    break
                time.sleep(0.02)
            self.assertIsNotNone(capture.error())
            self.assertIn("FATAL: Device or resource busy", capture.error())
            capture.stop()

    def test_8_ctrl_c_keyboard_interrupt_top_level(self) -> None:
        from lavatune.__main__ import _install_signal_handlers
        _install_signal_handlers()
        import signal
        handler = signal.getsignal(signal.SIGTERM)
        self.assertTrue(callable(handler))

    def test_9_10_threads_exit(self) -> None:
        with patch("lavatune.audio.platform.system", return_value="Linux"), patch(
            "lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"
        ):
            capture = AudioCapture(AudioConfig())
        with patch.object(
            capture, "_command", return_value=[__import__("sys").executable, "-c", CHILD_FIXTURE_SCRIPT]
        ):
            capture.start()
            t_cap = capture._thread
            t_err = capture._stderr_thread
            self.assertTrue(t_cap is not None and t_cap.is_alive())
            self.assertTrue(t_err is not None and t_err.is_alive())
            capture.stop()
            self.assertFalse(t_cap.is_alive())
            self.assertFalse(t_err.is_alive())

    def test_11_descriptor_cleanup(self) -> None:
        fd_baseline = _get_open_fd_count()
        with patch("lavatune.audio.platform.system", return_value="Linux"), patch(
            "lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"
        ):
            capture = AudioCapture(AudioConfig())
        with patch.object(
            capture, "_command", return_value=[__import__("sys").executable, "-c", CHILD_FIXTURE_SCRIPT]
        ):
            capture.start()
            import time
            time.sleep(0.02)
            capture.stop()
        fd_after = _get_open_fd_count()
        self.assertEqual(fd_baseline, fd_after)

    def test_12_no_zombie_child_after_shutdown(self) -> None:
        with patch("lavatune.audio.platform.system", return_value="Linux"), patch(
            "lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"
        ):
            capture = AudioCapture(AudioConfig())
        with patch.object(
            capture, "_command", return_value=[__import__("sys").executable, "-c", CHILD_FIXTURE_SCRIPT]
        ):
            capture.start()
            pid = capture._proc.pid
            capture.stop()
            with self.assertRaises(ChildProcessError):
                os.waitpid(pid, os.WNOHANG)

    def test_13_single_use_start_after_stop_contract(self) -> None:
        with patch("lavatune.audio.platform.system", return_value="Linux"), patch(
            "lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"
        ):
            capture = AudioCapture(AudioConfig())
        with patch.object(
            capture, "_command", return_value=[__import__("sys").executable, "-c", CHILD_FIXTURE_SCRIPT]
        ):
            capture.start()
            with self.assertRaises(RuntimeError) as ctx1:
                capture.start()
            self.assertIn("already running", str(ctx1.exception))
            capture.stop()
            with self.assertRaises(RuntimeError) as ctx2:
                capture.start()
            self.assertIn("single-use and cannot be restarted", str(ctx2.exception))

    def test_14_repeated_cycles_no_growth(self) -> None:
        import threading
        fd_baseline = _get_open_fd_count()
        threads_baseline = threading.active_count()

        for _ in range(15):
            with patch("lavatune.audio.platform.system", return_value="Linux"), patch(
                "lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"
            ):
                capture = AudioCapture(AudioConfig())
            with patch.object(
                capture, "_command", return_value=[__import__("sys").executable, "-c", CHILD_FIXTURE_SCRIPT]
            ):
                capture.start()
                import time
                time.sleep(0.01)
                capture.stop()

        fd_after = _get_open_fd_count()
        threads_after = threading.active_count()
        self.assertEqual(threads_baseline, threads_after)
        self.assertEqual(fd_baseline, fd_after)


class SoakLeakTests(unittest.TestCase):
    def test_lifecycle_soak_leak_proof(self) -> None:
        import threading, time
        baseline_fds = _get_open_fd_count()
        baseline_threads = threading.active_count()

        iterations = 10
        for _ in range(iterations):
            with patch("lavatune.audio.platform.system", return_value="Linux"), patch(
                "lavatune.audio.shutil.which", return_value="/usr/bin/pw-cat"
            ):
                capture = AudioCapture(AudioConfig())
            with patch.object(
                capture,
                "_command",
                return_value=[__import__("sys").executable, "-c", CHILD_FIXTURE_SCRIPT],
            ):
                capture.start()
                time.sleep(0.02)
                capture.stop()

        self.assertEqual(threading.active_count(), baseline_threads)
        self.assertEqual(_get_open_fd_count(), baseline_fds)


if __name__ == "__main__":
    unittest.main()
