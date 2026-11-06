"""Read-only, local FlightGear property telemetry using the standard HTTP API.

Start FlightGear with ``--httpd=127.0.0.1:8088``. Each GET uses
``/json/<property>?t=y&d=1``. Properties, units and meanings remain aircraft
specific: this transport does not turn arbitrary simulator state into sensors.
Only explicitly configured observation properties belong in a diagnostic input.

Protocol sources (checked 22 October 2026):
https://wiki.flightgear.org/Json_Properties
https://github.com/FlightGear/flightgear/blob/next/src/Network/http/JsonUriHandler.cxx
https://github.com/FlightGear/flightgear/blob/next/src/Network/http/jsonprops.cxx
https://github.com/FlightGear/flightgear/blob/next/src/Main/options.cxx

Current FlightGear emits typed JSON values; older implementations used strings.
Both formats are accepted. Missing, malformed or disconnected readings have no
value. There is no retry, cached last value, or simulator write operation.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import http.client
import ipaddress
import json
import math
import re
import time
from typing import Literal, Mapping
from urllib.parse import quote


PropertyKind = Literal["number", "bool", "string"]
PropertyValue = float | bool | str | None


def _validate_path(path: str) -> None:
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or "//" in path
        or any(character in path for character in "?#\\")
        or any(ord(character) < 33 for character in path)
        or any(part in (".", "..") for part in path.split("/"))
    ):
        raise ValueError("property path must be an absolute FlightGear path without a query")


def _canonical_path(path: str) -> str:
    # FlightGear may spell the first node as engine or engine[0].
    return re.sub(r"\[0\](?=/|$)", "", path.rstrip("/")) or "/"


@dataclass(frozen=True)
class PropertySpec:
    """An explicitly selected observation; unit is descriptive, never converted."""

    path: str
    kind: PropertyKind = "number"
    unit: str = ""

    def __post_init__(self) -> None:
        _validate_path(self.path)
        if self.kind not in ("number", "bool", "string"):
            raise ValueError("kind must be number, bool or string")
        if not isinstance(self.unit, str):
            raise ValueError("unit must be text")


@dataclass(frozen=True)
class PropertyReading:
    path: str
    value: PropertyValue
    valid: bool
    error: str | None
    sim_time_s: float | None
    received_monotonic_s: float
    reachable: bool
    unit: str = ""


@dataclass(frozen=True)
class TelemetrySnapshot:
    """A collection of independent reads, not one atomic simulation frame.

    ``connected`` means an HTTP response was received for at least one selected
    property. It does not assert that FlightGear is advancing, an aircraft is
    healthy, or even that every requested property exists. ``complete`` requires
    valid readings for all selected channels. Simulator timestamps are seconds
    from FlightGear's /sim/time/elapsed-sec; local monotonic times are seconds
    on this process's clock and cannot be subtracted from simulator time.
    """

    readings: dict[str, PropertyReading]
    connected: bool
    complete: bool
    received_monotonic_s: float

    def to_dict(self) -> dict:
        """JSON-safe data with invalid values represented as null, never zero."""
        return asdict(self)


def _finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("value is not numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("value is not finite")
    return result


def _convert_value(value: object, kind: PropertyKind) -> float | bool | str:
    if kind == "number":
        return _finite_number(value)
    if kind == "string":
        if not isinstance(value, str):
            raise ValueError("value is not text")
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in ("true", "1"):
            return True
        if lowered in ("false", "0"):
            return False
    raise ValueError("value is not boolean")


class FlightGearClient:
    """Short-timeout HTTP GET client restricted to loopback addresses.

    No proxies or redirects are used. A fresh connection is opened per reading;
    a poll uses a bounded number of independent concurrent GET requests and may
    span several simulation frames. Request completion order is unspecified;
    returned channel order follows the caller's mapping. Use each reading's
    own timestamp when interpreting changes. A timeout is per socket operation
    rather than a hard deadline for the whole multi-node poll.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8088,
        timeout_s: float = 0.3,
        max_response_bytes: int = 262_144,
        max_workers: int = 4,
    ) -> None:
        try:
            local = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
        if not local:
            raise ValueError("FlightGear telemetry must use a loopback host")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("port must be an integer from 1 to 65535")
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(timeout_s)
            or timeout_s <= 0
        ):
            raise ValueError("timeout_s must be finite and positive")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes <= 0
        ):
            raise ValueError("max_response_bytes must be a positive integer")
        if (
            isinstance(max_workers, bool)
            or not isinstance(max_workers, int)
            or not 1 <= max_workers <= 8
        ):
            raise ValueError("max_workers must be an integer from 1 to 8")
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self.max_response_bytes = max_response_bytes
        self.max_workers = max_workers

    def read_property(
        self, path: str, kind: PropertyKind = "number", unit: str = ""
    ) -> PropertyReading:
        """Fetch one node. Configuration errors raise; transport errors are data."""
        spec = PropertySpec(path, kind, unit)
        reachable = False
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout_s)

        def invalid(error: str) -> PropertyReading:
            return PropertyReading(path, None, False, error, None, time.monotonic(), reachable, unit)

        try:
            target = "/json" + quote(path, safe="/") + "?t=y&d=1"
            connection.request("GET", target, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
            response = connection.getresponse()
            reachable = True
            if response.status == 404:
                return invalid("missing_property")
            if response.status != 200:
                return invalid(f"http_{response.status}")
            payload = response.read(self.max_response_bytes + 1)
            if len(payload) > self.max_response_bytes:
                return invalid("response_too_large")
            try:
                node = json.loads(payload)
            except (ValueError, UnicodeDecodeError):
                return invalid("malformed_json")
            if not isinstance(node, dict) or not isinstance(node.get("path"), str):
                return invalid("malformed_property")
            if _canonical_path(node["path"]) != _canonical_path(path):
                return invalid("property_path_mismatch")
            if "value" not in node or node["value"] is None:
                return invalid("missing_value")
            try:
                value = _convert_value(node["value"], spec.kind)
            except (ValueError, OverflowError):
                return invalid("invalid_value")
            sim_time_s = None
            if "ts" in node:
                try:
                    sim_time_s = _finite_number(node["ts"])
                    if sim_time_s < 0:
                        raise ValueError("negative simulator time")
                except (ValueError, OverflowError):
                    return invalid("invalid_timestamp")
            return PropertyReading(path, value, True, None, sim_time_s, time.monotonic(), True, unit)
        except TimeoutError:
            return invalid("timeout")
        except (OSError, http.client.HTTPException):
            return invalid("connection_error")
        finally:
            connection.close()

    def poll(self, channels: Mapping[str, PropertySpec]) -> TelemetrySnapshot:
        """Read only caller-selected channels; never discover private fault nodes.

        Empty selections are a configuration error: they cannot demonstrate a
        connection. No previous poll is consulted if a new reading fails. Up to
        max_workers properties are fetched concurrently within this one poll;
        max_workers=1 selects sequential operation. No background poll is started.
        """
        if not channels:
            raise ValueError("select at least one telemetry channel")
        for name, spec in channels.items():
            if not isinstance(name, str) or not name or not isinstance(spec, PropertySpec):
                raise ValueError("channels must map nonempty names to PropertySpec objects")
        items = tuple(channels.items())

        def read_item(item: tuple[str, PropertySpec]) -> tuple[str, PropertyReading]:
            name, spec = item
            return name, self.read_property(spec.path, spec.kind, spec.unit)

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(items))) as executor:
            readings = dict(executor.map(read_item, items))
        return TelemetrySnapshot(
            readings,
            connected=any(reading.reachable for reading in readings.values()),
            complete=all(reading.valid for reading in readings.values()),
            received_monotonic_s=time.monotonic(),
        )
