import asyncio
import logging
import aiohttp
from datetime import timedelta
from bs4 import BeautifulSoup
import base64

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

DOMAIN = "huayuan_gas"
UPDATE_INTERVAL = timedelta(hours=1)
LOGGER = logging.getLogger(__name__)

HTTP_REFERER = base64.b64decode('aHR0cDovL3FjLmh1YXl1YW5yYW5xaS5jb20vaW5kZXgucGhwP2c9V2FwJm09SW5kZXgmYT1iYWxhbmNlX2RldGFpbCZzbj0=').decode()
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_1) AppleWebKit/537 (KHTML, like Gecko) Chrome/116.0 Safari/537'

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    LOGGER.info(f"Setting up {DOMAIN} entry")
    coordinator = HuayuanGasCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
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
        url = HTTP_REFERER+f"{self.sn}"
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
