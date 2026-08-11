"""Spike harness: validate the blink->vivint Python Scrypted camera plugin wiring.

Uses REAL vivintpy classes (installed in .venv) with crafted device data + a
stubbed scrypted_sdk plugin runtime. No live Vivint credentials are used here.

The provider's real startup path is exercised: VivintProvider() schedules
start_init(), which builds an Account via vivint.provider.Account — we monkeypatch
that symbol to return a FakeAccount, so connect/discover/2FA flows run for real
against deterministic fakes.

Run: .venv/bin/python tests/spike_harness.py
"""

import asyncio
import os
import sys
from types import SimpleNamespace

# stub scrypted_sdk first, then the plugin source
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "stub_sdk"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import scrypted_sdk  # noqa: E402
import vivint.provider as vp  # noqa: E402
from vivint.provider import VivintProvider  # noqa: E402
from vivint.camera import VivintCamera  # noqa: E402
from vivintpy.devices.camera import Camera as VivintCameraLib  # noqa: E402
from vivintpy.exceptions import (  # noqa: E402
    VivintSkyApiAuthenticationError,
    VivintSkyApiMfaRequiredError,
)

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

class FakeApi:
    def __init__(self):
        self.thumb_requests = []
        self.thumb_url = "https://thumb.vivint.example/cam1.jpg?token=x"

    async def request_camera_thumbnail(self, panel_id, partition_id, device_id):
        self.thumb_requests.append((panel_id, partition_id, device_id))

    async def get_camera_thumbnail_url(self, panel_id, partition_id, device_id, timestamp):
        return self.thumb_url


class FakeSystem:
    def __init__(self, api, alarm_panels):
        self.id = alarm_panels[0].id
        self.api = api
        self.alarm_panels = alarm_panels
        self.is_admin = True


class FakeAlarmPanel:
    def __init__(self, id, partition_id, devices, api):
        self.id = id
        self.partition_id = partition_id
        self.devices = devices
        self.system = FakeSystem(api, [self])
        self.credentials = None
        self.can_creds = True

    async def get_panel_credentials(self):
        if not self.can_creds:
            self.credentials = None
            return
        self.credentials = {"n": "paneluser", "pswd": "panelpass"}


class FakeAccount:
    """Duck-typed stand-in for vivintpy Account (login is not exercised live)."""

    def __init__(self, scenario="ok"):
        self.scenario = scenario
        self.systems = []
        self.connected = False
        self.refresh_token = "rt-123"
        self.verified = False
        self.subscribe = None

    async def connect(self, load_devices=False, subscribe_for_realtime_updates=False):
        self.subscribe = subscribe_for_realtime_updates
        if self.scenario == "mfa":
            raise VivintSkyApiMfaRequiredError()
        if self.scenario == "auth":
            raise VivintSkyApiAuthenticationError()
        self.connected = True

    async def verify_mfa(self, code):
        self.verified = True
        self.connected = True

    async def disconnect(self):
        self.connected = False


class FakeSession:
    def __init__(self, body=b"\xff\xd8fakejpeg"):
        self.body = body
        self.gets = []
        self.closed = False

    class _Resp:
        def __init__(self, body):
            self._body = body

        async def read(self):
            return self._body

    async def get(self, url):
        self.gets.append(url)
        return self._Resp(self.body)

    async def close(self):
        self.closed = True


def make_panel(api):
    doorbell_data = {
        "_id": 1, "n": "Front Door", "t": "camera", "panid": 111,
        "cmac": "AA:BB:CC:DD:EE:01", "sv": "4.2.1", "ol": True,
        "ctd": "2026-08-10T12:00:00.000",
        "act": "vivint_dbc350_camera_device",
        # NOTE: no "cda" key at all - real Vivint data omits it for non-direct cameras,
        # and vivintpy KeyErrors on the direct lookup. Exercises the plugin's guard.
        "ciu": ["rtsp://10.10.1.6:8554/panel-hd"],
        "cus": ["rtsp://10.10.1.6:8554/panel-sd"],
        "ceu": ["rtsp://relay.vivint.example/cloud-hd"],
        "ces": ["rtsp://relay.vivint.example/cloud-sd"],
    }
    outdoor_data = {
        "_id": 2, "n": "Backyard", "t": "camera", "panid": 111,
        "cmac": "AA:BB:CC:DD:EE:02", "sv": "4.2.1", "ol": True,
        "ctd": "2026-08-10T12:00:00.000",
        "act": "vivint_odc350_camera_device",
        "cda": True, "caip": "192.168.1.50", "cap": 6500,
        "cdp": "h264", "cdps": "h264sd", "un": "camuser", "pswd": "campass",
        "ciu": ["rtsp://10.10.1.6:8554/panel-hd"],
        "ceu": ["rtsp://relay.vivint.example/cloud-hd"],
    }
    ping_data = {
        "_id": 3, "n": "Ping Cam", "t": "camera", "panid": 111,
        "cmac": "AA:BB:CC:DD:EE:03", "sv": "1.0", "ol": True,
        "ctd": "2026-08-10T12:00:00.000",
        "act": "alpha_cs6022_camera_device",
        "cda": True, "caip": "10.0.0.9", "cap": 6500,
        "cdp": "h264", "cdps": "h264sd", "un": "u", "pswd": "p",
        "ciu": ["rtsp://10.10.1.6:8554/panel-hd"],
        "ceu": ["rtsp://relay.vivint.example/cloud-hd"],
    }
    panel = FakeAlarmPanel(111, 1, [], api)
    panel.devices = [
        VivintCameraLib(doorbell_data, panel),
        VivintCameraLib(outdoor_data, panel),
        VivintCameraLib(ping_data, panel),
        SimpleNamespace(name="Motion Sensor", id=99),  # non-camera device
    ]
    return panel


def make_account_with_panel(scenario="ok"):
    api = FakeApi()
    panel = make_panel(api)
    account = FakeAccount(scenario)
    account.systems = [panel.system]
    return account, panel, api


async def make_provider(use_cloud_motion="true"):
    """Construct a VivintProvider whose auto-start init runs against a fake account."""
    provider = VivintProvider()
    provider.session = FakeSession()
    provider.storage.setItem("username", "asher@example.com")
    provider.storage.setItem("password", "hunter2")
    provider.storage.setItem("use_cloud_motion", use_cloud_motion)
    account, panel, api = make_account_with_panel()
    provider._fake_account = account
    vp.Account = lambda **kw: account
    await asyncio.sleep(0)  # let the constructor's start_init task run
    return provider, account, panel, api


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

async def test_discovery_and_wiring():
    print("T2 discovery + manifests (real auto-init path)")
    provider, account, panel, _ = await make_provider()

    captured = scrypted_sdk.deviceManager.captured
    check("3 camera manifests", len(captured["devices"]) == 3,
          f"got {len(captured['devices'])}")
    by_id = {d["nativeId"]: d for d in captured["devices"]}

    doorbell = by_id.get("111-1")
    check("doorbell manifest", doorbell is not None)
    if doorbell:
        check("doorbell name", doorbell["name"] == "Front Door")
        check("doorbell info", doorbell["info"]["model"] == "Doorbell Camera Pro Gen 2 (DBC350)")
        check("doorbell serial", doorbell["info"]["serialNumber"] == "AA:BB:CC:DD:EE:01")
        check("doorbell interfaces", "MotionSensor" in doorbell["interfaces"] and "Doorbell" in doorbell["interfaces"],
              str(doorbell["interfaces"]))
        check("doorbell has Camera+VideoCamera", "Camera" in doorbell["interfaces"] and "VideoCamera" in doorbell["interfaces"])

    outdoor = by_id.get("111-2")
    check("outdoor manifest", outdoor is not None)
    if outdoor:
        check("outdoor no Doorbell", "Doorbell" not in outdoor["interfaces"])
        check("outdoor has MotionSensor", "MotionSensor" in outdoor["interfaces"])

    check("non-camera skipped", len(captured["devices"]) == 3)

    print("T3 getDevice")
    cam = await provider.getDevice("111-2")
    check("returns VivintCamera", isinstance(cam, VivintCamera))
    check("wrapped and cached", provider.cameras["111-2"] is cam)
    cam2 = await provider.getDevice("111-2")
    check("idempotent", cam2 is cam)
    try:
        await provider.getDevice("nope")
        check("unknown nativeId raises", False)
    except ValueError:
        check("unknown nativeId raises", True)

    print("T6 cloud motion wiring")
    # simulate PubNub messages through vivintpy's own message handler
    cam.camera.handle_pubnub_message({"vdt": True, "_id": 2})
    check("motion event -> motionDetected", cam.motionDetected is True)
    cam.set_motion(False)
    door_cam = await provider.getDevice("111-1")
    door_cam.camera.handle_pubnub_message({"dng": 1, "_id": 1})
    check("doorbell event emitted", any(
        e["interface"] == "Doorbell" for e in door_cam._events
    ), str(door_cam._events))

    return provider


async def test_streams():
    print("T4 getVideoStream URL selection")
    provider, account, panel, _ = await make_provider()

    # outdoor: direct RTSP on LAN
    outdoor = await provider.getDevice("111-2")
    mo = await outdoor.getVideoStream()
    ffi = mo.mediaStreamOptions
    check("outdoor direct url", ffi["url"] == "rtsp://camuser:campass@192.168.1.50:6500/h264", ffi["url"])
    check("outdoor source local", ffi["mediaStreamOptions"]["source"] == "local")
    check("outdoor ffmpeg args", ffi["inputArguments"] == ["-i", ffi["url"]])

    # doorbell: no direct -> panel relay (credentials fetched)
    doorbell = await provider.getDevice("111-1")
    mo = await doorbell.getVideoStream()
    ffi = mo.mediaStreamOptions
    check("doorbell panel url", ffi["url"] == "rtsp://paneluser:panelpass@10.10.1.6:8554/panel-hd", ffi["url"])
    check("doorbell source panel", ffi["mediaStreamOptions"]["source"] == "panel")

    # ping cam: no panel-stream field -> panel lookup raises -> falls to cloud relay
    ping = await provider.getDevice("111-3")
    ping.camera.data.pop("ciu")  # simulate camera without a panel stream
    mo = await ping.getVideoStream()
    ffi = mo.mediaStreamOptions
    # ping cam has cda=True but is in SKIP_DIRECT: direct must NOT be used
    check("ping cam skips direct", "10.0.0.9" not in ffi["url"], ffi["url"])
    check("ping cam falls back to cloud", ffi["url"].endswith("@relay.vivint.example/cloud-hd"), ffi["url"])
    check("ping cam source cloud", ffi["mediaStreamOptions"]["source"] == "cloud")

    print("T12 no panel credentials at all -> no stream (vivintpy requires creds for panel+cloud)")
    ping.camera.data["ciu"] = ["rtsp://10.10.1.6:8554/panel-hd"]  # restore
    panel.can_creds = False
    try:
        await ping.getVideoStream()
        check("no-creds raises", False)
    except Exception:
        check("no-creds raises", True)


async def test_snapshot():
    print("T5 takePicture")
    provider, account, panel, api = await make_provider()
    session = provider.session

    cam = await provider.getDevice("111-1")
    mo = await cam.takePicture()
    check("thumbnail requested", len(api.thumb_requests) == 1)
    check("thumbnail url fetched", session.gets == ["https://thumb.vivint.example/cam1.jpg?token=x"])
    check("media object jpeg", mo.mimeType == "image/jpeg" and mo.data == b"\xff\xd8fakejpeg")
    mo2 = await cam.takePicture()
    check("cached within 60s", len(session.gets) == 1)


async def test_auth_flows():
    print("T7 2FA flow (real auto-init path)")
    scrypted_sdk.deviceManager.captured = None  # clear previous test's capture
    provider = VivintProvider()
    provider.session = FakeSession()
    provider.storage.setItem("username", "u")
    provider.storage.setItem("password", "p")
    provider.storage.setItem("use_cloud_motion", "true")
    account, panel, _ = make_account_with_panel(scenario="mfa")
    provider._fake_account = account
    vp.Account = lambda **kw: account
    await asyncio.sleep(0)  # auto-init hits MFA
    check("waiting_for_2fa set", provider.waiting_for_2fa is True)
    check("no discovery yet", scrypted_sdk.deviceManager.captured is None)
    check("account kept for mfa", provider.account is not None)

    await provider.finish_init("123456")
    check("mfa verified", account.verified is True)
    check("discovery after 2FA", scrypted_sdk.deviceManager.captured is not None)
    check("refresh token persisted", provider.storage.getItem("refresh_token") == "rt-123")
    check("waiting cleared", provider.waiting_for_2fa is False)

    print("T8 invalid credentials")
    provider2 = VivintProvider()
    provider2.session = FakeSession()
    provider2.storage.setItem("username", "u")
    provider2.storage.setItem("password", "wrong")
    provider2.storage.setItem("use_cloud_motion", "true")
    bad = FakeAccount(scenario="auth")
    provider2._fake_account = bad
    vp.Account = lambda **kw: bad
    await asyncio.sleep(0)
    check("account cleaned up", provider2.account is None)
    check("session closed", provider2.session is None)

    print("T9 no credentials")
    provider3 = VivintProvider()
    await asyncio.sleep(0)
    check("early return, no crash", provider3.account is None)


async def test_local_motion_toggle():
    print("T11 use_cloud_motion=false (real auto-init path)")
    provider = VivintProvider()
    provider.session = FakeSession()
    provider.storage.setItem("username", "u")
    provider.storage.setItem("password", "p")
    provider.storage.setItem("use_cloud_motion", "false")
    account, panel, _ = make_account_with_panel()
    provider._fake_account = account
    vp.Account = lambda **kw: account
    await asyncio.sleep(0)  # auto-init connects + discovers

    check("connect without pubnub", account.subscribe is False)
    manifests = scrypted_sdk.deviceManager.captured["devices"]
    check("no MotionSensor interface", all("MotionSensor" not in d["interfaces"] for d in manifests))
    check("doorbell interface kept", any("Doorbell" in d["interfaces"] for d in manifests))


async def main():
    print("T1 imports (real vivintpy + plugin)")
    check("vivintpy camera import", VivintCameraLib is not None)
    check("plugin entry import", VivintProvider is not None)
    from main import create_scrypted_plugin  # noqa: E402  (src on path)
    p = create_scrypted_plugin()
    check("create_scrypted_plugin returns provider", isinstance(p, VivintProvider))
    check("scrypted_sdk stub surface", hasattr(scrypted_sdk, "deviceManager") and hasattr(scrypted_sdk, "mediaManager"))

    await test_discovery_and_wiring()
    await test_streams()
    await test_snapshot()
    await test_auth_flows()
    await test_local_motion_toggle()

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
