"""The gate: every action Marco takes passes here first, or it does not happen.

Two entry points, each raising ``Refused`` with a reason:

    check_outbound(conn, *, tenant_id, idempotency_key, capability, channel,
                   target, message, department, workflow_name=None)
    check_model_call(tenant_id, *, model, system, prompt)

``execute_effect`` wraps an action: it checks, asks the critic when the action
cannot be taken back, runs it, and records it, so the duplicate and rate
counts are real. A check that cannot run refuses; nothing fails open.
"""

from .checks import (
    CHANNEL_TOOLS,
    DAILY_LIMITS,
    DAILY_MODEL_CAP_USD,
    DUPLICATE_WINDOW_S,
    RECORDING_NOTICE,
    Refused,
    check_model_call,
    check_outbound,
    connect,
    execute_effect,
    record_effect,
)
from .kill import kill_switch_on, set_kill_switch

__all__ = [
    "CHANNEL_TOOLS",
    "DAILY_LIMITS",
    "DAILY_MODEL_CAP_USD",
    "DUPLICATE_WINDOW_S",
    "RECORDING_NOTICE",
    "Refused",
    "check_model_call",
    "check_outbound",
    "connect",
    "execute_effect",
    "kill_switch_on",
    "record_effect",
    "set_kill_switch",
]
