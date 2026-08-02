# Design Intent

Lavatune should not depict audio. It should depict what audio did to something alive.

The default is buoyant, conversational, and softly bruisable. It remains alive in silence, reacts clearly without performing for the user, and carries short physical memories of sound through motion, deformation, pressure, and afterglow.

## Identity

The first four bodies are always the same characters:

| Body | Silhouette | Listens for | Behavioral role |
| --- | --- | --- | --- |
| Ballast | largest and slowest | lows | carries weight and meets walls |
| Listener | medium and mobile | voice | circulates and turns toward activity |
| Glint | smallest and quickest | high detail | textures, deforms, and catches bright impacts |
| Drifter | compact and steady | midrange | keeps the group from becoming a three-note diagram |

Additional bodies extend the population without replacing these identities. Sound disturbs existing motion; it does not spawn anonymous particles.

## Habitats

Resizing changes the stage, not the cast.

- **Micro:** protect one readable ballast body.
- **Chimney:** stack three bodies in a loose vertical convection path.
- **Basin:** give four bodies separate home regions with room to meet.
- **Current:** distribute bodies horizontally and let motion travel along the tile.

Habitat anchors are weak. Continuous currents do most of the moving: chimney tiles rise through the middle and return at the walls, current tiles travel horizontally with a quiet return lane, and basin or micro tiles circulate. Bodies should settle toward a composition without looking attached to animation waypoints.

The active cast has a mass-weighted visual center. A first viewport composes that center near the middle of the available tile. In a wide current, the useful middle is a dead zone with no group correction; near an edge, a nonlinear shared leash progressively redirects the cast and bleeds only its outward mean momentum. This permits a brief edge composition but prevents sustained sound from parking the whole cast in a corner. Other habitats retain a weak shared correction. Both approaches translate the cast without pinning any individual body or erasing spacing, collisions, and wall contact.

## Acoustic Grammar

- Silence sustains slow independent circulation.
- Bass moves mass outward and downward, then leaves wall pressure to resolve.
- Voice changes circulation most strongly around the listener.
- High detail deforms and textures smaller bodies more than it translates the group.
- Tempo changes the rate of convection and gives every body phase-offset breathing, stretch, and orbital pressure.
- Rapid rhythmic density is separate from tempo. Closely spaced attacks add bounded contour flutter, repeated compression, and circulation pressure without pretending every subdivision is the main beat.
- A transient selects one pitch-adjacent body for physical impact and softer afterglow.
- Its contour points only when the listening band also exceeds its learned baseline.
- A band spikes only when it rises meaningfully above its noise-aware rolling average over roughly 2.4 seconds. Steady loudness and repeated ordinary attacks remain soft.
- Strong rising events also send a bounded pressure wave across the shared tile. Nearby bodies feel it first; it changes motion and compression without spending the attention color.

The mapping is intentionally elastic. Believable cause and effect matters more than frame-perfect beat synchronization.

## Embodied Mirror

The organism responds on three overlapping clocks. Gesture-scale cues such as attacks and band rises land immediately and leave a brief physical memory. Phrase-scale cues accumulate agitation, tension, volatility, and novelty over a few seconds. Atmosphere-scale cues slowly establish weight, cohesion, openness, and intimacy. A sudden fall after sustained pressure becomes release.

Restrained passages establish a separate readiness for contrast. Readiness fills over roughly eight to ten seconds, saturates, and never grows larger merely because restraint continues. A credible attack followed by one confirming frame of coherent multi-band change consumes that readiness as a snap: first local impact, then bounded group opening and cathartic circulation. Equivalent snaps after 10 seconds and 130 seconds should therefore produce equivalent action. A lone notification remains local, while a gradual crescendo opens the posture without crossing an arbitrary snap threshold.

These values describe posture rather than claiming to recognize sadness, joy, anger, or any other named emotion. Tension and intimacy contract the group, weight lowers its center, agitation roughens circulation and edges, and openness or release expands the cast. Brightness remains on a separate attention budget, so an emotionally intense passage can change stance and motion without washing out the tile.

## Narrative Context

Predictable timing and stable posture build expectation. A strong gesture becomes interruption in proportion to the expectation it violates, so the same transient can carry more consequence after an established pattern than in isolation. Tension followed by release becomes resolution. Expectation gently contracts the cast; interruption and resolution reuse bounded opening, acceleration, and breathing rather than triggering scripted scenes.

These relationships are authored subtext, not detected meaning. Lavatune never claims to know the artist's intent or the listener's emotion. The narrative layer describes why its own organism responds differently to acoustically similar events in different temporal contexts.

The intended arc is legible but restrained: pressure gathers, bodies draw closer and hold more memory, a change in the source registers promptly, and release opens the composition. The posture should remain believable across speech and noisy guitars without pretending that either has one deterministic meaning.

## Midwest Emo Grammar

The default behavior is authored around a Midwest emo arc without attempting genre recognition. Quiet high detail and conversational voice accumulate fragility and yearning: smaller listening bodies become more intricate, the cast draws inward, and vertical shapes reach without resolving. Tension remains in the longer posture instead of flashing on every note.

When a strong rise arrives after that held posture, catharsis converts the stored tension into outward pressure, larger breathing, and faster circulation. The response is intentionally disproportionate to the event because the preceding restraint is part of its meaning. Bodies keep different phases, so intricate or irregular tempo feels collective but never lockstep. After the break, pressure and spikes recover quickly while afterglow and yearning take longer to leave.

These are transparent acoustic relationships, not a model deciding whether the source is Midwest emo. Other speech and music can produce the same posture when they share the same dynamics.

Listening mode keeps real spectral bands even under the restrained display cadence. Analysis cost is small compared with terminal rendering, and broad envelope history is not an acceptable substitute for tonal response when the measured power difference is negligible. Low-power mode may use coarse three-region analysis.

## Attention Budget

Body color is muted and matte. The final palette color belongs only to local afterglow. Loudness may change motion and deformation, but it must not turn the entire field bright.

Normal operation shows the organism and optional local media title. Controls and diagnostics are temporary editing surfaces, not part of the daily composition.

Text and Fluid are output materials applied after physics. Weight changes field occupancy, Edge changes surface definition, and Afterglow changes only the bounded attention contribution. A material change must never reset or reinterpret the organism.

Calmness includes resource use. Silence should not keep a CPU core or laptop fan busy merely to prove the organism is alive. The display cadence therefore ranges from 2 FPS at rest through 4 and 8 FPS in ordinary listening, with 14 FPS reserved for short transients. Physics uses its own lower 2/4/6/8 FPS schedule and bounded elapsed-time substeps, so conserving terminal work must not change the organism's personality or sense of time.

## Review Protocol

Every behavior pass is judged with the same silence, speech, bass, music, and transient sequence in micro, chimney, basin, and current tiles.

A pass succeeds when:

- the default is recognizable in a still frame
- sound categories produce different physical consequences without labels
- resizing preserves identity and momentum
- silence remains alive without demanding attention
- a transient stays local and visibly recovers
- a rapid run remains patterned instead of collapsing into one sustained maximum, then settles promptly when the run ends
- steady compressed audio does not create rapid motion without repeated attacks
- established restraint produces the same bounded snap after 10 seconds or 130 seconds
- a lone notification remains local and a gradual crescendo opens without a false snap
- predictable motion establishes expectation and the same surprise has more consequence in context
- resolution requires prior tension and release rather than loudness alone
- sustained action may visit a current's edge but cannot leave the whole cast parked there
- ordinary body intensity never receives the attention color
- the closed control dock consumes no tile area
- silence settles to the lowest cadence and ordinary music does not require transient cadence

## Non-goals

Lavatune is not a bar equalizer, waveform display, beat detector demo, dashboard, screensaver, or collection of unrelated visualizer skins.
