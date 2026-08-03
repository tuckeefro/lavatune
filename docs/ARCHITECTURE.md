# Architecture

Lavatune has one data path:

```text
Linux monitor process
        |
        v
    AudioCapture  ->  bounded sequenced AudioFrames
        |                     |
        |              nonblocking notifier
        |
        v
 AudioForceMapper ->  AudioForces
        |                    |
        v                    v
  ReactionLatch       AffectiveTracker
        |                    |
        |             NarrativeTracker
        |                    |
        +---------+----------+
                  |
                  v
        AcousticOrganism -> persistent Body objects
        |
        v
        +-----------------------------+
        |                             |
        v                             v
 Fluid / experimental Volume  OrganismFieldRenderer
                                      |
                                      v
                              mass, surface, and
                               attention grids
                                      |
                                      v
                               Text material
        |                             |
        +--------------+--------------+
                       |
                       v
         sparse changed curses runs only
```

The divisions are deliberate. Audio analysis does not know about brightness, physics does not know about terminal glyphs, and the terminal renderer does not decide how sound moves a body.

## Modules

`audio.py` launches one local capture backend and reads signed 16-bit PCM. Normal listening uses a small Goertzel filter bank because its measured cost at the 1024-sample window is nearly identical to coarse analysis. `atlas` uses two one-pole filters in the envelope pass to retain broad low, mid, and high contrast at the larger low-power window.

`organism.py` has five stages:

1. `AudioForceMapper` converts signal measurements into bass, voice, detail, transient, beat-scale tempo, rapid rhythmic density, spectral forces, and per-band deviation from recent context.
2. `AffectiveTracker` integrates those forces into weight, agitation, cohesion, tension, openness, release, intimacy, volatility, novelty, fragility, yearning, restraint, snap, and catharsis. Restraint saturates after a short qualified passage; snap requires a credible attack plus one confirming frame of coherent long-baseline contrast. These are transparent acoustic posture axes, not classified emotions or genres.
3. `NarrativeTracker` interprets gestures through that posture as expectation, interruption, resolution, and fixed-cost phrase memory: cadence regularity, held pressure, rupture, and aftermath. It retains only scalar timing estimates, never audio frames or a growing event history. This is a small deterministic context layer, not an inference model or a claim about authorial intent.
4. `signals.py` converts capture features into bounded audio forces and maintains slow affective and narrative state without retaining audio. `AcousticOrganism` applies those inputs as immediate forces, slower posture, and low-gain narrative modifiers to persistent bodies in normalized coordinates. Radio additionally maintains bounded speech posture: one stable voice carrier follows voice/mid flow, cadence, syllable-scale detail, and pause release while the other active bodies orient as listeners; a handoff needs sustained tone evidence. Experimental Volume caps its visible cast at four and adds bounded scalar scar residue and thermal wax state per body: compressed authored lanes and a low-gain centroid pull concentrate the vessel while preserving role positions; phrase-held pressure warms wax into slow buoyancy, cooling thickens and sinks it; low-pass velocity/pressure memory gives it delayed bulges and slow recovery. At most six fixed pairwise proximity checks use hysteresis to select one dominant temporary adhesion/bridge pair among four bodies, while all other cores retain normal collision separation. A credible rise in phrase rupture after held pressure marks each role differently, and recovery requires several seconds of audible low-volatility cadence with no fresh interruption. Silence does not heal it.
5. `OrganismFieldRenderer` rasterizes body mass, surface activity, and local attention into separate values from `0.0` to `1.0` for Text.

`material_core.py` owns shared terminal cells, styles, Unicode glyph validation, and semantic-field sampling. `materials.py` is the compatibility façade for Text and experimental Wax; it re-exports Fluid and Volume. `fluid.py` prepares body geometry once, emits only occupied row spans, and caches the latest quantized contour instead of rasterizing a full scalar field. `volume.py` evaluates only projected body bounds, depth-tests four terminal subcells, and gives one warm/near body a restrained surface lead without assigning group-wide attention color. Wax owns a fixed 64×32 density/heat/flow lattice: one fixed advection pass and one fixed surface-tension pass permit real topology changes, then only its occupied lattice bounds are projected into terminal quadrants. It never allocates a terminal-sized simulation buffer. Volume and Wax are not defaults until their cost is within the Fluid gate. No material contains curses state, audio analysis, or body physics, so output behavior can be tested directly. `runtime.py` owns the renderer-neutral `LavaField`, reaction latch, metrics, audio-to-force mapping, and physics advance. `tui.py` owns terminal UI state, safe cell writes, and tile geometry. `app.py` owns the curses event loop, multi-rate scheduler, controls, palette capacity, and final terminal writes; it re-exports the established UI and runtime symbols for compatibility.

`media.py` polls `playerctl` on a separate thread. Metadata is optional and never participates in audio analysis.

`doctor.py` checks platform and terminal capabilities, discovers local helper programs, and can open the normal capture path briefly to distinguish missing dependencies from an inaccessible or incorrect monitor source.

`config.py` contains only settings that the current runtime consumes. Profiles change groups of settings; legacy scenes remain config-compatible; product presets change operating behavior without replacing presentation. Default launches layer versioned XDG preferences over built-ins. An explicit TOML config is self-contained, ignores those preferences, and disables preference writes. Preference updates use a same-directory temporary file and atomic replacement.

## Coordinates and resizing

Bodies keep planar positions, velocity, depth, and character in normalized `0.0` to `1.0` coordinates. Radius and collision calculations convert the planar coordinates through an approximate terminal cell aspect ratio, so a body keeps the same physical silhouette in a narrow chimney and a wide current. Depth is a shallow, bounded presentation axis: voice and tempo maintain independent orbits, while bass and credible gestures add short pushes. Materials project it as modest perspective scale, foreground luminance, and opposing camera-drift parallax; it does not alter habitat anchors or collisions. A resize changes `TileComposition` and the size of the scalar field, but does not recreate the bodies.

Weak habitat anchors establish home regions while a continuous circulation field does most of the movement. Rising transients can emit up to three short-lived pressure waves from pitch-dependent tile edges. A wave travels through the shared vessel, disturbs each body when it arrives, and decays independently of the local afterglow assigned to the pitch-adjacent body. Beat-scale tempo ignores intervals shorter than 140 milliseconds, while a separate density envelope accepts gated repeated attacks down to 35 milliseconds. This lets rapid subdivisions drive bounded flutter and pressure without replacing the larger tempo estimate. Each frequency band keeps a noise-aware 2.4-second rolling baseline after a short warmup. Only meaningful upward deviation from that baseline feeds a body's faster spike envelope; raw loudness and ordinary attacks cannot sharpen it. The point and impulse collapse before afterglow or phrase posture fades. This is why the reaction can be believable without making every body jump on the same frame.

Snap contrast uses a separate 12-second capture-level and spectral baseline. Quiet readiness is capped after eight seconds, so a longer wait cannot make the response unbounded. The first attack arms a short candidate; sustained coherent contrast on the following frame confirms it. Confirmation consumes readiness and reuses the existing catharsis and outward-pressure vocabulary instead of adding another rendering system.

The first viewport seeds the cast in its actual habitat and translates its mass-weighted center near the visual midpoint. Later resizes never reseed it. Basin, chimney, and micro habitats use a weak group correction. A wide current instead gives its centroid a central dead zone, then applies a smooth nonlinear leash as the cast approaches an edge. The same correction removes only outward mean velocity, so an inward return and edge-parallel flow survive. Because the acceleration is shared, body spacing and internal circulation remain intact.

For Text, compact mode adjusts simulated cell width against a target cell budget and the material interpolates the scalar field back across available terminal columns. Fluid instead composes bodies in the actual viewport and computes row spans at two vertical samples per terminal row. Both paths preserve normalized body state through resize.

## Brightness budget

The force mapper never emits color or luminance. Most field intensity comes from a soft union of persistent body mass, which lets skirts meet without summing into a saturated slab. Surface activity and attention remain separate through rasterization. A material combines them using bounded Weight, Edge, and Afterglow gains. The terminal renderer reserves the final palette color for attention; ordinary body intensity cannot spend it. Tests measure visible, bright, and saturated area so a loud source cannot wash the whole tile out.

Fluid projects slowly turning analytic body ellipses before intersecting them with the top and bottom halves of each terminal row, then merges intervals and selects foreground-only quadrant glyphs at their boundaries. A turn changes the projected width and tilt. Per-cell surface normals choose between the palette's ordinary body colors, while the final palette color remains reserved for local acoustic attention. Adjacent cells therefore describe continuous contours, while body cores remain solid. At overlaps, the nearest contour receives a small foreground emphasis within the existing color budget. Fluid does not allocate foreground/background color combinations, so transparent terminal backgrounds remain intact and palette-pair use stays bounded. Non-UTF-8 terminals fall back to Text.

## Cadence and terminal writes

Audio capture publishes a bounded sequence of analyzed frames and signals a nonblocking pipe. The main loop waits on that pipe and keyboard input instead of polling every 10 milliseconds, then maps every retained frame in order. `ReactionLatch` holds peak gestures and accumulates bounded rapid impulses until the next physics step, so several attacks do not collapse into one merely because terminal drawing is slower than audio capture.

Rendering cadence follows a hysteretic acoustic state rather than one fixed display rate. Resting, breathing, engaged, and burst states draw at 2, 4, 8, and 14 FPS. Physics advances independently at 2, 4, 6, and 8 FPS, using bounded elapsed-time substeps. Release starts one short burst when it crosses the meaningful threshold; its slower posture can remain visible without continuously extending that expensive state. The `power-save` profile caps display cadence at 6 FPS.

The curses layer caches only occupied visual cells and writes sparse runs whose glyph or color changed, including blanks needed to clear an old contour. A resize, material change, palette change, or diagnostic overlay invalidates that cache. This keeps the daily view cheap while preserving immediate feedback for interaction and sudden sound.

## Threads and processes

The curses loop stays on the main thread. Audio capture and MPRIS polling each use one daemon thread:

- the audio thread blocks on PCM reads, keeps at most eight sequenced analyzed frames, and signals the main loop
- the media thread polls at a low fixed rate
- a small stderr-draining thread prevents an audio backend from blocking on its diagnostic pipe

Shutdown terminates and reaps the audio subprocess, stops both workers, and disables terminal focus reporting.

## Where to tune behavior

- Frequency and level response: `AudioCapture` in `audio.py`
- Mapping from sound to physical meaning: `AudioForceMapper` in `organism.py`
- Body motion, collisions, and wall response: `AcousticOrganism` in `organism.py`
- Semantic field rasterization for Text: `OrganismFieldRenderer` in `organism.py`
- Text row preparation and Fluid contour rendering: `materials.py`
- Terminal UI state and tile layout: `tui.py`; palettes, controls, and persistence: `app.py` and `config.py`
- Power defaults and presets: `config.py` and the preset tables in `app.py`

Behavior changes should be covered by the synthetic audio and field-metric tests before being judged interactively in a real terminal.
