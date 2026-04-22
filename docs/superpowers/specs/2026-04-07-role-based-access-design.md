# Role-Based Access Control Design

## Overview

This document describes the role-based access control (RBAC) system for the Horticulture Management System. The system supports three distinct user roles with different permissions and data access levels.

## User Roles

### 1. Admin/Manager

**Responsibilities:**
- Full access to all data and system configuration
- Approve/reject work orders (maintenance, project support, water requests)
- Approve/reject user registration requests
- Manage zones, workers, events
- View all work logs and requests

**Data Access:**
- All zones (CRUD)
- All work orders (CRUD)
- All work logs (read)
- All requests (CRUD - can approve/reject)
- All worker profiles
- Registration requests (approval)

**Sub-roles:**
- **Super Admin**: Full system access including Django admin
- **Manager**: Can approve work orders and registrations, but limited admin access

### 2. Field Worker

**Responsibilities:**
- Submit work logs via mobile app
- Submit maintenance requests
- Submit project support requests
- Submit water requests
- View their own submissions

**Data Access:**
- All zones (read-only)
- Own work logs (read/create)
- Own requests (maintenance, project support, water) - read/create
- Cannot access admin interface
- Cannot view other workers' data

### 3. Department User (FES, FAM, ENT)

**Responsibilities:**
- Submit water coordination requests only
- View all water requests (for coordination)
- View zone information

**Data Access:**
- All zones (read-only)
- All water requests (read/create)
- Cannot access work logs
- Cannot access maintenance/project support requests
- Cannot access admin interface

## Database Models

### Role Constants

```python
# models.py

ROLE_SUPER_ADMIN = 'super_admin'
ROLE_MANAGER = 'manager'
ROLE_FIELD_WORKER = 'field_worker'
ROLE_DEPT_USER = 'dept_user'

ROLE_CHOICES = [
    (ROLE_SUPER_ADMIN, '超级管理员'),
    (ROLE_MANAGER, '管理员'),
    (ROLE_FIELD_WORKER, '现场工作人员'),
    (ROLE_DEPT_USER, '部门用户'),
]
```

### ManagerProfile Model

```python
class ManagerProfile(models.Model):
    """Profile for admin/manager users."""
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='manager_profile')
    employee_id = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    
    # Permission flags
    is_super_admin = models.BooleanField(default=False)
    can_approve_registrations = models.BooleanField(default=True)
    can_approve_work_orders = models.BooleanField(default=True)
    
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### DepartmentUserProfile Model

```python
class DepartmentUserProfile(models.Model):
    """Profile for department users (FES, FAM, ENT)."""
    
    DEPARTMENT_CHOICES = [
        ('FES', 'FES'),
        ('FAM', 'FAM'),
        ('ENT', 'ENT'),
        ('其他', '其他'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='dept_profile')
    employee_id = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    department = models.CharField(max_length=20, choices=DEPARTMENT_CHOICES)
    department_other = models.CharField(max_length=50, blank=True)
    
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

### Updated RegistrationRequest Model

```python
class RegistrationRequest(models.Model):
    """Registration request with role selection."""
    
    # Add to existing model
    requested_role = models.CharField(
        max_length=20, 
        choices=ROLE_CHOICES,
        default=ROLE_FIELD_WORKER
    )
    employee_id = models.CharField(max_length=50, blank=True)
    
    # Existing fields remain...
```

### Worker Model (Unchanged)

The existing `Worker` model remains for field workers, linked to User.

## Registration Flow

### Step 1: User Registration

1. User visits registration page
2. Selects role: Field Worker / Department User / Manager
3. Fills common fields:
   - Full name
   - Phone
   - Department (for Dept User, optional for others)
   - Employee ID (optional - auto-generated if blank)
4. Submits form → creates RegistrationRequest

### Step 2: Admin Approval

1. Admin views pending registration requests
2. Can approve, reject, or request more info
3. On approval:
   - Create Django User with generated password
   - Create appropriate profile based on requested_role:
     - Field Worker → Worker model
     - Dept User → DepartmentUserProfile
     - Manager → ManagerProfile
   - Send credentials via email/SMS (optional)
4. On rejection: Update status with reason

### Step 3: Account Activation

1. User receives credentials
2. Logs in with username (employee_id) and temp password
3. Redirected to role-specific dashboard:
   - Admin/Manager → Full dashboard
   - Field Worker → Dashboard (read-only, mobile app focus)
   - Dept User → Water requests + Zones page

## Permission System

### Decorators

```python
# decorators.py

def admin_required(view_func):
    """Check if user is admin or manager."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        if not request.user.is_admin():
            messages.error(request, '无权限访问')
            return redirect('core:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper

def field_worker_required(view_func):
    """Check if user is field worker or above."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        role = request.user.get_role()
        if role not in [ROLE_FIELD_WORKER, ROLE_MANAGER, ROLE_SUPER_ADMIN]:
            messages.error(request, '无权限访问')
            return redirect('core:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper

def dept_user_required(view_func):
    """Check if user is dept user or admin."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        role = request.user.get_role()
        if role not in [ROLE_DEPT_USER, ROLE_MANAGER, ROLE_SUPER_ADMIN]:
            messages.error(request, '无权限访问')
            return redirect('core:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper
```

### User Model Extensions

```python
# Add to User model via custom User model or monkey-patch

class User(AbstractUser):
    def get_role(self):
        """Return user role."""
        if self.is_superuser:
            return ROLE_SUPER_ADMIN
        if hasattr(self, 'manager_profile') and self.manager_profile.active:
            return ROLE_MANAGER
        if hasattr(self, 'worker_profile') and self.worker_profile.active:
            return ROLE_FIELD_WORKER
        if hasattr(self, 'dept_profile') and self.dept_profile.active:
            return ROLE_DEPT_USER
        return None
    
    def is_admin(self):
        """Check if user is admin or manager."""
        role = self.get_role()
        return role in [ROLE_SUPER_ADMIN, ROLE_MANAGER]
    
    def is_field_worker(self):
        return self.get_role() == ROLE_FIELD_WORKER
    
    def is_dept_user(self):
        return self.get_role() == ROLE_DEPT_USER
    
    def get_profile(self):
        """Return active profile."""
        role = self.get_role()
        if role == ROLE_MANAGER:
            return self.manager_profile
        elif role == ROLE_FIELD_WORKER:
            return self.worker_profile
        elif role == ROLE_DEPT_USER:
            return self.dept_profile
        return None
```

## View-Level Data Filtering

### Dashboard View

All roles see dashboard, but content varies:

```python
@login_required
def dashboard(request):
    user = request.user
    is_admin = user.is_admin()
    
    # All roles see zones
    zones = Zone.objects.all().annotate(...)
    
    # Only admins see pending counts
    pending_counts = None
    if is_admin:
        pending_counts = {
            'registrations': RegistrationRequest.objects.filter(status='pending').count(),
            'work_orders': WorkOrder.objects.filter(status='pending').count(),
        }
    
    context = {
        'zones': zones,
        'is_admin': is_admin,
        'pending_counts': pending_counts,
        'role': user.get_role(),
    }
    return render(request, 'core/dashboard.html', context)
```

### Requests Page

Filtered by role:

```python
@login_required
def requests_page(request):
    user = request.user
    role = user.get_role()
    
    if user.is_admin():
        # All request types
        maintenance = MaintenanceRequest.objects.all()
        project_support = ProjectSupportRequest.objects.all()
        water = WaterRequest.objects.all()
    elif user.is_field_worker():
        worker = user.worker_profile
        maintenance = MaintenanceRequest.objects.filter(submitter=worker)
        project_support = ProjectSupportRequest.objects.filter(submitter=worker)
        water = WaterRequest.objects.filter(submitter=worker)
    elif user.is_dept_user():
        # Only water requests
        maintenance = []
        project_support = []
        water = WaterRequest.objects.all()
    
    context = {
        'maintenance': maintenance,
        'project_support': project_support,
        'water': water,
        'role': role,
    }
    return render(request, 'core/requests.html', context)
```

### Request Detail & Approval

```python
@login_required
def request_detail(request, type_code, request_id):
    user = request.user
    is_admin = user.is_admin()
    
    # Get request object
    req = get_request_by_type(type_code, request_id)
    
    # Check permissions
    if not is_admin:
        if user.is_field_worker():
            # Can only view own requests
            if req.submitter != user.worker_profile:
                messages.error(request, '无权限查看此工单')
                return redirect('core:requests')
        elif user.is_dept_user():
            # Can only view water requests
            if type_code != 'water':
                messages.error(request, '无权限查看此工单')
                return redirect('core:requests')
    
    context = {
        'req': req,
        'is_admin': is_admin,
        'can_approve': is_admin and req.status == 'submitted',
    }
    return render(request, 'core/request_detail.html', context)


@require_POST
@login_required
def update_request_status(request, type_code, request_id):
    """Only admins can update request status."""
    if not request.user.is_admin():
        messages.error(request, '无权限操作')
        return redirect('core:request_detail', ...)
    
    # Update logic...
```

## Admin Interface Customization

### Registration Request Admin

```python
@admin.register(RegistrationRequest)
class RegistrationRequestAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'department_display', 'requested_role', 'status', 'created_at')
    list_filter = ('status', 'requested_role', 'department', 'created_at')
    actions = ['approve_requests', 'reject_requests']
    
    def approve_requests(self, request, queryset):
        for reg in queryset.filter(status='pending'):
            # Generate employee ID
            employee_id = reg.employee_id or self._generate_employee_id(reg.requested_role)
            
            # Create Django User
            user = User.objects.create_user(
                username=employee_id,
                password=self._generate_temp_password(),
            )
            
            # Create role-specific profile
            if reg.requested_role == ROLE_FIELD_WORKER:
                Worker.objects.create(
                    user=user,
                    employee_id=employee_id,
                    full_name=reg.full_name,
                    phone=reg.phone,
                    department=reg.department,
                )
            elif reg.requested_role == ROLE_DEPT_USER:
                DepartmentUserProfile.objects.create(
                    user=user,
                    employee_id=employee_id,
                    full_name=reg.full_name,
                    phone=reg.phone,
                    department=reg.department,
                )
            elif reg.requested_role == ROLE_MANAGER:
                ManagerProfile.objects.create(
                    user=user,
                    employee_id=employee_id,
                    full_name=reg.full_name,
                    phone=reg.phone,
                    can_approve_registrations=True,
                    can_approve_work_orders=True,
                )
            
            # Update registration
            reg.status = 'approved'
            reg.processed_at = timezone.now()
            reg.save()
```

## API Permissions

### Permission Classes

```python
# permissions.py

class IsAdminOrReadOnly(permissions.BasePermission):
    """Admin can write, others read-only."""
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_admin()

class IsOwnerOrAdmin(permissions.BasePermission):
    """Object owner or admin can modify."""
    def has_object_permission(self, request, view, obj):
        if request.user.is_admin():
            return True
        if hasattr(obj, 'submitter'):
            return obj.submitter.user == request.user
        return False

class IsDeptUserWaterOnly(permissions.BasePermission):
    """Dept users can only access water requests."""
    def has_permission(self, request, view):
        if not request.user.is_dept_user():
            return True
        return view.basename in ['waterrequest', 'zone']
```

### ViewSet Permissions

| ViewSet | Permission Class | Notes |
|---------|-----------------|-------|
| ZoneViewSet | IsAuthenticatedByTokenOrSession | All roles can view zones |
| WorkLogViewSet | IsOwnerOrAdmin | Field workers: own logs, Admin: all |
| MaintenanceRequestViewSet | IsOwnerOrAdmin | Field workers: own, Admin: all, Dept: none |
| ProjectSupportRequestViewSet | IsOwnerOrAdmin | Field workers: own, Admin: all, Dept: none |
| WaterRequestViewSet | IsOwnerOrAdmin + IsDeptUserWaterOnly | Field: own, Admin: all, Dept: all water |
| WorkerViewSet | IsAdminOrReadOnly | Admin only for write, all can read |

## Navigation Menu (Role-Based)

| Menu Item | Super Admin | Manager | Field Worker | Dept User |
|-----------|-------------|---------|--------------|-----------|
| Dashboard | ✓ | ✓ | ✓ | ✓ |
| Zones | ✓ (CRUD) | ✓ (CRUD) | ✓ (View) | ✓ (View) |
| Work Orders | ✓ (CRUD) | ✓ (CRUD) | ✗ | ✗ |
| Work Logs | ✓ (View) | ✓ (View) | ✓ (Own) | ✗ |
| Maintenance | ✓ (Approve) | ✓ (Approve) | ✓ (Own) | ✗ |
| Project Support | ✓ (Approve) | ✓ (Approve) | ✓ (Own) | ✗ |
| Water Requests | ✓ (Approve) | ✓ (Approve) | ✓ (Own) | ✓ (All) |
| Workers | ✓ (CRUD) | ✓ (View) | ✗ | ✗ |
| Registration | ✓ (Approve) | ✓ (Approve) | ✗ | ✗ |
| Settings | ✓ | ✓ | ✗ | ✗ |

## Migration Plan

1. **Create new models** (ManagerProfile, DepartmentUserProfile)
2. **Update RegistrationRequest** with role field
3. **Add role helper methods** to User
4. **Create decorators** for role-based access
5. **Update views** with role-based filtering
6. **Update templates** with conditional UI
7. **Update API permissions**
8. **Migrate existing users** (mark existing workers as field workers)

## Files to Modify

### Models
- `core/models.py` - Add new models, update RegistrationRequest

### Views
- `core/views.py` - Add role-based filtering
- `core/decorators.py` - New file for role decorators
- `core/permissions.py` - New file for API permissions

### Admin
- `core/admin.py` - Update RegistrationRequestAdmin, add new model admins

### Templates
- `core/templates/core/base.html` - Role-based navigation
- `core/templates/core/dashboard.html` - Conditional content
- `core/templates/core/requests.html` - Filtered by role
- `core/templates/core/register.html` - Role selection

### API
- `core/api.py` - Update ViewSet permissions

### Settings
- `config/settings.py` - Custom User model (if needed)

## Testing Checklist

- [ ] Admin can view all data
- [ ] Admin can approve/reject requests
- [ ] Manager can approve work orders
- [ ] Field worker can only view own data
- [ ] Field worker cannot access admin pages
- [ ] Dept user can only see water requests
- [ ] Dept user cannot see work logs
- [ ] Registration flow creates correct profile type
- [ ] Role-based navigation shows correct items
- [ ] API respects role permissions
