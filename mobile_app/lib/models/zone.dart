class Zone {
  final int id;
  final String code;
  final String name;
  final String? description;
  final String status;
  final String statusDisplay;
  final String? boundaryColor;
  final List<dynamic> boundaryPoints;
  final int plantCount;
  final int pendingWorkOrders;
  final List<Map<String, dynamic>> pendingRequests;  // 待审批浇水协调需求
  final Map<String, double>? centerFromApi;
  // Priority & irrigation attributes
  final String priority;
  final String currentStatus;
  final String sprinklerType;
  final double? irrigationIntensity;
  final double? solenoidValveSize;
  final double? landscapeCoefficient;
  final String plantType;
  final String irrigationForeman;
  final String greeneryZone;
  final String greeneryForeman;
  final String pestControlZone;
  final String pestControlForeman;
  final String terrainFeature;
  final String plantFeature;
  final String soilMoisture;
  final String equipmentMaintenanceNotes;
  final String irrigationManagementNotes;
  // Patch info for grouping
  final int? patchId;
  final String? patchName;
  final String? patchCode;
  // Region info (via patch)
  final int? regionId;
  final String? regionName;

  Zone({
    required this.id,
    required this.code,
    required this.name,
    this.description,
    required this.status,
    required this.statusDisplay,
    this.boundaryColor,
    this.boundaryPoints = const [],
    this.plantCount = 0,
    this.pendingWorkOrders = 0,
    this.pendingRequests = const [],
    this.centerFromApi,
    this.priority = 'medium',
    this.currentStatus = '',
    this.sprinklerType = '',
    this.irrigationIntensity,
    this.solenoidValveSize,
    this.landscapeCoefficient,
    this.plantType = '',
    this.irrigationForeman = '',
    this.greeneryZone = '',
    this.greeneryForeman = '',
    this.pestControlZone = '',
    this.pestControlForeman = '',
    this.terrainFeature = '',
    this.plantFeature = '',
    this.soilMoisture = '',
    this.equipmentMaintenanceNotes = '',
    this.irrigationManagementNotes = '',
    this.patchId,
    this.patchName,
    this.patchCode,
    this.regionId,
    this.regionName,
  });

  factory Zone.fromJson(Map<String, dynamic> json) {
    // Parse patch info with proper type casting
    int? patchId;
    String? patchName;
    String? patchCode;
    if (json['patch'] != null && json['patch'] is Map) {
      final patchMap = json['patch'] as Map<String, dynamic>;
      patchId = patchMap['id'] is int ? patchMap['id'] : (patchMap['id'] as num?)?.toInt();
      patchName = patchMap['name']?.toString();
      patchCode = patchMap['code']?.toString();
    } else if (json['patch_id'] != null) {
      patchId = json['patch_id'] is int ? json['patch_id'] : (json['patch_id'] as num?)?.toInt();
      patchName = json['patch_name']?.toString();
      patchCode = json['patch_code']?.toString();
    }

    double? _toDouble(dynamic val) {
      if (val == null) return null;
      if (val is double) return val;
      if (val is num) return val.toDouble();
      return null;
    }

    return Zone(
      id: json['id'] is int ? json['id'] : (json['id'] as num).toInt(),
      code: json['code']?.toString() ?? '',
      name: json['name']?.toString() ?? '',
      description: json['description']?.toString(),
      status: json['status']?.toString() ?? 'unarranged',
      statusDisplay: json['statusDisplay']?.toString() ?? json['status_display']?.toString() ?? '未安排',
      boundaryColor: json['boundary_color']?.toString(),
      boundaryPoints: json['boundary_points'] ?? json['boundaryPoints'] ?? [],
      plantCount: json['plant_count'] is int ? json['plant_count'] : (json['plant_count'] as num?)?.toInt() ?? (json['plantCount'] as num?)?.toInt() ?? 0,
      pendingWorkOrders: json['pending_work_orders'] is int ? json['pending_work_orders'] : (json['pending_work_orders'] as num?)?.toInt() ?? (json['pendingWorkOrders'] as num?)?.toInt() ?? 0,
      pendingRequests: (json['pending_requests'] as List?)
          ?.map((e) => Map<String, dynamic>.from(e))
          .toList() ?? [],
      centerFromApi: json['center'] != null && json['center'] is Map
          ? (() {
              final c = json['center'] as Map;
              final lat = c['lat'];
              final lng = c['lng'];
              if (lat is num && lng is num) {
                return {'lat': lat.toDouble(), 'lng': lng.toDouble()};
              }
              return null;
            })()
          : null,
      priority: json['priority']?.toString() ?? 'medium',
      currentStatus: json['current_status']?.toString() ?? '',
      sprinklerType: json['sprinkler_type']?.toString() ?? '',
      irrigationIntensity: _toDouble(json['irrigation_intensity']),
      solenoidValveSize: _toDouble(json['solenoid_valve_size']),
      landscapeCoefficient: _toDouble(json['landscape_coefficient']),
      plantType: json['plant_type']?.toString() ?? '',
      irrigationForeman: json['irrigation_foreman']?.toString() ?? '',
      greeneryZone: json['greenery_zone']?.toString() ?? '',
      greeneryForeman: json['greenery_foreman']?.toString() ?? '',
      pestControlZone: json['pest_control_zone']?.toString() ?? '',
      pestControlForeman: json['pest_control_foreman']?.toString() ?? '',
      terrainFeature: json['terrain_feature']?.toString() ?? '',
      plantFeature: json['plant_feature']?.toString() ?? '',
      soilMoisture: json['soil_moisture']?.toString() ?? '',
      equipmentMaintenanceNotes: json['equipment_maintenance_notes']?.toString() ?? '',
      irrigationManagementNotes: json['irrigation_management_notes']?.toString() ?? '',
      patchId: patchId,
      patchName: patchName,
      patchCode: patchCode,
      regionId: json['region_id'] is int ? json['region_id'] : (json['region_id'] as num?)?.toInt(),
      regionName: json['region_name']?.toString(),
    );
  }

  Map<String, double>? get center {
    // Prefer API-provided center
    if (centerFromApi != null) return centerFromApi;
    // Calculate from boundary points
    if (boundaryPoints.isEmpty) return null;
    double lat = 0, lng = 0;
    for (var p in boundaryPoints) {
      if (p is List && p.length >= 2) {
        lat += (p[0] as num).toDouble();
        lng += (p[1] as num).toDouble();
      } else if (p is Map) {
        lat += (p['lat'] as num).toDouble();
        lng += (p['lng'] as num).toDouble();
      }
    }
    return {'lat': lat / boundaryPoints.length, 'lng': lng / boundaryPoints.length};
  }

  String get priorityDisplay {
    const map = {
      'critical': '超级重点',
      'high': '重点',
      'medium': '一般',
      'low': '次要',
      'abolished': '废除',
    };
    return map[priority] ?? '一般';
  }
}
