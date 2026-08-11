import asyncio
from datetime import datetime

from vivintpy.devices.camera import Camera as VivintCameraLib
from vivintpy.devices.camera import DOORBELL_DING, MOTION_DETECTED, RtspUrlType

import scrypted_sdk
from scrypted_sdk import (
    ScryptedDeviceBase,
    Camera,
    VideoCamera,
    MotionSensor,
    MediaObject,
    ResponsePictureOptions,
    RequestPictureOptions,
    RequestMediaStreamOptions,
    ResponseMediaStreamOptions,
    FFmpegInput,
    ScryptedInterface,
)

MOTION_RESET_SECONDS = 30
SNAPSHOT_CACHE_SECONDS = 60


class VivintCamera(ScryptedDeviceBase, Camera, VideoCamera, MotionSensor):
    """A single Vivint camera. Ported from scryptedapp/blink (BlinkCamera).

    The Doorbell interface has no Python class in the bundled scrypted_sdk; it is
    declared via ScryptedInterface.Doorbell in the device manifest and events are
    emitted with ScryptedInterface.Doorbell.value.
    """

    account: object
    panel: object
    camera: VivintCameraLib

    last_image: bytes = None
    last_image_timestamp: datetime = None
    __motion_task: asyncio.Task = None

    def __init__(
        self,
        nativeId: str,
        account: object,
        panel: object,
        camera: VivintCameraLib,
        session: object,
        use_cloud_motion: bool,
    ) -> None:
        super().__init__(nativeId=nativeId)
        self.account = account
        self.panel = panel
        self.camera = camera
        self.session = session

        if use_cloud_motion:
            # vivintpy emits these events from the PubNub realtime subscription.
            self.camera.on(MOTION_DETECTED, lambda *args: self.set_motion(True))
            self.camera.on(DOORBELL_DING, lambda *args: self.doorbell())

    def print(self, *args, **kwargs) -> None:
        print(*args, **kwargs)

    def set_motion(self, state: bool) -> None:
        self.motionDetected = state
        if state and self.__motion_task:
            self.__motion_task.cancel()

        if state:
            async def _reset():
                await asyncio.sleep(MOTION_RESET_SECONDS)
                self.motionDetected = False
            self.__motion_task = asyncio.create_task(_reset())

    def doorbell(self) -> None:
        self.onDeviceEvent(ScryptedInterface.Doorbell.value, {"doorbell": True})

    async def getPictureOptions(self) -> ResponsePictureOptions:
        return []

    async def takePicture(self, options: RequestPictureOptions = None) -> MediaObject:
        if self.last_image and self.last_image_timestamp:
            # If the last image is recent, return it instead of taking a new picture.
            if (datetime.now() - self.last_image_timestamp).total_seconds() < SNAPSHOT_CACHE_SECONDS:
                return await scrypted_sdk.mediaManager.createMediaObject(self.last_image, mimeType='image/jpeg')

        try:
            await self.camera.request_thumbnail()
            url = await self.camera.get_thumbnail_url()
            if not url:
                raise Exception("no thumbnail url returned")
            response = await self.session.get(url)
            picture = await response.read()
        except Exception as e:
            self.print(f"snapshot via thumbnail failed: {e}")
            return None

        self.last_image = picture
        self.last_image_timestamp = datetime.now()
        return await scrypted_sdk.mediaManager.createMediaObject(picture, mimeType='image/jpeg')

    async def getVideoStreamOptions(self) -> list[ResponseMediaStreamOptions]:
        return [
            {
                "id": "default",
                "name": "Vivint Camera Stream",
                # "audio": {"codec": "aac"},
                "audio": None,
                "video": {
                    "codec": "h264",
                },
                "source": "cloud",
                "tool": "ffmpeg",
                "userConfigurable": False,
            }
        ]

    async def getVideoStream(self, options: RequestMediaStreamOptions = None) -> MediaObject:
        msos = (await self.getVideoStreamOptions())[0]

        # prefer a direct LAN stream, then the panel relay, then the Vivint cloud.
        # vivintpy raises KeyError when a camera has no direct-access data at all
        # (cda key missing), so the direct attempt must be guarded.
        url = None
        try:
            url = await self.camera.get_direct_rtsp_url(hd=True)
        except (KeyError, TypeError, AttributeError):
            url = None
        source = "local" if url else None
        if not url:
            # panel relay; may raise if the camera has no panel-stream data at all
            await self.panel.get_panel_credentials()
            try:
                url = self.camera.get_rtsp_access_url(RtspUrlType.PANEL, True)
                source = "panel"
            except (KeyError, IndexError, TypeError):
                url = None
        if not url:
            # Vivint cloud relay (also requires panel credentials, like the panel path)
            try:
                url = self.camera.get_rtsp_access_url(RtspUrlType.EXTERNAL, True)
                source = "cloud"
            except (KeyError, IndexError, TypeError):
                url = None
        if not url:
            raise Exception("no RTSP url available for this camera")

        msos["source"] = source

        ffmpeg_input: FFmpegInput = {
            "url": url,
            "inputArguments": [
                "-i", url,
            ],
            "mediaStreamOptions": msos,
        }
        return await scrypted_sdk.mediaManager.createFFmpegMediaObject(ffmpeg_input)
