"""
IAT Protocol Security Layer.

Every security evolution must strengthen:

1. Protocol autonomy:
   the protocol must enforce its own rules without depending on manual action.

2. Protocol intelligence:
   security decisions must be explicit, auditable and usable by future
   governance, scoring and adaptive-policy engines.

3. Protocol scalability:
   identity and authorization rules must be centralized and reusable across
   Foundation agents, sellers, buyers, workers, services and settlements.
"""

from .authorities import (
    AccessDecision,
    enforce_foundation_authority,
    evaluate_foundation_authority,
)

__all__ = [
    "AccessDecision",
    "enforce_foundation_authority",
    "evaluate_foundation_authority",
]
