import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, BALANCE_URL, RECHARGE_LOG_URL, USER_AGENT
from .coordinator import HuayuanGasCoordinator, GasRechargeCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    # 创建两个数据协调器
    gas_balance_coordinator = HuayuanGasCoordinator(hass, config_entry)
    gas_recharge_coordinator = GasRechargeCoordinator(hass, config_entry)

    # 进行首次刷新，确保数据可用
    await gas_balance_coordinator.async_config_entry_first_refresh()
    await gas_recharge_coordinator.async_config_entry_first_refresh()

    # 将协调器存储在配置条目中
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        "gas_balance_coordinator": gas_balance_coordinator,
        "gas_recharge_coordinator": gas_recharge_coordinator,
    }

    config_entry.async_on_unload(
        config_entry.add_update_listener(_async_update_listener)
    )

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True

async def _async_update_listener(hass: HomeAssistant, config_entry):
    """Handle config options update."""
    # Reload the integration when the options change.
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
