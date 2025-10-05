"""DataUpdateCoordinator for Bali Blinds."""

from __future__ import annotations

from datetime import timedelta
from functools import partial
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BaliAPI, BaliAPIError, BaliDevice
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class BaliBlindCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Class to manage fetching Bali Blind data via WebSocket."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: BaliAPI,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        # Use longer polling interval since WebSocket provides real-time updates
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=DEFAULT_SCAN_INTERVAL * 10
            ),  # 10 minutes backup polling
            config_entry=config_entry,
        )
        self.api = api
        self._devices: list[BaliDevice] = []
        # Track commanded positions for battery-powered devices that go to sleep
        self._pending_positions: dict[str, int] = {}
        # Track timeout callbacks for pending positions
        self._pending_timeouts: dict[str, Any] = {}

        # Register WebSocket listener for real-time updates
        self.api.add_update_listener(self._handle_websocket_update)

    @callback
    def _clear_pending_position(self, device_id: str) -> None:
        """Clear pending position and cancel timeout for a device."""
        if device_id in self._pending_positions:
            del self._pending_positions[device_id]
        if device_id in self._pending_timeouts:
            self._pending_timeouts[device_id]()
            del self._pending_timeouts[device_id]

    @callback
    def _handle_item_update(self, device_id: str, item_name: str, value: Any) -> None:
        """Handle hub.item.updated message."""
        if device_id not in self.data:
            return

        if item_name == "dimmer":
            self.data[device_id]["position"] = value
            # Clear pending position since we got an actual update
            if device_id in self._pending_positions:
                _LOGGER.debug(
                    "Clearing pending position for %s (got actual update: %s)",
                    device_id,
                    value,
                )
                self._clear_pending_position(device_id)
        elif item_name == "battery":
            self.data[device_id]["battery"] = value
        elif item_name == "switch":
            self.data[device_id]["switch"] = value

        # Notify listeners of the update
        self.async_set_updated_data(self.data)
        _LOGGER.debug("Updated device %s: %s=%s", device_id, item_name, value)

    @callback
    def _handle_device_update(self, device_id: str, reachable: bool | None) -> None:
        """Handle hub.device.updated message."""
        if reachable is False and device_id in self._pending_positions:
            # Device went to sleep - assume it reached the commanded position
            pending_position = self._pending_positions[device_id]
            _LOGGER.info(
                "Device %s went to sleep, assuming it reached commanded position: %s",
                device_id,
                pending_position,
            )

            if device_id in self.data:
                self.data[device_id]["position"] = pending_position
                self.async_set_updated_data(self.data)

            self._clear_pending_position(device_id)

    @callback
    def _handle_websocket_update(self, message: dict[str, Any]) -> None:
        """Handle WebSocket push update."""
        try:
            _LOGGER.debug("Received WebSocket update: %s", message)

            msg_subclass = message.get("msg_subclass")
            result = message.get("result", {})

            # Handle hub.item.updated (position, battery, etc.)
            if msg_subclass == "hub.item.updated":
                device_id = result.get("deviceId")
                item_name = result.get("name")
                value = result.get("value")

                if device_id and item_name:
                    self._handle_item_update(device_id, item_name, value)

            # Handle hub.device.updated (reachability changes)
            elif msg_subclass == "hub.device.updated":
                device_id = result.get("_id")
                reachable = result.get("reachable")

                if device_id:
                    self._handle_device_update(device_id, reachable)

        except Exception as err:
            _LOGGER.exception("Error handling WebSocket update: %s", err)

    @callback
    def _apply_pending_position_callback(self, now, device_id: str) -> None:
        """Apply a pending position after timeout (callback for async_call_later)."""
        if device_id not in self._pending_positions:
            return

        pending_position = self._pending_positions[device_id]
        _LOGGER.info(
            "Timeout waiting for updates from %s, assuming it reached commanded position: %s",
            device_id,
            pending_position,
        )

        if device_id in self.data:
            self.data[device_id]["position"] = pending_position
            self.async_set_updated_data(self.data)

        # Clear the pending position and timeout
        del self._pending_positions[device_id]
        if device_id in self._pending_timeouts:
            del self._pending_timeouts[device_id]

    def set_target_position(self, device_id: str, position: int) -> None:
        """Track a commanded position for a device."""
        # Cancel any existing timeout for this device
        if device_id in self._pending_timeouts:
            self._pending_timeouts[device_id]()
            del self._pending_timeouts[device_id]

        self._pending_positions[device_id] = position
        _LOGGER.debug("Set pending position for %s: %s", device_id, position)

        # Schedule a timeout to apply the position if we don't get updates
        # Battery-powered devices often go to sleep immediately without reporting final position
        cancel_callback = async_call_later(
            self.hass,
            30.0,  # 30 second timeout
            partial(self._apply_pending_position_callback, device_id=device_id),
        )
        self._pending_timeouts[device_id] = cancel_callback

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch data from API via WebSocket."""
        try:
            # Get list of devices (only once or when needed)
            if not self._devices:
                self._devices = await self.api.get_devices()
                _LOGGER.debug("Discovered %d devices", len(self._devices))

            # Get state for each device via WebSocket
            data: dict[str, dict[str, Any]] = {}
            for device in self._devices:
                device_items = await self.api.get_device_items(device.device_id)
                data[device.device_id] = {
                    "name": device.name,
                    "category": device.category,
                    "manufacturer": device.manufacturer,
                    "model": device.model,
                    **device_items,
                }

            return data

        except BaliAPIError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    @property
    def devices(self) -> list[BaliDevice]:
        """Return list of devices."""
        return self._devices
