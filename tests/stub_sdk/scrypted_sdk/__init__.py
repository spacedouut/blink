"""Minimal stub of the scrypted_sdk plugin runtime for local harness testing.

The real scrypted_sdk is injected by the Scrypted Python runtime (server/python).
This stub provides just the surface the vivint plugin uses, so we can exercise
provider/camera wiring without a live Scrypted server.
"""

from enum import Enum
from types import SimpleNamespace


class ScryptedInterface(Enum):
    Camera = "Camera"
    VideoCamera = "VideoCamera"
    MotionSensor = "MotionSensor"
    Settings = "Settings"


class ScryptedDeviceType(Enum):
    Camera = "Camera"
    Doorbell = "Doorbell"


class ScryptedDeviceBase:
    def __init__(self, nativeId: str = None):
        self.nativeId = nativeId
        self._storage = {}
        self._events = []
        self._motionDetected = False

    # storage
    class _Storage:
        def __init__(self, d):
            self._d = d
        def getItem(self, key, default=None):
            return self._d.get(key, default)
        def setItem(self, key, value):
            self._d[key] = value

    @property
    def storage(self):
        return self._Storage(self._storage)

    # motion sensor state (real SDK auto-emits MotionSensor events on set)
    @property
    def motionDetected(self):
        return self._motionDetected

    @motionDetected.setter
    def motionDetected(self, value):
        self._motionDetected = bool(value)

    def onDeviceEvent(self, interface, eventData, nativeId=None):
        self._events.append({"interface": interface, "eventData": eventData, "nativeId": nativeId})

    def print(self, *args, **kwargs):
        pass


class DeviceProvider:
    pass


class Settings:
    pass


# interface marker classes (runtime provides typed bases; plain classes suffice for the stub)
class Camera:
    pass


class VideoCamera:
    pass


class MotionSensor:
    pass


Setting = dict
Device = dict
ResponsePictureOptions = list
ResponseMediaStreamOptions = dict
RequestPictureOptions = dict
RequestMediaStreamOptions = dict
FFmpegInput = dict
MediaObject = SimpleNamespace


class _DeviceManager:
    def __init__(self):
        self.captured = None

    async def onDevicesChanged(self, data):
        self.captured = data


class _MediaManager:
    def __init__(self):
        self.objects = []

    async def createMediaObject(self, data, mimeType=None, **kwargs):
        obj = SimpleNamespace(data=data, mimeType=mimeType, **kwargs)
        self.objects.append(obj)
        return obj

    async def createFFmpegMediaObject(self, mediaStreamOptions, **kwargs):
        obj = SimpleNamespace(mediaStreamOptions=mediaStreamOptions, **kwargs)
        self.objects.append(obj)
        return obj


deviceManager = _DeviceManager()
mediaManager = _MediaManager()
