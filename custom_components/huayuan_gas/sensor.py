import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor.const import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .coordinator import HuayuanGasCoordinator, GasRechargeCoordinator
from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    coordinators = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities(
        [
            GasBalanceSensor(coordinators["gas_balance_coordinator"], config_entry, "表端余额"),
            GasUsageSensor(coordinators["gas_balance_coordinator"], config_entry, "累计用气量"),
            GasRechargeSensor(coordinators["gas_recharge_coordinator"], config_entry, "充值记录"),
            GasCostSensor(
                hass,
                coordinators["gas_balance_coordinator"],
                coordinators["gas_recharge_coordinator"],
            ),
        ]
    )

class GasUsageSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry, attribute):
        super().__init__(coordinator)
        self._attr_name = f"{attribute}"
        self._attr_unique_id = f"huayuan_gas_{attribute}_{entry.entry_id}"
        self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
        self._attr_device_class = SensorDeviceClass.GAS
        self._attr_state_class = SensorStateClass.TOTAL
        self.attribute = attribute

    @property
    def native_value(self):
        data = self.coordinator.data
        if data:
            return data.get(self.attribute)
        return None


class GasBalanceSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry, attribute):
        super().__init__(coordinator)
        self._attr_name = f"{attribute}"
        self._attr_unique_id = f"huayuan_gas_{attribute}_{entry.entry_id}"
        self._attr_native_unit_of_measurement = "元"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self.attribute = attribute

    @property
    def native_value(self):
        data = self.coordinator.data
        if data:
            return data.get(self.attribute)
        return None


class GasRechargeSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry, attribute):
        super().__init__(coordinator)
        self._attr_name = f"{attribute}"
        self._attr_unique_id = f"huayuan_gas_{attribute}_{entry.entry_id}"
        self._attr_native_unit_of_measurement = "元"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self.attribute = attribute

    @property
    def native_value(self):
        data = self.coordinator.data
        if data:
            return data.get(self.attribute)
        return None


class GasCostSensor(SensorEntity):
    """燃气费用传感器，根据前一日和当日余额及充值记录计算燃气费用"""

    def __init__(
        self,
        hass,
        balance_coordinator: HuayuanGasCoordinator,
        recharge_coordinator: GasRechargeCoordinator,
    ):
        self.hass = hass
        self.balance_coordinator = balance_coordinator
        self.recharge_coordinator = recharge_coordinator
        self._attr_name = "燃气费用"
        self._attr_unique_id = f"huayuan_gas_cost_{balance_coordinator.sn}"
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = "mdi:currency-cny"
        self._attr_native_unit_of_measurement = "元"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_value = 0.0
        self.previous_balance = None  # 用于存储上一次（前一日）的余额

    async def async_update(self):
        # 刷新余额和充值数据
        await self.balance_coordinator.async_request_refresh()
        await self.recharge_coordinator.async_request_refresh()
        balance_data = self.balance_coordinator.data
        recharge_data = self.recharge_coordinator.data
        current_balance = balance_data.get("表端余额", 0.0) if balance_data else 0.0
        yesterday_recharge = recharge_data.get("充值记录", 0.0) if recharge_data else 0.0

        if self.previous_balance is None:
            # 第一次初始化时不计算费用
            self._attr_native_value = 0.0
        else:
            # 如果有充值，则费用 = 前一日余额 + 充值金额 - 当前余额，否则费用 = 前一日余额 - 当前余额
            self._attr_native_value = self.previous_balance + yesterday_recharge - current_balance
        # 更新 previous_balance 为当前余额，用于下一次计算
        self.previous_balance = current_balance
