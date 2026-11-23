"""Expose the meter readings and settled costs as Home Assistant sensors."""

from decimal import Decimal, InvalidOperation

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SN, DOMAIN
from .coordinator import HuayuanGasCoordinator

LEGACY_TOTAL_ID = "huayuan_gas_cumulative_cost"
REMOVED_KEYS = (
    "recharge_time", "recharge_channel", "recharge_sequence", "account_balance", "arrears",
    "valve",
)


SENSORS = (
    SensorEntityDescription(
        key="meter_balance",
        name="表端余额",
        native_unit_of_measurement="CNY",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
    ),
    SensorEntityDescription(
        key="usage",
        name="累计用气量",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL,
    ),
    SensorEntityDescription(
        key="recharge",
        name="充值记录",
        native_unit_of_measurement="CNY",
        device_class=SensorDeviceClass.MONETARY,
    ),
    SensorEntityDescription(
        key="cost",
        name="昨日燃气费用",
        icon="mdi:currency-cny",
        native_unit_of_measurement="CNY",
        device_class=SensorDeviceClass.MONETARY,
    ),
    SensorEntityDescription(
        key="total",
        name="累计燃气费用",
        native_unit_of_measurement="CNY",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    ids = {
        "cost": f"huayuan_gas_cost_{entry.data[CONF_SN]}",
        "total": f"{LEGACY_TOTAL_ID}_{entry.entry_id}",
        "recharge": f"huayuan_gas_充值记录_{entry.entry_id}",
        "meter_balance": f"huayuan_gas_表端余额_{entry.entry_id}",
        "usage": f"huayuan_gas_累计用气量_{entry.entry_id}",
    }
    registry = er.async_get(hass)
    legacy_id = registry.async_get_entity_id("sensor", DOMAIN, LEGACY_TOTAL_ID)
    if legacy_id is not None:
        legacy = registry.async_get(legacy_id)
        if legacy is not None and legacy.config_entry_id == entry.entry_id:
            registry.async_update_entity(legacy_id, new_unique_id=ids["total"])

    for key in REMOVED_KEYS:
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"huayuan_gas_{key}_{entry.entry_id}"
        )
        if entity_id is not None:
            registry.async_remove(entity_id)

    classes = {"total": CumulativeCostSensor, "recharge": RechargeSensor}
    async_add_entities(
        classes.get(description.key, GasSensor)(
            coordinator,
            description,
            ids.get(description.key)
            or f"huayuan_gas_{description.key}_{entry.entry_id}",
        )
        for description in SENSORS
    )


class GasSensor(CoordinatorEntity, SensorEntity):
    """Read the last coordinator result without scheduling I/O."""

    entity_description: SensorEntityDescription

    def __init__(
        self, coordinator: HuayuanGasCoordinator,
        description: SensorEntityDescription, unique_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = unique_id

    @property
    def available(self) -> bool:
        data = self.coordinator.data or {}
        key = self.entity_description.key
        required = {"cost": "daily_cost", "total": "settlement", "recharge": "payments"}.get(
            key, key
        )
        return super().available and required in data

    @property
    def native_value(self) -> Decimal | str | None:
        data = self.coordinator.data or {}
        key = self.entity_description.key
        if key == "cost":
            daily = data.get("daily_cost")
            return daily[1] if daily is not None else None
        if key == "total":
            settlement = data.get("settlement")
            return settlement.total if settlement is not None else None
        return data.get(key)

    @property
    def extra_state_attributes(self) -> dict | None:
        data = self.coordinator.data or {}
        key = self.entity_description.key
        if key == "cost" and (daily := data.get("daily_cost")) is not None:
            return {"billing_date": daily[0].isoformat()}
        if key in ("meter_balance", "usage", "total"):
            return {"stale": data.get(f"{key}_stale", False)}
        return None


class RechargeSensor(GasSensor):
    """Record new payments as short, numeric spikes."""

    _unrecorded_attributes = frozenset({"records"})
    _attr_native_value = Decimal(0)
    _last_pulse = None
    _cancel_reset = None

    @property
    def native_value(self) -> Decimal:
        return self._attr_native_value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_pulse_reset)
        self._accept_pulse()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._accept_pulse()
        super()._handle_coordinator_update()

    @callback
    def _accept_pulse(self) -> None:
        pulse = (self.coordinator.data or {}).get("recharge_pulse")
        if pulse is None or pulse == self._last_pulse:
            return
        self._last_pulse = pulse
        self._attr_native_value = pulse[1]
        self._cancel_pulse_reset()
        self._cancel_reset = async_call_later(self.hass, 60, self._reset_pulse)

    @callback
    def _cancel_pulse_reset(self) -> None:
        if self._cancel_reset is not None:
            self._cancel_reset()
            self._cancel_reset = None

    @callback
    def _reset_pulse(self, _now) -> None:
        self._cancel_reset = None
        self._attr_native_value = Decimal(0)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict | None:
        payments = (self.coordinator.data or {}).get("payments")
        if payments is None:
            return None
        return {
            "latest": payments[-1].serialize() if payments else None,
            "records": [payment.serialize() for payment in reversed(payments)],
        }


class CumulativeCostSensor(GasSensor, RestoreEntity):
    """Import the pre-upgrade cumulative state once."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        total = Decimal(0)
        if state is not None and "last_update_date" in state.attributes:
            try:
                total = Decimal(state.state)
            except InvalidOperation:
                pass
        await self.coordinator.async_import_legacy_total(
            total if total.is_finite() else Decimal(0)
        )
