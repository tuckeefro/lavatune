"""Truecolor lava-lamp renderer for terminals implementing Kitty graphics.

This is deliberately a renderer, not another motion system.  It reads the
fixed-cost conserved WaxState already advanced by LavaField, reconstructs a
smooth continuous surface from that 64x32 density field, lights it in software,
and sends RGB frames to the terminal with the Kitty graphics protocol.
"""

from __future__ import annotations

import base64
import math
import os
import re
import select
import sys
import termios
import time
import tty
import zlib
from dataclasses import dataclass
from typing import BinaryIO

from .audio import AudioCapture, AudioFrame, DemoAudioCapture
from .config import AppConfig
from .organism import behavior_for_context
from .signals import clamp
from .wax import WAX_HEIGHT, WAX_WIDTH, WaxState

_IMAGE_ID = 719
_PLACEMENT_ID = 1
_MAX_RENDER_WIDTH = 320
_MAX_RENDER_HEIGHT = 192
_DEFAULT_CELL_WIDTH_PX = 10
_DEFAULT_CELL_HEIGHT_PX = 19


@dataclass(slots=True, frozen=True)
class PixelFrame:
    width: int
    height: int
    rgb: bytes


def kitty_graphics_supported(environment: dict[str, str] | None = None) -> bool:
    """Conservatively recognize terminals known to implement Kitty graphics."""

    env = os.environ if environment is None else environment
    if env.get("LAVATUNE_KITTY_FORCE") == "1":
        return True
    if env.get("KITTY_WINDOW_ID"):
        return True
    term_program = env.get("TERM_PROGRAM", "").lower()
    term = env.get("TERM", "").lower()
    return (
        "ghostty" in term_program
        or "kitty" in term_program
        or "wezterm" in term_program
        or "kitty" in term
        or "ghostty" in term
    )


def _parse_cell_size_response(response: bytes) -> tuple[int, int] | None:
    """Parse an XTWINOPS CSI 16 t response into (cell_width_px, cell_height_px)."""

    match = re.search(rb"\x1b\[6;(\d+);(\d+)t", response)
    if match is None:
        return None
    height = int(match.group(1))
    width = int(match.group(2))
    if width <= 0 or height <= 0:
        return None
    return width, height


def _query_cell_pixels(
    input_fd: int,
    stream: BinaryIO,
    *,
    timeout: float = 0.08,
) -> tuple[int, int] | None:
    """Ask a supporting terminal for its real cell size without making it required."""

    stream.write(b"\x1b[16t")
    stream.flush()
    deadline = time.monotonic() + max(0.0, timeout)
    response = bytearray()
    while time.monotonic() < deadline and len(response) < 256:
        remaining = max(0.0, deadline - time.monotonic())
        readable, _, _ = select.select([input_fd], [], [], remaining)
        if not readable:
            break
        chunk = os.read(input_fd, 64)
        if not chunk:
            break
        response.extend(chunk)
        parsed = _parse_cell_size_response(bytes(response))
        if parsed is not None:
            return parsed
    return None


def _render_size(
    columns: int,
    rows: int,
    cell_width_px: int = _DEFAULT_CELL_WIDTH_PX,
    cell_height_px: int = _DEFAULT_CELL_HEIGHT_PX,
) -> tuple[int, int]:
    """Match the framebuffer aspect to the terminal's real drawable cell grid."""

    columns = max(1, int(columns))
    rows = max(1, int(rows))
    cell_width_px = max(1, int(cell_width_px))
    cell_height_px = max(1, int(cell_height_px))
    grid_width_px = columns * cell_width_px
    grid_height_px = rows * cell_height_px

    # Kitty/Ghostty scales the supplied RGB frame over exactly c×r cells.
    # Preserve that physical aspect here so the terminal only scales size,
    # never shape.  This removes the old guessed 1.85 cell-aspect stretch.
    scale = min(
        1.0,
        _MAX_RENDER_WIDTH / grid_width_px,
        _MAX_RENDER_HEIGHT / grid_height_px,
    )
    width = max(32, int(round(grid_width_px * scale)))
    height = max(24, int(round(grid_height_px * scale)))
    return min(_MAX_RENDER_WIDTH, width), min(_MAX_RENDER_HEIGHT, height)


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge0 == edge1:
        return 0.0
    t = clamp((value - edge0) / (edge1 - edge0))
    return t * t * (3.0 - 2.0 * t)


def _bilinear(values: list[float], x: float, y: float) -> float:
    """Sample one WaxState-sized scalar field without allocating per pixel."""

    x = clamp(x, 0.0, WAX_WIDTH - 1.0)
    y = clamp(y, 0.0, WAX_HEIGHT - 1.0)
    left = int(x)
    top = int(y)
    right = min(WAX_WIDTH - 1, left + 1)
    bottom = min(WAX_HEIGHT - 1, top + 1)
    tx = x - left
    ty = y - top
    upper = values[top * WAX_WIDTH + left] * (1.0 - tx) + values[
        top * WAX_WIDTH + right
    ] * tx
    lower = values[bottom * WAX_WIDTH + left] * (1.0 - tx) + values[
        bottom * WAX_WIDTH + right
    ] * tx
    return upper * (1.0 - ty) + lower * ty


def _smooth_density(state: WaxState) -> list[float]:
    """One renderer-only blur removes lattice faceting without changing mass physics."""

    source = state.density
    smoothed = [0.0] * len(source)
    for y in range(WAX_HEIGHT):
        up = max(0, y - 1)
        down = min(WAX_HEIGHT - 1, y + 1)
        for x in range(WAX_WIDTH):
            left = max(0, x - 1)
            right = min(WAX_WIDTH - 1, x + 1)
            index = y * WAX_WIDTH + x
            neighborhood = (
                source[y * WAX_WIDTH + left]
                + source[y * WAX_WIDTH + right]
                + source[up * WAX_WIDTH + x]
                + source[down * WAX_WIDTH + x]
            )
            smoothed[index] = source[index] * 0.58 + neighborhood * 0.105
    return smoothed


def _gradients(values: list[float]) -> tuple[list[float], list[float]]:
    gx = [0.0] * len(values)
    gy = [0.0] * len(values)
    for y in range(WAX_HEIGHT):
        up = max(0, y - 1)
        down = min(WAX_HEIGHT - 1, y + 1)
        for x in range(WAX_WIDTH):
            left = max(0, x - 1)
            right = min(WAX_WIDTH - 1, x + 1)
            index = y * WAX_WIDTH + x
            gx[index] = (values[y * WAX_WIDTH + right] - values[y * WAX_WIDTH + left]) * 0.5
            gy[index] = (values[down * WAX_WIDTH + x] - values[up * WAX_WIDTH + x]) * 0.5
    return gx, gy


def _background(x: int, y: int, width: int, height: int) -> tuple[int, int, int]:
    """Near-black vessel with a tiny warm lift where the lamp heater would be."""

    nx = (x + 0.5) / max(1, width)
    ny = (y + 0.5) / max(1, height)
    center_vignette = clamp(
        1.0 - math.hypot((nx - 0.5) * 1.05, (ny - 0.48) * 0.82) * 1.18
    )
    heater = math.exp(-(((nx - 0.5) / 0.34) ** 2 + ((ny - 1.04) / 0.25) ** 2))
    return (
        int(round(7 + center_vignette * 3 + heater * 4)),
        int(round(10 + center_vignette * 3 + heater * 2)),
        int(round(16 + center_vignette * 4 + heater)),
    )


class ImplicitWaxRenderer:
    """Turn conserved 2D wax density into a smooth volumetric-looking RGB surface."""

    iso_level = 0.13

    def __init__(self) -> None:
        self._cache_key: tuple[int, int] | None = None
        self._background_rgb = b""
        self._sample_x: tuple[float | None, ...] = ()
        self._sample_y: tuple[float, ...] = ()
        self._projection_x = 1.0

    def _prepare_geometry(self, width: int, height: int) -> None:
        key = (width, height)
        if key == self._cache_key:
            return

        # The framebuffer aspect already matches Ghostty's physical cell grid.
        # Map the complete wax domain directly across that framebuffer.  The old
        # square-root projection applied a second aspect correction here, which
        # manufactured visible side dead-space even though the Kitty placement
        # itself correctly occupied the full terminal grid.
        projection_x = 1.0
        background = bytearray(width * height * 3)
        offset = 0
        for py in range(height):
            for px in range(width):
                r, g, b = _background(px, py, width, height)
                background[offset : offset + 3] = bytes((r, g, b))
                offset += 3
        sample_x: list[float | None] = [
            ((px + 0.5) / width) * (WAX_WIDTH - 1) for px in range(width)
        ]
        self._cache_key = key
        self._background_rgb = bytes(background)
        self._sample_x = tuple(sample_x)
        self._sample_y = tuple(
            (py + 0.5) / height * (WAX_HEIGHT - 1) for py in range(height)
        )
        self._projection_x = projection_x

    def render(self, state: WaxState, width: int, height: int) -> PixelFrame:
        width = max(1, int(width))
        height = max(1, int(height))
        self._prepare_geometry(width, height)
        density = _smooth_density(state)
        gradient_x, gradient_y = _gradients(density)
        pixels = bytearray(self._background_rgb)

        # A large soft light above-left.  The view vector is +z.
        lx, ly, lz = -0.40, -0.48, 0.78
        light_norm = math.sqrt(lx * lx + ly * ly + lz * lz)
        lx, ly, lz = lx / light_norm, ly / light_norm, lz / light_norm

        bounds = state.occupied_bounds(0.06)
        if bounds is None:
            return PixelFrame(width=width, height=height, rgb=bytes(pixels))
        wax_left, wax_top, wax_right, wax_bottom = bounds
        screen_left = 0.5 + (wax_left - 0.5) / self._projection_x
        screen_right = 0.5 + (wax_right - 0.5) / self._projection_x
        left = max(0, int(screen_left * width) - 5)
        right = min(width - 1, int(math.ceil(screen_right * width)) + 5)
        top = max(0, int(wax_top * height) - 5)
        bottom = min(height - 1, int(math.ceil(wax_bottom * height)) + 5)

        for py in range(top, bottom + 1):
            sample_y = self._sample_y[py]
            for px in range(left, right + 1):
                sample_x = self._sample_x[px]
                if sample_x is None:
                    continue
                local_density = _bilinear(density, sample_x, sample_y)
                coverage = _smoothstep(
                    self.iso_level - 0.035,
                    self.iso_level + 0.040,
                    local_density,
                )
                if coverage <= 0.003:
                    continue

                heat = _bilinear(state.heat, sample_x, sample_y)
                gx = _bilinear(gradient_x, sample_x, sample_y)
                gy = _bilinear(gradient_y, sample_x, sample_y)

                # Density is treated as material thickness and inflated into
                # a height field.  Normals therefore follow every natural
                # merge, neck, pinch-off and droplet created by WaxState.
                height_z = _smoothstep(self.iso_level, 0.82, local_density)
                slope = 2.6 * max(0.10, 1.0 - height_z)
                nx = -gx * slope * 18.0
                ny = -gy * slope * 18.0
                nz = 1.0
                normal_length = math.sqrt(nx * nx + ny * ny + nz * nz)
                nx, ny, nz = nx / normal_length, ny / normal_length, nz / normal_length
                diffuse = max(0.0, nx * lx + ny * ly + nz * lz)
                # Broad rather than glassy: this is wax, not chrome.
                specular = max(0.0, diffuse) ** 12
                rim = (1.0 - nz) ** 1.45
                thickness = clamp(height_z**0.68)
                warm = clamp(heat * 0.82 + state.impulse * 0.08)

                # Cool wax leans violet-blue; heated wax drifts toward a
                # restrained rose.  Thick centers absorb more light while
                # thin necks and edges scatter it, giving real topology a
                # readable translucent cue without drawing an outline.
                base_r = 0.31 + warm * 0.20
                base_g = 0.24 + (1.0 - warm) * 0.10
                base_b = 0.48 + (1.0 - warm) * 0.18
                absorption = 0.98 - thickness * 0.28
                lighting = 0.44 + diffuse * 0.48
                scatter = rim * 0.22 + (1.0 - thickness) * 0.11
                rf = base_r * absorption * lighting + specular * 0.28 + scatter * 0.34
                gf = base_g * absorption * lighting + specular * 0.23 + scatter * 0.16
                bf = (
                    base_b * (0.96 + thickness * 0.06) * lighting
                    + specular * 0.34
                    + scatter * 0.46
                )

                offset = (py * width + px) * 3
                br, bg, bb = pixels[offset], pixels[offset + 1], pixels[offset + 2]
                r = int(
                    round(br * (1.0 - coverage) + clamp(rf) * 255.0 * coverage)
                )
                g = int(
                    round(bg * (1.0 - coverage) + clamp(gf) * 255.0 * coverage)
                )
                b = int(
                    round(bb * (1.0 - coverage) + clamp(bf) * 255.0 * coverage)
                )
                pixels[offset] = max(0, min(255, r))
                pixels[offset + 1] = max(0, min(255, g))
                pixels[offset + 2] = max(0, min(255, b))

        return PixelFrame(width=width, height=height, rgb=bytes(pixels))


class KittyGraphicsWriter:
    """Minimal direct-data Kitty graphics protocol writer for one placement."""

    def __init__(self, stream: BinaryIO | None = None) -> None:
        self.stream = stream if stream is not None else sys.stdout.buffer

    def _command(self, control: str, payload: bytes = b"") -> None:
        self.stream.write(b"\x1b_G")
        self.stream.write(control.encode("ascii"))
        self.stream.write(b";")
        self.stream.write(payload)
        self.stream.write(b"\x1b\\")

    def display(self, frame: PixelFrame, columns: int, rows: int) -> None:
        compressed = zlib.compress(frame.rgb, level=1)
        encoded = base64.standard_b64encode(compressed)
        chunks = [
            encoded[index : index + 4096] for index in range(0, len(encoded), 4096)
        ] or [b""]
        for index, chunk in enumerate(chunks):
            more = 1 if index < len(chunks) - 1 else 0
            if index == 0:
                control = (
                    f"a=T,f=24,s={frame.width},v={frame.height},o=z,t=d,"
                    f"i={_IMAGE_ID},p={_PLACEMENT_ID},c={max(1, columns)},r={max(1, rows)},"
                    f"C=1,N=1,q=1,m={more}"
                )
            else:
                # Kitty requires continuation chunks to carry only m and q.
                control = f"m={more},q=1"
            self._command(control, chunk)
        self.stream.flush()

    def delete(self) -> None:
        self._command(f"a=d,d=I,i={_IMAGE_ID},q=1")
        self.stream.flush()


class KittyCompanion:
    """Advance Lavatune's existing wax world and display it as terminal pixels."""

    def __init__(self, config: AppConfig, demo: bool = False) -> None:
        self.config = config
        self.demo = demo
        self.renderer = ImplicitWaxRenderer()
        self.writer = KittyGraphicsWriter()
        self.capture: AudioCapture | DemoAudioCapture | None = None
        self.sequence = 0
        self.last_frame = AudioFrame(
            0.0, [0.0] * 8, 0.0, 0.0, time.monotonic()
        )

    def run(self) -> int:
        if not sys.stdout.isatty() or not sys.stdin.isatty():
            raise RuntimeError("The kitty renderer requires an interactive terminal.")
        if not kitty_graphics_supported():
            raise RuntimeError(
                "The kitty renderer requires a Kitty-graphics terminal such as Ghostty, Kitty, or "
                "WezTerm. Use --renderer tui elsewhere."
            )

        from .runtime import LavaField

        field = LavaField()
        capture = DemoAudioCapture() if self.demo else AudioCapture(self.config.audio)
        self.capture = capture
        original_termios = termios.tcgetattr(sys.stdin.fileno())
        target_fps = max(8, min(20, self.config.fps))
        deadline = time.monotonic()
        cell_width_px = _DEFAULT_CELL_WIDTH_PX
        cell_height_px = _DEFAULT_CELL_HEIGHT_PX
        last_grid: tuple[int, int] | None = None

        capture.start()
        try:
            tty.setcbreak(sys.stdin.fileno())
            sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H")
            sys.stdout.flush()
            measured_cell = _query_cell_pixels(sys.stdin.fileno(), sys.stdout.buffer)
            if measured_cell is not None:
                cell_width_px, cell_height_px = measured_cell
            try:
                while True:
                    now = time.monotonic()
                    if now < deadline:
                        time.sleep(min(0.01, deadline - now))
                        continue
                    deadline = max(deadline + 1.0 / target_fps, now)

                    for captured in capture.drain_after(self.sequence):
                        self.sequence = captured.sequence
                        self.last_frame = captured.frame
                    if capture.error():
                        raise RuntimeError(f"Audio capture error: {capture.error()}")

                    columns, rows = os.get_terminal_size(sys.stdout.fileno())
                    columns = max(20, columns)
                    rows = max(8, rows)
                    grid = (columns, rows)
                    if grid != last_grid:
                        if last_grid is not None:
                            # Remove the old full-grid placement before drawing
                            # at a new size so a resize cannot leave stale pixels.
                            self.writer.delete()
                            sys.stdout.write("\x1b[2J\x1b[H")
                            sys.stdout.flush()
                        last_grid = grid

                    render_width, render_height = _render_size(
                        columns,
                        rows,
                        cell_width_px,
                        cell_height_px,
                    )
                    field.resize(max(60, columns), max(30, rows * 2))
                    field.step(
                        self.last_frame,
                        self.config.listening_context,
                        self.config.profile,
                        self.config.lava.reactivity,
                        self.config.lava,
                        rasterize=False,
                        behavior=behavior_for_context(self.config.listening_context),
                        embody_posture=True,
                        embody_wax=True,
                    )
                    pixel_frame = self.renderer.render(
                        field.wax, render_width, render_height
                    )
                    sys.stdout.write("\x1b[H")
                    sys.stdout.flush()
                    self.writer.display(pixel_frame, columns, rows)

                    readable, _, _ = select.select([sys.stdin.fileno()], [], [], 0)
                    if readable:
                        key = os.read(sys.stdin.fileno(), 1)
                        if key in (b"q", b"Q", b"\x1b", b"\x03"):
                            break
            except KeyboardInterrupt:
                pass
        finally:
            try:
                capture.stop()
            finally:
                try:
                    self.writer.delete()
                except OSError:
                    pass
                try:
                    termios.tcsetattr(
                        sys.stdin.fileno(), termios.TCSADRAIN, original_termios
                    )
                finally:
                    sys.stdout.write("\x1b[?25h\x1b[?1049l")
                    sys.stdout.flush()
                    self.capture = None
        return 0


def run_kitty(config: AppConfig, demo: bool = False) -> int:
    """Run the continuous wax framebuffer inside a capable terminal."""

    return KittyCompanion(config, demo).run()