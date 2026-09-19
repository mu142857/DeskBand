# DeskBand ending screen, loop export, and ElevenLabs song roadmap

Status: Milestones 0–1 complete. Milestones 2–5 remain open.

## Product flow and decisions

1. The user photographs objects as today. Each recognized instrument type occupies one persistent shelf slot; a second object of the same type replaces that slot's picture. This is **not** per-physical-object recognition yet.
2. A new **Finish** button opens an ending screen inside the existing 1280×720 desktop window. It shows every collected shelf entry, including entries currently switched off. Each entry shows its thumbnail, object name, instrument name, and a short visual representation of its actual melody or rhythm. Switched-on entries are marked **In this song**.
3. The user can adjust which collected entries are included, then choose **Render loop**. DeskBand freezes that selection and the active BPM/chords into a session snapshot, renders one complete chord cycle, and offers playback plus a local WAV file. The default progression has four bars; at 120 BPM its duration is 8 seconds. If a remote `style` command changed the progression length, the UI must show and render the actual cycle length rather than claim it is always four bars.
4. After rendering, **Make a full song with ElevenLabs** uploads that exact WAV and generates a longer track. The default experience keeps the DeskBand clip unchanged as the intro and asks ElevenLabs Music v2.5 to continue it. The output is saved locally and can be played from the ending screen. This is an explicit, potentially paid network action; no upload starts when the user merely opens the screen.
5. **Back to collecting** returns to the previous camera state with the shelf intact. Changing the selection, BPM, chord progression, or an item's motif invalidates the old render as the *current* song. The previous WAV remains on disk but cannot be sent as if it represents the new selection.

### Locked screen copy and file contract

- **Collected** counts all saved shelf categories, including those switched off. **In this song** labels each card's selection toggle and counts only selected categories. A collected item can therefore be left out of the mix without being forgotten.
- **Finish** opens the `SUMMARY` state in the existing OpenCV window. **Back to collecting** returns to the previous preview or frozen-photo state. **Render loop** renders one complete active chord progression from bar one; its button is disabled when the song has no selected parts.
- **Continue with ElevenLabs** appears only after a current local render exists. Its action explicitly says the WAV will be uploaded and generation may use paid credits; opening the summary never starts an upload. **Render again** replaces the current result after a sound-changing edit.
- Export exactly one complete progression to a stereo 16-bit PCM WAV at the app's output sample rate. The default is four bars and about eight seconds at 120 BPM; always show the actual bar count and computed duration. The full-song target is roughly 30–45 seconds, with the local loop kept unchanged at the beginning. The exact generated duration is shown from the resulting file.
- Store loop WAVs under `cache/exports/`, song audio and job metadata under `cache/songs/`, and any service response/debug payloads under `cache/`. Never write API keys to these files. All three locations are ignored by Git. Python packages come from `requirements.txt` installed into `.venv`; the cloud calls use standard-library `urllib` and read `ELEVENLABS_API_KEY` from the process environment.

### Important current-code facts

- `deskband/config.py` defines four default chords, one bar each, and 120 BPM. `Composer` can also accept a different progression with 1–16 chords through the remote `style` command.
- `deskband/shelf.py` now persists thumbnails, selected state, stage position, and the random seed from the latest capture in `cache/shelf/shelf.json`. There is one slot per instrument type, not one slot per physical item.
- `deskband/music.py` uses the saved seed for a repeating standard-mode motif; math mode intentionally keeps evolving. `deskband/arrangement.py` provides a fresh bar-one score with the active chords, BPM, selected parts, stage positions, and math-mode setting. This is a new cycle, not a recording of the one already sounding.
- The synced app also has a stage view, Gemini captions for the current photo, and optional ElevenLabs-generated vocal samples. Captions are not stored per shelf item, and those vocal samples are separate from the planned full-song continuation.
- `tools/render_demo.py` exercises offline rendering, but is a scripted demo with hard-coded entries (including an obsolete `lamp`). It should be refactored or used as a reference, not called unchanged from the ending screen.
- `deskband/synth.py` mixes audio through samples, reverb, and limiter. The live `Engine` and `Composer` are mutable; exporting should use an isolated engine rather than drive the live audio callback from a worker.

## Proposed data contracts

- **Shelf entry**: existing class key, display name, thumbnail, instrument key/label, random motif seed or versioned motif parameters, saved time, and selected flag. Re-photographing the same slot generates a new seed. Preserve existing saved seeds when loading and migrate older entries without losing thumbnails.
- **Arrangement snapshot** (immutable): included shelf IDs, each item's instrument and motif, ordered chord list, BPM, sample rate, bar count, creation time, and a content fingerprint. Take it on **Render loop**, after all UI choices are settled. Use the same snapshot to draw note/rhythm previews and to render audio.
- **Rendered loop**: snapshot fingerprint, absolute WAV path, sample rate, exact frame count/duration, and creation time. Store under ignored `cache/exports/`; expose **Reveal in Finder** or an equivalent visible path so the user can retrieve it.
- **Song job**: snapshot fingerprint, reference WAV, ElevenLabs upload `song_id`, requested model/structure, status, output path, and a user-readable error. Never persist the API key. If the user changes the band during a job, keep the job's snapshot and label its result accordingly.

## Milestone 0 — lock the behavior and prepare the project

**Goal:** everyone implements the same meaning of “collected,” “melody,” and “based on my loop.”

- [x] M0.1 Confirm the ending screen is a new state in the existing OpenCV window, with **Finish** and **Back to collecting** navigation (`main.py`).
- [x] M0.2 Define copy for **Collected**, **In this song**, **Render loop**, and **Continue with ElevenLabs** so saved items and selected items are visibly different.
- [x] M0.3 Choose the initial output contract: one active chord cycle, stereo WAV, original clip retained as the full-song intro, approximately 30–45 seconds for the complete generated track. Display the actual bar count and duration.
- [x] M0.4 Add a direct dependency list or lock file for the Python packages the new integration imports. Keep installation scoped to `.venv`; read `ELEVENLABS_API_KEY` from the process environment.
- [x] M0.5 Keep generated exports, song results, thumbnails, credentials, and API responses in ignored locations. Verify the ignore rules with `git check-ignore` and inspect `git status`.

**Done when:** the product flow and local file formats are documented with no ambiguous “saved means playing” behavior.

## Milestone 1 — saved item motifs and snapshot

**Goal:** each card describes the part the user will actually hear in the exported arrangement.

- [x] M1.1 Extend `Shelf.Entry` serialization with a versioned motif seed and instrument key. Migrate existing shelf entries without losing pictures or order (`deskband/shelf.py`).
- [x] M1.2 Decide whether selection should survive an app restart; for this flow, persist the selected flag and load it before `App.apply_parts()` so a returning user sees the intended band. Provide a clear “select none” action.
- [x] M1.3 Replace `hash(name)` as the source of musical identity with a fresh random seed on each capture. Keep the latest seed per shelf slot, and define how it is harmonized when the chord loop changes (`deskband/music.py`).
- [x] M1.4 Make each part expose a four-bar note/hit timeline or a compact motif description. For drums, display a beat grid rather than pretending pitched notes exist. Include note, step, duration, and velocity in the underlying data.
- [x] M1.5 Ensure live playback and offline rendering consume the same saved seed. Re-photographing an item updates its thumbnail and requests a new motif from the next full loop.
- [x] M1.6 Define and implement an immutable `ArrangementSnapshot` factory from the shelf selection, current `Engine.bpm`, and active `Composer.chords`. Resolve any pending `style` command before freezing the snapshot or explicitly show that it is pending.
- [x] M1.7 Include a fingerprint of all sound-changing inputs, including selected slots, motif versions, BPM, and chord voicings. Use it to detect stale exports after edits.
- [x] M1.8 Add focused tests for shelf migration, restart stability, re-photograph behavior, chord changes, selected-only timelines, and snapshot fingerprints.
- [x] M1.9 Capture the audio thread's active chord/BPM state at a defined bar boundary or through a synchronized read. Do not copy mutable composer fields while the callback is changing them; document whether the summary uses the currently sounding cycle or the next complete cycle.

Implementation note: the score and future WAV export describe a **new complete chord cycle starting at bar one** using the active published harmony and current BPM. If a new style is pending, `ArrangementSnapshot.style_pending` is true. `ArrangementSnapshot.make_composer()` restores the motif seeds, stage complexity, and math mode for that fresh cycle. Stage loudness is stored in each item's position for the future exporter. In math mode the melody evolves, so a fresh score cannot be described as the live cycle already sounding.

**Done when:** reopening the app does not alter a saved item's motif, and the ending screen can show the exact note/hit pattern chosen for the export.

## Milestone 2 — ending screen and navigation

**Goal:** a complete local experience before any cloud integration.

- [ ] M2.1 Add `SUMMARY` to the app state machine. Remember whether the user came from preview or frozen-photo mode; Back restores that state without discarding the shelf (`main.py`).
- [ ] M2.2 Add a visible **Finish** button and a keyboard shortcut that do not collide with shutter, play/pause, shelf slots, or fullscreen. Route mouse and keyboard input by state so camera controls do not fire under the summary.
- [ ] M2.3 Draw the ending screen with all saved entries in shelf order; support 0–8 entries at 1280×720 without clipping. Use saved thumbnails and labels from the shelf; no live camera frame is required for the screen to render.
- [ ] M2.4 Show instrument name and motif/rhythm strip for each entry, plus a clear **In this song** toggle. Toggling updates the shelf selection and the proposed snapshot, but does not silently overwrite an existing WAV.
- [ ] M2.5 Show title, BPM, chord names, bar count, estimated duration, and number of included instruments. Offer an empty-state explanation and disable Render/ElevenLabs when nothing is selected.
- [ ] M2.6 Add **Render loop**, local playback controls, **Reveal file**, **Continue with ElevenLabs**, and **Back** states. Disable conflicting actions and show progress while a worker is busy.
- [ ] M2.7 Keep the main OpenCV loop responsive: UI reads job status from a thread-safe queue; no sample loading, file writing, upload, or generation occurs in `render()` or the audio callback.
- [ ] M2.8 Add UI tests for state transitions and hitboxes, plus a manual visual check with 0, 1, 4, and 7 collected items and long labels.

**Done when:** the user can inspect the collection, choose the band, and return to the camera even with no network or API key.

## Milestone 3 — accurate four-bar loop export

**Goal:** generate a listenable file from the exact arrangement shown on the ending screen.

- [ ] M3.1 Extract a reusable offline render path from the approach in `tools/render_demo.py`; give it an `ArrangementSnapshot` input and a WAV output path. Do not reuse its hard-coded demo script.
- [ ] M3.2 Create a separate `Composer` and `Engine` for export. Load the needed samples outside the audio callback, use the snapshot's tempo/chords/motifs, and use the Mac clock even when live playback is FPGA-controlled.
- [ ] M3.3 Render from a bar-one downbeat for exactly one active chord cycle. Account for the engine's initial gain ramp and reverb state with pre-roll or another explicit strategy, then apply a short boundary-safe fade so the exported file does not click.
- [ ] M3.4 Use the same recorded event timeline to draw each card's melody/rhythm and to render the mix. Exclude live-only `sfx` and transient hardware events unless deliberately captured in the snapshot.
- [ ] M3.5 Write stereo PCM WAV to a temporary file, validate sample rate/frame count/non-silence/finite samples/peak, then atomically move it into `cache/exports/`. Include a readable timestamp and fingerprint in the filename or metadata.
- [ ] M3.6 Show rendering progress and errors without freezing the UI. Prevent a second concurrent render from corrupting the first.
- [ ] M3.7 Let the user play, stop, and reveal the resulting clip. Keep playback from the summary from accidentally layering with the live band; define whether entering summary pauses the live engine and restore its prior play state on Back.
- [ ] M3.8 Invalidate the “send current loop” action if the selected band, BPM, chords, or motif changed since export. Offer **Render again**.
- [ ] M3.9 Test empty band, single instrument, all eight instruments, custom chord-loop length, changed BPM, paused live playback, FPGA mode, output length, clipping, and deterministic repeat export in standard mode. Define and test fresh-cycle export behavior for evolving math mode. Listen to at least one real WAV.

**Done when:** the WAV and the on-screen item patterns refer to the same arrangement, and a default four-bar export lasts about eight seconds at 120 BPM.

## Milestone 4 — ElevenLabs full-song continuation

**Goal:** turn the user-approved local loop into a longer song while preserving its provenance.

- [ ] M4.1 Confirm the team's ElevenLabs account has Music API access, available credits, and permission to upload the rendered source audio. Check whether any bundled instrument samples trigger the upload copyright screening; prepare an upload-safe fallback sound palette if needed.
- [ ] M4.2 Build a small integration module, separate from `deskband/synth.py`, with an injectable HTTP client so API calls can be tested without charging credits. Read `ELEVENLABS_API_KEY` only from the environment and show a useful missing-key state.
- [ ] M4.3 Require an explicit click after local preview. Display that the WAV will be sent to ElevenLabs and that generation can take time or consume credits.
- [ ] M4.4 Validate the selected WAV exists, matches the current snapshot fingerprint, has a supported format and sensible duration, and is at most the reference limit used by the chosen API path.
- [ ] M4.5 Upload the WAV with the Music Upload API and save the returned `song_id` with the local job. Handle content screening or upload rejection without losing the WAV.
- [ ] M4.6 Submit an explicit `music_v2_5` composition plan: first an audio-reference chunk containing the full DeskBand loop unchanged, then one or more instrumental generation chunks. Apply `conditioning_ref` to the first generated chunk and specify the selected instrument palette, tempo, mood, and high context adherence. Keep the plan short for demo latency.
- [ ] M4.7 Stream or download the generated audio to a temporary file, validate that it decodes and has the expected duration, then move it atomically to `cache/songs/`. Persist the model, prompt/plan, uploaded `song_id`, source fingerprint, output path, and status without logging secrets.
- [ ] M4.8 Show queued/uploading/generating/saving/done/error states. Keep the UI and local audio usable during network waits. Support retry from the saved WAV; avoid blindly repeating an uncertain, possibly charged compose request.
- [ ] M4.9 Provide play/stop and reveal controls for the full song. Label the retained intro and AI-generated continuation honestly; the generated portion may reinterpret rather than duplicate the original motif.
- [ ] M4.10 Test request construction, upload rejection, invalid key, timeout, partial download, malformed output, stale snapshot, and a successful mocked job. Run one end-to-end real API call with the team's key before the demo and keep the resulting track as a fallback.

**Done when:** a fresh local four-bar WAV can be uploaded, heard unchanged at the start of a longer downloaded track, and shown with clear failure states if the service is unavailable.

## Milestone 5 — release and demo verification

- [ ] M5.1 Document the new controls, `.venv` dependencies, `ELEVENLABS_API_KEY` setup, local export locations, model choice, and API/network requirements in `README.md`.
- [ ] M5.2 Verify `cache/exports/`, `cache/songs/`, shelf photos, API keys, and generated audio remain outside Git; inspect `git status` after a complete session.
- [ ] M5.3 Run the existing reverb, voice, remote, shelf, and FPGA tests. Add only meaningful tests for new snapshot, exporter, UI transitions, and API integration behavior.
- [ ] M5.4 Rebuild `dist/DeskBand.app`, verify its arm64 launcher/signature, and test the full click path in the app on the presentation Mac with the actual camera and audio output.
- [ ] M5.5 Do a timed rehearsal: collect 2–4 reliable objects, inspect the summary, render and play the loop, generate and play the full track. Record actual upload/generation times and adjust the demo script.
- [ ] M5.6 Prepare an offline demo fallback: the local render must work without ElevenLabs, and a previously generated full song should be available if network or credits fail.

**Demo-ready cutoff:** Milestones 0–3 provide a complete, local, reliable ending screen and four-bar export. Milestone 4 is the sponsor feature. Milestone 5 makes the presentation dependable.

## Main risks and scope boundary

| Risk | Plan |
|---|---|
| “Dedicated melody” is not yet visible in an ending screen | Milestone 1 stores the latest capture seed and exposes real note/hit events; Milestone 2 presents them. |
| Multiple physical objects of one class | Existing shelf has one slot per instrument type. Keep that behavior for this feature; per-instance tracking is separate work. |
| New `style` command changes bar count | Render and label one whole active progression, normally four bars. |
| API changes, paid access, upload screening, latency | Use documented Music v2.5 upload + inpainting/conditioning path, a mockable client, one real rehearsal, and a cached fallback. |
| Reference does not preserve exact notes in generated audio | Keep the original WAV as an unchanged intro chunk; describe the following section as a continuation inspired by it. |
| Existing sample-library content and upload rights | Verify the source-audio rights and screening outcome before sending demo clips; substitute owned/synthesized sounds if needed. |
| UI/audio stalls | Render and network calls run in workers; live callback only plays audio. |

## API references checked for this plan

- [ElevenLabs Music Upload API](https://elevenlabs.io/docs/api-reference/music/upload): upload existing audio and obtain a `song_id`; uploads are screened.
- [ElevenLabs Music inpainting guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/music/inpainting): audio-reference chunks can preserve uploaded sections; `conditioning_ref` guides generated chunks; Music v2/v2.5 is required.
- [ElevenLabs Music Compose API](https://elevenlabs.io/docs/api-reference/music/compose): composition plans generate downloadable audio.
- [ElevenLabs Music overview](https://elevenlabs.io/docs/overview/capabilities/music): audio references guide sound and style but do not copy the source; check account/API availability before implementation.
