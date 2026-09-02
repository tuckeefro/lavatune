# Privacy-first macOS direction

Status: architecture specification for future native Swift application.

> **Important distinction:** This document describes the planned architecture for the future native macOS Swift application (utilizing Core Audio process taps). It does **not** describe the current Python companion.
>
> The current Python companion on macOS supports:
> - Terminal TUI renderer (`lavatune`)
> - Standalone floating window renderer (`lavatune --window`)
> - Synthetic demo mode (`lavatune --demo`)
> - Live microphone input (`lavatune` with `Microphone` listening context via `ffmpeg` or `sox`)
>
> Live system-output audio capture on macOS is unsupported in the Python companion and will be delivered by the native Swift application.

The native macOS version should feel like the same acoustic organism while behaving like a small native utility. It should not embed the Linux terminal interface, a Python runtime, Electron, or a browser view.

## Platform boundary

The proposed minimum is macOS 14.2. That release introduced public Core Audio process-tap APIs, including `AudioHardwareCreateProcessTap` and `CATapDescription`, for capturing outgoing audio from selected processes or a system-wide mix. This route must be compiled and verified against the current macOS SDK on the target Mac before support is declared.

Core Audio taps receive audio buffers, not display frames. macOS still presents an explicit, revocable system-audio recording authorization to the user. Lavatune should explain why it needs that access, capture only while visibly running, and release the tap immediately when paused or closed.

The first macOS release will not use:

- ScreenCaptureKit or screen pixels
- microphone input as a substitute for system audio
- private `MediaRemote` frameworks
- Spotify, Apple Music, or other network APIs
- OAuth, user accounts, telemetry, or cloud storage
- bundled virtual audio drivers such as BlackHole
- Accessibility permission for scraping other applications

On older macOS versions, live system-audio mode should report that it is unsupported and leave demo mode available. It should not silently request a broader permission or install a driver.

## Native application

The macOS target should be a small SwiftUI application with:

- a resizable utility window using a monospaced, terminal-influenced presentation
- SwiftUI `Canvas` rendering rather than one view per visual cell
- Accelerate/vDSP analysis for frequency bands and transients
- music, speech, low-power, and demo modes
- explicit pause and quit controls
- optional always-on-top behavior
- remembered window size and position
- reduced-motion and low-power behavior
- no network entitlement or network code

The app should analyze audio in memory and retain only smoothed force values. It should not write PCM samples to disk.

## Metadata adapters

macOS does not provide a general public reader for the system-wide Now Playing title. Metadata support should therefore be local, optional, and adapter-based:

- Apple Music: its public AppleScript/ScriptingBridge dictionary
- Spotify desktop: its local AppleScript dictionary when available
- unsupported players: display `System Audio` without a title

Each adapter must be disabled by default until the user enables it. Enabling an adapter may trigger macOS Automation permission for that specific application. Denial must leave audio visualization working without repeated prompts.

Browser tab scraping is out of scope for the first macOS release because it adds browser-specific automation or Accessibility permissions. Private media frameworks and web-service tokens are not acceptable fallbacks.

## Shared behavior contract

The Python and Swift implementations should share test data rather than a runtime:

1. Store synthetic silence, speech, bass, music, and transient frames as versioned fixtures.
2. Store expected force ranges, composition topology, brightness budgets, and resize-continuity metrics.
3. Run the Python implementation against those fixtures in Linux CI.
4. Run the Swift implementation against the same fixtures in macOS CI.
5. Treat fixture changes as product-behavior changes requiring review.

This keeps each installation native and small while preventing the two versions from drifting into unrelated visualizers.

## Delivery sequence

1. Extract the cross-platform acoustic behavior fixtures from the current Python tests.
2. Validate a minimal Core Audio tap on the target Mac, including authorization, pause, sleep, and cleanup behavior.
3. Build the native window and synthetic demo renderer.
4. Port force mapping and organism motion against the shared fixtures.
5. Add global system-audio capture, then optional Music and Spotify metadata adapters.
6. Measure idle CPU, active CPU, memory, binary size, and battery impact on the 2023 MacBook Pro.
7. Add macOS CI and ad-hoc personal builds.
8. Add Developer ID signing and notarization only when distributing downloadable builds broadly.
