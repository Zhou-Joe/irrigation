"""One authorization rule for the map launcher and AI endpoints."""
from django.conf import settings

from .role_utils import get_user_role, ROLE_MANAGER, ROLE_SUPER_ADMIN


def can_use_assistant(request):
    user = request.user
    if get_user_role(user) not in (ROLE_MANAGER, ROLE_SUPER_ADMIN):
        return False
    # Staff retain the existing cross-business AI access. Ordinary managers
    # use the assistant within their authorized irrigation workspace.
    if user.is_staff or user.is_superuser or not settings.MULTI_TEAM_ENABLED:
        return True
    from operations.access import active_membership, has_irrigation_access
    member = active_membership(request)
    return bool(member and member.team.business.code == 'irrigation'
                and has_irrigation_access(user))
