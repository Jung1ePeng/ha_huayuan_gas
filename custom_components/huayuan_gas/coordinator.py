"""Poll meter data and settle completed sampling intervals."""

from asyncio import Lock
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GasApi, GasApiError, Payment, now
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
ZERO = Decimal(0)
HISTORY_START = date(2000, 1, 1)
SCAN_INTERVAL = timedelta(hours=1)
RETRY_INTERVAL = timedelta(minutes=5)
MIDNIGHT_WINDOW = timedelta(minutes=15)


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
        self.payments: tuple[Payment, ...] | None = None
        self.meter_balance: Decimal | None = None
        self.usage: Decimal | None = None
        self.boundaries: dict[date, Decimal] = {}
        self.daily_cost: tuple[date, Decimal] | None = None
        self._settlement_lock = Lock()

    async def async_load_baseline(self) -> None:
        if (stored := await self.store.async_load()) is not None:
            if stored["settlement"] is not None:
                self.settlement = Settlement.restore(stored["settlement"])
                self.meter_balance = self.settlement.balance
            if stored.get("meter_balance") is not None:
                self.meter_balance = Decimal(stored["meter_balance"])
            if stored["legacy_total"] is not None:
                self._legacy_total = Decimal(stored["legacy_total"])
            if stored.get("payments") is not None:
                self.payments = tuple(Payment.restore(row) for row in stored["payments"])
            if stored.get("usage") is not None:
                self.usage = Decimal(stored["usage"])
            self.boundaries = {
                date.fromisoformat(day): Decimal(balance)
                for day, balance in stored.get("boundaries", {}).items()
            }
            if (daily := stored.get("daily_cost")) is not None:
                self.daily_cost = (date.fromisoformat(daily[0]), Decimal(daily[1]))

    async def _save(
        self,
        settlement: Settlement | None,
        legacy_total: Decimal | None,
    ) -> None:
        await self.store.async_save(
            {
                "settlement": settlement.serialize() if settlement is not None else None,
                "legacy_total": str(legacy_total) if legacy_total is not None else None,
                "payments": (
                    [payment.serialize() for payment in self.payments]
                    if self.payments is not None else None
                ),
                "usage": str(self.usage) if self.usage is not None else None,
                "meter_balance": (
                    str(self.meter_balance) if self.meter_balance is not None else None
                ),
                "boundaries": {
                    day.isoformat(): str(balance) for day, balance in self.boundaries.items()
                },
                "daily_cost": (
                    [self.daily_cost[0].isoformat(), str(self.daily_cost[1])]
                    if self.daily_cost is not None else None
                ),
            }
        )
        self.settlement = settlement
        self._legacy_total = legacy_total

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
            await self._save(updated, total)
            if self.data is not None and self.data.get("settlement") is not None:
                self.async_set_updated_data({**self.data, "settlement": updated})

    async def _async_update_data(self) -> dict:
        async with self._settlement_lock:
            return await self._async_refresh_meter()

    async def async_refresh_recharge_history(self) -> None:
        """Replace the recharge archive after a successful full lookup."""
        async with self._settlement_lock:
            today = now().date()
            try:
                payments = await self.api.payments(HISTORY_START, today)
            except GasApiError as err:
                raise HomeAssistantError(str(err)) from err

            previous = self.payments
            self.payments = tuple(sorted(payments, key=lambda payment: payment.time))
            try:
                await self._save(self.settlement, self._legacy_total)
            except Exception:
                self.payments = previous
                raise
            if self.data is not None:
                self.data = {**self.data, "payments": self.payments}
                self.async_update_listeners()

    async def _async_refresh_meter(self) -> dict:
        try:
            data = await self.api.balance()
        except GasApiError as err:
            self.update_interval = RETRY_INTERVAL
            if self.usage is None and self.settlement is None:
                raise UpdateFailed(str(err)) from err
            _LOGGER.warning("Meter data unavailable: %s", err)
            return self._snapshot({}, now().date(), meter_stale=True, total_stale=True)

        sampled_at = now()
        today = sampled_at.date()
        yesterday = today - timedelta(days=1)
        midnight = sampled_at.replace(hour=0, minute=0, second=0, microsecond=0)
        balance = data["meter_balance"]
        old_balance = self.meter_balance
        old_usage = self.usage
        old_boundaries = self.boundaries
        old_payments = self.payments
        old_daily = self.daily_cost
        self.meter_balance, self.usage = balance, data["usage"]
        if today not in self.boundaries and sampled_at - midnight < MIDNIGHT_WINDOW:
            self.boundaries = {
                day: value for day, value in self.boundaries.items() if day >= yesterday
            }
            self.boundaries[today] = balance
        previous = self.settlement
        begin = (
            min(yesterday, previous.sampled_at.date())
            if previous is not None and self.payments is not None
            else HISTORY_START
        )
        try:
            payments = await self.api.payments(begin, today)
        except GasApiError as err:
            self.update_interval = RETRY_INTERVAL
            _LOGGER.warning("Payment data unavailable: %s", err)
            if (
                balance != old_balance or self.usage != old_usage
                or self.boundaries != old_boundaries
            ):
                try:
                    await self._save(previous, self._legacy_total)
                except Exception:
                    self.boundaries, self.usage = old_boundaries, old_usage
                    self.meter_balance = old_balance
                    raise
            return self._snapshot(data, today, total_stale=True)

        refreshed_at = now()
        self.update_interval = (
            refreshed_at.replace(minute=0, second=0, microsecond=0)
            + SCAN_INTERVAL - refreshed_at
        )
        # Replace the range returned by the provider and keep earlier records.
        self.payments = tuple(sorted(
            [p for p in self.payments or () if p.time.date() < begin] + payments,
            key=lambda p: p.time,
        ))
        if yesterday in self.boundaries and today in self.boundaries:
            recharged_yesterday = sum(
                (p.amount for p in payments if p.time.date() == yesterday), ZERO
            )
            self.daily_cost = (
                yesterday,
                self.boundaries[yesterday] + recharged_yesterday - self.boundaries[today],
            )

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
            settlement != previous or self.payments != old_payments
            or self.daily_cost != old_daily or self.boundaries != old_boundaries
            or self.usage != old_usage
            or balance != old_balance
        ):
            try:
                await self._save(settlement, self._legacy_total)
            except Exception:
                self.payments, self.daily_cost = old_payments, old_daily
                self.boundaries, self.usage = old_boundaries, old_usage
                self.meter_balance = old_balance
                raise
        snapshot = self._snapshot(data, today)
        if old_payments is not None:
            latest_time = old_payments[-1].time if old_payments else None
            incoming = Counter(
                payment for payment in payments
                if latest_time is None or payment.time >= latest_time
            )
            incoming.subtract(old_payments)
            amount = sum(
                (payment.amount * count for payment, count in incoming.items() if count > 0),
                ZERO,
            )
            if amount:
                snapshot["recharge_pulse"] = (sampled_at, amount)
        return snapshot

    def _snapshot(
        self, data: dict, today: date, *, meter_stale: bool = False, total_stale: bool = False
    ) -> dict:
        data.update(
            usage=self.usage,
            meter_balance=self.meter_balance,
            meter_balance_stale=meter_stale,
            usage_stale=meter_stale,
            total_stale=total_stale,
            settlement=self.settlement,
            payments=self.payments,
            daily_cost=(
                self.daily_cost if self.daily_cost and
                self.daily_cost[0] == today - timedelta(days=1) else None
            ),
        )
        return data
