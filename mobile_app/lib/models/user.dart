/// Base user class for all user types
class User {
  final int id;
  final String username;
  final String fullName;
  final String? phone;
  final String role;
  final bool active;
  final String? employeeId;
  final String? department;
  final String? departmentOther;

  User({
    required this.id,
    required this.username,
    required this.fullName,
    this.phone,
    required this.role,
    this.active = true,
    this.employeeId,
    this.department,
    this.departmentOther,
  });

  factory User.fromJson(Map<String, dynamic> json) {
    return User(
      id: json['id'] ?? json['user'] ?? 0,
      username: json['username'] ?? json['employee_id'] ?? '',
      fullName: json['full_name'] ?? json['fullName'] ?? '',
      phone: json['phone'],
      role: json['role'] ?? 'field_worker',
      active: json['active'] ?? true,
      employeeId: json['employee_id'],
      department: json['department'],
      departmentOther: json['department_other'],
    );
  }

  Map<String, dynamic> toJson() => {
    'id': id,
    'username': username,
    'full_name': fullName,
    'phone': phone,
    'role': role,
    'active': active,
    'employee_id': employeeId,
    'department': department,
    'department_other': departmentOther,
  };

  /// Check if user is admin/manager
  bool get isAdmin => role == 'super_admin' || role == 'manager';

  /// Check if user is field worker
  bool get isFieldWorker => role == 'field_worker';

  /// Check if user is department user
  bool get isDeptUser => role == 'dept_user';

  /// Get role display name
  String get roleDisplay {
    switch (role) {
      case 'super_admin':
        return '超级管理员';
      case 'manager':
        return '管理员';
      case 'field_worker':
        return '现场工作人员';
      case 'dept_user':
        return '部门用户';
      default:
        return '未知';
    }
  }

  /// Get department display name
  String get departmentDisplay {
    if (department == '其他' && departmentOther != null && departmentOther!.isNotEmpty) {
      return departmentOther!;
    }
    return department ?? '-';
  }
}

/// Worker profile (field worker)
class Worker extends User {
  final String employeeId;
  final String? department;
  final String? departmentOther;

  Worker({
    required super.id,
    required super.username,
    required super.fullName,
    super.phone,
    super.active,
    required this.employeeId,
    this.department,
    this.departmentOther,
  }) : super(role: 'field_worker');

  factory Worker.fromJson(Map<String, dynamic> json) {
    return Worker(
      id: json['id'] ?? json['user'] ?? 0,
      username: json['username'] ?? json['employee_id'] ?? '',
      fullName: json['full_name'] ?? json['fullName'] ?? '',
      phone: json['phone'],
      active: json['active'] ?? true,
      employeeId: json['employee_id'] ?? json['employeeId'] ?? '',
      department: json['department'],
      departmentOther: json['department_other'],
    );
  }

  @override
  Map<String, dynamic> toJson() => {
    ...super.toJson(),
    'employee_id': employeeId,
    'department': department,
    'department_other': departmentOther,
  };
}

/// Manager profile (admin)
class ManagerProfile extends User {
  final String employeeId;
  final bool isSuperAdmin;
  final bool canApproveRegistrations;
  final bool canApproveWorkOrders;

  ManagerProfile({
    required super.id,
    required super.username,
    required super.fullName,
    super.phone,
    super.active,
    required this.employeeId,
    this.isSuperAdmin = false,
    this.canApproveRegistrations = true,
    this.canApproveWorkOrders = true,
  }) : super(role: 'manager');

  factory ManagerProfile.fromJson(Map<String, dynamic> json) {
    return ManagerProfile(
      id: json['id'] ?? json['user'] ?? 0,
      username: json['username'] ?? json['employee_id'] ?? '',
      fullName: json['full_name'] ?? json['fullName'] ?? '',
      phone: json['phone'],
      active: json['active'] ?? true,
      employeeId: json['employee_id'] ?? '',
      isSuperAdmin: json['is_super_admin'] ?? false,
      canApproveRegistrations: json['can_approve_registrations'] ?? true,
      canApproveWorkOrders: json['can_approve_work_orders'] ?? true,
    );
  }

  @override
  Map<String, dynamic> toJson() => {
    ...super.toJson(),
    'employee_id': employeeId,
    'is_super_admin': isSuperAdmin,
    'can_approve_registrations': canApproveRegistrations,
    'can_approve_work_orders': canApproveWorkOrders,
  };
}

/// Department User profile
class DepartmentUserProfile extends User {
  final String employeeId;
  final String department;
  final String? departmentOther;

  DepartmentUserProfile({
    required super.id,
    required super.username,
    required super.fullName,
    super.phone,
    super.active,
    required this.employeeId,
    required this.department,
    this.departmentOther,
  }) : super(role: 'dept_user');

  factory DepartmentUserProfile.fromJson(Map<String, dynamic> json) {
    return DepartmentUserProfile(
      id: json['id'] ?? json['user'] ?? 0,
      username: json['username'] ?? json['employee_id'] ?? '',
      fullName: json['full_name'] ?? json['fullName'] ?? '',
      phone: json['phone'],
      active: json['active'] ?? true,
      employeeId: json['employee_id'] ?? '',
      department: json['department'] ?? 'ENT',
      departmentOther: json['department_other'],
    );
  }

  String get departmentDisplay {
    if (department == '其他' && departmentOther != null && departmentOther!.isNotEmpty) {
      return departmentOther!;
    }
    return department;
  }

  @override
  Map<String, dynamic> toJson() => {
    ...super.toJson(),
    'employee_id': employeeId,
    'department': department,
    'department_other': departmentOther,
  };
}