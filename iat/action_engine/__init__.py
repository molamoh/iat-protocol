"""
IAT Action Engine.

The Action Engine is the protocol organ responsible for executing actions
decided by higher-level engines.

It must stay separate from:
- Decision Engine: decides
- Workflow Engine: transitions
- Supervisor: observes and orchestrates
- API layer: exposes routes only
"""

__version__ = "0.1.0"
