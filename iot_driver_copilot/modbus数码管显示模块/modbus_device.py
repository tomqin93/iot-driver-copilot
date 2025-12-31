import logging
import struct
import time
from typing import List, Optional, Dict, Any

# Pymodbus import compatibility across versions
try:
    from pymodbus.client import ModbusSerialClient
except Exception:
    try:
        from pymodbus.client.sync import ModbusSerialClient  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("pymodbus is required. Please install via 'pip install pymodbus'.") from e

from config import Config


class ModbusDisplayModule:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client: Optional[ModbusSerialClient] = None
        self.connected = False
        self._mapping_ranges: List[Dict[str, int]] = []

    def connect(self) -> bool:
        if self.client is None:
            self.client = ModbusSerialClient(
                method=self.cfg.modbus_method,
                port=self.cfg.serial_port,
                baudrate=self.cfg.serial_baudrate,
                parity=self.cfg.serial_parity,
                bytesize=self.cfg.serial_bytesize,
                stopbits=self.cfg.serial_stopbits,
                timeout=self.cfg.modbus_timeout_ms / 1000.0,
            )
        ok = bool(self.client.connect())
        self.connected = ok
        if ok:
            logging.info("Modbus connected to %s (%s %s baud)", self.cfg.serial_port, self.cfg.modbus_method, self.cfg.serial_baudrate)
        else:
            logging.error("Modbus connect failed to %s", self.cfg.serial_port)
        return ok

    def close(self):
        try:
            if self.client:
                self.client.close()
        finally:
            self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def _retry_call(self, func, *args, **kwargs):
        tries = self.cfg.operation_retries
        last_exc = None
        for attempt in range(1, tries + 1):
            try:
                res = func(*args, **kwargs)
                # pymodbus response objects expose isError()
                if hasattr(res, "isError") and res.isError():
                    raise RuntimeError(f"Modbus error response: {res}")
                return res
            except Exception as e:
                last_exc = e
                logging.warning("Modbus operation failed (attempt %d/%d): %s", attempt, tries, e)
                time.sleep(0.05 * attempt)
        raise last_exc  # type: ignore

    def read_holding(self, address: int, count: int) -> List[int]:
        resp = self._retry_call(
            self.client.read_holding_registers,  # type: ignore
            address=address,
            count=count,
            unit=self.cfg.modbus_device_id,
        )
        regs = getattr(resp, "registers", None)
        if regs is None:
            raise RuntimeError("No registers in response")
        return list(regs)

    def write_single(self, address: int, value: int) -> None:
        self._retry_call(
            self.client.write_register,  # type: ignore
            address=address,
            value=value,
            unit=self.cfg.modbus_device_id,
        )

    def write_multi(self, address: int, values: List[int]) -> None:
        self._retry_call(
            self.client.write_registers,  # type: ignore
            address=address,
            values=values,
            unit=self.cfg.modbus_device_id,
        )

    # Packing / unpacking helpers
    def _pack_value(self, value: Any, dtype: str) -> List[int]:
        if dtype == "int16":
            val = int(value)
            if not (-32768 <= val <= 65535):
                raise ValueError("int16 value out of range")
            # For uint16, accept 0..65535; int16 negative also fits in 16 bits. We'll mask to 16 bits.
            return [val & 0xFFFF]
        elif dtype == "uint16":
            val = int(value)
            if not (0 <= val <= 65535):
                raise ValueError("uint16 value out of range")
            return [val & 0xFFFF]
        elif dtype == "int32":
            val = int(value)
            if not (-2147483648 <= val <= 4294967295):
                raise ValueError("int32 value out of range")
            packed = struct.pack(
                ">I" if val >= 0 else ">i",
                val if val >= 0 else val,
            )
            hi = (packed[0] << 8) | packed[1]
            lo = (packed[2] << 8) | packed[3]
            if self.cfg.word_order == "high_first":
                return [hi, lo]
            else:
                return [lo, hi]
        elif dtype == "uint32":
            val = int(value)
            if not (0 <= val <= 0xFFFFFFFF):
                raise ValueError("uint32 value out of range")
            packed = struct.pack(">I", val)
            hi = (packed[0] << 8) | packed[1]
            lo = (packed[2] << 8) | packed[3]
            if self.cfg.word_order == "high_first":
                return [hi, lo]
            else:
                return [lo, hi]
        elif dtype == "float32":
            val = float(value)
            packed = struct.pack(">f", val)
            hi = (packed[0] << 8) | packed[1]
            lo = (packed[2] << 8) | packed[3]
            if self.cfg.word_order == "high_first":
                return [hi, lo]
            else:
                return [lo, hi]
        else:
            raise ValueError(f"Unsupported dtype: {dtype}")

    def _unpack_value(self, regs: List[int], dtype: str) -> Any:
        if dtype in ("int16", "uint16"):
            raw = regs[0] & 0xFFFF
            if dtype == "int16":
                if raw >= 0x8000:
                    raw = raw - 0x10000
                return int(raw)
            else:
                return int(raw)
        elif dtype in ("int32", "uint32", "float32"):
            if len(regs) < 2:
                raise ValueError("Need 2 registers for 32-bit value")
            if self.cfg.word_order == "high_first":
                hi, lo = regs[0] & 0xFFFF, regs[1] & 0xFFFF
            else:
                lo, hi = regs[0] & 0xFFFF, regs[1] & 0xFFFF
            b = bytes([(hi >> 8) & 0xFF, hi & 0xFF, (lo >> 8) & 0xFF, lo & 0xFF])
            if dtype == "int32":
                val = struct.unpack(">i", b)[0]
                return int(val)
            elif dtype == "uint32":
                val = struct.unpack(">I", b)[0]
                return int(val)
            else:
                val = struct.unpack(">f", b)[0]
                return float(val)
        else:
            raise ValueError(f"Unsupported dtype: {dtype}")

    # Device operations
    def set_display_value(self, value: Any) -> None:
        regs = self._pack_value(value, self.cfg.reg_display_value_type)
        if len(regs) == 1:
            self.write_single(self.cfg.reg_display_value_addr, regs[0])
        else:
            self.write_multi(self.cfg.reg_display_value_addr, regs)
        logging.info("Set display value: %s -> regs %s", value, regs)

    def set_display_ascii(self, text: str) -> None:
        if not (1 <= len(text) <= 6):
            raise ValueError("ascii must be 1..6 characters")
        # Each character goes into one 16-bit register as ASCII code
        regs = [ord(c) & 0xFFFF for c in text]
        # pad to 6 with zeros (clear remaining positions)
        while len(regs) < 6:
            regs.append(0)
        self.write_multi(self.cfg.reg_ascii_base_addr, regs)
        logging.info("Set display ascii: '%s' -> regs %s", text, regs)

    def set_mode(self, mode: int) -> None:
        self.write_single(self.cfg.reg_mode_addr, int(mode) & 0xFFFF)
        logging.info("Set mode: %s", mode)

    def set_modbus_config(self, target_slave_id: int, function_code: int, target_register_addr: int, target_data_type: int) -> None:
        self.write_single(self.cfg.reg_target_slave_id_addr, int(target_slave_id) & 0xFFFF)
        self.write_single(self.cfg.reg_function_code_addr, int(function_code) & 0xFFFF)
        self.write_single(self.cfg.reg_target_register_addr, int(target_register_addr) & 0xFFFF)
        self.write_single(self.cfg.reg_target_data_type_addr, int(target_data_type) & 0xFFFF)
        logging.info(
            "Set modbus config: target_slave_id=%s function_code=%s target_register_addr=%s target_data_type=%s",
            target_slave_id,
            function_code,
            target_register_addr,
            target_data_type,
        )

    def set_mapping_ranges(self, ranges: List[Dict[str, int]]) -> None:
        # Store locally
        self._mapping_ranges = []
        for r in ranges:
            if not all(k in r for k in ("input_min", "input_max", "output_value")):
                raise ValueError("Each range must have input_min, input_max, output_value")
            self._mapping_ranges.append({
                "input_min": int(r["input_min"]),
                "input_max": int(r["input_max"]),
                "output_value": int(r["output_value"]),
            })
        logging.info("Updated local mapping ranges: %d entries", len(self._mapping_ranges))
        # Optionally push to device if base address provided
        if self.cfg.reg_map_ranges_base_addr is not None and self.cfg.map_max_entries is not None:
            max_entries = self.cfg.map_max_entries
            entries = self._mapping_ranges[:max_entries]
            # Each entry uses 3 registers: input_min, input_max, output_value
            base = self.cfg.reg_map_ranges_base_addr
            # Write entries sequentially
            for idx, entry in enumerate(entries):
                addr = base + idx * 3
                vals = [entry["input_min"] & 0xFFFF, entry["input_max"] & 0xFFFF, entry["output_value"] & 0xFFFF]
                self.write_multi(addr, vals)
            # Clear remaining slots if fewer than max_entries
            for idx in range(len(entries), max_entries):
                addr = base + idx * 3
                vals = [0, 0, 0]
                self.write_multi(addr, vals)
            logging.info("Pushed %d mapping range entries to device starting at 0x%X", len(entries), base)

    def read_status(self) -> Dict[str, Any]:
        # Read display value
        dv_type = self.cfg.reg_display_value_type
        dv_count = 1 if dv_type in ("int16", "uint16") else 2
        dv_regs = self.read_holding(self.cfg.reg_display_value_addr, dv_count)
        display_value = self._unpack_value(dv_regs, dv_type)

        # Read ASCII 6 registers
        ascii_regs = self.read_holding(self.cfg.reg_ascii_base_addr, 6)
        ascii_chars = []
        for r in ascii_regs:
            code = r & 0xFF
            if code == 0:
                ascii_chars.append(" ")
            else:
                try:
                    ascii_chars.append(chr(code))
                except ValueError:
                    ascii_chars.append("?")
        display_ascii = "".join(ascii_chars)

        # Other fields
        blink_mask = self.read_holding(self.cfg.reg_blink_mask_addr, 1)[0] & 0xFFFF
        numeric_type = self.read_holding(self.cfg.reg_numeric_type_addr, 1)[0] & 0xFFFF
        decimal_places = self.read_holding(self.cfg.reg_decimal_places_addr, 1)[0] & 0xFFFF
        mode = self.read_holding(self.cfg.reg_mode_addr, 1)[0] & 0xFFFF

        target_slave_id = self.read_holding(self.cfg.reg_target_slave_id_addr, 1)[0] & 0xFFFF
        function_code = self.read_holding(self.cfg.reg_function_code_addr, 1)[0] & 0xFFFF
        target_register_addr = self.read_holding(self.cfg.reg_target_register_addr, 1)[0] & 0xFFFF
        target_data_type = self.read_holding(self.cfg.reg_target_data_type_addr, 1)[0] & 0xFFFF

        return {
            "display_value": display_value,
            "display_ascii_1_6": display_ascii,
            "blink_mask": blink_mask,
            "numeric_type": numeric_type,
            "decimal_places": decimal_places,
            "mode": mode,
            "target_slave_id": target_slave_id,
            "function_code": function_code,
            "target_register_addr": target_register_addr,
            "target_data_type": target_data_type,
        }
