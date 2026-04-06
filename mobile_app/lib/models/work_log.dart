class WorkLog {
  final int? id;
  final int zoneId;
  final int? workOrderId;
  final String workType;
  final String? notes;
  final double? latitude;
  final double? longitude;
  final DateTime workTimestamp;

  WorkLog({
    this.id,
    required this.zoneId,
    this.workOrderId,
    required this.workType,
    this.notes,
    this.latitude,
    this.longitude,
    required this.workTimestamp,
  });

  Map<String, dynamic> toJson() {
    return {
      if (id != null) 'id': id,
      'zone': zoneId,
      if (workOrderId != null) 'work_order': workOrderId,
      'work_type': workType,
      if (notes != null) 'notes': notes,
      if (latitude != null) 'latitude': latitude,
      if (longitude != null) 'longitude': longitude,
      'work_timestamp': workTimestamp.toIso8601String(),
    };
  }

  factory WorkLog.fromJson(Map<String, dynamic> json) {
    return WorkLog(
      id: json['id'],
      zoneId: json['zone'],
      workOrderId: json['work_order'],
      workType: json['work_type'],
      notes: json['notes'],
      latitude: json['latitude']?.toDouble(),
      longitude: json['longitude']?.toDouble(),
      workTimestamp: DateTime.parse(json['work_timestamp']),
    );
  }
}