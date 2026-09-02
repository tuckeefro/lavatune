"""Photographic renderer laboratory for the Kitty/Ghostty wax prototype.

The design target is deliberately narrow: a real lava lamp photographed in a
dark room, except the wax has subtly impossible depth and elegance.

This module does not own or alter wax physics.  It reads WaxState, performs
renderer-only spatial and temporal reconstruction, then hands RGB pixels to
the existing Kitty graphics transport.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

from .config import AppConfig, load_config, preference_path
from .kitty import KittyCompanion, PixelFrame
from .signals import clamp
from .wax import WAX_HEIGHT, WAX_WIDTH, WaxState


@dataclass(slots=True, frozen=True)
class _PreparedField:
    density: list[float]
    broad_density: list[float]
    gradient_x: list[float]
    gradient_y: list[float]


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge0 == edge1:
        return 0.0
    t = clamp((value - edge0) / (edge1 - edge0))
    return t * t * (3.0 - 2.0 * t)


def _sample(values: list[float], x: float, y: float) -> float:
    """Bilinearly sample one WaxState-sized renderer field."""

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


def _blur(values: list[float], center_weight: float = 0.44) -> list[float]:
    """Small separable-looking blur without changing the simulation field."""

    side_weight = (1.0 - center_weight) / 4.0
    result = [0.0] * len(values)
    for y in range(WAX_HEIGHT):
        up = max(0, y - 1)
        down = min(WAX_HEIGHT - 1, y + 1)
        for x in range(WAX_WIDTH):
            left = max(0, x - 1)
            right = min(WAX_WIDTH - 1, x + 1)
            index = y * WAX_WIDTH + x
            result[index] = (
                values[index] * center_weight
                + values[y * WAX_WIDTH + left] * side_weight
                + values[y * WAX_WIDTH + right] * side_weight
                + values[up * WAX_WIDTH + x] * side_weight
                + values[down * WAX_WIDTH + x] * side_weight
            )
    return result


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


def _tone(value: float) -> int:
    """Soft photographic shoulder followed by display gamma."""

    mapped = 1.0 - math.exp(-max(0.0, value) * 1.20)
    encoded = clamp(mapped) ** (1.0 / 2.2)
    return max(0, min(255, int(round(encoded * 255.0))))


def _background(nx: float, ny: float) -> tuple[float, float, float]:
    """A dark room, not a digital gradient backdrop."""

    vignette = clamp(1.0 - math.hypot((nx - 0.5) * 1.12, (ny - 0.48) * 0.90))
    lamp_pool = math.exp(-(((nx - 0.5) / 0.38) ** 2 + ((ny - 1.08) / 0.28) ** 2))
    # Linear-light values.  The warm pool is almost subliminal; it should feel
    # like illumination leaking from a real lamp base, not a visible glow FX.
    return (
        0.0035 + vignette * 0.0020 + lamp_pool * 0.0100,
        0.0042 + vignette * 0.0021 + lamp_pool * 0.0045,
        0.0065 + vignette * 0.0028 + lamp_pool * 0.0025,
    )


class PhotographicWaxRenderer:
    """Render WaxState as dense, softly backlit photographed wax."""

    iso_level = 0.13

    def __init__(self) -> None:
        self._previous_density: list[float] | None = None
        self._cache_key: tuple[int, int] | None = None
        self._projection_x = 1.0
        self._sample_x: tuple[float | None, ...] = ()
        self._sample_y: tuple[float, ...] = ()
        self._background_rgb = b""

    def _prepare_geometry(self, width: int, height: int) -> None:
        key = (width, height)
        if key == self._cache_key:
            return
        self._cache_key = key
        self._projection_x = max(1.0, math.sqrt(width / max(1.0, height)))
        self._sample_x = tuple(
            (
                wax_x * (WAX_WIDTH - 1)
                if 0.0 <= wax_x <= 1.0
                else None
            )
            for px in range(width)
            for wax_x in (
                0.5 + (((px + 0.5) / width) - 0.5) * self._projection_x,
            )
        )
        self._sample_y = tuple(
            (py + 0.5) / height * (WAX_HEIGHT - 1) for py in range(height)
        )
        background = bytearray(width * height * 3)
        offset = 0
        for py in range(height):
            ny = (py + 0.5) / height
            for px in range(width):
                nx = (px + 0.5) / width
                r, g, b = _background(nx, ny)
                background[offset] = _tone(r)
                background[offset + 1] = _tone(g)
                background[offset + 2] = _tone(b)
                offset += 3
        self._background_rgb = bytes(background)

    def _prepare_field(self, state: WaxState) -> _PreparedField:
        # Two spatial passes hide the 64x32 simulation lattice.  A modest
        # renderer-only temporal low-pass removes digital contour chatter while
        # leaving the WaxState topology and timing untouched.
        spatial = _blur(_blur(state.density, 0.52), 0.46)
        if self._previous_density is None:
            density = spatial
        else:
            density = [
                previous * 0.34 + current * 0.66
                for previous, current in zip(self._previous_density, spatial)
            ]
        self._previous_density = density.copy()
        broad_density = _blur(_blur(density, 0.38), 0.34)
        gradient_x, gradient_y = _gradients(broad_density)
        return _PreparedField(density, broad_density, gradient_x, gradient_y)

    def render(self, state: WaxState, width: int, height: int) -> PixelFrame:
        width = max(1, int(width))
        height = max(1, int(height))
        self._prepare_geometry(width, height)
        prepared = self._prepare_field(state)
        pixels = bytearray(self._background_rgb)

        bounds = state.occupied_bounds(0.045)
        if bounds is None:
            return PixelFrame(width=width, height=height, rgb=bytes(pixels))
        wax_left, wax_top, wax_right, wax_bottom = bounds
        screen_left = 0.5 + (wax_left - 0.5) / self._projection_x
        screen_right = 0.5 + (wax_right - 0.5) / self._projection_x
        left = max(0, int(screen_left * width) - 7)
        right = min(width - 1, int(math.ceil(screen_right * width)) + 7)
        top = max(0, int(wax_top * height) - 7)
        bottom = min(height - 1, int(math.ceil(wax_bottom * height)) + 7)

        # A weak large photographic key gives curvature legibility.  The lamp
        # itself still supplies the dominant material character from below.
        key_x, key_y, key_z = -0.22, -0.28, 0.94
        key_length = math.sqrt(key_x * key_x + key_y * key_y + key_z * key_z)
        key_x /= key_length
        key_y /= key_length
        key_z /= key_length

        for py in range(top, bottom + 1):
            sample_y = self._sample_y[py]
            ny_screen = (py + 0.5) / height
            for px in range(left, right + 1):
                sample_x = self._sample_x[px]
                if sample_x is None:
                    continue
                local_density = _sample(prepared.density, sample_x, sample_y)
                broad_density = _sample(prepared.broad_density, sample_x, sample_y)
                coverage = _smoothstep(
                    self.iso_level - 0.052,
                    self.iso_level + 0.046,
                    broad_density,
                )
                if coverage <= 0.002:
                    continue

                heat = _sample(state.heat, sample_x, sample_y)
                gx = _sample(prepared.gradient_x, sample_x, sample_y)
                gy = _sample(prepared.gradient_y, sample_x, sample_y)

                # Inflated 2D density becomes a smooth fictive surface.  Using
                # the broader field for normals prevents glossy little bumps
                # and makes the object read as one heavy body of wax.
                thickness = _smoothstep(self.iso_level, 0.82, local_density)
                broad_height = _smoothstep(self.iso_level, 0.70, broad_density)
                slope = 9.5 * (0.42 + (1.0 - broad_height) * 0.58)
                normal_x = -gx * slope
                normal_y = -gy * slope
                normal_z = 1.0
                normal_length = math.sqrt(
                    normal_x * normal_x + normal_y * normal_y + normal_z * normal_z
                )
                normal_x /= normal_length
                normal_y /= normal_length
                normal_z /= normal_length

                key = max(
                    0.0,
                    normal_x * key_x + normal_y * key_y + normal_z * key_z,
                )
                # Nearly matte.  A broad, low-energy sheen is enough to make
                # the surface physical without turning it into a jellybean.
                sheen = max(0.0, key) ** 18 * 0.045

                nx_screen = (px + 0.5) / width
                lamp_axis = math.exp(-((nx_screen - 0.5) / 0.46) ** 2)
                lamp_reach = 0.20 + 0.80 * (ny_screen**1.75)
                lamp = lamp_axis * lamp_reach

                # Thin wax transmits the warm lamp; thick wax absorbs it and
                # becomes darker, denser, and more saturated.  This is the
                # primary depth cue, not an outline or neon rim.
                thinness = (1.0 - thickness) ** 1.55
                transmitted = lamp * (0.08 + thinness * 0.46) * (0.34 + heat * 0.66)
                body_light = 0.16 + key * 0.17 + lamp * 0.055
                warm = clamp(heat * 0.68 + lamp * 0.18)

                # Real dark-room lava-lamp palette: deep mulberry wax moves
                # toward dusty rose and ember only where heat/light justify it.
                cool_r, cool_g, cool_b = 0.115, 0.030, 0.080
                hot_r, hot_g, hot_b = 0.455, 0.115, 0.125
                base_r = cool_r + (hot_r - cool_r) * warm
                base_g = cool_g + (hot_g - cool_g) * warm
                base_b = cool_b + (hot_b - cool_b) * warm

                # Beer-Lambert-ish absorption: the belly is visually heavy;
                # necks remain luminous enough to expose stretch and pinch.
                absorption = math.exp(-thickness * 0.88)
                saturation_gain = 0.78 + thickness * 0.42
                r = base_r * saturation_gain * (body_light + absorption * 0.12)
                g = base_g * saturation_gain * (body_light + absorption * 0.10)
                b = base_b * saturation_gain * (body_light + absorption * 0.12)

                # Subsurface lamp contribution is warm and soft, strongest in
                # thin suspended necks and lower warm masses.
                r += transmitted * 0.54 + sheen
                g += transmitted * 0.20 + sheen * 0.84
                b += transmitted * 0.16 + sheen * 0.70

                # A tiny cool ambient fill on front-facing areas adds the
                # "subtly impossible" depth without announcing a shader.
                front_fill = normal_z**3 * 0.010
                r += front_fill * 0.62
                g += front_fill * 0.72
                b += front_fill * 1.00

                offset = (py * width + px) * 3
                bg_r = pixels[offset] / 255.0
                bg_g = pixels[offset + 1] / 255.0
                bg_b = pixels[offset + 2] / 255.0
                # Decode approximately back to linear before compositing.  The
                # background is tiny, so this keeps the edge soft without a
                # visible bright halo.
                bg_r = bg_r**2.2
                bg_g = bg_g**2.2
                bg_b = bg_b**2.2
                pixels[offset] = _tone(bg_r * (1.0 - coverage) + r * coverage)
                pixels[offset + 1] = _tone(bg_g * (1.0 - coverage) + g * coverage)
                pixels[offset + 2] = _tone(bg_b * (1.0 - coverage) + b * coverage)

        return PixelFrame(width=width, height=height, rgb=bytes(pixels))


def run_photographic(config: AppConfig, demo: bool = False) -> int:
    companion = KittyCompanion(config, demo)
    companion.renderer = PhotographicWaxRenderer()
    return companion.run()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m lavatune.kitty_v2",
        description="Photographic wax renderer laboratory for Ghostty/Kitty terminals.",
    )
    parser.add_argument("--demo", action="store_true", help="Use synthetic audio.")
    parser.add_argument("--config", help="Optional Lavatune TOML config override.")
    args = parser.parse_args()

    saved_preferences = preference_path()
    config: AppConfig = load_config(
        args.config,
        saved_preferences=None if args.config else saved_preferences,
    )
    # This module is intentionally a renderer lab, not another persisted mode.
    config.render.renderer = "kitty"
    return run_photographic(config, args.demo)


if __name__ == "__main__":
    raise SystemExit(main())
