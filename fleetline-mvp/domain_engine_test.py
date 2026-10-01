#!/usr/bin/env python3
"""Golden tests for the paise-exact duty calculation engine."""

from domain_engine import CalculationError, calculate_duty


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print("PASS", message)


def main() -> None:
    result = calculate_duty({
        "base_paise": 100_000,
        "distance_km": 120,
        "per_km_paise": 1_500,
        "duration_minutes": 150,
        "per_hour_paise": 2_400,
        "waiting_minutes": 30,
        "waiting_paise": 1_200,
        "toll_paise": 350_00,
        "parking_paise": 100_00,
        "expense_paise": 75_00,
        "tax_rate_bps": 1_800,
    })
    # 100000 + 180000 + 6000 + 600 + 35000 + 10000 + 7500 = 339100.
    expect(result["subtotal_paise"] == 339_100, "subtotal is calculated in integer paise")
    expect(result["tax_paise"] == 61_038, "tax uses half-up paise rounding")
    expect(result["total_paise"] == 400_138, "total equals subtotal plus tax")
    expect(len(result["lines"]) == 7, "explainable line items are emitted")
    expect(result["engine_version"] == "2026.09.1", "calculation version is recorded")

    half_up = calculate_duty({"duration_minutes": 1, "per_hour_paise": 1, "tax_rate_bps": 5000})
    expect(half_up["subtotal_paise"] == 0, "sub-minute rate rounds deterministically")
    expect(half_up["total_paise"] == 0, "zero subtotal produces zero total")

    try:
        calculate_duty({"base_paise": -1})
    except CalculationError:
        print("PASS negative monetary input is rejected")
    else:
        raise AssertionError("negative monetary input should be rejected")

    for invalid, label in [
        ({"distance_km": 1_000_001}, "distance business ceiling"),
        ({"base_paise": 1.5}, "fractional monetary input"),
        ({"tax_rate_bps": 10_001}, "tax-rate ceiling"),
    ]:
        try:
            calculate_duty(invalid)
        except CalculationError:
            print("PASS", label, "is rejected")
        else:
            raise AssertionError(f"{label} should be rejected")

    print("RESULT calculation engine tests passed")


if __name__ == "__main__":
    main()
