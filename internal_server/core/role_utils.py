"""Utility functions for role-based access control."""
from .models import (
    ManagerProfile, DepartmentUserProfile, Worker,
    ROLE_SUPER_ADMIN, ROLE_MANAGER, ROLE_FIELD_WORKER, ROLE_DEPT_USER
)


def get_django_user(user):
    """Extract the Django User from any user-like object (User, Worker, ManagerProfile, etc.)."""
    if hasattr(user, 'user') and user.user is not None:
        return user.user
    from django.contrib.auth import get_user_model
    User = get_user_model()
    if isinstance(user, User):
        return user
    return None


def get_user_role(user):
    """Return the role constant for a user (supports Django User and profile models)."""
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    if not account_enabled(user):
        return None
    # Profile model instances
    if isinstance(user, ManagerProfile):
        return ROLE_SUPER_ADMIN if user.is_super_admin else ROLE_MANAGER
    if isinstance(user, Worker):
        return ROLE_FIELD_WORKER
    if isinstance(user, DepartmentUserProfile):
        return ROLE_DEPT_USER
    # Django User
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False):
        return ROLE_SUPER_ADMIN
    if ManagerProfile.objects.filter(user=user, active=True).exists():
        return ROLE_MANAGER
    if Worker.objects.filter(user=user, active=True).exists():
        return ROLE_FIELD_WORKER
    if DepartmentUserProfile.objects.filter(user=user, active=True).exists():
        return ROLE_DEPT_USER
    return None


def is_admin(user):
    """Check if user has admin privileges (super_admin, staff, or manager)."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if not account_enabled(user):
        return False
    # Profile model instances
    if isinstance(user, ManagerProfile):
        return True
    if isinstance(user, (Worker, DepartmentUserProfile)):
        return False
    # Django User
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False):
        return True
    return ManagerProfile.objects.filter(user=user, active=True).exists()


def account_enabled(user):
    if isinstance(user, (ManagerProfile, Worker, DepartmentUserProfile)):
        return user.active and (not user.user_id or user.user.is_active)
    return bool(getattr(user, 'is_active', False))


def is_field_worker(user):
    """Check if user is a field worker."""
    return get_user_role(user) == ROLE_FIELD_WORKER


def is_dept_user(user):
    """Check if user is a department user."""
    return get_user_role(user) == ROLE_DEPT_USER


def get_worker_for_user(user):
    """Get the Worker for any user-like object. Returns Worker or None."""
    if isinstance(user, Worker):
        return user
    django_user = get_django_user(user)
    if django_user:
        try:
            return Worker.objects.get(user=django_user, active=True)
        except Worker.DoesNotExist:
            pass
    return None


def resolve_or_create_worker(user):
    """Resolve a Worker for the submitter, creating one for any account type.

    Field workers already have a linked Worker row. Admin/manager/department
    users do not — they only have a ManagerProfile / DepartmentUserProfile, or
    (for a plain Django superuser) nothing at all. Historically the workorder
    save path fell back to ``Worker.objects.first()``, attributing every such
    submission to the same arbitrary worker.

    To keep ``WorkReport.worker`` (a non-null FK) satisfied while crediting the
    real submitter, we lazily provision a Worker from whichever profile the user
    has — and if they have no profile at all (e.g. a raw superuser), from the
    Django User itself (employee_id derived from the username → idempotent).
    Returns (Worker, bool created).
    """
    from .models import ManagerProfile, DepartmentUserProfile

    worker = get_worker_for_user(user)
    if worker:
        return worker, False

    django_user = get_django_user(user)
    if not django_user:
        return None, False

    # Prefer an explicit profile (manager / dept) when present.
    profile = (ManagerProfile.objects.filter(user=django_user, active=True).first()
               or DepartmentUserProfile.objects.filter(user=django_user, active=True).first())
    if profile:
        employee_id = profile.employee_id or django_user.username
        full_name = profile.full_name or django_user.get_full_name() or django_user.username
        phone = getattr(profile, 'phone', '') or ''
    else:
        # Plain Django user (e.g. a superuser with no profile): derive a stable
        # Worker from the user's own attributes. employee_id keyed on username.
        employee_id = django_user.username
        full_name = django_user.get_full_name() or django_user.username
        phone = ''

    # Employee IDs are shared with legacy imports. A matching ID must never
    # attribute this account's actions to another person's linked Worker.
    collision = Worker.objects.filter(employee_id=employee_id).first()
    if collision and collision.user_id != django_user.pk:
        employee_id = f'SYS-USER-{django_user.pk}'
        if Worker.objects.filter(employee_id=employee_id).exclude(user=django_user).exists():
            import uuid
            employee_id = f'SYS-{django_user.pk}-{uuid.uuid4().hex[:12]}'
    worker, created = Worker.objects.get_or_create(
        user=django_user,
        defaults={
            'employee_id': employee_id,
            'full_name': full_name,
            'phone': phone,
        },
    )
    # This row is attribution only. Access is checked against the account's
    # actual role by each entry point; do not reactivate an inactive Worker.
    return worker, created


def get_worker_profile(user):
    """Get the Worker profile for a user, or None."""
    return get_worker_for_user(user)


def get_manager_profile(user):
    """Get the ManagerProfile profile for a user, or None."""
    if isinstance(user, ManagerProfile):
        return user
    django_user = get_django_user(user)
    if django_user:
        try:
            return ManagerProfile.objects.get(user=django_user, active=True)
        except ManagerProfile.DoesNotExist:
            pass
    return None


def get_dept_profile(user):
    """Get the DepartmentUserProfile profile for a user, or None."""
    if isinstance(user, DepartmentUserProfile):
        return user
    django_user = get_django_user(user)
    if django_user:
        try:
            return DepartmentUserProfile.objects.get(user=django_user, active=True)
        except DepartmentUserProfile.DoesNotExist:
            pass
    return None
