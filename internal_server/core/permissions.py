from rest_framework import permissions
from .models import ManagerProfile, DepartmentUserProfile, Worker
from .role_utils import is_admin as is_admin_user, is_dept_user as is_dept_user_check


class AdminCheckMixin:
    """Mixin providing admin check functionality."""

    def _is_admin(self, user):
        return is_admin_user(user)


class IsAdminOrReadOnly(AdminCheckMixin, permissions.BasePermission):
    """
    Admin can write, others read-only.
    Used for Zone, WorkOrder, Worker management.
    """
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        return self._is_admin(request.user)


class IsOwnerOrAdmin(AdminCheckMixin, permissions.BasePermission):
    """
    Object owner or admin can modify.
    Used for WorkLog, MaintenanceRequest, ProjectSupportRequest, WaterRequest.
    """
    def has_object_permission(self, request, view, obj):
        if self._is_admin(request.user):
            return True

        if hasattr(obj, 'submitter'):
            from .role_utils import get_worker_for_user
            worker = get_worker_for_user(request.user)
            if worker and obj.submitter == worker:
                return True

            submitter_user = getattr(obj.submitter, 'user', None)
            if submitter_user:
                return submitter_user == request.user

        return False


class IsDeptUserWaterOnly(permissions.BasePermission):
    """
    Department users can only access water requests and zones.
    """
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if is_dept_user_check(user):
            return view.basename in ['waterrequest', 'zone']

        return True

    def has_object_permission(self, request, view, obj):
        user = request.user

        if is_dept_user_check(user):
            from .models import WaterRequest
            if isinstance(obj, WaterRequest):
                return True
            return False

        return True


class IsFieldWorker(permissions.BasePermission):
    """
    Field worker can access own data.
    """
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if is_admin_user(user):
            return True

        from .role_utils import is_field_worker as is_field_worker_check
        return is_field_worker_check(user)