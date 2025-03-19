from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        HuayuanGasBalanceSensor(coordinator, entry, "表端余额"),
        HuayuanGasBalanceSensor(coordinator, entry, "账户余额"),
        HuayuanGasBalanceSensor(coordinator, entry, "欠费金额"),
        HuayuanGasBalanceSensor(coordinator, entry, "累计用气量"),
        HuayuanGasBalanceSensor(coordinator, entry, "阀门状态"),
    ])

class HuayuanGasBalanceSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry, attribute):
        super().__init__(coordinator)
        self._attr_name = f"Huayuan Gas {attribute}"
        self._attr_unique_id = f"huayuan_gas_{attribute}_{entry.entry_id}"
        self.attribute = attribute

    @property
    def native_value(self):
        data = self.coordinator.data
        if data:
            return data.get(self.attribute)
        return None
