"""
Axiom Mobility - Hyper-Network Exchange Verification Suite
Executes end-to-end multi-tenant network clearing tests:
1. Anti-Poaching Double-Blind Masking & Ghost Mode
2. Waterfall Escalation & Atomic Claim Lock
3. Margin Floor Guardrails & Surge Boost
4. EV SoC Range-Safety Gate & Compliance Passport
5. Zero-Knowledge Corporate Compliance Seal
6. T+0 Instant Factoring Clearinghouse (1.75% fee)
7. Empty-Leg Return Radar Matchmaker
"""
import sys
import unittest

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(
        start_dir="fleetline-mvp/tests",
        pattern="test_hyper_network.py"
    )
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
