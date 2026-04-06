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
  });

  factory Zone.fromJson(Map<String, dynamic> json) {
    return Zone(
      id: json['id'],
      code: json['code'],
      name: json['name'],
      description: json['description'],
      status: json['status'] ?? 'unarranged',
      statusDisplay: json['statusDisplay'] ?? json['status_display'] ?? '未安排',
      boundaryColor: json['boundary_color'],
      boundaryPoints: json['boundary_points'] ?? json['boundaryPoints'] ?? [],
      plantCount: json['plant_count'] ?? json['plantCount'] ?? 0,
      pendingWorkOrders: json['pending_work_orders'] ?? json['pendingWorkOrders'] ?? 0,
      pendingRequests: (json['pending_requests'] as List?)
          ?.map((e) => Map<String, dynamic>.from(e))
          .toList() ?? [],
      centerFromApi: json['center'] != null
          ? {
              'lat': (json['center']['lat'] as num).toDouble(),
              'lng': (json['center']['lng'] as num).toDouble(),
            }
          : null,
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