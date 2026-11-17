from django.contrib.auth.models import User
from django.db import transaction, IntegrityError
from django.utils import timezone
from .models import RegistrationRequest, Worker, DepartmentUserProfile, ManagerProfile
from .role_utils import is_admin, get_manager_profile, get_user_role, ROLE_SUPER_ADMIN
from django.core.exceptions import PermissionDenied


def require_approver(user):
    profile = get_manager_profile(user)
    from operations.access import memberships
    if (not is_admin(user) and not memberships(user).filter(role='manager').exists()) or (get_user_role(user) != ROLE_SUPER_ADMIN and profile and not profile.can_approve_registrations and not profile.is_super_admin):
        raise PermissionDenied('无注册审批权限')


def reject(registration_id, actor, reason=''):
    require_approver(actor)
    from operations.administration import can_approve
    reg=RegistrationRequest.objects.get(pk=registration_id)
    if not can_approve(actor,reg):raise PermissionDenied('不能审批其他业务的注册申请。')
    if not RegistrationRequest.objects.filter(pk=registration_id,status='pending').update(
            status='rejected',status_notes=reason,processed_at=timezone.now()):
        raise ValueError('注册申请已处理或不存在')


def approve(registration_id, actor):
    require_approver(actor)
    try:
        with transaction.atomic():
            # First write obtains SQLite's write reservation before reading the
            # request or generating a new employee number.
            if not RegistrationRequest.objects.filter(pk=registration_id, status='pending').update(processed_at=timezone.now()):
                raise ValueError('注册申请已处理或不存在')
            reg=RegistrationRequest.objects.get(pk=registration_id)
            from operations.administration import can_approve
            if not can_approve(actor,reg):raise PermissionDenied('不能审批其他业务的注册申请。')
            if reg.email_confirmation_required and not reg.email_verified_at:
                raise ValueError('该申请尚未完成邮箱确认，暂不能批准')
            role_map={'manager':(ManagerProfile,'ADM'),'dept_user':(DepartmentUserProfile,'DEPT'),'field_worker':(Worker,'EMP')}
            if reg.requested_role == 'field_worker' and reg.worker_type not in dict(Worker.WORKER_TYPE_CHOICES):
                raise ValueError('请选择有效的一线种类')
            model,prefix=role_map[reg.requested_role]
            if User.objects.filter(username=reg.username).exists():
                raise ValueError('用户名已存在，请先处理重复申请')
            employee=reg.employee_id.strip()
            if not employee:
                used=list(model.objects.values_list('employee_id',flat=True))
                numbers=[int(x[len(prefix):]) for x in used if x.startswith(prefix) and x[len(prefix):].isdigit()]
                employee=f'{prefix}{max(numbers,default=0)+1:03d}'
            if any(m.objects.filter(employee_id=employee).exists() for m in (Worker,ManagerProfile,DepartmentUserProfile)):
                raise ValueError('工号已存在，请修改注册申请中的工号')
            user=User.objects.create(username=reg.username,password=reg.password,first_name=reg.full_name,email=reg.email)
            fields=dict(user=user,employee_id=employee,full_name=reg.full_name,phone=reg.phone)
            if model is Worker:
                fields['worker_type'] = reg.worker_type
            if model is not ManagerProfile:
                fields.update(department=reg.department or ('ENT' if model is DepartmentUserProfile else ''),
                    department_other=reg.department_other if reg.department=='其他' else '')
            model.objects.create(**fields)
            from django.conf import settings
            if settings.MULTI_TEAM_ENABLED:
                from operations.models import Team, Membership
                business = reg.worker_type if model is Worker else reg.admin_business if model is ManagerProfile else Worker.TYPE_IRRIGATION
                if model is ManagerProfile:
                    from operations.models import AdministratorScope,BusinessArea
                    area=None if business=='general' else BusinessArea.objects.filter(code=business,active=True).first()
                    if business!='general' and area is None:raise ValueError('管理员对应的业务尚未启用')
                    AdministratorScope.objects.create(user=user,business=area)
                    if business=='general':
                        reg.status='approved';reg.employee_id=employee;reg.created_user=user
                        reg.save(update_fields=['status','employee_id','created_user','processed_at'])
                        return reg
                teams = Team.objects.filter(business__code=business, active=True, business__active=True)
                if business == Worker.TYPE_IRRIGATION:
                    teams = teams.filter(legacy_irrigation_access=True)
                team = teams.filter(code=business).first()
                if team is None and teams.count() == 1:
                    team = teams.first()
                if team is None:
                    label = dict(Worker.WORKER_TYPE_CHOICES)[business]
                    raise ValueError(f'{label}对应团队尚未启用或默认团队不明确，无法完成注册审批')
                Membership.objects.create(user=user,team=team,
                    role={'manager':'manager','field_worker':'field','dept_user':'requester'}[reg.requested_role])
            reg.status='approved';reg.employee_id=employee;reg.created_user=user
            reg.save(update_fields=['status','employee_id','created_user','processed_at'])
            return reg
    except IntegrityError as exc:
        raise ValueError('用户名或工号已被使用，请刷新后重新审批') from exc
