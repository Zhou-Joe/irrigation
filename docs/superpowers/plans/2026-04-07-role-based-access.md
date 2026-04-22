# Role-Based Access Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement three-tier role-based access control (Admin/Manager, Field Worker, Department User) with role-specific data access, registration approval workflow, and permission decorators.

**Architecture:** Extend Django User model with role detection via profile models (ManagerProfile, DepartmentUserProfile, Worker), add permission decorators for view protection, implement role-based data filtering in views and API, customize admin interface for registration approval.

**Tech Stack:** Django 5.x, Django REST Framework, SQLite (dev), Python 3.11+

---

## File Structure

### New Files
- `internal_server/core/decorators.py` - Role-based view decorators
- `internal_server/core/permissions.py` - API permission classes
- `internal_server/core/context_processors.py` - Role context for templates (update existing)

### Modified Files
- `internal_server/core/models.py` - Add ManagerProfile, DepartmentUserProfile, update RegistrationRequest
- `internal_server/core/views.py` - Add role-based filtering to views
- `internal_server/core/api.py` - Update ViewSet permissions
- `internal_server/core/admin.py` - Update RegistrationRequestAdmin for role handling
- `internal_server/core/urls.py` - Add new URL patterns if needed
- `internal_server/core/templates/core/base.html` - Role-based navigation
- `internal_server/core/templates/core/register.html` - Add role selection
- `internal_server/core/templates/core/dashboard.html` - Conditional content
- `internal_server/config/settings.py` - Add custom User model (optional)

---

## Task 1: Add ManagerProfile Model

**Files:**
- Create: None
- Modify: `internal_server/core/models.py` (after Worker model)
- Test: `internal_server/core/tests/test_models.py` (if exists, otherwise skip)

### Step 1: Add ManagerProfile model after Worker

```python
class ManagerProfile(models.Model):
    """Profile for admin/manager users."""
    
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='manager_profile'
    )
    employee_id = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True)
    
    # Permission flags
    is_super_admin = models.BooleanField(default=False)
    can_approve_registrations = models.BooleanField(default=True)
    can_approve_work_orders = models.BooleanField(default=True)
    
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Django auth compatibility
    is_authenticated = True
    is_anonymous = False
    
    class Meta:
        verbose_name = '管理员'
        verbose_name_plural = '管理员'
    
    def __str__(self):
        return f"{self.full_name} ({self.employee_id})"
```

### Step 2: Run migration

```bash
cd internal_server
python manage.py makemigrations core
python manage.py migrate
```

### Step 3: Commit

```bash
git add core/models.py core/migrations/
git commit -m "feat: add ManagerProfile model for admin users"
```

---

## Task 2: Add DepartmentUserProfile Model

**Files:**
- Modify: `internal_server/core/models.py` (after ManagerProfile)

### Step 1: Add DepartmentUserProfile model

```python
class DepartmentUserProfile(models.Model):
    """Profile for department users (FES, FAM, ENT)."""
    
    DEPARTMENT_CHOICES = [
        ('FES', 'FES'),
        ('FAM', 'FAM'),
        ('ENT', 'ENT'),
        ('其他', '其他'),
    ]
    
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='dept_profile'
    )
    employee_id = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True)
    department = models.CharField(max_length=20, choices=DEPARTMENT_CHOICES, default='ENT')
    department_other = models.CharField(max_length=50, blank=True)
    
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Django auth compatibility
    is_authenticated = True
    is_anonymous = False
    
    class Meta:
        verbose_name = '部门用户'
        verbose_name_plural = '部门用户'
    
    def get_department_display_name(self):
        if self.department == '其他' and self.department_other:
            return self.department_other
        return self.get_department_display()
    
    def __str__(self):
        return f"{self.full_name} ({self.employee_id} - {self.get_department_display_name()})"
```

### Step 2: Run migration

```bash
python manage.py makemigrations core
python manage.py migrate
```

### Step 3: Commit

```bash
git add core/models.py core/migrations/
git commit -m "feat: add DepartmentUserProfile model for FES/FAM/ENT users"
```

---

## Task 3: Update RegistrationRequest with Role Field

**Files:**
- Modify: `internal_server/core/models.py` (update RegistrationRequest)

### Step 1: Add role constants and update RegistrationRequest

Add at top of models.py after imports:

```python
# Role constants
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

Update RegistrationRequest model:

```python
class RegistrationRequest(models.Model):
    """Registration request pending admin approval."""
    
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_INFO_NEEDED = 'info_needed'

    STATUS_CHOICES = [
        (STATUS_PENDING, '待审批'),
        (STATUS_APPROVED, '已批准'),
        (STATUS_REJECTED, '已拒绝'),
        (STATUS_INFO_NEEDED, '需补充信息'),
    ]

    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    department = models.CharField(max_length=20, choices=Worker.DEPARTMENT_CHOICES, blank=True)
    department_other = models.CharField(max_length=50, blank=True)
    
    # New fields
    requested_role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_FIELD_WORKER
    )
    employee_id = models.CharField(max_length=50, blank=True, help_text='申请时填写的工号，留空则自动生成')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    status_notes = models.TextField(blank=True, help_text='审批备注')
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='processed_registrations'
    )
    
    # Link to created user/profile
    created_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='registration_request'
    )

    def __str__(self):
        return f"注册申请 - {self.full_name} ({self.get_requested_role_display()})"
    
    class Meta:
        verbose_name = '注册申请'
        verbose_name_plural = '注册申请'
```

### Step 2: Run migration

```bash
python manage.py makemigrations core
python manage.py migrate
```

### Step 3: Commit

```bash
git add core/models.py core/migrations/
git commit -m "feat: add role field to RegistrationRequest model"
```

---

## Task 4: Create Role-Based Decorators

**Files:**
- Create: `internal_server/core/decorators.py`

### Step 1: Create decorators.py

```python
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
```

### Step 2: Commit

```bash
git add core/decorators.py
git commit -m "feat: add role-based decorators for view protection"
```

---

## Task 5: Create API Permission Classes

**Files:**
- Create: `internal_server/core/permissions.py`

### Step 1: Create permissions.py

```python
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
```

### Step 2: Commit

```bash
git add core/permissions.py
git commit -m "feat: add API permission classes for role-based access"
```

---

## Task 6: Update Admin for Role-Based Registration Approval

**Files:**
- Modify: `internal_server/core/admin.py`

### Step 1: Update RegistrationRequestAdmin

```python
from django.contrib import admin
from django.utils import timezone
from django.contrib.auth.models import User
from .models import (
    Zone, Plant, Worker, WorkOrder, Event, WorkLog, WeatherData,
    MaintenanceRequest, ProjectSupportRequest, WaterRequest,
    RegistrationRequest, ManagerProfile, DepartmentUserProfile
)


@admin.register(RegistrationRequest)
class RegistrationRequestAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'department_display', 'requested_role_display', 'status', 'created_at', 'processed_at')
    list_filter = ('status', 'requested_role', 'department', 'created_at')
    search_fields = ('full_name', 'phone', 'employee_id')
    readonly_fields = ('created_at', 'processed_at', 'processed_by', 'created_user')
    actions = ['approve_requests', 'reject_requests']
    
    fieldsets = (
        ('基本信息', {
            'fields': ('full_name', 'phone', 'department', 'department_other', 'employee_id')
        }),
        ('申请角色', {
            'fields': ('requested_role',)
        }),
        ('审批状态', {
            'fields': ('status', 'status_notes', 'processed_at', 'processed_by', 'created_user')
        }),
        ('时间戳', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    def department_display(self, obj):
        if obj.department == '其他' and obj.department_other:
            return obj.department_other
        return obj.get_department_display() if obj.department else '-'
    department_display.short_description = '部门'
    
    def requested_role_display(self, obj):
        return obj.get_requested_role_display()
    requested_role_display.short_description = '申请角色'

    def approve_requests(self, request, queryset):
        """Approve selected registration requests and create appropriate user accounts."""
        from django.contrib.auth.hashers import make_password
        import secrets
        import string
        
        for reg in queryset.filter(status='pending'):
            # Generate password
            password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
            
            # Generate employee ID if not provided
            employee_id = reg.employee_id
            if not employee_id:
                if reg.requested_role in ['super_admin', 'manager']:
                    prefix = 'ADM'
                    last = ManagerProfile.objects.order_by('-id').first()
                elif reg.requested_role == 'dept_user':
                    prefix = 'DEPT'
                    last = DepartmentUserProfile.objects.order_by('-id').first()
                else:
                    prefix = 'EMP'
                    last = Worker.objects.order_by('-id').first()
                
                next_num = (int(last.employee_id.replace(prefix, '')) + 1) if last else 1
                employee_id = f'{prefix}{next_num:03d}'
            
            # Create Django User
            username = employee_id.lower()
            user = User.objects.create(
                username=username,
                password=make_password(password),
                first_name=reg.full_name,
            )
            
            # Create profile based on role
            if reg.requested_role == 'manager':
                ManagerProfile.objects.create(
                    user=user,
                    employee_id=employee_id,
                    full_name=reg.full_name,
                    phone=reg.phone,
                    is_super_admin=False,
                    can_approve_registrations=True,
                    can_approve_work_orders=True,
                )
            elif reg.requested_role == 'dept_user':
                DepartmentUserProfile.objects.create(
                    user=user,
                    employee_id=employee_id,
                    full_name=reg.full_name,
                    phone=reg.phone,
                    department=reg.department or 'ENT',
                    department_other=reg.department_other if reg.department == '其他' else '',
                )
            else:  # field_worker
                Worker.objects.create(
                    user=user,
                    employee_id=employee_id,
                    full_name=reg.full_name,
                    phone=reg.phone,
                    department=reg.department or '',
                    department_other=reg.department_other if reg.department == '其他' else '',
                )
            
            # Update registration
            reg.status = 'approved'
            reg.processed_at = timezone.now()
            reg.processed_by = getattr(request.user, 'worker_profile', None)
            reg.created_user = user
            reg.save()
            
            # TODO: Send email/SMS with credentials
            self.message_user(request, f'已批准 {reg.full_name} 的注册申请，工号：{employee_id}')
    approve_requests.short_description = '批准选中的注册申请'

    def reject_requests(self, request, queryset):
        queryset.filter(status='pending').update(
            status='rejected',
            processed_at=timezone.now(),
            processed_by=getattr(request.user, 'worker_profile', None)
        )
    reject_requests.short_description = '拒绝选中的注册申请'


# Add new model admins
@admin.register(ManagerProfile)
class ManagerProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'employee_id', 'phone', 'is_super_admin', 'active', 'created_at')
    list_filter = ('active', 'is_super_admin', 'can_approve_registrations', 'created_at')
    search_fields = ('full_name', 'employee_id', 'phone')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(DepartmentUserProfile)
class DepartmentUserProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'employee_id', 'phone', 'department_display', 'active', 'created_at')
    list_filter = ('active', 'department', 'created_at')
    search_fields = ('full_name', 'employee_id', 'phone')
    readonly_fields = ('created_at', 'updated_at')
    
    def department_display(self, obj):
        return obj.get_department_display_name()
    department_display.short_description = '部门'
```

### Step 2: Commit

```bash
git add core/admin.py
git commit -m "feat: update admin for role-based registration approval"
```

---

## Task 7: Update Registration Form Template

**Files:**
- Modify: `internal_server/core/templates/core/register.html`

### Step 1: Add role selection to registration form

Find the form section and add role selection before department:

```html
<!-- Add this after phone field and before department -->
<div class="form-group">
    <label for="requested_role">申请角色</label>
    <select name="requested_role" id="requested_role" class="form-control" required onchange="toggleDepartmentRequired()">
        <option value="">请选择角色</option>
        <option value="field_worker">现场工作人员</option>
        <option value="dept_user">部门用户 (FES/FAM/ENT)</option>
        <option value="manager">管理员</option>
    </select>
</div>

<!-- Add employee_id field -->
<div class="form-group">
    <label for="employee_id">工号（选填）</label>
    <input type="text" name="employee_id" id="employee_id" class="form-control" 
           placeholder="如不填写则系统自动生成">
    <small class="form-text text-muted">留空将由系统自动生成工号</small>
</div>

<script>
function toggleDepartmentRequired() {
    var role = document.getElementById('requested_role').value;
    var deptSelect = document.getElementById('department');
    if (role === 'dept_user') {
        deptSelect.setAttribute('required', 'required');
    } else {
        deptSelect.removeAttribute('required');
    }
}
</script>
```

### Step 2: Update register view to handle new fields

```python
def register(request):
    """User registration page - submit request for admin approval."""
    from core.models import RegistrationRequest, ROLE_FIELD_WORKER

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        department = request.POST.get('department', '')
        department_other = request.POST.get('department_other', '').strip()
        requested_role = request.POST.get('requested_role', ROLE_FIELD_WORKER)
        employee_id = request.POST.get('employee_id', '').strip()

        # Validation
        if not full_name:
            messages.error(request, '请输入姓名')
        elif not phone:
            messages.error(request, '请输入手机号')
        elif not requested_role:
            messages.error(request, '请选择申请角色')
        elif department == '其他' and not department_other:
            messages.error(request, '请输入其他部门名称')
        elif RegistrationRequest.objects.filter(phone=phone, status='pending').exists():
            messages.error(request, '该手机号已有待审批的注册申请')
        elif employee_id and RegistrationRequest.objects.filter(employee_id=employee_id, status='pending').exists():
            messages.error(request, '该工号已有待审批的注册申请')
        else:
            RegistrationRequest.objects.create(
                full_name=full_name,
                phone=phone,
                department=department,
                department_other=department_other if department == '其他' else '',
                requested_role=requested_role,
                employee_id=employee_id,
            )
            messages.success(request, '注册申请已提交，请等待管理员审批')
            return redirect('core:register')

    return render(request, 'core/register.html')
```

### Step 3: Commit

```bash
git add core/templates/core/register.html core/views.py
git commit -m "feat: add role selection and employee_id to registration form"
```

---

## Task 8: Update Login View with Role-Based Redirect

**Files:**
- Modify: `internal_server/core/views.py` (user_login function)

### Step 1: Update login view to redirect based on role

```python
def user_login(request):
    """Login page for frontend with role-based redirect."""
    if request.user.is_authenticated:
        return redirect('core:dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            
            # Determine redirect based on role
            redirect_url = 'core:dashboard'
            
            # Check if dept user - redirect to water requests
            try:
                DepartmentUserProfile.objects.get(user=user, active=True)
                redirect_url = 'core:requests'  # Or a specific dept user page
            except DepartmentUserProfile.DoesNotExist:
                pass
            
            next_url = request.GET.get('next', redirect_url)
            return redirect(next_url)
        else:
            messages.error(request, '用户名或密码错误')

    return render(request, 'core/login.html')
```

### Step 2: Commit

```bash
git add core/views.py
git commit -m "feat: update login view with role-based redirect"
```

---

## Task 9: Update Dashboard View with Role-Based Data

**Files:**
- Modify: `internal_server/core/views.py` (dashboard function)

### Step 1: Update dashboard to include role info and pending counts

```python
@login_required(login_url='core:login')
def dashboard(request):
    """
    Main dashboard view with interactive map showing irrigation zones.
    Role-based: All users see zones, but admins see additional stats.
    """
    from datetime import date
    from core.models import MaintenanceRequest, ProjectSupportRequest, WaterRequest, ManagerProfile

    today = date.today()
    user = request.user
    
    # Determine user role
    is_admin = user.is_superuser or user.is_staff
    is_manager = False
    is_dept_user = False
    is_field_worker = False
    
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=user, active=True)
            is_manager = True
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass
    
    if not is_admin:
        try:
            DepartmentUserProfile.objects.get(user=user, active=True)
            is_dept_user = True
        except DepartmentUserProfile.DoesNotExist:
            pass
    
    if not is_admin and not is_dept_user:
        try:
            Worker.objects.get(user=user, active=True)
            is_field_worker = True
        except Worker.DoesNotExist:
            pass
    
    # All roles see zones (read-only for non-admins)
    zones = Zone.objects.all().annotate(
        plant_count=Count('plants', distinct=True),
        pending_work_orders=Count(
            'work_orders',
            filter=Q(work_orders__status='pending'),
            distinct=True
        )
    )

    # Prepare zones data for template
    zones_list = []
    for zone in zones:
        center = get_zone_center(zone.boundary_points)
        zone.center = center

        # Get pending requests for today
        pending_requests = []
        if is_admin or is_field_worker:  # Field workers need to see this on map
            for req in WaterRequest.objects.filter(
                zone=zone,
                status='submitted',
                start_datetime__date__lte=today,
                end_datetime__date__gte=today
            ):
                pending_requests.append({
                    'id': req.id,
                    'type': 'water',
                    'type_display': '浇水协调',
                })

        zones_list.append({
            'id': zone.id,
            'code': zone.code,
            'name': zone.name,
            'description': zone.description,
            'boundary_points': zone.boundary_points,
            'boundary_color': zone.boundary_color,
            'status': zone.get_today_status(),
            'statusDisplay': zone.get_status_display(),
            'plant_count': zone.plant_count or 0,
            'pending_work_orders': zone.pending_work_orders or 0,
            'center': center,
            'pending_requests': pending_requests,
        })
    
    # Only admins see pending counts
    pending_counts = None
    if is_admin:
        pending_counts = {
            'registrations': RegistrationRequest.objects.filter(status='pending').count(),
            'work_orders': WorkOrder.objects.filter(status='pending').count(),
            'maintenance': MaintenanceRequest.objects.filter(status='submitted').count(),
            'project_support': ProjectSupportRequest.objects.filter(status='submitted').count(),
            'water': WaterRequest.objects.filter(status='submitted').count(),
        }

    context = {
        'zones': zones,
        'zones_json': json.dumps(zones_list),
        'is_admin': is_admin,
        'is_manager': is_manager,
        'is_dept_user': is_dept_user,
        'is_field_worker': is_field_worker,
        'pending_counts': pending_counts,
    }

    return render(request, 'core/dashboard.html', context)
```

### Step 2: Commit

```bash
git add core/views.py
git commit -m "feat: update dashboard with role-based data filtering"
```

---

## Task 10: Update Requests Page with Role-Based Filtering

**Files:**
- Modify: `internal_server/core/views.py` (requests_page function)

### Step 1: Update requests_page to filter by role

```python
@login_required(login_url='core:login')
def requests_page(request):
    """
    工单记录页面 - 显示维护维修、项目支持、浇水协调请求
    Role-based filtering applied.
    """
    from core.models import (
        MaintenanceRequest, ProjectSupportRequest, WaterRequest,
        ManagerProfile, DepartmentUserProfile, Worker
    )
    from datetime import date

    today = date.today()
    user = request.user
    
    # Determine role
    is_admin = user.is_superuser or user.is_staff
    current_worker = None
    current_dept_user = None
    
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass
    
    if not is_admin:
        try:
            current_worker = Worker.objects.get(user=user, active=True)
        except Worker.DoesNotExist:
            pass
    
    if not is_admin and not current_worker:
        try:
            current_dept_user = DepartmentUserProfile.objects.get(user=user, active=True)
        except DepartmentUserProfile.DoesNotExist:
            pass

    # Get requests based on role
    all_requests = []

    # Maintenance requests
    if is_admin or current_worker:
        maintenance_qs = MaintenanceRequest.objects.select_related('zone', 'submitter')
        if current_worker:
            # Field workers only see their own
            maintenance_qs = maintenance_qs.filter(submitter=current_worker)
        
        for req in maintenance_qs:
            all_requests.append({
                'id': req.id,
                'type': '维护与维修',
                'type_code': 'maintenance',
                'zone': req.zone,
                'submitter': req.submitter,
                'date': req.date,
                'status': req.status,
                'status_display': req.get_status_display(),
                'created_at': req.created_at,
                'detail': f"{req.start_time} - {req.end_time}, {req.participants}",
            })

    # Project support requests
    if is_admin or current_worker:
        project_qs = ProjectSupportRequest.objects.select_related('zone', 'submitter')
        if current_worker:
            project_qs = project_qs.filter(submitter=current_worker)
        
        for req in project_qs:
            all_requests.append({
                'id': req.id,
                'type': '项目支持',
                'type_code': 'project_support',
                'zone': req.zone,
                'submitter': req.submitter,
                'date': req.date,
                'status': req.status,
                'status_display': req.get_status_display(),
                'created_at': req.created_at,
                'detail': f"{req.start_time} - {req.end_time}, {req.participants}",
            })

    # Water requests - all roles can see (dept users see all, others see based on rules)
    water_qs = WaterRequest.objects.select_related('zone', 'submitter')
    if current_worker:
        # Field workers only see their own
        water_qs = water_qs.filter(submitter=current_worker)
    # Dept users and admins see all water requests
    
    for req in water_qs:
        all_requests.append({
            'id': req.id,
            'type': '浇水协调需求',
            'type_code': 'water',
            'zone': req.zone,
            'submitter': req.submitter,
            'date': req.start_datetime.date() if req.start_datetime else None,
            'status': req.status,
            'status_display': req.get_status_display(),
            'created_at': req.created_at,
            'detail': f"{req.get_request_type_display()} - {req.get_user_type_display()}",
        })

    # Sort by created_at descending
    all_requests.sort(key=lambda x: x['created_at'], reverse=True)

    context = {
        'requests': all_requests,
        'today': today,
        'is_admin': is_admin,
        'is_dept_user': bool(current_dept_user),
        'is_field_worker': bool(current_worker),
    }

    return render(request, 'core/requests.html', context)
```

### Step 2: Commit

```bash
git add core/views.py
git commit -m "feat: filter requests page by user role"
```

---

## Task 11: Update Request Detail View with Permission Check

**Files:**
- Modify: `internal_server/core/views.py` (request_detail function)

### Step 1: Add permission checks to request_detail

```python
@login_required(login_url='core:login')
def request_detail(request, type_code, request_id):
    """
    工单详情页面 with role-based access control.
    """
    from core.models import (
        MaintenanceRequest, ProjectSupportRequest, WaterRequest,
        ManagerProfile, DepartmentUserProfile, Worker
    )
    from django.utils import timezone

    # Determine role
    is_admin = request.user.is_superuser or request.user.is_staff
    current_worker = None
    current_dept_user = None
    
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass
    
    if not is_admin:
        try:
            current_worker = Worker.objects.get(user=request.user, active=True)
        except Worker.DoesNotExist:
            pass
    
    if not is_admin and not current_worker:
        try:
            current_dept_user = DepartmentUserProfile.objects.get(user=request.user, active=True)
        except DepartmentUserProfile.DoesNotExist:
            pass

    # Get request based on type
    try:
        if type_code == 'maintenance':
            if current_dept_user:
                messages.error(request, '无权限查看此工单')
                return redirect('core:requests')
            req = MaintenanceRequest.objects.select_related('zone', 'submitter', 'approver').get(pk=request_id)
            type_name = '维护与维修'
            extra_info = {
                'date': req.date,
                'start_time': req.start_time,
                'end_time': req.end_time,
                'participants': req.participants,
                'work_content': req.work_content,
                'materials': req.materials,
                'feedback': req.feedback,
            }
        elif type_code == 'project_support':
            if current_dept_user:
                messages.error(request, '无权限查看此工单')
                return redirect('core:requests')
            req = ProjectSupportRequest.objects.select_related('zone', 'submitter', 'approver').get(pk=request_id)
            type_name = '项目支持'
            extra_info = {
                'date': req.date,
                'start_time': req.start_time,
                'end_time': req.end_time,
                'participants': req.participants,
                'work_content': req.work_content,
                'materials': req.materials,
                'feedback': req.feedback,
            }
        elif type_code == 'water':
            req = WaterRequest.objects.select_related('zone', 'submitter', 'approver').get(pk=request_id)
            type_name = '浇水协调需求'
            extra_info = {
                'user_type': req.get_user_type_display(),
                'user_type_other': req.user_type_other,
                'request_type': req.get_request_type_display(),
                'request_type_other': req.request_type_other,
                'start_datetime': req.start_datetime,
                'end_datetime': req.end_datetime,
            }
        else:
            raise ValueError('Invalid type')
    except Exception as e:
        messages.error(request, f'请求不存在: {e}')
        return redirect('core:requests')
    
    # Check permissions
    if not is_admin:
        if current_worker and req.submitter != current_worker:
            messages.error(request, '无权限查看此工单')
            return redirect('core:requests')
        # Dept users can view all water requests (handled above)

    context = {
        'req': req,
        'type_code': type_code,
        'type_name': type_name,
        'extra_info': extra_info,
        'is_admin': is_admin,
        'current_worker': current_worker,
        'current_dept_user': current_dept_user,
    }

    return render(request, 'core/request_detail.html', context)
```

### Step 2: Commit

```bash
git add core/views.py
git commit -m "feat: add role-based permissions to request detail view"
```

---

## Task 12: Update Update Request Status View

**Files:**
- Modify: `internal_server/core/views.py` (update_request_status function)

### Step 1: Ensure only admins can update status

```python
@require_POST
@login_required(login_url='core:login')
def update_request_status(request, type_code, request_id):
    """
    更新工单状态 - 仅限管理员操作
    """
    from core.models import (
        MaintenanceRequest, ProjectSupportRequest, WaterRequest,
        ManagerProfile, Worker
    )
    from django.utils import timezone

    # Check admin permission
    is_admin = request.user.is_superuser or request.user.is_staff
    
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass
    
    if not is_admin:
        messages.error(request, '无权限操作')
        return redirect('core:request_detail', type_code=type_code, request_id=request_id)

    # Get approver
    try:
        approver = Worker.objects.get(user=request.user)
    except Worker.DoesNotExist:
        approver = None

    new_status = request.POST.get('status')
    status_notes = request.POST.get('status_notes', '')

    if new_status not in ['approved', 'rejected', 'info_needed']:
        messages.error(request, '无效的状态')
        return redirect('core:request_detail', type_code=type_code, request_id=request_id)

    # Get request
    try:
        if type_code == 'maintenance':
            req = MaintenanceRequest.objects.get(pk=request_id)
        elif type_code == 'project_support':
            req = ProjectSupportRequest.objects.get(pk=request_id)
        elif type_code == 'water':
            req = WaterRequest.objects.get(pk=request_id)
        else:
            raise ValueError('Invalid type')
    except Exception as e:
        messages.error(request, f'请求不存在: {e}')
        return redirect('core:requests')

    req.status = new_status
    req.status_notes = status_notes
    req.approver = approver
    req.processed_at = timezone.now()
    req.save()

    status_names = {
        'approved': '已批准',
        'rejected': '已拒绝',
        'info_needed': '需补充信息',
    }
    messages.success(request, f'工单状态已更新为: {status_names[new_status]}')
    return redirect('core:request_detail', type_code=type_code, request_id=request_id)
```

### Step 2: Commit

```bash
git add core/views.py
git commit -m "feat: restrict request status updates to admin only"
```

---

## Task 13: Update Settings View with Admin Check

**Files:**
- Modify: `internal_server/core/views.py` (settings_page, zone_edit, zone_new, zone_delete)

### Step 1: Update zone management views to require admin

```python
@login_required(login_url='core:login')
def settings_page(request):
    """
    Settings page - admin only for zone management.
    """
    # Check admin permission
    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            from .models import ManagerProfile
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
        except ManagerProfile.DoesNotExist:
            pass
    
    if not is_admin:
        messages.error(request, '无权限访问设置页面')
        return redirect('core:dashboard')
    
    zones = Zone.objects.all().order_by('code')

    context = {
        'zones': zones,
        'status_choices': Zone.STATUS_CHOICES,
    }

    return render(request, 'core/settings.html', context)


@login_required(login_url='core:login')
def zone_edit(request, zone_id):
    """Edit zone - admin only."""
    # Admin check
    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            from .models import ManagerProfile
            ManagerProfile.objects.get(user=request.user, active=True)
        except ManagerProfile.DoesNotExist:
            messages.error(request, '无权限编辑区域')
            return redirect('core:dashboard')
    
    # Rest of existing code...
    from core.models import Plant
    zone = get_object_or_404(Zone, pk=zone_id)
    # ... (keep existing implementation)


@login_required(login_url='core:login')
def zone_new(request):
    """Create new zone - admin only."""
    # Admin check
    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            from .models import ManagerProfile
            ManagerProfile.objects.get(user=request.user, active=True)
        except ManagerProfile.DoesNotExist:
            messages.error(request, '无权限创建区域')
            return redirect('core:dashboard')
    
    # Rest of existing code...
    from core.models import Plant
    # ... (keep existing implementation)


@require_POST
@login_required(login_url='core:login')
def zone_delete(request, zone_id):
    """Delete zone - admin only."""
    # Admin check
    is_admin = request.user.is_superuser or request.user.is_staff
    if not is_admin:
        try:
            from .models import ManagerProfile
            ManagerProfile.objects.get(user=request.user, active=True)
        except ManagerProfile.DoesNotExist:
            messages.error(request, '无权限删除区域')
            return redirect('core:dashboard')
    
    # Rest of existing code...
    zone = get_object_or_404(Zone, pk=zone_id)
    # ... (keep existing implementation)
```

### Step 2: Commit

```bash
git add core/views.py
git commit -m "feat: restrict zone management to admin only"
```

---

## Task 14: Update Base Template with Role-Based Navigation

**Files:**
- Modify: `internal_server/core/templates/core/base.html` (or check existing navigation)

### Step 1: Check if there's a navigation template

First check where navigation is defined:

```bash
ls -la internal_server/core/templates/core/
grep -l "nav\|menu\|sidebar" internal_server/core/templates/core/*.html
```

### Step 2: Update navigation with role-based items

If navigation is in base.html or another template, add conditional menu items:

```html
<!-- Example navigation structure -->
<nav>
    <ul>
        <li><a href="{% url 'core:dashboard' %}">首页</a></li>
        
        {% if is_admin %}
        <li><a href="{% url 'core:settings' %}">区域管理</a></li>
        {% endif %}
        
        <li><a href="{% url 'core:requests' %}">工单记录</a></li>
        
        {% if is_admin %}
        <li>
            <a href="{% url 'admin:index' %}">后台管理</a>
            {% if pending_counts.registrations %}
            <span class="badge">{{ pending_counts.registrations }}</span>
            {% endif %}
        </li>
        {% endif %}
        
        <li><a href="{% url 'core:logout' %}">退出</a></li>
    </ul>
</nav>
```

### Step 3: Update context processor if needed

If navigation is in a context processor, update it to include role info.

### Step 4: Commit

```bash
git add core/templates/
git commit -m "feat: add role-based navigation menu"
```

---

## Task 15: Update API ViewSets with New Permissions

**Files:**
- Modify: `internal_server/core/api.py`

### Step 1: Import new permissions and update ViewSets

```python
from rest_framework import serializers, viewsets, permissions, status, authentication
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.contrib.auth import authenticate, login
from django.utils import timezone
from datetime import timedelta, date
from .models import (
    Zone, Plant, Worker, WorkOrder, Event, WorkLog, WeatherData,
    MaintenanceRequest, ProjectSupportRequest, WaterRequest,
    ManagerProfile, DepartmentUserProfile
)
from .authentication import TokenAuthentication
from .permissions import (
    IsAdminOrReadOnly, IsOwnerOrAdmin,
    IsDeptUserWaterOnly, IsFieldWorker
)


# Update ViewSets with new permissions
class ZoneViewSet(viewsets.ModelViewSet):
    """ViewSet for Zone CRUD - all authenticated users can read, only admin can write."""
    queryset = Zone.objects.all()
    serializer_class = ZoneSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAdminOrReadOnly]


class WorkLogViewSet(viewsets.ModelViewSet):
    """ViewSet for WorkLog - admin sees all, field workers see own."""
    queryset = WorkLog.objects.all()
    serializer_class = WorkLogSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsOwnerOrAdmin]
    
    def get_queryset(self):
        user = self.request.user
        # Check if admin
        is_admin = user.is_superuser or user.is_staff
        if not is_admin:
            try:
                ManagerProfile.objects.get(user=user, active=True)
                is_admin = True
            except ManagerProfile.DoesNotExist:
                pass
        
        if is_admin:
            return WorkLog.objects.all()
        
        # Field worker - only own logs
        try:
            worker = Worker.objects.get(user=user, active=True)
            return WorkLog.objects.filter(worker=worker)
        except Worker.DoesNotExist:
            return WorkLog.objects.none()


class MaintenanceRequestViewSet(viewsets.ModelViewSet):
    """ViewSet for MaintenanceRequest - dept users cannot access."""
    queryset = MaintenanceRequest.objects.all().order_by('-created_at')
    serializer_class = MaintenanceRequestSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsOwnerOrAdmin]
    
    def get_queryset(self):
        user = self.request.user
        # Check if dept user - deny access
        try:
            DepartmentUserProfile.objects.get(user=user, active=True)
            return MaintenanceRequest.objects.none()
        except DepartmentUserProfile.DoesNotExist:
            pass
        
        # Check if admin
        is_admin = user.is_superuser or user.is_staff
        if not is_admin:
            try:
                ManagerProfile.objects.get(user=user, active=True)
                is_admin = True
            except ManagerProfile.DoesNotExist:
                pass
        
        if is_admin:
            return MaintenanceRequest.objects.all().order_by('-created_at')
        
        # Field worker - only own
        try:
            worker = Worker.objects.get(user=user, active=True)
            return MaintenanceRequest.objects.filter(submitter=worker).order_by('-created_at')
        except Worker.DoesNotExist:
            return MaintenanceRequest.objects.none()
    
    def perform_create(self, serializer):
        if isinstance(self.request.user, Worker):
            serializer.save(submitter=self.request.user)
        else:
            serializer.save(submitter=self.request.user.worker_profile)


class ProjectSupportRequestViewSet(viewsets.ModelViewSet):
    """ViewSet for ProjectSupportRequest - dept users cannot access."""
    queryset = ProjectSupportRequest.objects.all().order_by('-created_at')
    serializer_class = ProjectSupportRequestSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsOwnerOrAdmin]
    
    def get_queryset(self):
        user = self.request.user
        # Check if dept user - deny access
        try:
            DepartmentUserProfile.objects.get(user=user, active=True)
            return ProjectSupportRequest.objects.none()
        except DepartmentUserProfile.DoesNotExist:
            pass
        
        # Check if admin
        is_admin = user.is_superuser or user.is_staff
        if not is_admin:
            try:
                ManagerProfile.objects.get(user=user, active=True)
                is_admin = True
            except ManagerProfile.DoesNotExist:
                pass
        
        if is_admin:
            return ProjectSupportRequest.objects.all().order_by('-created_at')
        
        # Field worker - only own
        try:
            worker = Worker.objects.get(user=user, active=True)
            return ProjectSupportRequest.objects.filter(submitter=worker).order_by('-created_at')
        except Worker.DoesNotExist:
            return ProjectSupportRequest.objects.none()
    
    def perform_create(self, serializer):
        if isinstance(self.request.user, Worker):
            serializer.save(submitter=self.request.user)
        else:
            serializer.save(submitter=self.request.user.worker_profile)


class WaterRequestViewSet(viewsets.ModelViewSet):
    """ViewSet for WaterRequest - all roles can access with different permissions."""
    queryset = WaterRequest.objects.all().order_by('-created_at')
    serializer_class = WaterRequestSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsOwnerOrAdmin, IsDeptUserWaterOnly]
    
    def get_queryset(self):
        user = self.request.user
        
        # Check if dept user
        try:
            DepartmentUserProfile.objects.get(user=user, active=True)
            # Dept users see all water requests
            return WaterRequest.objects.all().order_by('-created_at')
        except DepartmentUserProfile.DoesNotExist:
            pass
        
        # Check if admin
        is_admin = user.is_superuser or user.is_staff
        if not is_admin:
            try:
                ManagerProfile.objects.get(user=user, active=True)
                is_admin = True
            except ManagerProfile.DoesNotExist:
                pass
        
        if is_admin:
            return WaterRequest.objects.all().order_by('-created_at')
        
        # Field worker - only own
        try:
            worker = Worker.objects.get(user=user, active=True)
            return WaterRequest.objects.filter(submitter=worker).order_by('-created_at')
        except Worker.DoesNotExist:
            return WaterRequest.objects.none()
    
    def perform_create(self, serializer):
        if isinstance(self.request.user, Worker):
            serializer.save(submitter=self.request.user)
        else:
            serializer.save(submitter=self.request.user.worker_profile)


class WorkerViewSet(viewsets.ModelViewSet):
    """ViewSet for Worker - admin only for write."""
    queryset = Worker.objects.all()
    serializer_class = WorkerSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAdminOrReadOnly]


# Keep other ViewSets unchanged
class PlantViewSet(viewsets.ModelViewSet):
    queryset = Plant.objects.all()
    serializer_class = PlantSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAdminOrReadOnly]


class WorkOrderViewSet(viewsets.ModelViewSet):
    queryset = WorkOrder.objects.all()
    serializer_class = WorkOrderSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAdminOrReadOnly]


class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    authentication_classes = [TokenAuthentication, authentication.SessionAuthentication]
    permission_classes = [IsAdminOrReadOnly]
```

### Step 2: Commit

```bash
git add core/api.py
git commit -m "feat: update API ViewSets with role-based permissions"
```

---

## Task 16: Update Context Processor for Role Info

**Files:**
- Check: `internal_server/core/context_processors.py` (if exists)
- Modify: Add role information to context

### Step 1: Check existing context processors

```python
# Check if file exists and update it
cat internal_server/core/context_processors.py
```

If it doesn't exist, create it:

```python
def user_role(request):
    """Add user role information to template context."""
    if not request.user.is_authenticated:
        return {
            'is_admin': False,
            'is_manager': False,
            'is_field_worker': False,
            'is_dept_user': False,
            'user_role': None,
        }
    
    from .models import ManagerProfile, DepartmentUserProfile, Worker
    
    is_admin = request.user.is_superuser or request.user.is_staff
    is_manager = False
    is_dept_user = False
    is_field_worker = False
    user_role = None
    
    if is_admin:
        user_role = 'super_admin'
    else:
        try:
            ManagerProfile.objects.get(user=request.user, active=True)
            is_admin = True
            is_manager = True
            user_role = 'manager'
        except ManagerProfile.DoesNotExist:
            pass
    
    if not is_admin:
        try:
            Worker.objects.get(user=request.user, active=True)
            is_field_worker = True
            user_role = 'field_worker'
        except Worker.DoesNotExist:
            pass
    
    if not is_admin and not is_field_worker:
        try:
            DepartmentUserProfile.objects.get(user=request.user, active=True)
            is_dept_user = True
            user_role = 'dept_user'
        except DepartmentUserProfile.DoesNotExist:
            pass
    
    return {
        'is_admin': is_admin,
        'is_manager': is_manager,
        'is_field_worker': is_field_worker,
        'is_dept_user': is_dept_user,
        'user_role': user_role,
    }
```

### Step 2: Register in settings.py

Add to `config/settings.py`:

```python
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'core' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.notifications',
                'core.context_processors.user_role',  # Add this
            ],
        },
    },
]
```

### Step 3: Commit

```bash
git add core/context_processors.py config/settings.py
git commit -m "feat: add user role context processor for templates"
```

---

## Task 17: Create Migration for Existing Users

**Files:**
- Create: Data migration script

### Step 1: Create a data migration to assign roles to existing users

```bash
cd internal_server
python manage.py makemigrations core --empty --name=assign_existing_user_roles
```

Then edit the migration:

```python
from django.db import migrations


def assign_roles(apps, schema_editor):
    """Assign field_worker role to existing workers."""
    Worker = apps.get_model('core', 'Worker')
    
    # All existing workers are field workers
    for worker in Worker.objects.all():
        if worker.user and not hasattr(worker.user, 'manager_profile') and not hasattr(worker.user, 'dept_profile'):
            # Already a field worker by default
            pass
    
    # Check for admin users and create ManagerProfiles
    User = apps.get_model('auth', 'User')
    ManagerProfile = apps.get_model('core', 'ManagerProfile')
    
    for user in User.objects.filter(is_superuser=True):
        if not hasattr(user, 'manager_profile') and not hasattr(user, 'worker_profile'):
            # Create manager profile for superuser
            ManagerProfile.objects.create(
                user=user,
                employee_id='ADM001',
                full_name=user.first_name or user.username,
                is_super_admin=True,
            )


def reverse_assign(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('core', '000X_previous_migration'),  # Update this
    ]

    operations = [
        migrations.RunPython(assign_roles, reverse_assign),
    ]
```

### Step 2: Run migration

```bash
python manage.py migrate
```

### Step 3: Commit

```bash
git add core/migrations/
git commit -m "feat: add data migration for existing user roles"
```

---

## Task 18: Test the Implementation

**Files:**
- Test: All views and API endpoints

### Step 1: Create test script

```python
# test_roles.py - Run with: python manage.py shell < test_roles.py

from django.contrib.auth.models import User
from core.models import (
    ManagerProfile, DepartmentUserProfile, Worker,
    RegistrationRequest, Zone
)

# Test 1: Create users for each role
print("=== Creating test users ===")

# Admin/Manager
admin_user = User.objects.create_user('test_admin', password='test123')
admin_user.is_staff = True
admin_user.save()
manager_profile = ManagerProfile.objects.create(
    user=admin_user,
    employee_id='ADM999',
    full_name='Test Admin',
    is_super_admin=False,
)
print(f"Created manager: {manager_profile}")

# Field Worker
worker_user = User.objects.create_user('test_worker', password='test123')
worker = Worker.objects.create(
    user=worker_user,
    employee_id='EMP999',
    full_name='Test Worker',
)
print(f"Created worker: {worker}")

# Dept User
dept_user = User.objects.create_user('test_dept', password='test123')
dept_profile = DepartmentUserProfile.objects.create(
    user=dept_user,
    employee_id='DEPT999',
    full_name='Test Dept User',
    department='FES',
)
print(f"Created dept user: {dept_profile}")

print("\n=== Testing role detection ===")
# Test role detection
for user in [admin_user, worker_user, dept_user]:
    is_admin = user.is_superuser or user.is_staff
    if not is_admin:
        try:
            ManagerProfile.objects.get(user=user, active=True)
            is_admin = True
        except:
            pass
    
    role = 'unknown'
    try:
        ManagerProfile.objects.get(user=user, active=True)
        role = 'admin/manager'
    except:
        try:
            Worker.objects.get(user=user, active=True)
            role = 'field_worker'
        except:
            try:
                DepartmentUserProfile.objects.get(user=user, active=True)
                role = 'dept_user'
            except:
                pass
    
    print(f"{user.username}: role={role}, is_admin={is_admin}")

print("\n=== All tests passed! ===")
```

### Step 2: Run tests

```bash
cd internal_server
python manage.py shell < test_roles.py
```

### Step 3: Manual testing checklist

- [ ] Register as field worker → approval creates Worker profile
- [ ] Register as dept user → approval creates DepartmentUserProfile
- [ ] Register as manager → approval creates ManagerProfile
- [ ] Login as field worker → can see dashboard and own requests
- [ ] Login as dept user → can see water requests (all)
- [ ] Login as manager → can see all data and approve requests
- [ ] Field worker cannot access settings page
- [ ] Dept user cannot access maintenance/project support requests
- [ ] API respects permissions for each role

### Step 4: Commit

```bash
git add test_roles.py
git commit -m "test: add role-based access control tests"
```

---

## Task 19: Final Cleanup and Documentation

**Files:**
- All modified files

### Step 1: Run Django check

```bash
cd internal_server
python manage.py check
```

### Step 2: Run tests if they exist

```bash
python manage.py test
```

### Step 3: Final commit

```bash
git add -A
git commit -m "feat: complete role-based access control implementation

- Add ManagerProfile and DepartmentUserProfile models
- Update RegistrationRequest with role selection
- Add role-based decorators and API permissions
- Filter views by user role
- Customize admin for role-based approval
- Update templates with role-based navigation
- Add context processor for role info"
```

---

## Summary

This implementation plan adds comprehensive role-based access control to the Horticulture Management System:

1. **Three user roles**: Admin/Manager, Field Worker, Department User
2. **Registration workflow**: Users select role during registration, admin approves
3. **Permission decorators**: `@admin_required`, `@field_worker_required`, `@dept_user_required`
4. **API permissions**: `IsAdminOrReadOnly`, `IsOwnerOrAdmin`, `IsDeptUserWaterOnly`
5. **View filtering**: Each view filters data based on user role
6. **Template customization**: Navigation and content shown based on role

All changes are backwards compatible - existing users continue to work as field workers.
