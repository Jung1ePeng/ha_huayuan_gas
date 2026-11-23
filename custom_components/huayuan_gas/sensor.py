"""Expose the meter readings and settled costs as Home Assistant sensors."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SN, DOMAIN
from .coordinator import HuayuanGasCoordinator

LEGACY_TOTAL_ID = "huayuan_gas_cumulative_cost"
PAYMENT_FIELDS = {
    "recharge": "amount",
    "recharge_time": "time",
    "recharge_channel": "channel",
    "recharge_sequence": "sequence",
}


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
        name="最近一次充值金额",
        native_unit_of_measurement="CNY",
        device_class=SensorDeviceClass.MONETARY,
    ),
    SensorEntityDescription(
        key="recharge_time",
        name="最近一次充值时间",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="recharge_channel",
        name="最近一次充值渠道",
    ),
    SensorEntityDescription(
        key="recharge_sequence",
        name="最近一次充值序号",
    ),
    SensorEntityDescription(
        key="account_balance",
        name="账户余额",
        native_unit_of_measurement="CNY",
        device_class=SensorDeviceClass.MONETARY,
    ),
    SensorEntityDescription(
        key="arrears",
        name="欠费金额",
        native_unit_of_measurement="CNY",
        device_class=SensorDeviceClass.MONETARY,
    ),
    SensorEntityDescription(
        key="valve",
        name="阀门状态",
    ),
    SensorEntityDescription(
        key="cost",
        name="燃气费用",
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

    async_add_entities(
        (CumulativeCostSensor if description.key == "total" else GasSensor)(
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
        required = "settlement" if key in ("cost", "total") else key
        if key in PAYMENT_FIELDS:
            required = "last_payment"
        return super().available and required in data

    @property
    def native_value(self) -> Decimal | datetime | int | str | None:
        data = self.coordinator.data or {}
        key = self.entity_description.key
        if key in PAYMENT_FIELDS:
            payment = data.get("last_payment")
            return getattr(payment, PAYMENT_FIELDS[key]) if payment is not None else None
        if key in ("cost", "total"):
            settlement = data.get("settlement")
            return getattr(settlement, key) if settlement is not None else None
        return data.get(key)

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        if self.entity_description.key not in ("cost", "total"):
            return None
        settlement = (self.coordinator.data or {}).get("settlement")
        if settlement is None or settlement.period_start is None:
            return None
        return {
            "period_start": settlement.period_start.isoformat(),
            "period_end": settlement.sampled_at.isoformat(),
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
