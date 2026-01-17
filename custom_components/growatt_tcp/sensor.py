import logging
import struct

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import CONF_HOST

from .const import (
    DOMAIN,
    SENSOR_REGISTERS,
    DEFAULT_PORT,
    SYSTEM_STATUS_MAP,
)
from .modbus_manager import GrowattModbusManager

_LOGGER = logging.getLogger(__name__)


def is_high_register(cfg: dict) -> bool:
    return "高位" in cfg.get("name", "")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
):
    host = entry.data[CONF_HOST]
    port = entry.data.get("port", DEFAULT_PORT)

    manager = GrowattModbusManager(host, port)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = manager

    entities = []
    used_addresses = set()

    sorted_items = sorted(
        SENSOR_REGISTERS.items(),
        key=lambda item: item[1]["address"],
    )

    for key, cfg in sorted_items:
        addr = cfg["address"]

        if addr in used_addresses:
            continue

        # ===== 32 位（高位 + 低位）=====
        if is_high_register(cfg):
            low_cfg = next(
                (
                    c for _, c in sorted_items
                    if c["address"] == addr + 1
                ),
                None,
            )

            if not low_cfg:
                _LOGGER.warning(
                    "高位寄存器 %s(address=%s) 未找到低位",
                    cfg["name"],
                    addr,
                )
                continue

            entities.append(
                GrowattTcp32BitSensor(
                    entry,
                    manager,
                    cfg,
                    low_cfg,
                )
            )

            used_addresses.update({addr, addr + 1})
            continue

        # ===== 普通 16 位 =====
        entities.append(
            GrowattTcp16BitSensor(
                entry,
                manager,
                cfg,
            )
        )
        used_addresses.add(addr)

    async_add_entities(entities, update_before_add=True)


# =========================
# 16 位传感器
# =========================
class GrowattTcp16BitSensor(SensorEntity):
    should_poll = True

    def __init__(self, entry, manager, cfg):
        self._entry = entry
        self._manager = manager
        self._cfg = cfg

        self._attr_name = cfg["name"]
        self._attr_unique_id = f"{entry.entry_id}_{cfg['address']}"

        self._attr_native_unit_of_measurement = cfg.get("unit")
        self._attr_device_class = cfg.get("device_class")
        self._attr_state_class = cfg.get("state_class")

        self._state = None

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Growatt 逆变器",
            manufacturer="Growatt",
            model="Modbus TCP",
        )

    @property
    def native_value(self):
        return self._state

    async def async_update(self):
        regs = await self._manager.read_input_registers(
            self._cfg["address"], 1
        )
        if not regs:
            return

        raw = regs[0]

        if self._cfg["name"] == "系统状态":
            self._state = SYSTEM_STATUS_MAP.get(
                raw, f"未知状态({raw})"
            )
            return

        scale = self._cfg.get("scale")
        if scale is not None:
            raw *= scale

        self._state = raw


# =========================
# 32 位有符号传感器
# =========================
class GrowattTcp32BitSensor(SensorEntity):
    should_poll = True

    def __init__(self, entry, manager, high_cfg, low_cfg):
        self._entry = entry
        self._manager = manager
        self._high_cfg = high_cfg
        self._low_cfg = low_cfg

        self._attr_name = high_cfg["name"].replace("高位", "").strip()
        self._attr_unique_id = (
            f"{entry.entry_id}_{high_cfg['address']}_32bit"
        )

        self._attr_native_unit_of_measurement = high_cfg.get("unit")
        self._attr_device_class = high_cfg.get("device_class")
        self._attr_state_class = high_cfg.get("state_class")

        self._state = None

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Growatt 逆变器",
            manufacturer="Growatt",
            model="Modbus TCP",
        )

    @property
    def native_value(self):
        return self._state

    async def async_update(self):
        regs = await self._manager.read_input_registers(
            self._high_cfg["address"], 2
        )
        if not regs:
            return

        high, low = regs

        value = struct.unpack(
            ">i",
            struct.pack(">HH", high, low)
        )[0]

        # 电池充放电功率：符号语义修正
        if self._high_cfg["address"] == 77:
            value = -value

        scale = self._high_cfg.get("scale")
        if scale is not None:
            value *= scale

        self._state = value
