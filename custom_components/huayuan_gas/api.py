"""Read the balance and payment pages without performing account changes."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import re

from aiohttp import ClientError, ClientSession, ClientTimeout
from bs4 import BeautifulSoup
from homeassistant.util import dt as dt_util

from .const import BASE_URL

BILLING_ZONE = dt_util.get_time_zone("Asia/Shanghai")
NUMBER = r"[-+−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
BALANCE_FIELDS = {
    "表端余额": "meter_balance",
    "账户余额": "account_balance",
    "欠费金额": "arrears",
    "累计用气量": "usage",
}
BALANCE_VALUE = re.compile(rf"(?:共计\s*)?[￥¥]?\s*({NUMBER})\s*(?:元|m³|m3|立方米)?")
PAYMENT_TIME = re.compile(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?=\s|$)")


class GasApiError(Exception):
    """The service could not return verified data."""


@dataclass(frozen=True)
class Payment:
    """A payment as displayed on the website."""

    time: datetime
    amount: Decimal

    @classmethod
    def restore(cls, data: dict) -> "Payment":
        return cls(
            datetime.fromisoformat(data["time"]),
            Decimal(data["amount"]),
        )

    def serialize(self) -> dict:
        return {
            "time": self.time.isoformat(),
            "amount": str(self.amount),
        }


def now() -> datetime:
    """Read time in the gas provider's local time zone."""
    return dt_util.now(BILLING_ZONE).replace(microsecond=0)


def parse_balance(html: str) -> dict[str, Decimal | str]:
    """Extract the known fields from a balance detail page."""
    data: dict[str, Decimal | str] = {}
    for row in BeautifulSoup(html, "html.parser").select("li"):
        label = row.find("span", recursive=False)
        value = row.find("b", recursive=False)
        if label is None or value is None:
            continue
        key = BALANCE_FIELDS.get(label.get_text(strip=True))
        raw = value.get_text(strip=True)
        if key and (match := BALANCE_VALUE.fullmatch(raw)):
            data[key] = Decimal(match[1].replace(",", "").replace("−", "-"))

    if not {"meter_balance", "usage"} <= data.keys():
        raise GasApiError("Required balance or usage field missing")
    return data


def parse_payments(html: str) -> list[Payment]:
    """Validate the payment results and parse their local timestamps."""
    history = BeautifulSoup(html, "html.parser").select_one(".history ul")
    if history is None:
        raise GasApiError("Payment results section missing")

    payments = []
    for row in history.find_all("li", recursive=False):
        header = row.select_one("h1")
        amount = header.select_one("b") if header else None
        date_text = row.select_one("p")
        raw_amount = amount.get_text(strip=True) if amount else ""
        stamp = (
            PAYMENT_TIME.match(date_text.get_text(" ", strip=True)) if date_text else None
        )
        if not re.fullmatch(NUMBER, raw_amount) or stamp is None:
            raise GasApiError("Unrecognized payment record")
        try:
            time = datetime.fromisoformat(" ".join(stamp[0].split()))
        except ValueError as err:
            raise GasApiError("Invalid payment timestamp") from err
        payments.append(
            Payment(
                time.replace(tzinfo=BILLING_ZONE),
                Decimal(raw_amount.replace(",", "").replace("−", "-")),
            )
        )
    return payments


class GasApi:
    """Use Home Assistant's shared HTTP session for lookup requests."""

    def __init__(self, session: ClientSession, sn: str) -> None:
        self.session = session
        self.sn = sn

    async def balance(self) -> dict[str, Decimal | str]:
        return parse_balance(await self._request("GET", "balance_detail"))

    async def payments(self, begin: date, end: date) -> list[Payment]:
        return parse_payments(
            await self._request(
                "POST",
                "pay_detail",
                {"begin_date": begin.isoformat(), "end_date": end.isoformat()},
            )
        )

    async def _request(
        self, method: str, action: str, data: dict[str, str] | None = None
    ) -> str:
        try:
            async with self.session.request(
                method,
                BASE_URL,
                params={"g": "Wap", "m": "Index", "a": action, "sn": self.sn},
                data=data,
                timeout=ClientTimeout(total=15),
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise GasApiError(f"{action} returned HTTP {response.status}")
                return await response.text()
        except (ClientError, TimeoutError, UnicodeError) as err:
            raise GasApiError(f"{action} request failed ({type(err).__name__})") from None
