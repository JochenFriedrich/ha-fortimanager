"""Sensor platform for FortiManager — one device per managed FortiGate."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class FortiManagerSensorEntityDescription(SensorEntityDescription):
    """Describes a FortiManager sensor."""
    value_fn: Any = None  # callable(device_dict) -> value


def _conn_status(d: dict) -> str:
    return d.get("conn_status", "unknown")

def _dev_status(d: dict) -> str:
    return d.get("dev_status", "unknown")

def _firmware(d: dict) -> str:
    major = d.get("os_ver", "?")
    minor = d.get("mr", "?")
    patch = d.get("patch", "?")
    build = d.get("build", "?")
    return f"{major}.{minor}.{patch} build{build}"

def _ha_mode(d: dict) -> str:
    return d.get("ha_mode", "unknown")


SENSOR_DESCRIPTIONS: tuple[FortiManagerSensorEntityDescription, ...] = (
    FortiManagerSensorEntityDescription(
        key="conn_status",
        name="Connection Status",
        icon="mdi:connection",
        value_fn=_conn_status,
    ),
    FortiManagerSensorEntityDescription(
        key="dev_status",
        name="Device Status",
        icon="mdi:shield-check",
        value_fn=_dev_status,
    ),
    FortiManagerSensorEntityDescription(
        key="firmware",
        name="Firmware Version",
        icon="mdi:package-up",
        value_fn=_firmware,
    ),
    FortiManagerSensorEntityDescription(
        key="ha_mode",
        name="HA Mode",
        icon="mdi:server-network",
        value_fn=_ha_mode,
    ),
    FortiManagerSensorEntityDescription(
        key="ip",
        name="IP Address",
        icon="mdi:ip-network",
        value_fn=lambda d: d.get("ip", "unknown"),
    ),
    FortiManagerSensorEntityDescription(
        key="platform_str",
        name="Platform",
        icon="mdi:chip",
        value_fn=lambda d: d.get("platform_str", d.get("os_type", "unknown")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FortiManager sensors."""
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    entities: list[FortiManagerSensor] = []

    # Build initial entities from first coordinator data
    known_devices: set[str] = set()

    def _add_new_devices() -> None:
        if not coordinator.data:
            return
        new_entities = []
        for device in coordinator.data:
            serial = device.get("sn") or device.get("name")
            if not serial or serial in known_devices:
                continue
            known_devices.add(serial)
            for description in SENSOR_DESCRIPTIONS:
                new_entities.append(FortiManagerSensor(coordinator, device, description))
        if new_entities:
            async_add_entities(new_entities)

    _add_new_devices()

    # Also add new devices that appear on subsequent polls
    entry.async_on_unload(coordinator.async_add_listener(_add_new_devices))


class FortiManagerSensor(CoordinatorEntity, SensorEntity):
    """Sensor representing a single attribute of a FortiManager-managed device."""

    entity_description: FortiManagerSensorEntityDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        device: dict,
        description: FortiManagerSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._serial = device.get("sn") or device.get("name")
        self._device_name = device.get("name", self._serial)

        self._attr_unique_id = f"{self._serial}_{description.key}"
        self._attr_name = f"{self._device_name} {description.name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=self._device_name,
            manufacturer="Fortinet",
            model=device.get("platform_str", device.get("os_type", "FortiGate")),
            sw_version=_firmware(device),
        )

    def _get_device(self) -> dict | None:
        if not self.coordinator.data:
            return None
        for d in self.coordinator.data:
            if (d.get("sn") or d.get("name")) == self._serial:
                return d
        return None

    @property
    def native_value(self) -> str | None:
        device = self._get_device()
        if device is None:
            return None
        return self.entity_description.value_fn(device)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._get_device() is not None
