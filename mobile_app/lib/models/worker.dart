class Worker {
  final int id;
  final String employeeId;
  final String fullName;
  final String? phone;
  final bool active;

  Worker({
    required this.id,
    required this.employeeId,
    required this.fullName,
    this.phone,
    this.active = true,
  });

  factory Worker.fromJson(Map<String, dynamic> json) {
    return Worker(
      id: json['id'] ?? json['user'],
      employeeId: json['employee_id'] ?? json['employeeId'] ?? '',
      fullName: json['full_name'] ?? json['fullName'] ?? '',
      phone: json['phone'],
      active: json['active'] ?? true,
    );
  }
}