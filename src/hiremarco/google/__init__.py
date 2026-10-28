"""Google: one sign-in for the Owner's mail (read only) and calendar (events).

Scopes: gmail.readonly and calendar.events, on an Internal Workspace app.
The refresh token lives in the secrets file as GOOGLE_REFRESH_TOKEN.
"""

from .auth import SCOPES, GoogleAuth
from .calendar import Calendar
from .mail import Mail, MailItem

__all__ = ["SCOPES", "Calendar", "GoogleAuth", "Mail", "MailItem"]
