"""Update platform for FortiManager.

One UpdateEntity per managed device. Reports when a newer firmware image is
available in the FMG Upgrade Manager (um/image/list). No install action is
implemented — this is notification-only.

Version comparison strategy:
  FMG stores installed firmware as three separate ints: os_ver, mr, patch.
  Available images have a version string like "7.4.5" or "7.4.5-b2573".
  We normalise both to a dotted tuple for comparison.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)

def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse '7.4.5' or '7.4.5-b2573' → (7, 4, 5). Returns (0,) on failure."""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", version_str or "")
    if m:
        return tuple(int(x) for x in m.groups())
    return (0,)


def _installed_version_str(device: dict) -> str:
    """Format installed version from raw FMG device dict."""
    major = device.get("os_ver", 0)
    minor = device.get("mr", 0)
    patch = device.get("patch", 0)
    build = device.get("build", 0)
    if build:
        return f"{major}.{minor}.{patch}-b{build}"
    return f"{major}.{minor}.{patch}"


def _latest_for_device(device: dict, available: list[dict]) -> str | None:
    """Find the highest available firmware version for this device's platform.

    Matches on os_type product code and platform_str (hardware model).
    Falls back to product-only match if no platform-specific image is found.
    """
    os_type = device.get("os_type", 0)
    if os_type == "fos":
      product = "fgt"
    else:
      product = os_type

    platform = device.get("platform_str", "")

    candidates: list[str] = []
    for img in available:
        if img.get("product", "").lower() != product:
            continue
        img_platform = img.get("platform", "")
        # Accept if platform matches or image is a "default" / generic entry
        if img_platform and platform and img_platform.lower() not in (
            platform.lower(),
            f"{product}-default",
            "default",
        ):
            continue
        ver = img.get("version") or img.get("img_version", "")
        if ver:
            candidates.append(ver)

    if not candidates:
        return None

    # Return the highest version
    return max(candidates, key=_parse_version)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FortiManager update entities."""
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    known: set[str] = set()

    def _add_new() -> None:
        if not coordinator.data:
            return
        devices, available = coordinator.data if isinstance(coordinator.data, tuple) else (coordinator.data, [])
        new: list[FortiManagerUpdateEntity] = []
        for device in devices:
            serial = device.get("sn") or device.get("name")
            if not serial or serial in known:
                continue
            known.add(serial)
            new.append(FortiManagerUpdateEntity(coordinator, device, available))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class FortiManagerUpdateEntity(CoordinatorEntity, UpdateEntity):
    """Firmware update notification entity for a FortiManager-managed device.

    State is 'on' (update available) when a newer image exists in the
    FMG Upgrade Manager. No install action is supported.
    """

    # Notification only — no install support
    _attr_supported_features = UpdateEntityFeature(0)

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        device: dict,
        available_firmware: list[dict],
    ) -> None:
        super().__init__(coordinator)
        self._serial = device.get("sn") or device.get("name")
        self._device_name = device.get("name", self._serial)
        self._attr_unique_id = f"{self._serial}_firmware_update"
        self._attr_name = f"{self._device_name} Firmware"
        self._attr_title = f"{self._device_name} Firmware"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=self._device_name,
            manufacturer="Fortinet",
        )

    def _get_device(self) -> dict | None:
        if not self.coordinator.data:
            return None
        devices = self.coordinator.data
        if isinstance(devices, tuple):
            devices = devices[0]
        for d in devices:
            if (d.get("sn") or d.get("name")) == self._serial:
                return d
        return None

    def _get_available(self) -> list[dict]:
        if isinstance(self.coordinator.data, tuple):
            return self.coordinator.data[1]
        return []

    @property
    def installed_version(self) -> str | None:
        device = self._get_device()
        return _installed_version_str(device) if device else None

    @property
    def latest_version(self) -> str | None:
        device = self._get_device()
        if device is None:
            return None
        latest = _latest_for_device(device, self._get_available())
        # If no image data from FMG, report same as installed (= no update known)
        return latest or self.installed_version

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        return _parse_version(latest_version) > _parse_version(installed_version)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._get_device() is not None
