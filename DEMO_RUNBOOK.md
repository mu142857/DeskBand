# DeskBand demo runbook

## Before presenting

1. Launch `dist/DeskBand.app` on the presentation Mac. Confirm a camera image appears and the MacBook speakers or chosen output device are audible. If using an iPhone, connect Continuity Camera before opening DeskBand and check the macOS Video menu for Main camera, Zoom 1×, and Center Stage off.
2. Keep 2–4 distinctive objects within reach. The saved shelf holds one slot per instrument category, so use different categories for a visibly growing band.
3. Check that `cache/elevenlabs_api_key` exists with mode `600` **only if** the account has Music API access. The key never belongs in Git. The present key authenticates but the Music endpoint returns `paid_plan_required`; do not promise a live ElevenLabs generation until that account restriction is resolved.
4. If a completed ElevenLabs song is available in `cache/songs/`, keep its job JSON and MP3 together. DeskBand restores a completed song when the same arrangement is selected on the Collected page. The current workspace has no completed ElevenLabs MP3.

## Live sequence

1. Point the camera at the first item, wait for its single white detection frame, then press `space` to capture. Repeat with other categories; `space` again returns to the camera after each shot.
2. Press `e` or **Finish**. Show each saved card's object name, instrument, and actual note or beat strip. Toggle cards to change the band if useful.
3. Click **Render loop**. The file is one complete chord cycle, normally four bars and about eight seconds at 120 BPM. Click **Play clip** and **Reveal file**. This entire path works offline.
4. If Music API access and source-audio rights are confirmed, click **Continue with ElevenLabs**, read the upload notice, then click **Upload & generate**. Wait for the completed MP3, then use **Play song** and **Reveal song**. Upload and generation may take time or credits; an upload can be rejected by screening. If the service errors, show the saved local WAV instead.
5. Click **Back to collecting** to resume the camera and band.

## Verified local timing and fallback

On 2026-09-19, an offline render of four saved selected categories (cup, book, laptop, cell phone) took **0.7 seconds** and produced a stereo 44.1 kHz PCM16 WAV lasting **7.999 seconds**. A two-second speaker-stream check started and stopped on MacBook Pro Speakers. DeskBand's running app reported all four saved items and detected a laptop through the camera. The full visual click sequence and subjective speaker listening still need a person at the presentation Mac.

The local WAV in `cache/exports/` is the current offline fallback. The app can also restore and play a previously generated full song from `cache/songs/` after a restart, but none exists yet. ElevenLabs upload/generation timing and full-song playback are unmeasured because the account's Music API returns HTTP 402 `paid_plan_required`. Do not describe a local loop or a mock test MP3 as an ElevenLabs result.

## Recovery

- **No camera:** check System Settings → Privacy & Security → Camera → DeskBand, then confirm the camera is available in macOS and reopen the app. DeskBand currently uses camera index `0`; device order can change when Continuity Camera connects.
- **No sound:** check the macOS output device and volume, then use **Play clip** again. The local WAV remains under `cache/exports/` even if playback fails.
- **Music API error:** preserve the WAV. Check the account plan and key permissions before another explicit attempt. A failed composition request may have consumed credits, so the app does not retry it automatically.
- **Changed band:** click **Render again** before uploading. The previous WAV stays on disk but no longer represents the current selection.
