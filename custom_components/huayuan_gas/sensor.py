import logging
import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor.const import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.restore_state import RestoreEntity


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
        self._attr_state_class = SensorStateClass.TOTAL
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
        self._attr_state_class = SensorStateClass.TOTAL
        self.attribute = attribute

    @property
    def native_value(self):
        data = self.coordinator.data
        if data:
            return data.get(self.attribute)
        return None


class GasCostSensor(SensorEntity, RestoreEntity):
    """燃气费用传感器，根据前一日和当日余额及充值记录计算燃气费用，
    支持重启后恢复昨日余额和最后更新时间
    每日费用 = 前一日余额 + 昨日充值 - 当日余额
    """
    def __init__(self, hass, balance_coordinator, recharge_coordinator):
        self.hass = hass
        self.balance_coordinator = balance_coordinator
        self.recharge_coordinator = recharge_coordinator

        self._attr_name = "燃气费用"
        self._attr_unique_id = f"huayuan_gas_cost_{balance_coordinator.sn}"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:currency-cny"
        self._attr_native_unit_of_measurement = "元"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_value = 0.0

        self.previous_balance = None  # 上一次记录的余额（即昨日余额）
        self.last_recorded_date = None  # 上一次更新的日期（格式：'YYYY-MM-DD'）

    async def async_added_to_hass(self):
        """当实体添加到 HA 后恢复状态"""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            try:
                self.previous_balance = float(last_state.attributes.get("previous_balance", 0.0))
            except (ValueError, TypeError):
                self.previous_balance = None
            self.last_recorded_date = last_state.attributes.get("last_recorded_date")
            _LOGGER.debug("恢复状态: previous_balance=%s, last_recorded_date=%s",
                         self.previous_balance, self.last_recorded_date)
        else:
            self.previous_balance = None
            self.last_recorded_date = None

    async def async_update(self):
        """更新燃气费用
        - 刷新余额和充值数据（分别由对应协调器管理）
        - 如果检测到新的一天（根据当前日期和上一次记录日期比较），则更新 previous_balance 为当天开始时的余额
        - 计算公式：如果有充值，则费用 = previous_balance + 昨日充值 - 当前余额，否则费用 = previous_balance - 当前余额
        """
        await self.balance_coordinator.async_request_refresh()
        await self.recharge_coordinator.async_request_refresh()
        
        balance_data = self.balance_coordinator.data
        recharge_data = self.recharge_coordinator.data
        current_balance = balance_data.get("表端余额", 0.0) if balance_data else 0.0
        yesterday_recharge = recharge_data.get("充值记录", 0.0) if recharge_data else 0.0
        
        today_str = datetime.date.today().isoformat()
        _LOGGER.info("当前时间：%s, 当前余额: %s, 昨日充值: %s, 上次记录余额: %s", 
                     datetime.datetime.now(), current_balance, yesterday_recharge, self.previous_balance)
        
        if self.last_recorded_date != today_str:
            # 如果今天是新的一天，则在今天第一次更新时记录昨天的余额为 previous_balance
            self.previous_balance = current_balance
            self.last_recorded_date = today_str
            _LOGGER.info("新的一天，记录昨日余额：%s (日期：%s)", self.previous_balance, today_str)
            # 初始化当天费用不计算
            self._attr_native_value = 0.0
        else:
            if self.previous_balance is None:
                self._attr_native_value = 0.0
            else:
                # 如果检测到充值，则费用 = previous_balance + 昨日充值 - 当前余额；否则费用 = previous_balance - 当前余额
                if yesterday_recharge > 0:
                    self._attr_native_value = self.previous_balance + yesterday_recharge - current_balance
                else:
                    self._attr_native_value = self.previous_balance - current_balance

        # 此处可以输出调试信息
        _LOGGER.debug("更新后: previous_balance=%s, current_balance=%s, 昨日充值=%s, 计算燃气费用=%s",
                     self.previous_balance, current_balance, yesterday_recharge, self._attr_native_value)

    @property
    def extra_state_attributes(self):
        """附加属性，用于保存 previous_balance 和 last_recorded_date，以便重启后恢复"""
        return {
            "previous_balance": self.previous_balance,
            "last_recorded_date": self.last_recorded_date,
        }