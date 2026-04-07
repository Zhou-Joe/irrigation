from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from .role_utils import is_admin, is_field_worker, is_dept_user


def admin_required(view_func):
    """Check if user is admin or manager (can approve work orders)."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')

        if not is_admin(request.user):
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

        if is_admin(request.user) or is_field_worker(request.user):
            return view_func(request, *args, **kwargs)

        messages.error(request, '无权限访问此页面')
        return redirect('core:dashboard')
    return wrapper


def dept_user_required(view_func):
    """Check if user is department user or admin."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')

        if is_admin(request.user) or is_dept_user(request.user):
            return view_func(request, *args, **kwargs)

        messages.error(request, '无权限访问此页面')
        return redirect('core:dashboard')
    return wrapper