import re
import aiohttp
import datetime
import datetime
from bs4 import BeautifulSoup
from datetime import timedelta
from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
import aiohttp
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import DOMAIN, HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .const import DOMAIN, BALANCE_URL, RECHARGE_LOG_URL, USER_AGENT
from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

class HuayuanGasCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(hours=DEFAULT_SCAN_INTERVAL))
        self.sn = entry.data["sn"]
        _LOGGER.info("初始化余额协调器")

    async def _async_update_data(self):
        url = BALANCE_URL + f"{self.sn}"
        try:
            async with aiohttp.ClientSession() as session, session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    return self.parse_html(html)
        except Exception as e:
            _LOGGER.error("Error fetching data: %s", e)
            return None

    def parse_html(self, html):
        soup = BeautifulSoup(html, "html.parser")
        data = {}
        balance_items = soup.find_all("li")
        for item in balance_items:
            key = item.find("span").text.strip()
            value = item.find("b").text.strip()
            match = re.search(r"[\d.]+", value)
            if match:
                data[key] = float(match.group())
        return data


class GasRechargeCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, config_entry):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=datetime.timedelta(hours=DEFAULT_SCAN_INTERVAL),
        )
        self.sn = config_entry.data["sn"]
        _LOGGER.info("初始化充值记录协调器")

    async def _async_update_data(self):
        """更新昨日的充值金额"""
        end_date = (datetime.date.today() - datetime.timedelta(days=1)).strftime(
            "%Y-%m-%d"
        )
        begin_date = (datetime.date.today() - datetime.timedelta(days=1)).strftime(
            "%Y-%m-%d"
        )
        api_url = RECHARGE_LOG_URL + f"{self.sn}"
        try:
            async with aiohttp.ClientSession() as session, session.post(
                api_url, data={"begin_date": begin_date, "end_date": end_date}
            ) as response:
                    if response.status == 200:
                        html = await response.text()
                        return self.parse_recharge(html, end_date)
                    _LOGGER.error(
                        "Failed to fetch recharge data: HTTP %s", response.status
                    )
        except aiohttp.ClientError as e:
            _LOGGER.error("Error fetching recharge data: %s", str(e))

    def parse_recharge(self, html, target_date):
        """解析HTML，提取昨日的充值金额"""
        soup = BeautifulSoup(html, "html.parser")
        total_recharge = 0.0
        data = {}

        for li in soup.select(".history ul li"):
            amount_text = li.select_one("h1 b")
            date_text = li.select_one("p")
            if amount_text and date_text:
                try:
                    amount = float(amount_text.text.strip())
                    date = date_text.text.strip().split(" ")[
                        0
                    ]  # 提取日期部分（不包括时间）
                    if date == target_date:
                        total_recharge += amount  # 仅统计昨日的充值金额
                except ValueError:
                    _LOGGER.warning("Failed to parse recharge record: %s", li.text)
        data["充值记录"] = total_recharge
        return data  # 返回昨日充值的总金额