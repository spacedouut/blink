# Vivint Camera Plugin for Scrypted (SPIKE)

Fork of [scryptedapp/blink](https://github.com/scryptedapp/blink) (a Python-runtime Scrypted
camera plugin) with the Blink API swapped for [vivintpy](https://github.com/natekspencer/vivintpy).

## What works (validated in spike harness)

- Settings UI: username/password/2FA code + "use cloud motion events" toggle
- vivintpy `Account` login incl. MFA flow (mirrors the Home Assistant integration)
- Camera discovery across systems → panels → devices (only `Camera`-type devices)
- Per-camera devices with `Camera`, `VideoCamera`, `MotionSensor` (cloud toggle),
  and `Doorbell` (models whose name contains "Doorbell")
- `getVideoStream()` → RTSP URL via ffmpeg media object, direct → panel → cloud fallback
- `takePicture()` → Vivint thumbnail URL fetched through the account session
- Cloud motion events via vivintpy PubNub subscription → Scrypted `MotionSensor`
  + `Doorbell` events (auto-clear after 30s)

## Not yet validated

- Live login against the real Vivint Sky API (needs Asher's credentials)
- Build/deploy to a real Scrypted server (`npm run build` / `scrypted-deploy`)
- Whether `ScryptedInterface.Doorbell` event payload `{doorbell: true}` is the
  correct Scrypted contract (matches other cloud camera plugins)

## Build / deploy (same as blink)

```bash
npm install
npm run build
# then deploy via VS Code (scrypted-vscode-launch) or scrypted-deploy
```

The Scrypted Python runtime installs `src/requirements.txt` (`vivintpy`) on plugin load.

## Spike

See `SPIKE.md` in the spike root (`../SPIKE.md`) for the verdict and evidence.
