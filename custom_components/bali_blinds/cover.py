"""Cover platform for Bali Blinds."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BaliBlindConfigEntry
from .coordinator import BaliBlindCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BaliBlindConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Bali Blind covers from a config entry."""
    coordinator = entry.runtime_data.coordinator

    # Create cover entities for all discovered devices
    async_add_entities(
        BaliBlindCover(coordinator, device_id) for device_id in coordinator.data
    )


class BaliBlindCover(CoordinatorEntity[BaliBlindCoordinator], CoverEntity):
    """Representation of a Bali Blind cover."""

    _attr_has_entity_name = True
    _attr_device_class = CoverDeviceClass.BLIND
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(
        self,
        coordinator: BaliBlindCoordinator,
        device_id: str,
    ) -> None:
        """Initialize the cover."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{device_id}"
            if coordinator.config_entry
            else device_id
        )

    @property
    def name(self) -> str | None:
        """Return the name of the cover."""
        device_data = self.coordinator.data.get(self._device_id, {})
        return device_data.get("name")

    @property
    def current_cover_position(self) -> int | None:
        """Return current position of cover."""
        device_data = self.coordinator.data.get(self._device_id, {})
        return device_data.get("position")

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        if self.current_cover_position is None:
            return None
        return self.current_cover_position == 0

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        self.coordinator.set_target_position(self._device_id, 100)
        await self.coordinator.api.set_device_position(self._device_id, 100)
        # WebSocket will push updates automatically, no need to refresh

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        self.coordinator.set_target_position(self._device_id, 0)
        await self.coordinator.api.set_device_position(self._device_id, 0)
        # WebSocket will push updates automatically, no need to refresh

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        position = kwargs["position"]
        self.coordinator.set_target_position(self._device_id, position)
        await self.coordinator.api.set_device_position(self._device_id, position)
        # WebSocket will push updates automatically, no need to refresh
