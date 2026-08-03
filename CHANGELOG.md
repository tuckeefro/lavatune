# Changelog

This project follows [Semantic Versioning](https://semver.org/). It is currently alpha software.

## Unreleased

No unreleased items are planned in this checkpoint.

## 0.0.2a - 2026-08-02

### Added

- Added an end-to-end benchmark for the alpha Fluid, analytic contour Fluid, and prepared Text render paths.
- Added an affective posture layer for weight, agitation, cohesion, tension, openness, release, intimacy, volatility, and novelty without named-emotion classification.
- Added a reaction latch so short attacks survive between lower-cadence visual frames.
- Added fast-decaying directional contour spikes gated by per-band deviation from a noise-aware 2.4-second rolling average.
- Added phase-offset tempo breathing, stretch, and circulation pressure to every persistent body.
- Added an authored Midwest emo posture arc from fragile detail and yearning contraction into stored-tension catharsis.
- Added genre-neutral rapid-pattern density so closely spaced attacks remain visibly patterned without replacing beat-scale tempo.
- Added saturating restraint and confirmed snap behavior so quiet-to-loud breaks receive consistent cathartic action without duration-based escalation.
- Added a deterministic narrative context layer for expectation, interruption, and earned resolution without named-emotion or intent classification.

### Changed

- Changed wide-current centering to an adaptive dead-zone leash that prevents sustained corner crowding without filling or pinning the composition.
- Replaced Fluid's full scalar-field raster and per-cell gradient sampling with analytic body contours and localized edge attention.
- Added hysteretic 2/4/8/14 FPS display pacing and a separate 2/4/6/8 FPS physics clock while preserving elapsed time through bounded simulation substeps.
- Decoupled capture-frame mapping from display cadence with a bounded sequenced queue and event notifier.
- Changed normal listening to real spectral bands and retained coarse single-pass analysis for low-power mode.
- Added bounded bass breathing, voice shear, tonal edge ripples, and impact bulges to Fluid contours.
- Changed Fluid rendering to emit sparse occupied row spans, cache repeated contours, and write only terminal runs that changed.
- Made audio-force smoothing elapsed-time based so response is stable across capture profiles and delayed frames.
- Prepared Text material rows once before viewport interpolation instead of repeatedly sampling all semantic fields per cell.
- Changed the reaction latch to accumulate bounded rapid impulses between lower-cadence physics steps instead of retaining only one peak.

## 0.1.0a1 - 2026-08-01

### Added

- Added semantic Text and foreground-only Fluid output materials.
- Refined Fluid edges with quarter-cell occupancy so silhouettes read less like solid pixels.
- Reduced wall restitution so contact reads as viscous squash instead of a rigid bounce.
- Added atomic XDG preference persistence for dock-controlled settings.
- Added mass-weighted composition centering that preserves body-relative motion.
- Added an environment doctor with optional live PCM verification.
- Added deterministic performance and distribution-content verification tools.
- Added tag-driven GitHub prereleases with wheel, source archive, and checksums.
- Added troubleshooting and measured performance documentation.
- Documented the project's human direction and substantial Codex assistance.
- Documented the privacy-first native macOS architecture and permission boundary.
- Responsive terminal compositions for compact, narrow, and wide tiles.
- PipeWire, PulseAudio, and FFmpeg monitor capture.
- Optional local MPRIS metadata through `playerctl`.
- Music, speech, and low-power presets.
- Synthetic demo mode.

### Changed

- Replaced the daily style list with orthogonal Material, Weight, Edge, Afterglow, and Palette controls.
- Separated body mass, surface activity, and attention through the field-rendering boundary.
- Bounded palette initialization to the terminal's reported color-pair capacity.
- Preserved organism state when changing output material or operating mode.
- Made body silhouettes scale against physical terminal dimensions instead of normalized tile width and height.
- Replaced index-driven drift with habitat circulation lanes and bounded traveling acoustic pressure.
- Made wall contact and acoustic impacts deform bodies along the actual pressure axis.
- Softened overlapping body mass so loud or crowded tiles retain recognizable lava bodies.
- Made the package version single-source and bounded CI jobs with concurrency control.
- Removed unused compatibility paths and configuration controls that no longer affected runtime behavior.
- Added source comments around audio normalization, body motion, terminal scaling, and process boundaries.
- Gave persistent bodies authored bass, voice, detail, and neutral identities.
- Replaced generic responsive scaling with micro, chimney, basin, and current habitats.
- Reserved the final palette color for localized, decaying afterglow.
- Moved the control dock backstage by default and kept operating modes on one canonical appearance.

### Security

- Sanitize control and formatting characters in displayed media metadata.
- Bound retained backend diagnostics and drain subprocess error output.
- Use fixed subprocess argument lists without shell interpolation.
