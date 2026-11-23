"""Set up the Huayuan Gas integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service import async_register_admin_service

from .api import GasApi
from .const import CONF_SN, DOMAIN
from .coordinator import HuayuanGasCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    async def refresh_recharge_history(call: ServiceCall) -> None:
        coordinators = tuple(hass.data.get(DOMAIN, {}).values())
        if not coordinators:
            raise HomeAssistantError("No Huayuan Gas entries are loaded")
        for coordinator in coordinators:
            await coordinator.async_refresh_recharge_history()

    async_register_admin_service(
        hass, DOMAIN, "refresh_recharge_history", refresh_recharge_history
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = GasApi(async_get_clientsession(hass), entry.data[CONF_SN].strip())
    coordinator = HuayuanGasCoordinator(hass, entry, api)
    await coordinator.async_load_baseline()
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data[DOMAIN].pop(entry.entry_id)
    return True
