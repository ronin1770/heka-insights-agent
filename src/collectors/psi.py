"""Collect Linux Pressure Stall Information (PSI) from procfs."""

from __future__ import annotations

import logging
import math
from pathlib import Path

_RESOURCES = ("cpu", "memory", "io")
_STALL_KINDS = ("some", "full")
_AVERAGE_FIELDS = ("avg10", "avg60", "avg300")
_REQUIRED_FIELDS = (*_AVERAGE_FIELDS, "total")


class PSICollector:
    """Read available PSI measurements using targeted procfs file reads."""

    def __init__(
        self,
        *,
        proc_root: Path | str = Path("/proc"),
        logger: logging.Logger | None = None,
    ) -> None:
        self._proc_root = Path(proc_root)
        self._logger = logger or logging.getLogger(__name__)

    def collect(self) -> dict[str, dict[str, dict[str, float | int]]]:
        """Return valid PSI measurements, omitting unavailable resources."""
        collected: dict[str, dict[str, dict[str, float | int]]] = {}
        for resource in _RESOURCES:
            path = self._proc_root / "pressure" / resource
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                self._logger.debug(
                    "PSI source unavailable | resource=%s | path=%s | error=%s",
                    resource,
                    path,
                    exc,
                )
                continue

            measurements = parse_psi_pressure(
                content,
                logger=self._logger,
                resource=resource,
            )
            if measurements:
                collected[resource] = measurements
        return collected


def parse_psi_pressure(
    content: str,
    *,
    logger: logging.Logger | None = None,
    resource: str = "unknown",
) -> dict[str, dict[str, float | int]]:
    """Parse valid ``some`` and ``full`` PSI lines independently."""
    result: dict[str, dict[str, float | int]] = {}

    for line_number, line in enumerate(content.splitlines(), start=1):
        fields = line.split()
        if not fields:
            continue

        stall = fields[0]
        if stall not in _STALL_KINDS:
            _debug_malformed(logger, resource, line_number, "unsupported stall kind")
            continue

        raw_values: dict[str, str] = {}
        malformed_reason: str | None = None
        for field in fields[1:]:
            key, separator, raw_value = field.partition("=")
            if not separator or not key or not raw_value:
                malformed_reason = "invalid key/value field"
                break
            if key in raw_values:
                malformed_reason = f"duplicate field '{key}'"
                break
            raw_values[key] = raw_value

        if malformed_reason is None:
            missing = [key for key in _REQUIRED_FIELDS if key not in raw_values]
            if missing:
                malformed_reason = f"missing fields: {','.join(missing)}"

        parsed: dict[str, float | int] = {}
        if malformed_reason is None:
            for key in _AVERAGE_FIELDS:
                try:
                    value = float(raw_values[key])
                except ValueError:
                    malformed_reason = f"invalid value for '{key}'"
                    break
                if not math.isfinite(value) or value < 0 or value > 100:
                    malformed_reason = f"out-of-range value for '{key}'"
                    break
                parsed[key] = value

        if malformed_reason is None:
            raw_total = raw_values["total"]
            if not raw_total.isdecimal():
                malformed_reason = "invalid value for 'total'"
            else:
                parsed["total"] = int(raw_total)

        if malformed_reason is not None:
            _debug_malformed(logger, resource, line_number, malformed_reason)
            continue

        result[stall] = parsed

    return result


def _debug_malformed(
    logger: logging.Logger | None,
    resource: str,
    line_number: int,
    reason: str,
) -> None:
    if logger is not None:
        logger.debug(
            "Malformed PSI line skipped | resource=%s | line=%d | reason=%s",
            resource,
            line_number,
            reason,
        )
