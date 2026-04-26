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
  // Patch info for grouping
  final int? patchId;
  final String? patchName;
  final String? patchCode;
  final String? patchType;
  final String? patchTypeDisplay;

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
    this.patchId,
    this.patchName,
    this.patchCode,
    this.patchType,
    this.patchTypeDisplay,
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
      patchId: patchId,
      patchName: patchName,
      patchCode: patchCode,
      patchType: json['patch_type']?.toString(),
      patchTypeDisplay: json['patch_type_display']?.toString(),
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
}