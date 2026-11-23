"""Poll meter data and settle completed sampling intervals."""

from asyncio import Lock
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GasApi, GasApiError, Payment, now
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, RETRY_INTERVAL_MINUTES

_LOGGER = logging.getLogger(__name__)
ZERO = Decimal(0)
HISTORY_START = date(2000, 1, 1)
SCAN_INTERVAL = timedelta(hours=DEFAULT_SCAN_INTERVAL)
RETRY_INTERVAL = timedelta(minutes=RETRY_INTERVAL_MINUTES)


@dataclass(frozen=True)
class Settlement:
    """A baseline and its corresponding cumulative cost."""

    sampled_at: datetime
    balance: Decimal
    total: Decimal
    period_start: datetime | None = None
    cost: Decimal | None = None

    @classmethod
    def restore(cls, data: dict) -> "Settlement":
        return cls(
            datetime.fromisoformat(data["sampled_at"]),
            Decimal(data["balance"]),
            Decimal(data["total"]),
            datetime.fromisoformat(data["period_start"]) if data["period_start"] else None,
            Decimal(data["cost"]) if data["cost"] is not None else None,
        )

    def serialize(self) -> dict[str, str | None]:
        return {
            "sampled_at": self.sampled_at.isoformat(),
            "balance": str(self.balance),
            "total": str(self.total),
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "cost": str(self.cost) if self.cost is not None else None,
        }


class HuayuanGasCoordinator(DataUpdateCoordinator):
    """Keep balance reads available when payment lookup fails."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: GasApi) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.api = api
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}", atomic_writes=True)
        self.settlement: Settlement | None = None
        self._legacy_total: Decimal | None = None
        self._last_payment: Payment | None = None
        self._history_initialized = False
        self._settlement_lock = Lock()

    async def async_load_baseline(self) -> None:
        if (stored := await self.store.async_load()) is not None:
            if stored["settlement"] is not None:
                self.settlement = Settlement.restore(stored["settlement"])
            if stored["legacy_total"] is not None:
                self._legacy_total = Decimal(stored["legacy_total"])
            if stored.get("last_payment") is not None:
                self._last_payment = Payment.restore(stored["last_payment"])
            self._history_initialized = stored.get("history_initialized", False)

    async def _save(
        self,
        settlement: Settlement | None,
        legacy_total: Decimal | None,
        last_payment: Payment | None,
        *,
        history_initialized: bool,
    ) -> None:
        await self.store.async_save(
            {
                "settlement": settlement.serialize() if settlement is not None else None,
                "legacy_total": str(legacy_total) if legacy_total is not None else None,
                "last_payment": last_payment.serialize() if last_payment is not None else None,
                "history_initialized": history_initialized,
            }
        )
        self.settlement = settlement
        self._legacy_total = legacy_total
        self._last_payment = last_payment
        self._history_initialized = history_initialized

    async def async_import_legacy_total(self, total: Decimal) -> None:
        """Carry the existing cumulative entity's total into its new storage once."""
        async with self._settlement_lock:
            if self._legacy_total is not None:
                return
            current = self.settlement
            updated = None
            if current is not None:
                updated = Settlement(
                    current.sampled_at, current.balance, current.total + total,
                    current.period_start, current.cost,
                )
            await self._save(
                updated, total, self._last_payment,
                history_initialized=self._history_initialized,
            )
            if self.data is not None and self.data.get("settlement") is not None:
                self.async_set_updated_data({**self.data, "settlement": updated})

    async def _async_update_data(self) -> dict:
        async with self._settlement_lock:
            return await self._async_refresh_meter()

    async def _async_refresh_meter(self) -> dict:
        try:
            data = await self.api.balance()
        except GasApiError as err:
            self.update_interval = RETRY_INTERVAL
            raise UpdateFailed(str(err)) from err

        sampled_at = now()
        previous = self.settlement
        begin = (
            previous.sampled_at.date()
            if previous is not None and self._history_initialized
            else HISTORY_START
        )
        try:
            payments = await self.api.payments(min(begin, sampled_at.date()), sampled_at.date())
        except GasApiError as err:
            self.update_interval = RETRY_INTERVAL
            _LOGGER.warning("Payment data unavailable: %s", err)
            if self._history_initialized:
                data["last_payment"] = self._last_payment
            return data

        self.update_interval = SCAN_INTERVAL
        latest = max(payments, key=lambda p: (p.time, p.sequence or 0), default=None)
        if latest is None or (
            self._last_payment is not None
            and (latest.time, latest.sequence or 0)
            < (self._last_payment.time, self._last_payment.sequence or 0)
        ):
            latest = self._last_payment

        balance = data["meter_balance"]
        settlement = previous
        if previous is None:
            settlement = Settlement(sampled_at, balance, self._legacy_total or ZERO)
        elif sampled_at > previous.sampled_at:
            recharged = sum(
                (
                    payment.amount for payment in payments
                    if previous.sampled_at < payment.time <= sampled_at
                ),
                ZERO,
            )
            cost = previous.balance + recharged - balance
            settlement = Settlement(
                sampled_at, balance, previous.total + cost, previous.sampled_at, cost
            )

        if (
            settlement != previous or latest != self._last_payment
            or not self._history_initialized
        ):
            await self._save(settlement, self._legacy_total, latest, history_initialized=True)
        data["last_payment"] = self._last_payment
        data["settlement"] = self.settlement
        return data
