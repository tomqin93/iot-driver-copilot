import os
import sys
from dataclasses import dataclass


def _require_env(name: str) -> str:
    v = os.getenv(name)
    if v is None or v == "":
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return v


def _require_int(name: str) -> int:
    v = _require_env(name)
    try:
        return int(v)
    except ValueError:
        print(f"Environment variable {name} must be an integer, got: {v}", file=sys.stderr)
        sys.exit(1)


def _require_choice(name: str, choices):
    v = _require_env(name)
    if v not in choices:
        print(f"Environment variable {name} must be one of {choices}, got: {v}", file=sys.stderr)
        sys.exit(1)
    return v


def _require_dtype(name: str):
    v = _require_env(name)
    allowed = {"int16", "uint16", "int32", "uint32", "float32"}
    if v not in allowed:
        print(f"Environment variable {name} must be one of {allowed}, got: {v}", file=sys.stderr)
        sys.exit(1)
    return v


@dataclass(frozen=True)
class Config:
    # HTTP server
    http_host: str
    http_port: int

    # Modbus serial config
    modbus_method: str  # "rtu" or "ascii"
    serial_port: str
    serial_baudrate: int
    serial_parity: str  # "N", "E", "O"
    serial_bytesize: int
    serial_stopbits: int
    modbus_timeout_ms: int
    modbus_device_id: int

    # Backround collection loop and retry/backoff
    read_poll_interval_ms: int
    connect_backoff_min_ms: int
    connect_backoff_max_ms: int
    operation_retries: int

    # Data type packing for 32-bit values
    word_order: str  # "high_first" or "low_first"

    # Register addresses
    reg_display_value_addr: int
    reg_display_value_type: str
    reg_ascii_base_addr: int
    reg_mode_addr: int
    reg_blink_mask_addr: int
    reg_numeric_type_addr: int
    reg_decimal_places_addr: int
    reg_target_slave_id_addr: int
    reg_function_code_addr: int
    reg_target_register_addr: int
    reg_target_data_type_addr: int

    # Optional mapping ranges to push to device (base address for entries)
    reg_map_ranges_base_addr: int | None
    map_max_entries: int | None


def load_config() -> Config:
    http_host = _require_env("HTTP_HOST")
    http_port = _require_int("HTTP_PORT")

    modbus_method = _require_choice("MODBUS_METHOD", {"rtu", "ascii"})
    serial_port = _require_env("SERIAL_PORT")
    serial_baudrate = _require_int("SERIAL_BAUDRATE")
    serial_parity = _require_choice("SERIAL_PARITY", {"N", "E", "O"})
    serial_bytesize = _require_int("SERIAL_BYTESIZE")
    serial_stopbits = _require_int("SERIAL_STOPBITS")
    modbus_timeout_ms = _require_int("MODBUS_TIMEOUT_MS")
    modbus_device_id = _require_int("MODBUS_DEVICE_ID")

    read_poll_interval_ms = _require_int("READ_POLL_INTERVAL_MS")
    connect_backoff_min_ms = _require_int("CONNECT_BACKOFF_MIN_MS")
    connect_backoff_max_ms = _require_int("CONNECT_BACKOFF_MAX_MS")
    operation_retries = _require_int("OPERATION_RETRIES")

    word_order = _require_choice("WORD_ORDER", {"high_first", "low_first"})

    reg_display_value_addr = _require_int("REG_DISPLAY_VALUE_ADDR")
    reg_display_value_type = _require_dtype("REG_DISPLAY_VALUE_TYPE")
    reg_ascii_base_addr = _require_int("REG_ASCII_BASE_ADDR")
    reg_mode_addr = _require_int("REG_MODE_ADDR")
    reg_blink_mask_addr = _require_int("REG_BLINK_MASK_ADDR")
    reg_numeric_type_addr = _require_int("REG_NUMERIC_TYPE_ADDR")
    reg_decimal_places_addr = _require_int("REG_DECIMAL_PLACES_ADDR")
    reg_target_slave_id_addr = _require_int("REG_TARGET_SLAVE_ID_ADDR")
    reg_function_code_addr = _require_int("REG_FUNCTION_CODE_ADDR")
    reg_target_register_addr = _require_int("REG_TARGET_REGISTER_ADDR")
    reg_target_data_type_addr = _require_int("REG_TARGET_DATA_TYPE_ADDR")

    map_base = os.getenv("REG_MAP_RANGES_BASE_ADDR")
    reg_map_ranges_base_addr = int(map_base) if map_base not in (None, "") else None
    map_max_entries_str = os.getenv("MAP_MAX_ENTRIES")
    map_max_entries = int(map_max_entries_str) if map_max_entries_str not in (None, "") else None

    return Config(
        http_host=http_host,
        http_port=http_port,
        modbus_method=modbus_method,
        serial_port=serial_port,
        serial_baudrate=serial_baudrate,
        serial_parity=serial_parity,
        serial_bytesize=serial_bytesize,
        serial_stopbits=serial_stopbits,
        modbus_timeout_ms=modbus_timeout_ms,
        modbus_device_id=modbus_device_id,
        read_poll_interval_ms=read_poll_interval_ms,
        connect_backoff_min_ms=connect_backoff_min_ms,
        connect_backoff_max_ms=connect_backoff_max_ms,
        operation_retries=operation_retries,
        word_order=word_order,
        reg_display_value_addr=reg_display_value_addr,
        reg_display_value_type=reg_display_value_type,
        reg_ascii_base_addr=reg_ascii_base_addr,
        reg_mode_addr=reg_mode_addr,
        reg_blink_mask_addr=reg_blink_mask_addr,
        reg_numeric_type_addr=reg_numeric_type_addr,
        reg_decimal_places_addr=reg_decimal_places_addr,
        reg_target_slave_id_addr=reg_target_slave_id_addr,
        reg_function_code_addr=reg_function_code_addr,
        reg_target_register_addr=reg_target_register_addr,
        reg_target_data_type_addr=reg_target_data_type_addr,
        reg_map_ranges_base_addr=reg_map_ranges_base_addr,
        map_max_entries=map_max_entries,
    )
