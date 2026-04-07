from rest_framework import permissions
from .models import ManagerProfile, DepartmentUserProfile, Worker


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Admin can write, others read-only.
    Used for Zone, WorkOrder, Worker management.
    """
    def has_permission(self, request, view):
        # Allow read-only for any authenticated user
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated

        # Write requires admin
        return self._is_admin(request.user)

    def _is_admin(self, user):
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.is_staff:
            return True
        try:
            ManagerProfile.objects.get(user=user, active=True)
            return True
        except ManagerProfile.DoesNotExist:
            return False


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Object owner or admin can modify.
    Used for WorkLog, MaintenanceRequest, ProjectSupportRequest, WaterRequest.
    """
    def has_object_permission(self, request, view, obj):
        # Admin can do anything
        if self._is_admin(request.user):
            return True

        # Check if user owns the object
        if hasattr(obj, 'submitter'):
            # For Worker-based submitter
            try:
                worker = Worker.objects.get(user=request.user, active=True)
                return obj.submitter == worker
            except Worker.DoesNotExist:
                pass

            # Check if submitter has user attribute
            submitter_user = getattr(obj.submitter, 'user', None)
            if submitter_user:
                return submitter_user == request.user

        return False

    def _is_admin(self, user):
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.is_staff:
            return True
        try:
            ManagerProfile.objects.get(user=user, active=True)
            return True
        except ManagerProfile.DoesNotExist:
            return False


class IsDeptUserWaterOnly(permissions.BasePermission):
    """
    Department users can only access water requests and zones.
    """
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # Check if dept user
        try:
            DepartmentUserProfile.objects.get(user=user, active=True)
            # Dept users can only access water requests and zones
            return view.basename in ['waterrequest', 'zone']
        except DepartmentUserProfile.DoesNotExist:
            pass

        # Not a dept user, allow
        return True

    def has_object_permission(self, request, view, obj):
        user = request.user

        # Check if dept user
        try:
            DepartmentUserProfile.objects.get(user=user, active=True)
            # Dept users can access all water requests (not just own)
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

        # Admin always allowed
        if user.is_superuser or user.is_staff:
            return True

        try:
            ManagerProfile.objects.get(user=user, active=True)
            return True
        except ManagerProfile.DoesNotExist:
            pass

        try:
            Worker.objects.get(user=user, active=True)
            return True
        except Worker.DoesNotExist:
            return False