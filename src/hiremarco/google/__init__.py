"""Google: one sign-in for the Owner's mail and calendar (events).

Scopes: gmail.readonly, gmail.modify and calendar.events, on an Internal Workspace app. gmail.modify lets the code
label, archive, trash, draft and send; what Marco actually does with it is in RULES.md and goes through the gate.
The refresh token lives in the secrets file as GOOGLE_REFRESH_TOKEN.
"""

from .auth import SCOPES, GoogleAuth
from .calendar import Calendar
from .mail import Mail, MailItem

__all__ = ["SCOPES", "Calendar", "GoogleAuth", "Mail", "MailItem"]
