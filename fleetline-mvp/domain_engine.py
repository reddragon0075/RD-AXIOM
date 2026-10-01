"""Deterministic paise-exact duty calculation engine for Axiom Fleet.

All monetary inputs and outputs are integer paise. Rates are expressed in
paise, durations in minutes and tax as basis points (18% = 1800).
"""

from __future__ import annotations

from dataclasses import dataclass


class CalculationError(ValueError):
    pass


# Business limits protect both PostgreSQL bigint persistence and JavaScript's
# safe-integer boundary. They are deliberately generous for fleet operations,
# but prevent malformed clients from creating astronomical ledger values.
MAX_CALCULATION_PAISE = 9_000_000_000_000_000
INPUT_LIMITS = {
    "base_paise": 100_000_000_000,
    "distance_km": 1_000_000,
    "per_km_paise": 1_000_000,
    "duration_minutes": 1_000_000,
    "per_hour_paise": 100_000_000,
    "waiting_minutes": 1_000_000,
    "waiting_paise": 100_000_000,
    "toll_paise": 100_000_000,
    "parking_paise": 100_000_000,
    "expense_paise": 100_000_000,
    "tax_rate_bps": 10_000,
}


def _non_negative_int(value: object, name: str) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool) or isinstance(value, float) and not value.is_integer():
        raise CalculationError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CalculationError(f"{name} must be an integer") from exc
    if number < 0:
        raise CalculationError(f"{name} cannot be negative")
    limit = INPUT_LIMITS.get(name)
    if limit is not None and number > limit:
        raise CalculationError(f"{name} exceeds the allowed business limit")
    return number


def _safe_product(left: int, right: int, name: str) -> int:
    value = left * right
    if value > MAX_CALCULATION_PAISE:
        raise CalculationError(f"{name} calculation exceeds the allowed business limit")
    return value


def round_div(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise CalculationError("denominator must be positive")
    if numerator < 0 or numerator > MAX_CALCULATION_PAISE:
        raise CalculationError("calculation exceeds the allowed business limit")
    return (numerator + denominator // 2) // denominator


def percentage_bps(amount: int, bps: int) -> int:
    if amount < 0 or amount > MAX_CALCULATION_PAISE:
        raise CalculationError("subtotal exceeds the allowed business limit")
    whole, remainder = divmod(amount, 10_000)
    return whole * bps + (remainder * bps + 5_000) // 10_000


@dataclass(frozen=True)
class DutyInputs:
    base_paise: int = 0
    distance_km: int = 0
    per_km_paise: int = 0
    duration_minutes: int = 0
    per_hour_paise: int = 0
    waiting_minutes: int = 0
    waiting_paise: int = 0
    toll_paise: int = 0
    parking_paise: int = 0
    expense_paise: int = 0
    tax_rate_bps: int = 0

    @classmethod
    def from_payload(cls, payload: dict) -> "DutyInputs":
        values = {field: _non_negative_int(payload.get(field), field) for field in cls.__dataclass_fields__}
        if values["tax_rate_bps"] > 10_000:
            raise CalculationError("tax_rate_bps cannot exceed 10000")
        return cls(**values)


def calculate_duty(payload: dict) -> dict:
    """Return explainable line items and totals for one duty.

    Hourly and waiting rates are prorated by minutes and rounded half-up at
    the line level. Tax is rounded half-up after subtotal calculation.
    """
    inputs = DutyInputs.from_payload(payload)
    lines = []

    def add_line(code: str, label: str, quantity: int, unit_paise: int, amount_paise: int, source: str) -> None:
        if amount_paise:
            lines.append({
                "code": code,
                "label": label,
                "quantity": quantity,
                "unit_paise": unit_paise,
                "amount_paise": amount_paise,
                "source": source,
            })

    add_line("base", "Base duty", 1, inputs.base_paise, inputs.base_paise, "price_book")
    km_amount = _safe_product(inputs.distance_km, inputs.per_km_paise, "distance")
    add_line("distance", "Distance", inputs.distance_km, inputs.per_km_paise, km_amount, "odometer")
    time_amount = round_div(_safe_product(inputs.duration_minutes, inputs.per_hour_paise, "time"), 60)
    add_line("time", "Time", inputs.duration_minutes, inputs.per_hour_paise, time_amount, "duty_clock")
    waiting_amount = round_div(_safe_product(inputs.waiting_minutes, inputs.waiting_paise, "waiting"), 60)
    add_line("waiting", "Waiting", inputs.waiting_minutes, inputs.waiting_paise, waiting_amount, "duty_clock")
    add_line("toll", "Toll", 1, inputs.toll_paise, inputs.toll_paise, "expense")
    add_line("parking", "Parking", 1, inputs.parking_paise, inputs.parking_paise, "expense")
    add_line("expense", "Other expense", 1, inputs.expense_paise, inputs.expense_paise, "expense")

    subtotal_paise = sum(line["amount_paise"] for line in lines)
    if subtotal_paise > MAX_CALCULATION_PAISE:
        raise CalculationError("subtotal exceeds the allowed business limit")
    tax_paise = percentage_bps(subtotal_paise, inputs.tax_rate_bps)
    total_paise = subtotal_paise + tax_paise
    if total_paise > MAX_CALCULATION_PAISE:
        raise CalculationError("total exceeds the allowed business limit")
    return {
        "engine_version": "2026.09.1",
        "inputs": inputs.__dict__,
        "lines": lines,
        "subtotal_paise": subtotal_paise,
        "tax_rate_bps": inputs.tax_rate_bps,
        "tax_paise": tax_paise,
        "total_paise": total_paise,
    }
