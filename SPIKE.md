# SPIKE: Python Vivint camera plugin for Scrypted (fork scryptedapp/blink + vivintpy)

## Verdict: VALIDATED

**Question:** Can a Scrypted *Python* camera plugin be forked from
[scryptedapp/blink](https://github.com/scryptedapp/blink) and wired to
[vivintpy](https://github.com/natekspencer/vivintpy) to expose Vivint cameras —
streams, snapshots, and cloud motion/doorbell events — to Scrypted?

**Evidence:** `tests/spike_harness.py` — **47/47 checks pass** against real
`vivintpy 2026.0.6` (installed cleanly on Python 3.14.4, MIT license, actively
maintained, backs the official Home Assistant integration) with a stubbed
`scrypted_sdk` plugin runtime and crafted Vivint device data. The provider's
real startup path (auto `start_init` → `Account.connect` → discovery) is
exercised end-to-end via a patched `Account` factory.

## What worked

- **Fork fidelity:** blink's 3-file structure ports 1:1 — `package.json`
  (`"runtime": "python"`, pluginDependencies `@scrypted/snapshot` +
  `@scrypted/prebuffer-mixin`), `main.py` (`create_scrypted_plugin`),
  `provider.py`, `camera.py`, `requirements.txt` (blinkpy → vivintpy).
- **Discovery:** systems → panels → devices, `isinstance(Camera)` filter, real
  vivintpy model/manufacturer/firmware/serial. Doorbell models
  (DBC350 etc.) get `MotionSensor` + `Doorbell` interfaces; non-camera devices
  skipped.
- **Streams:** `getVideoStream()` returns an ffmpeg `MediaObject`; URL chain
  direct-LAN → panel relay → Vivint cloud, with correct vivintpy URL formats
  (creds embedded). Stream source correctly labeled local/panel/cloud.
- **Snapshots:** `request_thumbnail()` → `get_thumbnail_url()` → session fetch
  → image/jpeg MediaObject, 60s cache.
- **Cloud motion (the ask):** PubNub messages routed through vivintpy's own
  `handle_pubnub_message` → `motionDetected` set (with 30s auto-reset);
  `doorbell_ding` → Scrypted `Doorbell` device event. No local video
  processing needed.
- **2FA:** MFA-required exception → waiting state → `verify_mfa(code)` →
  discovery; refresh token persisted to storage for reconnects.
- **Toggle:** `use_cloud_motion=false` → `connect(subscribe_for_realtime_updates=False)`
  and no `MotionSensor` interface, so Scrypted's local analysis (OpenCV etc.)
  can be used instead.
- **Failure paths:** invalid creds → cleanup (account + session closed);
  missing creds → early return.

## What failed or surprised us

- **vivintpy KeyErrors on cameras without direct-access data** (`cda` key
  missing entirely) — the direct-URL attempt must be wrapped (fixed in
  `camera.py`).
- **Panel AND cloud RTSP URLs both require panel credentials** — with no
  creds there is no stream at all; the plugin raises cleanly. (HA integration
  avoids this by defaulting to the internal stream; our chain prefers direct
  first.)
- Camera without a panel-stream field (`ciu`) raises `IndexError` — guarded,
  falls through to the cloud relay.
- Harness-only: `asyncio.coroutine` removed in Python 3.14.

## Not validated (needs the real world)

- **Live Vivint Sky login** and real device payloads (no test account —
  needs Asher's credentials).
- **Scrypted server deploy** (`npm run build` / scrypted-deploy; the Python
  runtime installs `requirements.txt` on load).
- `ScryptedInterface.Doorbell` event payload contract `{doorbell: true}`
  (matches other cloud camera plugins; confirm on a server).
- Real stream latency/reliability over the Vivint relay (panel path expected).

## Recommendation: SHIP (as a real plugin)

This spike is a working v0.1 port — small enough that "rewrite for production"
is mostly polish + live validation. Next steps:

1. Live-login test with Asher's Vivint account (expect: 2FA code entry).
2. Deploy to a Scrypted server, verify streams, HKSV, motion + doorbell events.
3. Decide on GitHub: fork `scryptedapp/blink` on Asher's account or a fresh
   `scrypted-vivint` repo (spike is currently local, no remote).

## Files

- `src/vivint/provider.py` — Settings/2FA/DeviceProvider/discovery (blink port)
- `src/vivint/camera.py` — Camera/VideoCamera/MotionSensor/Doorbell (blink port)
- `tests/spike_harness.py` + `tests/stub_sdk/` — 47-check validation harness
- `.venv/` — throwaway (vivintpy 2026.0.6, Python 3.14.4)
