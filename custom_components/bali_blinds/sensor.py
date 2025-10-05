"""Sensor platform for Bali Blinds."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
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
    """Set up Bali Blind sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator

    # Create battery sensor for all discovered devices
    entities = []
    for device_id in coordinator.data:
        device_data = coordinator.data[device_id]
        # Only add battery sensor if device has battery info
        if "battery" in device_data:
            entities.append(BaliBlindBatterySensor(coordinator, device_id))

    async_add_entities(entities)


class BaliBlindBatterySensor(CoordinatorEntity[BaliBlindCoordinator], SensorEntity):
    """Representation of a Bali Blind battery sensor."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self,
        coordinator: BaliBlindCoordinator,
        device_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{device_id}_battery"
            if coordinator.config_entry
            else f"{device_id}_battery"
        )
        self._attr_translation_key = "battery"

    @property
    def native_value(self) -> int | None:
        """Return the battery level."""
        device_data = self.coordinator.data.get(self._device_id, {})
        return device_data.get("battery")
