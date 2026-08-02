"""Linux monitor capture and lightweight PCM analysis."""

from __future__ import annotations

import math
import os
import shutil
import struct
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass

from .config import AudioConfig
from .text import sanitize_display_text


CAPTURE_BINARIES: dict[str, str] = {
    "pipewire": "pw-cat",
    "pulse": "parec",
    "ffmpeg": "ffmpeg",
}


@dataclass(slots=True)
class AudioFrame:
    """One normalized analysis window consumed by the organism."""

    rms: float
    bands: list[float]
    attack: float
    zcr: float
    timestamp: float


@dataclass(slots=True, frozen=True)
class CapturedAudioFrame:
    """One analyzed capture window with a loss-aware sequence number."""

    sequence: int
    frame: AudioFrame


class AudioCapture:
    """Read signed 16-bit PCM from one local Linux audio backend."""

    def __init__(self, config: AudioConfig) -> None:
        self.config = config
        self._frames: deque[CapturedAudioFrame] = deque(maxlen=8)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._stderr_tail = bytearray()
        self._error: str | None = None
        self.backend = self._pick_backend(config.backend)
        self.source = self._resolve_source(config.source)
        self._atlas_history: deque[float] = deque([0.0] * 8, maxlen=8)
        self._atlas_last = 0.0
        self._atlas_lowpass = 0.0
        self._atlas_midpass = 0.0
        self._level_floor = 0.01
        self._level_ceiling = 0.18
        self._level_drive = 0.0
        self._sequence = 0
        self._analysis_seconds = 0.0
        self._analysis_frames = 0
        self._notify_read, self._notify_write = os.pipe()
        for descriptor in (self._notify_read, self._notify_write):
            os.set_blocking(descriptor, False)
            os.set_inheritable(descriptor, False)

    def status(self) -> str:
        return sanitize_display_text(
            f"{self.backend}:{self.source or 'default'}:{self.config.analysis}"
        )

    def error(self) -> str | None:
        return self._error

    def frames_received(self) -> int:
        with self._lock:
            return len(self._frames)

    def fileno(self) -> int:
        return self._notify_read

    def consume_signal(self) -> None:
        try:
            while os.read(self._notify_read, 256):
                pass
        except (BlockingIOError, OSError):
            pass

    def drain_after(self, sequence: int) -> list[CapturedAudioFrame]:
        with self._lock:
            return [captured for captured in self._frames if captured.sequence > sequence]

    def analysis_metrics(self) -> tuple[int, float]:
        with self._lock:
            return self._analysis_frames, self._analysis_seconds

    def _publish(self, frame: AudioFrame, analysis_seconds: float) -> None:
        with self._lock:
            self._sequence += 1
            self._frames.append(CapturedAudioFrame(self._sequence, frame))
            self._analysis_frames += 1
            self._analysis_seconds += analysis_seconds
        try:
            os.write(self._notify_write, b"\0")
        except (BlockingIOError, OSError):
            pass

    def start(self) -> None:
        if self._thread is not None:
            return
        self._spawn_process()
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            name="lavatune-audio-stderr",
            daemon=True,
        )
        self._stderr_thread.start()
        self._thread = threading.Thread(target=self._run, name="lavatune-audio", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._terminate_process()
        if self._thread is not None:
            self._thread.join(timeout=0.75)
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=0.25)
        for descriptor in (self._notify_read, self._notify_write):
            try:
                os.close(descriptor)
            except OSError:
                pass

    def latest(self) -> AudioFrame:
        with self._lock:
            if self._frames:
                return self._frames[-1].frame
        return AudioFrame(
            rms=0.0,
            bands=[0.0] * 8,
            attack=0.0,
            zcr=0.0,
            timestamp=time.monotonic(),
        )

    def _pick_backend(self, preferred: str) -> str:
        if preferred != "auto":
            if preferred not in CAPTURE_BINARIES:
                raise RuntimeError(f"Unsupported audio backend '{preferred}'")
            if shutil.which(CAPTURE_BINARIES[preferred]) is None:
                raise RuntimeError(
                    f"Audio backend '{preferred}' requires "
                    f"'{CAPTURE_BINARIES[preferred]}' in PATH."
                )
            return preferred
        for backend, binary in CAPTURE_BINARIES.items():
            if shutil.which(binary):
                return backend
        raise RuntimeError(
            "No supported audio capture backend found. Install pw-cat, parec, or ffmpeg."
        )

    def _resolve_source(self, configured: str | None) -> str | None:
        if configured:
            return configured
        if self.backend == "pipewire":
            return "@DEFAULT_AUDIO_SINK@.monitor"
        if self.backend in {"pulse", "ffmpeg"}:
            return "@DEFAULT_MONITOR@"
        return None

    def _spawn_process(self) -> None:
        try:
            self._proc = subprocess.Popen(
                self._command(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Failed to start backend '{self.backend}'. Missing executable: {exc.filename}"
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"Failed to start backend '{self.backend}': {exc}") from exc

        if self._proc.stdout is None:
            raise RuntimeError("Audio capture stdout was not available")

    def _drain_stderr(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return
        # Backends can be noisy. Drain continuously so their pipe cannot block
        # capture, but retain only enough tail text to explain a failure.
        while chunk := self._proc.stderr.read(512):
            self._stderr_tail.extend(chunk)
            if len(self._stderr_tail) > 2048:
                del self._stderr_tail[:-2048]

    def _backend_message(self) -> str:
        decoded = bytes(self._stderr_tail).decode("utf-8", errors="replace")
        return sanitize_display_text(decoded, max_chars=512)

    def _terminate_process(self) -> None:
        process = self._proc
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=0.5)

    def _command(self) -> list[str]:
        rate = str(self.config.sample_rate)
        channels = str(self.config.channels)
        if self.backend == "pipewire":
            command = [
                "pw-cat",
                "--record",
                "--format",
                "s16",
                "--rate",
                rate,
                "--channels",
                channels,
            ]
            if self.source:
                command.extend(["--target", self.source])
            command.append("-")
            return command
        if self.backend == "pulse":
            command = [
                "parec",
                "--format=s16le",
                f"--rate={rate}",
                f"--channels={channels}",
            ]
            if self.source:
                command.append(f"--device={self.source}")
            return command
        if self.backend == "ffmpeg":
            source = self.source or "default"
            return [
                "ffmpeg",
                "-loglevel",
                "error",
                "-f",
                "pulse",
                "-i",
                source,
                "-ac",
                channels,
                "-ar",
                rate,
                "-f",
                "s16le",
                "-",
            ]
        raise RuntimeError(f"Unsupported backend '{self.backend}'")

    def _run(self) -> None:
        if self._proc is None or self._proc.stdout is None:
            self._error = "Audio capture was not initialized."
            return

        bytes_per_frame = self.config.frame_size * self.config.channels * 2
        while not self._stop.is_set():
            chunk = self._proc.stdout.read(bytes_per_frame)
            if not chunk:
                if self._proc.poll() is not None:
                    if not self._stop.is_set():
                        if self._stderr_thread is not None:
                            self._stderr_thread.join(timeout=0.05)
                        stderr = self._backend_message()
                        detail = f" Backend message: {stderr}" if stderr else ""
                        self._error = (
                            f"Audio capture stopped for backend '{self.backend}' using "
                            f"source '{sanitize_display_text(str(self.source))}'. "
                            f"Try setting --source explicitly or "
                            f"switching --backend.{detail}"
                        )
                    break
                time.sleep(0.01)
                continue

            started = time.perf_counter()
            frame = self._analyze(chunk)
            elapsed = time.perf_counter() - started
            self._publish(frame, elapsed)

        if self._proc.poll() is None:
            self._terminate_process()

    def _analyze(self, chunk: bytes) -> AudioFrame:
        sample_count = len(chunk) // 2
        if sample_count == 0:
            return AudioFrame(
                rms=0.0,
                bands=[0.0] * 8,
                attack=0.0,
                zcr=0.0,
                timestamp=time.monotonic(),
            )

        samples = struct.unpack("<" + "h" * sample_count, chunk)
        if self.config.analysis == "atlas":
            return self._analyze_atlas(samples)
        norm = []
        total = 0.0
        sign_changes = 0
        previous_positive = samples[0] >= 0
        for sample in samples:
            value = sample / 32768.0
            norm.append(value)
            total += value * value
            positive = sample >= 0
            if positive != previous_positive:
                sign_changes += 1
                previous_positive = positive
        rms = math.sqrt(total / len(norm))
        attack = max(0.0, rms - self._atlas_last)
        self._atlas_last = rms * 0.55 + self._atlas_last * 0.45
        zcr = sign_changes / max(1, len(samples) - 1)
        bands = self._band_energy(norm, self.config.sample_rate)
        rms, attack = self._normalize_level(rms, attack)
        bands = [
            min(1.0, (band ** 0.88) * (0.35 + rms * 0.65) + attack * 0.28)
            for band in bands
        ]
        return AudioFrame(
            rms=rms,
            bands=bands,
            attack=attack,
            zcr=zcr,
            timestamp=time.monotonic(),
        )

    def _analyze_atlas(self, samples: tuple[int, ...]) -> AudioFrame:
        if not samples:
            return AudioFrame(
                rms=0.0,
                bands=[0.0] * 8,
                attack=0.0,
                zcr=0.0,
                timestamp=time.monotonic(),
            )

        # Atlas gets a coarse low/mid/high shape from two one-pole filters in
        # the same pass as its envelope. This remains much cheaper than the
        # eight-filter Goertzel mode while giving bodies real tonal contrast.
        step = 2 if len(samples) >= 2048 else 1
        total = 0.0
        peak = 0.0
        low_total = 0.0
        mid_total = 0.0
        high_total = 0.0
        count = 0
        sign_changes = 0
        previous_positive = samples[0] >= 0
        effective_step = step / max(1, self.config.sample_rate)
        low_alpha = 1.0 - math.exp(-math.tau * 220.0 * effective_step)
        mid_alpha = 1.0 - math.exp(-math.tau * 1900.0 * effective_step)
        for sample in samples[::step]:
            signed = sample / 32768.0
            value = abs(signed)
            total += signed * signed
            peak = max(peak, value)
            self._atlas_lowpass += low_alpha * (signed - self._atlas_lowpass)
            self._atlas_midpass += mid_alpha * (signed - self._atlas_midpass)
            low = self._atlas_lowpass
            mid = self._atlas_midpass - self._atlas_lowpass
            high = signed - self._atlas_midpass
            low_total += low * low
            mid_total += mid * mid
            high_total += high * high
            positive = sample >= 0
            if positive != previous_positive:
                sign_changes += 1
                previous_positive = positive
            count += 1

        rms = math.sqrt(total / max(1, count))
        envelope = min(1.0, rms * 1.35 + peak * 0.30)
        attack = max(0.0, envelope - self._atlas_last)
        self._atlas_last = envelope * 0.55 + self._atlas_last * 0.45
        envelope, attack = self._normalize_level(envelope, attack)
        drive = min(1.0, envelope * 0.95 + attack * 1.85)
        zcr = sign_changes / max(1, count - 1)

        low_level = math.sqrt(low_total / max(1, count))
        mid_level = math.sqrt(mid_total / max(1, count))
        high_level = math.sqrt(high_total / max(1, count))
        spectral_total = max(0.0001, low_level + mid_level + high_level)
        low_shape = low_level / spectral_total
        mid_shape = mid_level / spectral_total
        high_shape = high_level / spectral_total
        shape = (
            low_shape,
            low_shape * 0.78 + mid_shape * 0.22,
            low_shape * 0.28 + mid_shape * 0.72,
            mid_shape,
            mid_shape * 0.68 + high_shape * 0.32,
            mid_shape * 0.25 + high_shape * 0.75,
            high_shape * 0.90,
            high_shape,
        )
        shape_peak = max(0.0001, max(shape))
        targets = [min(1.0, drive * (0.24 + value / shape_peak * 0.76)) for value in shape]
        bands = []
        for index, target in enumerate(targets):
            previous = self._atlas_history[index]
            bands.append(max(target, previous * 0.70))
        self._atlas_history = deque(bands, maxlen=8)
        return AudioFrame(
            rms=envelope,
            bands=bands,
            attack=attack,
            zcr=zcr,
            timestamp=time.monotonic(),
        )

    def _normalize_level(self, level: float, attack: float) -> tuple[float, float]:
        # Audio sources vary wildly in loudness. The floor moves slowly upward,
        # while the ceiling catches peaks quickly and relaxes over time.
        if level > self._level_ceiling:
            self._level_ceiling = self._level_ceiling * 0.90 + level * 0.10
        else:
            self._level_ceiling = max(level, self._level_ceiling * 0.998 + level * 0.002)

        if level < self._level_floor:
            self._level_floor = self._level_floor * 0.85 + level * 0.15
        else:
            self._level_floor = self._level_floor * 0.999 + level * 0.001

        if self._level_ceiling < self._level_floor + 0.08:
            self._level_ceiling = self._level_floor + 0.08

        span = self._level_ceiling - self._level_floor
        normalized = max(0.0, min(1.0, (level - self._level_floor) / span))
        attack_norm = max(0.0, min(1.0, attack / span * 2.4))

        self._level_drive = self._level_drive * 0.96 + normalized * 0.04
        sustained = max(0.0, self._level_drive - attack_norm * 0.55)
        normalized = max(
            0.0,
            min(1.0, normalized * (0.82 + attack_norm * 0.55) - sustained * 0.26),
        )
        return normalized, attack_norm

    def _band_energy(self, samples: list[float], sample_rate: int) -> list[float]:
        # A small Goertzel bank is cheaper than a general FFT at this scale and
        # gives the force mapper stable low/voice/detail anchors.
        targets = [80, 160, 320, 640, 1250, 2500, 5000, min(9000, sample_rate * 0.45)]
        energies = []
        n = len(samples)
        for freq in targets:
            omega = 2.0 * math.pi * freq / sample_rate
            coeff = 2.0 * math.cos(omega)
            s_prev = 0.0
            s_prev2 = 0.0
            for sample in samples:
                s = sample + coeff * s_prev - s_prev2
                s_prev2 = s_prev
                s_prev = s
            power = s_prev2 * s_prev2 + s_prev * s_prev - coeff * s_prev * s_prev2
            energies.append(min(1.0, math.sqrt(max(power, 0.0)) / max(n, 1) * 8.0))
        return energies


class DemoAudioCapture:
    """Produce a repeatable moving signal for demos and terminal smoke tests."""

    def __init__(self) -> None:
        self._start = time.monotonic()
        self._sequence = 0
        self._last_tick = -1

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    @staticmethod
    def fileno() -> None:
        return None

    @staticmethod
    def consume_signal() -> None:
        return None

    @staticmethod
    def analysis_metrics() -> tuple[int, float]:
        return 0, 0.0

    @staticmethod
    def status() -> str:
        return "demo:synth:atlas"

    @staticmethod
    def error() -> str | None:
        return None

    def _frame(self, tick: int) -> AudioFrame:
        t = tick / 30.0
        bands = []
        for index in range(8):
            base = 0.5 + 0.5 * math.sin(t * (0.8 + index * 0.17) + index * 0.9)
            pulse = max(0.0, math.sin(t * (2.4 + index * 0.11) - index * 0.6)) ** 3
            bands.append(min(1.0, 0.20 + base * 0.35 + pulse * 0.55))
        rms = sum(bands) / len(bands) * 0.75
        attack = max(0.0, math.sin(t * 2.8)) * 0.18
        zcr = 0.10 + max(0.0, math.sin(t * 0.9 + 1.4)) * 0.16
        return AudioFrame(rms, bands, attack, zcr, self._start + t)

    def drain_after(self, sequence: int) -> list[CapturedAudioFrame]:
        tick = int((time.monotonic() - self._start) * 30.0)
        if tick == self._last_tick and sequence >= self._sequence:
            return []
        self._last_tick = tick
        self._sequence += 1
        return [CapturedAudioFrame(self._sequence, self._frame(tick))]

    def latest(self) -> AudioFrame:
        tick = int((time.monotonic() - self._start) * 30.0)
        return self._frame(tick)
