from functools import wraps
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib import messages


def admin_required(view_func):
    """Check if user is admin or manager (can approve work orders)."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')

        # Check if admin or manager
        is_admin = request.user.is_superuser or request.user.is_staff
        if not is_admin:
            try:
                from .models import ManagerProfile
                manager = ManagerProfile.objects.get(user=request.user, active=True)
                is_admin = True
            except ManagerProfile.DoesNotExist:
                pass

        if not is_admin:
            messages.error(request, '无权限访问此页面')
            return redirect('core:dashboard')

        return view_func(request, *args, **kwargs)
    return wrapper


def field_worker_required(view_func):
    """Check if user is field worker or above."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')

        # Allow if admin
        if request.user.is_superuser or request.user.is_staff:
            return view_func(request, *args, **kwargs)

        # Check if manager
        try:
            from .models import ManagerProfile
            ManagerProfile.objects.get(user=request.user, active=True)
            return view_func(request, *args, **kwargs)
        except ManagerProfile.DoesNotExist:
            pass

        # Check if field worker
        try:
            from .models import Worker
            Worker.objects.get(user=request.user, active=True)
            return view_func(request, *args, **kwargs)
        except Worker.DoesNotExist:
            messages.error(request, '无权限访问此页面')
            return redirect('core:dashboard')
    return wrapper


def dept_user_required(view_func):
    """Check if user is department user or admin."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')

        # Allow if admin
        if request.user.is_superuser or request.user.is_staff:
            return view_func(request, *args, **kwargs)

        # Check if manager
        try:
            from .models import ManagerProfile
            ManagerProfile.objects.get(user=request.user, active=True)
            return view_func(request, *args, **kwargs)
        except ManagerProfile.DoesNotExist:
            pass

        # Check if department user
        try:
            from .models import DepartmentUserProfile
            DepartmentUserProfile.objects.get(user=request.user, active=True)
            return view_func(request, *args, **kwargs)
        except DepartmentUserProfile.DoesNotExist:
            messages.error(request, '无权限访问此页面')
            return redirect('core:dashboard')
    return wrapper