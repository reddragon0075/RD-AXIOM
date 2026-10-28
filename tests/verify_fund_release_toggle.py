"""
Axiom Mobility - Treasury Fund Release Hold & Payout Gate Verification Runner.
Executes the test suite covering:
1. Duty completion lands in FUNDS_HELD_BY_AXIOM and cannot be withdrawn.
2. Global switch / vendor switch HOLD freezes mature funds even after 72 hours.
3. Toggling Release: ON moves exact Decimal amount to RELEASED_TO_WALLET with audit logs.
"""
import sys
import unittest

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(
        start_dir="fleetline-mvp/tests",
        pattern="test_treasury_release.py"
    )
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
