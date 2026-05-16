"""Backward-compatible facade for core views.

View implementations are split by responsibility across:
public_views, auth_views, merchant_views, staff_views, employee_views,
play_views and wallet_views.
"""

from apps.core.auth_views import *  # noqa: F401,F403
from apps.core.employee_views import *  # noqa: F401,F403
from apps.core.merchant_views import *  # noqa: F401,F403
from apps.core.play_views import *  # noqa: F401,F403
from apps.core.public_views import *  # noqa: F401,F403
from apps.core.staff_views import *  # noqa: F401,F403
from apps.core.wallet_views import *  # noqa: F401,F403
