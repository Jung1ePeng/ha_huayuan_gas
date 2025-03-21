from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor.const import SensorDeviceClass,SensorStateClass
from homeassistant.const import UnitOfVolume

DOMAIN = "huayuan_gas"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        GasBalanceSensor(coordinator, entry, "表端余额"),
        GasBalanceSensor(coordinator, entry, "账户余额"),
        GasBalanceSensor(coordinator, entry, "欠费金额"),
        GasUsageSensor(coordinator, entry, "累计用气量")
    ])


class GasUsageSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry, attribute):
        super().__init__(coordinator)
        self._attr_name = f"花源燃气 {attribute}"
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
        self._attr_name = f"花源燃气 {attribute}"
        self._attr_unique_id = f"huayuan_gas_{attribute}_{entry.entry_id}"
        self._attr_native_unit_of_measurement = "元"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self.attribute = attribute

    @property
    def native_value(self):
        data = self.coordinator.data
        if data:
            return data.get(self.attribute)
        return None