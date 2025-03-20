import asyncio
import logging
import aiohttp
from datetime import timedelta
from bs4 import BeautifulSoup

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

DOMAIN = "huayuan_gas"
UPDATE_INTERVAL = timedelta(hours=1)
LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    coordinator = HuayuanGasCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    hass.data[DOMAIN].pop(entry.entry_id)
    return True

class HuayuanGasCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(hass, LOGGER, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.sn = entry.data["sn"]

    async def _async_update_data(self):
        url = f"http://qc.huayuanranqi.com/index.php?g=Wap&m=Index&a=balance_detail&sn={self.sn}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    html = await response.text()
                    return self.parse_html(html)
        except Exception as e:
            LOGGER.error(f"Error fetching data: {e}")
            return None

    def parse_html(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        data = {}
        balance_items = soup.find_all('li')
        for item in balance_items:
            key = item.find('span').text.strip()
            value = item.find('b').text.strip()
            data[key] = value
        return data
