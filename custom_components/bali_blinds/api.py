"""API client for Bali Blinds."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import logging
from typing import Any
import uuid

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Bali-specific constants (extracted from Bali Motorization Android app)
PK_OEM = "73"
APP_KEY = "255C5AC6213CEB860AA6EDB23D6F714C5DFC1139"
PASSWORD_SEED = "oZ7QE6LcLJp6fiWzdqZc"

AUTH_BASE_URL = "https://swf-us-oem-autha1.mios.com/autha/auth/username"


@dataclass
class BaliAuthData:
    """Authentication data for Bali API."""

    identity_token: str
    identity_signature: str
    session_token: str
    server_account: str
    server_relay: str
    account_id: str
    device_id: str


@dataclass
class BaliDevice:
    """Represents a Bali blind device."""

    device_id: str
    name: str
    category: str
    manufacturer: str | None = None
    model: str | None = None


class BaliAPIError(Exception):
    """Base exception for Bali API errors."""


class BaliAuthError(BaliAPIError):
    """Authentication error."""


class BaliConnectionError(BaliAPIError):
    """Connection error."""


class BaliWebSocket:
    """WebSocket connection manager for Bali API."""

    def __init__(
        self,
        server_relay: str,
        device_id: str,
        identity_token: str,
        identity_signature: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize WebSocket manager."""
        self._server_relay = server_relay
        self._device_id = device_id
        self._identity_token = identity_token
        self._identity_signature = identity_signature
        self._session = session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._listeners: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._pending_responses: dict[str, asyncio.Future] = {}
        self._receive_task: asyncio.Task | None = None
        self._connected = False

    async def connect(self, max_retries: int = 3, retry_delay: float = 2.0) -> None:
        """Connect to WebSocket and login with retry logic.

        Args:
            max_retries: Maximum number of connection attempts (default: 3)
            retry_delay: Base delay in seconds between retries (default: 2.0)
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                _LOGGER.debug(
                    "Connecting to WebSocket (attempt %d/%d): %s",
                    attempt + 1,
                    max_retries,
                    self._server_relay,
                )

                self._ws = await self._session.ws_connect(self._server_relay)
                _LOGGER.debug("WebSocket connected, starting receive task")

                # Start receive task
                self._receive_task = asyncio.create_task(self._receive_messages())

                # Login to the hub
                login_result = await self._send_message(
                    "loginUserMios",
                    {
                        "PK_Device": self._device_id,
                        "MMSAuthSig": self._identity_signature,
                        "MMSAuth": self._identity_token,
                    },
                )
                _LOGGER.debug("Login result: %s", login_result)

                # Register with the hub
                register_result = await self._send_message(
                    "register",
                    {"serial": self._device_id},
                )
                _LOGGER.debug("Register result: %s", register_result)

                self._connected = True
                _LOGGER.info("Successfully connected to Bali WebSocket")
                return

            except Exception as err:
                last_error = err
                _LOGGER.warning(
                    "Failed to connect to WebSocket (attempt %d/%d): %s",
                    attempt + 1,
                    max_retries,
                    err,
                )

                # Clean up on failure
                if self._ws and not self._ws.closed:
                    await self._ws.close()
                self._ws = None
                self._connected = False

                # Wait before retrying (exponential backoff)
                if attempt < max_retries - 1:
                    delay = retry_delay * (2 ** attempt)
                    _LOGGER.debug("Waiting %.1f seconds before retry...", delay)
                    await asyncio.sleep(delay)

        # All retries exhausted
        _LOGGER.error("Failed to connect after %d attempts", max_retries)
        raise BaliConnectionError(
            f"WebSocket connection failed after {max_retries} attempts: {last_error}"
        ) from last_error

    async def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        _LOGGER.debug("Disconnecting from WebSocket")
        self._connected = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        if self._ws and not self._ws.closed:
            await self._ws.close()

        _LOGGER.info("WebSocket disconnected")

    async def _receive_messages(self) -> None:
        """Receive messages from WebSocket."""
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        _LOGGER.debug("Received WebSocket message: %s", data)
                        await self._handle_message(data)
                    except json.JSONDecodeError:
                        _LOGGER.error(
                            "Failed to decode WebSocket message: %s", msg.data
                        )
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("WebSocket error: %s", self._ws.exception())
                    break
        except asyncio.CancelledError:
            _LOGGER.debug("WebSocket receive task cancelled")
        except Exception as err:
            _LOGGER.exception("Error in WebSocket receive loop: %s", err)

    async def _handle_message(self, data: dict[str, Any]) -> None:
        """Handle incoming WebSocket message."""
        msg_id = data.get("id")

        # Check if this is a response to a pending request
        if msg_id and msg_id in self._pending_responses:
            future = self._pending_responses.pop(msg_id)
            if not future.done():
                future.set_result(data.get("result"))
            return

        # Check if this is a broadcast notification (e.g., hub.item.updated)
        msg_subclass = data.get("msg_subclass")
        if msg_subclass and msg_subclass in self._listeners:
            for callback in self._listeners[msg_subclass]:
                try:
                    callback(data)
                except Exception as err:
                    _LOGGER.exception("Error in listener callback: %s", err)

    async def _send_message(
        self, method: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Send a message and wait for response."""
        if not self._ws or self._ws.closed:
            raise BaliConnectionError("WebSocket not connected")

        msg_id = str(uuid.uuid4())
        message = {
            "id": msg_id,
            "method": method,
            "params": params or {},
        }

        # Create future for response
        future: asyncio.Future = asyncio.Future()
        self._pending_responses[msg_id] = future

        _LOGGER.debug("Sending WebSocket message: %s", message)
        await self._ws.send_json(message)

        try:
            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=30.0)
            return result
        except TimeoutError:
            self._pending_responses.pop(msg_id, None)
            raise BaliConnectionError(f"Timeout waiting for response to {method}")

    def add_listener(
        self, event_id: str, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        """Add a listener for push notifications."""
        if event_id not in self._listeners:
            self._listeners[event_id] = []
        self._listeners[event_id].append(callback)

    def remove_listener(
        self, event_id: str, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        """Remove a listener."""
        if event_id in self._listeners and callback in self._listeners[event_id]:
            self._listeners[event_id].remove(callback)

    async def get_items(self) -> list[dict[str, Any]]:
        """Get list of items (device properties) from hub."""
        result = await self._send_message("hub.items.list", {})
        return result.get("items", []) if result else []

    async def get_devices_list(self) -> list[dict[str, Any]]:
        """Get list of devices with metadata from hub."""
        result = await self._send_message("hub.devices.list", {})
        return result.get("devices", []) if result else []

    async def set_item_value(self, item_id: str, value: Any) -> None:
        """Set value of an item."""
        await self._send_message("hub.item.value.set", {"_id": item_id, "value": value})

    @property
    def connected(self) -> bool:
        """Return if WebSocket is connected."""
        return self._connected and self._ws is not None and not self._ws.closed


class BaliAPI:
    """API client for Bali Blinds."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
        gateway_id: str | None = None,
    ) -> None:
        """Initialize the Bali API client."""
        self._username = username
        self._password = password
        self._session = session
        self._gateway_id = gateway_id
        self._auth_data: BaliAuthData | None = None
        self._websocket: BaliWebSocket | None = None
        self._update_callbacks: list[Callable[[dict[str, Any]], None]] = []

    async def authenticate(self) -> bool:
        """Authenticate with Bali cloud API."""
        _LOGGER.debug("Starting authentication for user: %s", self._username)
        try:
            # Step 1: Get authentication tokens
            password_hash = hashlib.sha1(
                (self._username + self._password + PASSWORD_SEED).encode()
            ).hexdigest()

            _LOGGER.debug("Password hash generated: %s", password_hash[:10])

            auth_url = f"{AUTH_BASE_URL}/{self._username}"
            auth_params = {
                "SHA1Password": password_hash,
                "PK_Oem": PK_OEM,
                "AppKey": APP_KEY,
            }

            _LOGGER.debug("Authentication URL: %s", auth_url)
            _LOGGER.debug("Auth params: PK_Oem=%s, AppKey=%s", PK_OEM, APP_KEY[:20])

            async with self._session.get(auth_url, params=auth_params) as response:
                _LOGGER.debug("Authentication response status: %s", response.status)

                if response.status != 200:
                    response_text = await response.text()
                    _LOGGER.error(
                        "Authentication failed with status %s: %s",
                        response.status,
                        response_text,
                    )
                    raise BaliAuthError(f"Authentication failed: {response.status}")

                data = await response.json()
                _LOGGER.debug(
                    "Authentication response data keys: %s", list(data.keys())
                )

                if not data.get("Identity"):
                    _LOGGER.error("No Identity in response. Response data: %s", data)
                    raise BaliAuthError("Invalid authentication response")

                # Identity is a base64-encoded JSON string
                identity_token = data["Identity"]
                identity_signature = data["IdentitySignature"]
                server_account = data.get("Server_Account", "")
                _LOGGER.debug(
                    "Got identity token and server_account: %s", server_account
                )

                # Decode the identity token to get account info
                identity_json = json.loads(base64.b64decode(identity_token))
                account_id = identity_json.get("PK_Account", "")
                _LOGGER.debug("Decoded identity - account_id: %s", account_id)

                # Step 2: Get session token (requires MMSAuth headers)
                session_token_url = f"https://{server_account}/info/session/token"
                session_headers = {
                    "MMSAuth": identity_token,
                    "MMSAuthSig": identity_signature,
                }
                _LOGGER.debug(
                    "Step 2: Getting session token from: %s", session_token_url
                )
                async with self._session.get(
                    session_token_url, headers=session_headers
                ) as token_response:
                    _LOGGER.debug(
                        "Session token response status: %s", token_response.status
                    )
                    if token_response.status != 200:
                        token_error = await token_response.text()
                        _LOGGER.error(
                            "Failed to get session token with status %s: %s",
                            token_response.status,
                            token_error,
                        )
                        raise BaliAuthError("Failed to get session token")

                    # Session token is returned as plain text, not JSON
                    session_token = await token_response.text()
                    _LOGGER.debug(
                        "Session token acquired: %s",
                        session_token[:20] if session_token else "empty",
                    )

                # Step 3: Get account devices to find gateway (requires MMSSession header)
                devices_url = f"https://{server_account}/account/account/account/{account_id}/devices"
                devices_headers = {"MMSSession": session_token}
                _LOGGER.debug(
                    "Step 3: Getting devices from: %s (account_id: %s)",
                    devices_url,
                    account_id,
                )

                async with self._session.get(
                    devices_url, headers=devices_headers
                ) as devices_response:
                    _LOGGER.debug(
                        "Devices response status: %s", devices_response.status
                    )
                    if devices_response.status != 200:
                        devices_error = await devices_response.text()
                        _LOGGER.error(
                            "Failed to get devices with status %s: %s",
                            devices_response.status,
                            devices_error,
                        )
                        raise BaliAuthError("Failed to get devices")

                    devices_data = await devices_response.json()
                    _LOGGER.debug("Devices data keys: %s", list(devices_data.keys()))
                    _LOGGER.debug(
                        "Number of devices found: %s",
                        len(devices_data.get("Devices", [])),
                    )

                    # Find the gateway device
                    gateway_device = None
                    if self._gateway_id:
                        _LOGGER.debug(
                            "Looking for specific gateway_id: %s", self._gateway_id
                        )
                        gateway_device = next(
                            (
                                d
                                for d in devices_data.get("Devices", [])
                                if d.get("PK_Device") == self._gateway_id
                            ),
                            None,
                        )
                    else:
                        # Use first device as gateway
                        devices = devices_data.get("Devices", [])
                        _LOGGER.debug(
                            "No gateway_id specified, using first device from %s devices",
                            len(devices),
                        )
                        if devices:
                            # Log all device info to debug
                            for idx, dev in enumerate(devices):
                                _LOGGER.debug(
                                    "Device %s: PK_Device=%s, Server_Relay=%s, keys=%s",
                                    idx,
                                    dev.get("PK_Device"),
                                    dev.get("Server_Relay"),
                                    list(dev.keys()),
                                )
                        gateway_device = devices[0] if devices else None

                    if not gateway_device:
                        _LOGGER.error(
                            "No gateway device found. Gateway ID: %s", self._gateway_id
                        )
                        raise BaliAuthError("No gateway device found")

                    _LOGGER.debug("Gateway device data: %s", gateway_device)
                    device_id = gateway_device.get("PK_Device", "")
                    server_device = gateway_device.get("Server_Device", "")
                    _LOGGER.debug(
                        "Selected gateway device_id: %s, server_device: %s",
                        device_id,
                        server_device,
                    )

                # Step 4: Get hub info to retrieve WebSocket Server_Relay URL
                hub_info_url = (
                    f"https://{server_device}/device/device/device/{device_id}"
                )
                hub_headers = {"MMSSession": session_token}
                _LOGGER.debug("Step 4: Getting hub info from: %s", hub_info_url)

                async with self._session.get(
                    hub_info_url, headers=hub_headers
                ) as hub_response:
                    _LOGGER.debug("Hub info response status: %s", hub_response.status)
                    if hub_response.status != 200:
                        hub_error = await hub_response.text()
                        _LOGGER.error(
                            "Failed to get hub info with status %s: %s",
                            hub_response.status,
                            hub_error,
                        )
                        raise BaliAuthError("Failed to get hub info")

                    hub_data = await hub_response.json()
                    _LOGGER.debug("Hub info keys: %s", list(hub_data.keys()))

                    # Extract WebSocket Server_Relay URL
                    server_relay = hub_data.get("Server_Relay", "")
                    _LOGGER.debug("WebSocket Server_Relay: %s", server_relay)

                    if not server_relay:
                        _LOGGER.error("No Server_Relay in hub info")
                        raise BaliAuthError("No WebSocket Server_Relay found")

                self._auth_data = BaliAuthData(
                    identity_token=identity_token,
                    identity_signature=identity_signature,
                    session_token=session_token,
                    server_account=server_account,
                    server_relay=server_relay,
                    account_id=account_id,
                    device_id=device_id,
                )

                _LOGGER.debug(
                    "Successfully authenticated with Bali API. Account ID: %s, Device ID: %s",
                    account_id,
                    device_id,
                )
                return True

        except aiohttp.ClientError as err:
            _LOGGER.exception("Connection error during authentication: %s", err)
            raise BaliConnectionError(f"Connection error: {err}") from err
        except (KeyError, IndexError) as err:
            _LOGGER.exception("Invalid API response structure: %s", err)
            raise BaliAuthError(f"Invalid API response: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error during authentication: %s", err)
            raise BaliAuthError(f"Unexpected authentication error: {err}") from err

    async def connect_websocket(self, max_retries: int = 3, retry_delay: float = 2.0) -> None:
        """Connect to WebSocket for real-time communication.

        Args:
            max_retries: Maximum number of connection attempts (default: 3)
            retry_delay: Base delay in seconds between retries (default: 2.0)
        """
        if not self._auth_data:
            raise BaliAuthError("Not authenticated")

        if self._websocket and self._websocket.connected:
            _LOGGER.debug("WebSocket already connected")
            return

        _LOGGER.debug(
            "Creating WebSocket connection to: %s", self._auth_data.server_relay
        )

        self._websocket = BaliWebSocket(
            server_relay=self._auth_data.server_relay,
            device_id=self._auth_data.device_id,
            identity_token=self._auth_data.identity_token,
            identity_signature=self._auth_data.identity_signature,
            session=self._session,
        )

        await self._websocket.connect(max_retries=max_retries, retry_delay=retry_delay)

    async def ensure_websocket_connected(self, max_retries: int = 3, retry_delay: float = 2.0) -> None:
        """Ensure WebSocket is connected, reconnect if necessary.

        Args:
            max_retries: Maximum number of connection attempts (default: 3)
            retry_delay: Base delay in seconds between retries (default: 2.0)
        """
        if self._websocket and self._websocket.connected:
            return

        _LOGGER.info("WebSocket not connected, attempting to reconnect...")

        # Disconnect old websocket if exists
        if self._websocket:
            try:
                await self._websocket.disconnect()
            except Exception as err:
                _LOGGER.debug("Error disconnecting old websocket: %s", err)
            self._websocket = None

        # Reconnect
        await self.connect_websocket(max_retries=max_retries, retry_delay=retry_delay)

        # Re-register all update listeners after reconnection
        for callback in self._update_callbacks:
            if self._websocket:
                self._websocket.add_listener("hub.item.updated", callback)
                self._websocket.add_listener("hub.device.updated", callback)
        _LOGGER.debug("Re-registered %d update listeners", len(self._update_callbacks))

    async def disconnect_websocket(self) -> None:
        """Disconnect from WebSocket."""
        if self._websocket:
            await self._websocket.disconnect()
            self._websocket = None

    def add_update_listener(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Add listener for hub.item.updated and hub.device.updated events."""
        # Store callback for re-registration after reconnection
        if callback not in self._update_callbacks:
            self._update_callbacks.append(callback)

        # Register with current websocket if connected
        if self._websocket:
            self._websocket.add_listener("hub.item.updated", callback)
            self._websocket.add_listener("hub.device.updated", callback)

    async def get_devices(self) -> list[BaliDevice]:
        """Get list of devices via WebSocket."""
        # Ensure websocket is connected, reconnect if needed
        await self.ensure_websocket_connected()

        try:
            # Get device list with metadata
            device_list = await self._websocket.get_devices_list()
            _LOGGER.debug("Retrieved %s devices from hub", len(device_list))

            # Log first device to see structure
            if device_list:
                _LOGGER.debug("Sample device structure: %s", device_list[0])

            # Convert to BaliDevice objects
            devices = []
            for device_data in device_list:
                device_id = device_data.get("_id")
                device_name = device_data.get("name", "Unknown")
                device_category = device_data.get("category")

                _LOGGER.debug(
                    "Device %s: name=%s, category=%s",
                    device_id,
                    device_name,
                    device_category,
                )

                # Only include window covering devices
                if device_category == "window_cov":
                    devices.append(
                        BaliDevice(
                            device_id=device_id,
                            name=device_name,
                            category=device_category,
                        )
                    )
                    _LOGGER.debug(
                        "Added window_cov device: %s (%s)",
                        device_name,
                        device_id,
                    )

            _LOGGER.debug("Returning %s window_cov devices", len(devices))
            return devices

        except Exception as err:
            _LOGGER.exception("Error getting devices via WebSocket: %s", err)
            raise BaliConnectionError(f"Failed to get devices: {err}") from err

    async def get_devices_old(self) -> list[BaliDevice]:
        """Get list of devices from the gateway."""
        if not self._auth_data:
            raise BaliAuthError("Not authenticated")

        try:
            device_url = (
                f"https://{self._auth_data.server_relay}/device/device/device/"
                f"{self._auth_data.device_id}"
            )
            headers = {"MMSSession": self._auth_data.session_token}

            async with self._session.get(device_url, headers=headers) as response:
                if response.status != 200:
                    raise BaliAPIError(f"Failed to get devices: {response.status}")

                data = await response.json()
                _LOGGER.debug("get_devices full response: %s", data)
                _LOGGER.debug("get_devices response keys: %s", list(data.keys()))
                _LOGGER.debug(
                    "get_devices Devices count: %s", len(data.get("Devices", []))
                )

                devices = []

                # Parse devices from response
                for device_data in data.get("Devices", []):
                    _LOGGER.debug(
                        "Device found: id=%s, category=%s, name=%s, keys=%s",
                        device_data.get("_id"),
                        device_data.get("category"),
                        device_data.get("name"),
                        list(device_data.keys()),
                    )
                    # Only include window covering devices
                    if device_data.get("category") == "window_cov":
                        devices.append(
                            BaliDevice(
                                device_id=device_data.get("_id", ""),
                                name=device_data.get("name", "Unknown"),
                                category=device_data.get("category", ""),
                                manufacturer=device_data.get("info", {}).get(
                                    "manufacturer"
                                ),
                                model=device_data.get("info", {}).get("model"),
                            )
                        )

                _LOGGER.debug("Returning %s window_cov devices", len(devices))
                return devices

        except aiohttp.ClientError as err:
            raise BaliConnectionError(f"Connection error: {err}") from err

    async def get_device_state(self, device_id: str) -> dict[str, Any]:
        """Get current state of a device."""
        if not self._auth_data:
            raise BaliAuthError("Not authenticated")

        # For HTTP polling, we'll need to query device items
        # This is a simplified version - full implementation would query specific items
        try:
            device_url = (
                f"https://{self._auth_data.server_relay}/device/device/device/"
                f"{self._auth_data.device_id}"
            )
            headers = {"MMSSession": self._auth_data.session_token}

            async with self._session.get(device_url, headers=headers) as response:
                if response.status != 200:
                    raise BaliAPIError(f"Failed to get device state: {response.status}")

                data = await response.json()

                # Find the specific device and its items
                for device in data.get("Devices", []):
                    if device.get("_id") == device_id:
                        items = device.get("items", [])
                        state: dict[str, Any] = {}

                        for item in items:
                            item_name = item.get("name")
                            if item_name == "dimmer":
                                state["position"] = item.get("value", 0)
                            elif item_name == "battery":
                                state["battery"] = item.get("value", 100)
                            elif item_name == "switch":
                                state["switch"] = item.get("value", False)

                        return state

                return {}

        except aiohttp.ClientError as err:
            raise BaliConnectionError(f"Connection error: {err}") from err

    async def get_device_items(self, device_id: str) -> dict[str, Any]:
        """Get all items for a specific device."""
        # Ensure websocket is connected, reconnect if needed
        await self.ensure_websocket_connected()

        try:
            items = await self._websocket.get_items()

            # Find items for this device
            device_items: dict[str, Any] = {}
            for item in items:
                if item.get("deviceId") == device_id:
                    item_name = item.get("name")
                    if item_name == "dimmer":
                        device_items["position"] = item.get("value", 0)
                        device_items["dimmer_id"] = item.get("_id")
                    elif item_name == "battery":
                        device_items["battery"] = item.get("value", 100)
                    elif item_name == "switch":
                        device_items["switch"] = item.get("value", False)

            return device_items

        except Exception as err:
            _LOGGER.exception("Error getting device items: %s", err)
            raise BaliConnectionError(f"Failed to get device items: {err}") from err

    async def set_device_position(self, device_id: str, position: int) -> None:
        """Set position of a blind device via WebSocket."""
        # Ensure websocket is connected, reconnect if needed
        await self.ensure_websocket_connected()

        if not 0 <= position <= 100:
            raise ValueError("Position must be between 0 and 100")

        try:
            # Get items to find the dimmer item ID
            items = await self._websocket.get_items()
            dimmer_id = None

            for item in items:
                if item.get("deviceId") == device_id and item.get("name") == "dimmer":
                    dimmer_id = item.get("_id")
                    break

            if not dimmer_id:
                raise BaliAPIError(f"No dimmer item found for device {device_id}")

            _LOGGER.debug(
                "Setting device %s dimmer %s to position %s",
                device_id,
                dimmer_id,
                position,
            )
            await self._websocket.set_item_value(dimmer_id, position)

        except Exception as err:
            _LOGGER.exception("Error setting device position: %s", err)
            raise BaliConnectionError(f"Failed to set device position: {err}") from err

    async def close(self) -> None:
        """Close the API client."""
        await self.disconnect_websocket()
