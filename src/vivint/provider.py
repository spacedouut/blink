import asyncio

from aiohttp import ClientSession
from vivintpy.account import Account
from vivintpy.devices.camera import Camera as VivintCameraLib
from vivintpy.exceptions import (
    VivintSkyApiAuthenticationError,
    VivintSkyApiMfaRequiredError,
)

import scrypted_sdk
from scrypted_sdk import (
    ScryptedDeviceBase,
    DeviceProvider,
    Settings,
    Setting,
    ScryptedInterface,
    ScryptedDeviceType,
    Device,
)

from .camera import VivintCamera


class VivintProvider(ScryptedDeviceBase, DeviceProvider, Settings):
    """Vivint camera provider. Ported from scryptedapp/blink (BlinkProvider)."""

    account: Account = None
    cameras: dict[str, VivintCamera] = {}
    session: ClientSession = None
    waiting_for_2fa: bool = False

    def __init__(self, nativeId: str = None) -> None:
        super().__init__(nativeId=nativeId)
        asyncio.create_task(self.start_init())

    def print(self, *args, **kwargs) -> None:
        # Override print() from ScryptedDeviceBase to avoid double-printing in the plugin console.
        print(*args, **kwargs)

    @property
    def username(self) -> str:
        return self.storage.getItem("username")

    @username.setter
    def username(self, value: str):
        self.storage.setItem("username", value)

    @property
    def password(self) -> str:
        return self.storage.getItem("password")

    @password.setter
    def password(self, value: str):
        self.storage.setItem("password", value)

    @property
    def refresh_token(self) -> str:
        return self.storage.getItem("refresh_token")

    @refresh_token.setter
    def refresh_token(self, value):
        if value:
            self.storage.setItem("refresh_token", value)

    @property
    def use_cloud_motion(self) -> bool:
        value = self.storage.getItem("use_cloud_motion")
        return True if value is None else value == "true"

    @use_cloud_motion.setter
    def use_cloud_motion(self, value: bool):
        self.storage.setItem("use_cloud_motion", "true" if value else "false")

    async def getSettings(self) -> list[Setting]:
        return [
            {
                "title": "Vivint Username",
                "key": "username",
                "value": self.username,
            },
            {
                "title": "Vivint Password",
                "key": "password",
                "value": self.password,
                "type": "password",
            },
            {
                "title": "2FA Code",
                "key": "2fa",
                "value": "",
            },
            {
                "title": "Use Vivint cloud motion events (instant; includes doorbell ding)",
                "key": "use_cloud_motion",
                "value": "true" if self.use_cloud_motion else "false",
                "type": "boolean",
            },
        ]

    async def putSetting(self, key: str, value: str) -> None:
        if key == "username":
            self.username = value
            # force fresh login when credentials change
            self.refresh_token = None
        elif key == "password":
            self.password = value
            self.refresh_token = None
        elif key == "2fa":
            if value:
                if self.account and self.waiting_for_2fa:
                    await self.finish_init(value)
                elif not self.account:
                    self.print("Cannot submit 2FA code: no active session. Please save your username and password first.")
                elif not self.waiting_for_2fa:
                    self.print("Cannot submit 2FA code: not in 2FA authentication state. Please save your username and password to start authentication.")
            else:
                self.print("Cannot submit 2FA code: no code provided.")

            await self.onDeviceEvent(ScryptedInterface.Settings.value, None)
            return
        elif key == "use_cloud_motion":
            self.use_cloud_motion = value == "true"
        else:
            raise ValueError(f"Unknown setting key: {key}")

        # Only start init if we don't have a session and we have credentials
        if not self.account and self.username and self.password:
            await self.start_init()

        await self.onDeviceEvent(ScryptedInterface.Settings.value, None)

    async def start_init(self) -> None:
        if not self.username or not self.password:
            self.print("Vivint username and password must be set before initializing.")
            return

        try:
            # Create or reuse session
            if not self.session:
                self.session = ClientSession()

            self.account = Account(
                username=self.username,
                password=self.password,
                refresh_token=self.refresh_token or None,
                client_session=self.session,
            )

            await self.account.connect(
                load_devices=True,
                subscribe_for_realtime_updates=self.use_cloud_motion,
            )

            # Success! Persist the refresh token and discover cameras.
            self.refresh_token = self.account.refresh_token
            self.waiting_for_2fa = False
            self.print("Authentication successful!")
            await self.discover_cameras()

        except VivintSkyApiMfaRequiredError:
            # 2FA is required: wait for the user to submit a code.
            self.print("2FA required. Please enter the code sent to your phone/email in the '2FA Code' field and click Save.")
            self.waiting_for_2fa = True

        except VivintSkyApiAuthenticationError:
            self.print("Invalid username or password.")
            await self.cleanup()

        except Exception as e:
            self.print(f"Authentication error: {e}")
            await self.cleanup()

    async def finish_init(self, mfa_code: str) -> None:
        """Complete authentication with the 2FA code."""
        if not mfa_code:
            self.print("No 2FA code provided.")
            return

        if not self.account or not self.waiting_for_2fa:
            self.print("Not in 2FA authentication state.")
            return

        try:
            await self.account.verify_mfa(mfa_code)
            self.refresh_token = self.account.refresh_token
            self.waiting_for_2fa = False
            self.print("2FA verification successful!")
            await self.discover_cameras()

        except Exception as e:
            self.print(f"Error verifying 2FA: {e}")
            # Don't cleanup - let the user try again with a different code.

    async def discover_cameras(self) -> None:
        """Discover and register cameras from all Vivint systems/panels."""
        try:
            devices = []
            for system in self.account.systems:
                for panel in system.alarm_panels:
                    for device in panel.devices:
                        if not isinstance(device, VivintCameraLib):
                            continue

                        native_id = f"{panel.id}-{device.id}"
                        interfaces = [
                            ScryptedInterface.Camera.value,
                            ScryptedInterface.VideoCamera.value,
                        ]
                        if self.use_cloud_motion:
                            interfaces.append(ScryptedInterface.MotionSensor.value)
                        if device.model and "Doorbell" in device.model:
                            interfaces.append(ScryptedInterface.Doorbell.value)

                        manifest: Device = {
                            "name": device.name,
                            "nativeId": native_id,
                            "info": {
                                "manufacturer": device.manufacturer,
                                "model": device.model,
                                "firmware": device.software_version,
                                "serialNumber": device.serial_number,
                            },
                            "type": ScryptedDeviceType.Camera.value,
                            "interfaces": interfaces,
                        }
                        devices.append(manifest)
                        self.cameras[native_id] = device

            self.print(f"Discovered {len(devices)} camera(s)")
            await scrypted_sdk.deviceManager.onDevicesChanged({
                "devices": devices
            })

        except Exception as e:
            self.print(f"Error discovering cameras: {e}")
            raise

    async def cleanup(self) -> None:
        """Clean up the account and session."""
        if self.account and self.account.connected:
            try:
                await self.account.disconnect()
            except Exception:
                pass
        self.account = None
        self.waiting_for_2fa = False
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def getDevice(self, nativeId: str) -> ScryptedDeviceBase:
        if nativeId not in self.cameras:
            raise ValueError(f"Camera with nativeId {nativeId} not found.")

        if isinstance(self.cameras[nativeId], VivintCamera):
            return self.cameras[nativeId]

        device = self.cameras[nativeId]
        # find the panel this device belongs to
        for system in self.account.systems:
            for panel in system.alarm_panels:
                if panel.id == device.panel_id:
                    camera = VivintCamera(
                        nativeId=nativeId,
                        account=self.account,
                        panel=panel,
                        camera=device,
                        session=self.session,
                        use_cloud_motion=self.use_cloud_motion,
                    )
                    self.cameras[nativeId] = camera
                    return camera

        raise ValueError(f"Panel for camera {nativeId} not found.")
