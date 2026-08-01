"""Linux monitor capture and lightweight PCM analysis."""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass

from .config import AudioConfig
from .text import sanitize_display_text


@dataclass(slots=True)
class AudioFrame:
    """One normalized analysis window consumed by the organism."""

    rms: float
    bands: list[float]
    attack: float
    zcr: float
    timestamp: float


class AudioCapture:
    """Read signed 16-bit PCM from one local Linux audio backend."""

    def __init__(self, config: AudioConfig) -> None:
        self.config = config
        self._frames: deque[AudioFrame] = deque(maxlen=4)
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
        self._level_floor = 0.01
        self._level_ceiling = 0.18
        self._level_drive = 0.0

    def status(self) -> str:
        return sanitize_display_text(
            f"{self.backend}:{self.source or 'default'}:{self.config.analysis}"
        )

    def error(self) -> str | None:
        return self._error

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

    def latest(self) -> AudioFrame:
        with self._lock:
            if self._frames:
                return self._frames[-1]
        return AudioFrame(
            rms=0.0,
            bands=[0.0] * 8,
            attack=0.0,
            zcr=0.0,
            timestamp=time.monotonic(),
        )

    def _pick_backend(self, preferred: str) -> str:
        binaries = {
            "pipewire": "pw-cat",
            "pulse": "parec",
            "ffmpeg": "ffmpeg",
        }
        if preferred != "auto":
            if preferred not in binaries:
                raise RuntimeError(f"Unsupported audio backend '{preferred}'")
            if shutil.which(binaries[preferred]) is None:
                raise RuntimeError(
                    f"Audio backend '{preferred}' requires '{binaries[preferred]}' in PATH."
                )
            return preferred
        for backend, binary in binaries.items():
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

            frame = self._analyze(chunk)
            with self._lock:
                self._frames.append(frame)

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

        # Atlas is the inexpensive mode. It follows the envelope and spreads a
        # short history across eight values instead of calculating frequencies.
        step = 2 if len(samples) >= 2048 else 1
        total = 0.0
        peak = 0.0
        count = 0
        sign_changes = 0
        previous_positive = samples[0] >= 0
        for sample in samples[::step]:
            value = abs(sample) / 32768.0
            total += value * value
            if value > peak:
                peak = value
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
        self._atlas_history.appendleft(max(drive, self._atlas_history[0] * 0.82))
        zcr = sign_changes / max(1, count - 1)

        bands = []
        for index, level in enumerate(self._atlas_history):
            tail = 1.0 - index * 0.09
            wobble = 0.96 + 0.04 * (index % 2)
            bands.append(max(0.0, min(1.0, level * tail * wobble)))
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
        targets = [80, 160, 320, 640, 1250, 2500, 5000, 9000]
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

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    @staticmethod
    def status() -> str:
        return "demo:synth:atlas"

    @staticmethod
    def error() -> str | None:
        return None

    def latest(self) -> AudioFrame:
        t = time.monotonic() - self._start
        bands = []
        for index in range(8):
            base = 0.5 + 0.5 * math.sin(t * (0.8 + index * 0.17) + index * 0.9)
            pulse = max(0.0, math.sin(t * (2.4 + index * 0.11) - index * 0.6)) ** 3
            bands.append(min(1.0, 0.20 + base * 0.35 + pulse * 0.55))
        rms = sum(bands) / len(bands) * 0.75
        attack = max(0.0, math.sin(t * 2.8)) * 0.18
        zcr = 0.10 + max(0.0, math.sin(t * 0.9 + 1.4)) * 0.16
        return AudioFrame(
            rms=rms,
            bands=bands,
            attack=attack,
            zcr=zcr,
            timestamp=time.monotonic(),
        )
