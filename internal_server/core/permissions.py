from rest_framework import permissions
from .models import ManagerProfile, DepartmentUserProfile, Worker
from .role_utils import is_admin as is_admin_user


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
            try:
                worker = Worker.objects.get(user=request.user, active=True)
                return obj.submitter == worker
            except Worker.DoesNotExist:
                pass

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

        try:
            DepartmentUserProfile.objects.get(user=user, active=True)
            return view.basename in ['waterrequest', 'zone']
        except DepartmentUserProfile.DoesNotExist:
            pass

        return True

    def has_object_permission(self, request, view, obj):
        user = request.user

        try:
            DepartmentUserProfile.objects.get(user=user, active=True)
            from .models import WaterRequest
            if isinstance(obj, WaterRequest):
                return True
            return False
        except DepartmentUserProfile.DoesNotExist:
            pass

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

        try:
            Worker.objects.get(user=user, active=True)
            return True
        except Worker.DoesNotExist:
            return False