import asyncio
import logging
from pymodbus.client.tcp import ModbusTcpClient

_LOGGER = logging.getLogger(__name__)


class GrowattModbusManager:
    """Growatt Modbus TCP 客户端管理器（单连接 + 串行访问）"""

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._client = ModbusTcpClient(host=host, port=port)
        self._lock = asyncio.Lock()
        self._connected = False

    async def _ensure_connected(self):
        if self._connected:
            return

        ok = await asyncio.to_thread(self._client.connect)
        if not ok:
            self._connected = False
            raise ConnectionError("Modbus TCP connect failed")

        _LOGGER.info(
            "Growatt Modbus connected (%s:%s)",
            self._host,
            self._port,
        )
        self._connected = True

    async def read_input_registers(self, address: int, count: int):
        async with self._lock:
            try:
                await self._ensure_connected()

                rr = await asyncio.to_thread(
                    self._client.read_input_registers,
                    address,
                    count=count,   # ⭐ 关键修复点
                )

                if rr is None or rr.isError():
                    raise IOError(f"Modbus error @ {address}")

                return rr.registers

            except Exception as err:
                _LOGGER.warning(
                    "Growatt Modbus read failed @ %s: %s",
                    address,
                    err,
                )
                self._connected = False
                return None

    async def close(self):
        async with self._lock:
            if self._connected:
                await asyncio.to_thread(self._client.close)
                self._connected = False
