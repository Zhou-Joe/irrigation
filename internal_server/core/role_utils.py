"""Utility functions for role-based access control."""
from .models import (
    ManagerProfile, DepartmentUserProfile, Worker,
    ROLE_SUPER_ADMIN, ROLE_MANAGER, ROLE_FIELD_WORKER, ROLE_DEPT_USER
)


def get_user_role(user):
    """Return the role constant for a user."""
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser or user.is_staff:
        return ROLE_SUPER_ADMIN
    if ManagerProfile.objects.filter(user=user, active=True).exists():
        return ROLE_MANAGER
    if Worker.objects.filter(user=user, active=True).exists():
        return ROLE_FIELD_WORKER
    if DepartmentUserProfile.objects.filter(user=user, active=True).exists():
        return ROLE_DEPT_USER
    return None


def is_admin(user):
    """Check if user has admin privileges (super_admin or manager)."""
    role = get_user_role(user)
    return role in [ROLE_SUPER_ADMIN, ROLE_MANAGER]


def is_field_worker(user):
    """Check if user is a field worker."""
    return get_user_role(user) == ROLE_FIELD_WORKER


def is_dept_user(user):
    """Check if user is a department user."""
    return get_user_role(user) == ROLE_DEPT_USER


def get_worker_profile(user):
    """Get the Worker profile for a user, or None."""
    try:
        return Worker.objects.get(user=user, active=True)
    except Worker.DoesNotExist:
        return None


def get_manager_profile(user):
    """Get the ManagerProfile for a user, or None."""
    try:
        return ManagerProfile.objects.get(user=user, active=True)
    except ManagerProfile.DoesNotExist:
        return None


def get_dept_profile(user):
    """Get the DepartmentUserProfile for a user, or None."""
    try:
        return DepartmentUserProfile.objects.get(user=user, active=True)
    except DepartmentUserProfile.DoesNotExist:
        return None


def is_admin(user):
    """Check if user has admin privileges (super_admin, staff, or manager)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return ManagerProfile.objects.filter(user=user, active=True).exists()