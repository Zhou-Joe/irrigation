import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';
import '../models/zone.dart';
import '../providers/auth_provider.dart';
import 'demand_list_screen.dart';
import 'water_request_screen.dart';
import 'request_detail_screen.dart';
import 'request_status_screen.dart';
import 'work_report_form_screen.dart';
import 'work_report_list_screen.dart';
import 'zone_detail_screen.dart';
import 'settings_screen.dart';
import '../widgets/modern_ui.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with TickerProviderStateMixin {
  int _currentIndex = 0;
  List<Zone> _zones = [];
  bool _isLoading = true;
  String? _error;
  MapController? _mapController;
  bool _isZoneDrawerExpanded = false;
  LatLng? _currentPosition;
  Zone? _selectedZone;
  List<Map<String, dynamic>> _weatherData = [];
  bool _isLoadingWeather = false;
  String _zoneSearchQuery = '';
  // Patch grouping
  Set<int> _expandedPatchIds = {}; // Track which patches are expanded
  int?
  _expandedOrphanGroup; // Track if orphan group is expanded (use -1 as sentinel)

  late AnimationController _popupAnimationController;
  late Animation<double> _popupScaleAnimation;
  late Animation<double> _popupFadeAnimation;

  AnimationController? _flyAnimationController;
  LatLng? _flyStart;
  LatLng? _flyEnd;

  @override
  void initState() {
    super.initState();
    _mapController = MapController();

    _popupAnimationController = AnimationController(
      duration: const Duration(milliseconds: 200),
      vsync: this,
    );

    _popupScaleAnimation = CurvedAnimation(
      parent: _popupAnimationController,
      curve: Curves.easeOutBack,
    );

    _popupFadeAnimation = CurvedAnimation(
      parent: _popupAnimationController,
      curve: Curves.easeOut,
    );

    _loadData();
    _getCurrentLocation();
    _loadWeather();
  }

  Future<void> _loadWeather() async {
    if (_isLoadingWeather) return;
    setState(() => _isLoadingWeather = true);

    try {
      final api = context.read<AuthProvider>().api;
      final weather = await api.getWeather();
      if (mounted) {
        setState(() {
          _weatherData = weather;
          _isLoadingWeather = false;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _isLoadingWeather = false);
    }
  }

  @override
  void dispose() {
    _flyAnimationController?.dispose();
    _popupAnimationController.dispose();
    super.dispose();
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final api = context.read<AuthProvider>().api;
      final zones = await api.getZones();
      setState(() {
        _zones = zones;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = '加载失败: $e';
        _isLoading = false;
      });
    }
  }

  Future<void> _getCurrentLocation() async {
    bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) return;

    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied) return;
    }
    if (permission == LocationPermission.deniedForever) return;

    try {
      final position = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high,
      );
      setState(() {
        _currentPosition = LatLng(position.latitude, position.longitude);
      });

      Future.delayed(const Duration(milliseconds: 500), () {
        _mapController?.move(_currentPosition!, 15);
      });
    } catch (e) {
      debugPrint('获取位置失败: $e');
    }
  }

  Color _getStatusColor(String status) {
    switch (status) {
      case 'completed':
        return const Color(0xFF40916C); // 已完成 - 绿色
      case 'in_progress':
        return const Color(0xFFCC7722); // 处理中 - 橙色
      case 'canceled':
        return const Color(0xFF9B2226); // 已取消 - 红色
      case 'delayed':
        return const Color(0xFF7B5544); // 已延期 - 深棕色
      case 'unarranged':
        return const Color(0xFF888888); // 未安排 - 灰色
      default:
        return const Color(0xFF52B788);
    }
  }

  void _selectZone(Zone zone) {
    setState(() {
      _selectedZone = zone;
    });
    _popupAnimationController.forward(from: 0);
    _flyToZone(zone);
  }

  // Helper to extract flat list of LatLng from boundary points
  List<LatLng> _extractPoints(List<dynamic> boundaryPoints) {
    final List<LatLng> points = [];
    for (var item in boundaryPoints) {
      if (item is List) {
        if (item.isNotEmpty && item[0] is num) {
          points.add(
            LatLng((item[0] as num).toDouble(), (item[1] as num).toDouble()),
          );
        } else if (item.isNotEmpty) {
          for (var sub in item) {
            if (sub is List && sub.length >= 2 && sub[0] is num) {
              points.add(
                LatLng((sub[0] as num).toDouble(), (sub[1] as num).toDouble()),
              );
            } else if (sub is Map) {
              final lat = sub['lat'];
              final lng = sub['lng'];
              if (lat is num && lng is num) {
                points.add(LatLng(lat.toDouble(), lng.toDouble()));
              }
            }
          }
        }
      } else if (item is Map) {
        final lat = item['lat'];
        final lng = item['lng'];
        if (lat is num && lng is num) {
          points.add(LatLng(lat.toDouble(), lng.toDouble()));
        }
      }
    }
    return points;
  }

  void _flyToZone(Zone zone) {
    if (_mapController == null) return;

    LatLng? target;
    if (zone.center != null) {
      target = LatLng(zone.center!['lat']!, zone.center!['lng']!);
    } else if (zone.boundaryPoints.isNotEmpty) {
      final points = _extractPoints(zone.boundaryPoints);
      if (points.isNotEmpty) {
        double sumLat = points.fold(0.0, (sum, p) => sum + p.latitude);
        double sumLng = points.fold(0.0, (sum, p) => sum + p.longitude);
        target = LatLng(sumLat / points.length, sumLng / points.length);
      }
    }

    if (target == null) return;

    // Cancel any previous flight
    _flyAnimationController?.dispose();

    _flyStart = _mapController!.camera.center;
    _flyEnd = target;

    _flyAnimationController = AnimationController(
      duration: const Duration(milliseconds: 600),
      vsync: this,
    )..addListener(_onFlyTick);

    _flyAnimationController!.forward();
  }

  void _onFlyTick() {
    if (_flyStart == null || _flyEnd == null || _mapController == null) return;
    final t = Curves.easeInOut.transform(_flyAnimationController!.value);
    final lat =
        _flyStart!.latitude + (_flyEnd!.latitude - _flyStart!.latitude) * t;
    final lng =
        _flyStart!.longitude + (_flyEnd!.longitude - _flyStart!.longitude) * t;
    _mapController!.move(LatLng(lat, lng), 19);

    if (_flyAnimationController!.isCompleted) {
      _flyAnimationController?.dispose();
      _flyAnimationController = null;
      _flyStart = null;
      _flyEnd = null;
    }
  }

  void _handleMapTap(LatLng point) {
    for (final zone in _zones) {
      if (zone.boundaryPoints.isEmpty) continue;

      final points = _extractPoints(zone.boundaryPoints);

      if (points.isEmpty) continue;

      if (_isPointInPolygon(point, points)) {
        _selectZone(zone);
        return;
      }
    }

    setState(() {
      _selectedZone = null;
    });
  }

  bool _isPointInPolygon(LatLng point, List<LatLng> polygon) {
    bool inside = false;
    int j = polygon.length - 1;

    for (int i = 0; i < polygon.length; j = i, i++) {
      if (((polygon[i].latitude > point.latitude) !=
              (polygon[j].latitude > point.latitude)) &&
          (point.longitude <
              (polygon[j].longitude - polygon[i].longitude) *
                      (point.latitude - polygon[i].latitude) /
                      (polygon[j].latitude - polygon[i].latitude) +
                  polygon[i].longitude)) {
        inside = !inside;
      }
    }

    return inside;
  }

  int get _pendingWaterRequestCount =>
      _zones.fold(0, (sum, zone) => sum + zone.pendingRequests.length);

  int get _activeZoneCount => _zones
      .where(
        (zone) => zone.status == 'in_progress' || zone.status == 'completed',
      )
      .length;

  int get _plantCount => _zones.fold(0, (sum, zone) => sum + zone.plantCount);

  void _goToWaterRequest() {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => WaterRequestScreen(zone: _selectedZone!),
      ),
    );
  }

  void _goToWorkReport() {
    final zoneCode = _selectedZone?.code;
    _popupAnimationController.reverse().then((_) {
      setState(() => _selectedZone = null);
    });
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => WorkReportFormScreen(initialZoneCode: zoneCode),
      ),
    ).then((result) {
      if (result == true) setState(() {});
    });
  }

  void _goToRequestStatus() {
    final auth = context.read<AuthProvider>();
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => RequestStatusScreen(
          isAdmin: auth.isAdmin,
          isDeptUser: auth.isDeptUser,
        ),
      ),
    );
  }

  void _goToWorkReportList() {
    final auth = context.read<AuthProvider>();
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => WorkReportListScreen(isAdmin: auth.isAdmin),
      ),
    );
  }

  void _goToDemandList() {
    final auth = context.read<AuthProvider>();
    final user = auth.user;
    if (user == null) return;
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => DemandListScreen(user: user, apiService: auth.api),
      ),
    );
  }

  void _goToSelectedZoneDetail() {
    final zone = _selectedZone;
    if (zone == null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('先在地图上选择一个区域')));
      return;
    }

    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => ZoneDetailScreen(zoneId: zone.id, zoneName: zone.name),
      ),
    );
  }

  void _focusCurrentLocation() {
    if (_currentPosition == null) {
      _getCurrentLocation();
      return;
    }
    _mapController?.move(_currentPosition!, 15);
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final isAdmin = auth.isAdmin;

    return Scaffold(
      body: _currentIndex == 0
          ? _buildMapTab()
          : _currentIndex == 1
          ? WorkReportListScreen(isAdmin: isAdmin)
          : const SettingsScreen(),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (index) => setState(() => _currentIndex = index),
        destinations: [
          const NavigationDestination(icon: Icon(Icons.map), label: '地图'),
          const NavigationDestination(
            icon: Icon(Icons.assignment),
            label: '维修日志',
          ),
          const NavigationDestination(icon: Icon(Icons.settings), label: '设置'),
        ],
      ),
    );
  }

  Widget _buildMapTab() {
    final auth = context.watch<AuthProvider>();
    final isDeptUser = auth.isDeptUser;
    final isFieldWorker = auth.isFieldWorker;

    return Stack(
      children: [
        FlutterMap(
          mapController: _mapController,
          options: MapOptions(
            initialCenter: _currentPosition ?? const LatLng(31.0, 121.6),
            initialZoom: 10,
            onTap: (tapPosition, point) => _handleMapTap(point),
          ),
          children: [
            TileLayer(
              urlTemplate:
                  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
              userAgentPackageName: 'com.maxicom.horticulture',
              maxNativeZoom: 19,
              maxZoom: 20,
            ),
            PolygonLayer(
              polygons: _zones
                  .where((z) => z.boundaryPoints.isNotEmpty)
                  .map((zone) {
                    final points = _extractPoints(zone.boundaryPoints);

                    if (points.isEmpty) return null;

                    // Use custom boundary color if set, otherwise use status color
                    Color color;
                    if (zone.boundaryColor != null &&
                        zone.boundaryColor!.isNotEmpty) {
                      try {
                        color = Color(
                          int.parse(
                            zone.boundaryColor!.replaceFirst('#', '0xFF'),
                          ),
                        );
                      } catch (_) {
                        color = _getStatusColor(zone.status);
                      }
                    } else {
                      color = _getStatusColor(zone.status);
                    }

                    final isSelected = _selectedZone?.id == zone.id;
                    return Polygon(
                      points: points,
                      color: (isSelected ? const Color(0xFFD4A574) : color)
                          .withOpacity(isSelected ? 0.4 : 0.25),
                      borderColor: isSelected ? const Color(0xFFD4A574) : color,
                      borderStrokeWidth: isSelected ? 3 : 2,
                    );
                  })
                  .whereType<Polygon>()
                  .toList(),
            ),
            // User marker
            if (_currentPosition != null)
              MarkerLayer(
                markers: [
                  Marker(
                    point: _currentPosition!,
                    width: 20,
                    height: 20,
                    child: Container(
                      decoration: BoxDecoration(
                        color: const Color(0xFFD4A574),
                        shape: BoxShape.circle,
                        border: Border.all(color: Colors.white, width: 2),
                      ),
                    ),
                  ),
                ],
              ),
            // Pending water request markers
            MarkerLayer(
              markers: _zones
                  .where(
                    (z) => z.pendingRequests.isNotEmpty && z.center != null,
                  )
                  .map(
                    (zone) => Marker(
                      point: LatLng(zone.center!['lat']!, zone.center!['lng']!),
                      width: 28,
                      height: 28,
                      child: GestureDetector(
                        onTap: () => _selectZone(zone),
                        child: Container(
                          decoration: BoxDecoration(
                            color: const Color(0xFFCC7722),
                            shape: BoxShape.circle,
                            border: Border.all(color: Colors.white, width: 2),
                            boxShadow: [
                              BoxShadow(
                                color: Colors.black.withOpacity(0.3),
                                blurRadius: 4,
                              ),
                            ],
                          ),
                          child: Center(
                            child: Text(
                              '${zone.pendingRequests.length}',
                              style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.bold,
                                fontSize: 14,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  )
                  .toList(),
            ),
            // Zone popup marker - hidden when drawer is expanded
            if (_selectedZone != null && _selectedZone!.center != null)
              MarkerLayer(
                markers: [
                  Marker(
                    point: LatLng(
                      _selectedZone!.center!['lat'] ?? 31.0,
                      _selectedZone!.center!['lng'] ?? 121.6,
                    ),
                    width: 180,
                    height: _selectedZone!.pendingRequests.isNotEmpty
                        ? 190
                        : 152,
                    child: _buildZonePopup(isDeptUser, isFieldWorker),
                  ),
                ],
              ),
          ],
        ),

        Positioned(top: 0, left: 0, right: 0, child: _buildQuickActionBar(auth)),

        _buildZoneDrawer(topOffset: 80),

        if (_isLoading)
          Container(
            color: Colors.black26,
            child: const Center(child: CircularProgressIndicator()),
          ),

        if (_error != null)
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: SafeArea(
              child: Container(
                margin: const EdgeInsets.all(8),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.errorContainer,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  children: [
                    Icon(
                      Icons.error,
                      color: Theme.of(context).colorScheme.error,
                    ),
                    const SizedBox(width: 8),
                    Expanded(child: Text(_error!)),
                    IconButton(
                      icon: const Icon(Icons.refresh),
                      onPressed: _loadData,
                    ),
                  ],
                ),
              ),
            ),
          ),

        Positioned(right: 12, bottom: 20, child: _buildMapFloatingActions()),

        // Map attribution at bottom left
        Positioned(
          bottom: 0,
          left: 0,
          child: SafeArea(
            child: Container(
              margin: const EdgeInsets.all(8),
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: Colors.white.withOpacity(0.7),
                borderRadius: BorderRadius.circular(4),
              ),
              child: const Text(
                'Esri World Imagery',
                style: TextStyle(fontSize: 10, color: Colors.black54),
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildQuickActionBar(AuthProvider auth) {
    final isDeptUser = auth.isDeptUser;
    final items = <_QuickActionItem>[];

    if (!isDeptUser) {
      items.add(_QuickActionItem(Icons.post_add_rounded, '新建工单', _goToWorkReport));
    }
    items.add(_QuickActionItem(
      isDeptUser ? Icons.water_drop : Icons.assignment_outlined,
      isDeptUser ? '浇水需求' : '维修日志',
      isDeptUser ? _goToRequestStatus : _goToWorkReportList,
    ));
    items.add(_QuickActionItem(Icons.event_note_rounded, '需求日志', _goToDemandList));
    items.add(_QuickActionItem(
      Icons.place_outlined,
      _selectedZone == null ? '选择区域' : _selectedZone!.name,
      _goToSelectedZoneDetail,
    ));

    return SafeArea(
      child: Container(
        margin: const EdgeInsets.fromLTRB(8, 8, 8, 0),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        decoration: BoxDecoration(
          color: Colors.white.withOpacity(0.92),
          borderRadius: BorderRadius.circular(12),
          boxShadow: [
            BoxShadow(color: Colors.black.withOpacity(0.1), blurRadius: 8),
          ],
        ),
        child: Row(
          children: items.map((item) => Expanded(
            child: InkWell(
              onTap: item.onTap,
              borderRadius: BorderRadius.circular(8),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(item.icon, size: 18, color: const Color(0xFF40916C)),
                    const SizedBox(height: 3),
                    Text(item.label,
                      style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w600, color: Color(0xFF1B4332)),
                      textAlign: TextAlign.center,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
            ),
          )).toList(),
        ),
      ),
    );
  }

  Widget _buildMapFloatingActions() {
    return Column(
      children: [
        FloatingActionButton.small(
          heroTag: 'map-refresh',
          onPressed: _loadData,
          child: const Icon(Icons.refresh_rounded),
        ),
        const SizedBox(height: 10),
        FloatingActionButton.small(
          heroTag: 'map-location',
          onPressed: _focusCurrentLocation,
          child: const Icon(Icons.my_location_rounded),
        ),
      ],
    );
  }

  Widget _buildZonePopup(bool isDeptUser, bool isFieldWorker) {
    final hasPendingWater = _selectedZone!.pendingRequests.isNotEmpty;

    return Material(
      color: Colors.transparent,
      child: FadeTransition(
        opacity: _popupFadeAnimation,
        child: ScaleTransition(
          scale: _popupScaleAnimation,
          child: Container(
            width: 180,
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.white.withOpacity(0.95),
              borderRadius: BorderRadius.circular(22),
              border: Border.all(color: AppColors.outline),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.16),
                  blurRadius: 24,
                  offset: const Offset(0, 12),
                ),
              ],
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Header row
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Flexible(
                      child: Text(
                        _selectedZone!.name,
                        style: const TextStyle(
                          fontWeight: FontWeight.w600,
                          fontSize: 12,
                          color: Color(0xFF1B4332),
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    GestureDetector(
                      onTap: () {
                        _popupAnimationController.reverse().then((_) {
                          setState(() => _selectedZone = null);
                        });
                      },
                      child: const Padding(
                        padding: EdgeInsets.only(left: 3),
                        child: Icon(Icons.close, size: 12, color: Colors.grey),
                      ),
                    ),
                  ],
                ),
                // Pending water request indicator
                if (hasPendingWater)
                  GestureDetector(
                    onTap: () {
                      final request = _selectedZone!.pendingRequests.first;
                      Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (_) => RequestDetailScreen(
                            typeCode: 'water',
                            requestId: request['id'],
                            typeName: '浇水协调需求',
                            zoneName: _selectedZone!.name,
                          ),
                        ),
                      );
                    },
                    child: Container(
                      margin: const EdgeInsets.only(top: 8),
                      padding: const EdgeInsets.symmetric(
                        vertical: 6,
                        horizontal: 8,
                      ),
                      decoration: BoxDecoration(
                        color: const Color(0xFFCC7722).withOpacity(0.15),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(
                            Icons.water_drop,
                            color: Color(0xFFCC7722),
                            size: 12,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            '浇水协调需求 (${_selectedZone!.pendingRequests.length})',
                            style: const TextStyle(
                              color: Color(0xFFCC7722),
                              fontSize: 10,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                const SizedBox(height: 8),
                // Zone detail button
                _buildPopupButton(
                  icon: Icons.info_outline,
                  label: '区域详情',
                  onTap: () {
                    _popupAnimationController.reverse().then((_) {
                      setState(() => _selectedZone = null);
                    });
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => ZoneDetailScreen(
                          zoneId: _selectedZone!.id,
                          zoneName: _selectedZone!.name,
                        ),
                      ),
                    );
                  },
                  color: const Color(0xFF1B4332),
                ),
                const SizedBox(height: 2),
                // Action buttons - Work Report for non-dept users
                if (!isDeptUser) ...[
                  _buildPopupButton(
                    icon: Icons.assignment,
                    label: '新建日报',
                    onTap: _goToWorkReport,
                    color: const Color(0xFF40916C),
                  ),
                  const SizedBox(height: 6),
                ],
                // Water request - all roles can submit
                _buildPopupButton(
                  icon: Icons.water_drop,
                  label: '浇水协调',
                  onTap: _goToWaterRequest,
                  color: const Color(0xFF2D6A4F),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildPopupButton({
    required IconData icon,
    required String label,
    required VoidCallback onTap,
    Color? color,
  }) {
    final btnColor = color ?? const Color(0xFF1B4332);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 10),
        decoration: BoxDecoration(
          color: btnColor.withOpacity(0.08),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, color: btnColor, size: 14),
            const SizedBox(width: 6),
            Text(
              label,
              style: TextStyle(
                color: btnColor,
                fontSize: 11,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildZoneDrawer({double topOffset = 0}) {
    // Group zones by patch
    final Map<int?, List<Zone>> zonesByPatch = {};
    final Map<int?, Map<String, dynamic>> patchInfo = {};

    for (var zone in _zones) {
      final patchId = zone.patchId;
      if (!zonesByPatch.containsKey(patchId)) {
        zonesByPatch[patchId] = [];
        if (patchId != null) {
          patchInfo[patchId] = {
            'id': patchId,
            'name': zone.patchName ?? '未知片区',
            'code': zone.patchCode ?? '',
          };
        }
      }
      zonesByPatch[patchId]!.add(zone);
    }

    // Filter zones by search query
    final filteredZonesByPatch = <int?, List<Zone>>{};
    for (var entry in zonesByPatch.entries) {
      final filtered = entry.value.where((z) {
        if (_zoneSearchQuery.isEmpty) return true;
        final query = _zoneSearchQuery.toLowerCase();
        return z.name.toLowerCase().contains(query) ||
            z.code.toLowerCase().contains(query) ||
            (z.patchName?.toLowerCase().contains(query) ?? false) ||
            (z.patchCode?.toLowerCase().contains(query) ?? false);
      }).toList();
      if (filtered.isNotEmpty) {
        filteredZonesByPatch[entry.key] = filtered;
      }
    }

    // Build ordered list of patch groups (patches first, then orphan)
    final orderedPatchIds = filteredZonesByPatch.keys.toList();
    orderedPatchIds.sort((a, b) {
      // Null (orphan) goes last
      if (a == null) return 1;
      if (b == null) return -1;
      // Sort by patch code or name
      final aCode = patchInfo[a]?['code'] ?? '';
      final bCode = patchInfo[b]?['code'] ?? '';
      return aCode.compareTo(bCode);
    });

    return Positioned(
      left: 0,
      top: topOffset,
      child: SafeArea(
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
          width: 220,
          height: _isZoneDrawerExpanded
              ? (MediaQuery.of(context).size.height - topOffset - 140).clamp(200.0, 450.0)
              : 48,
          margin: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.92),
            borderRadius: BorderRadius.circular(12),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.1),
                blurRadius: 8,
              ),
            ],
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                // Header - always visible, clickable to toggle
                InkWell(
                  onTap: () => setState(
                    () => _isZoneDrawerExpanded = !_isZoneDrawerExpanded,
                  ),
                  borderRadius: BorderRadius.circular(12),
                  child: Container(
                    height: 48,
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: Row(
                      children: [
                        Icon(
                          Icons.map,
                          size: 18,
                          color: const Color(0xFF1B4332),
                        ),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(
                            '区域 ${_zones.length}',
                            style: const TextStyle(
                              fontWeight: FontWeight.w600,
                              fontSize: 13,
                              color: const Color(0xFF1B4332),
                            ),
                          ),
                        ),
                        Icon(
                          _isZoneDrawerExpanded
                              ? Icons.expand_less
                              : Icons.expand_more,
                          color: const Color(0xFF52B788),
                        ),
                      ],
                    ),
                  ),
                ),
                // Expandable content
                if (_isZoneDrawerExpanded) ...[
                  // Search box
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 8,
                    ),
                    decoration: BoxDecoration(
                      border: Border(
                        bottom: BorderSide(color: Colors.grey.shade200),
                      ),
                    ),
                    child: TextField(
                      onChanged: (val) =>
                          setState(() => _zoneSearchQuery = val),
                      decoration: InputDecoration(
                        hintText: '搜索区域...',
                        hintStyle: TextStyle(
                          fontSize: 13,
                          color: Colors.grey.shade500,
                        ),
                        prefixIcon: const Icon(
                          Icons.search,
                          size: 16,
                          color: Colors.grey,
                        ),
                        prefixIconConstraints: const BoxConstraints(
                          minWidth: 32,
                          minHeight: 32,
                        ),
                        isDense: true,
                        contentPadding: const EdgeInsets.symmetric(vertical: 8),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(16),
                          borderSide: BorderSide(color: Colors.grey.shade300),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(16),
                          borderSide: BorderSide(color: Colors.grey.shade300),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(16),
                          borderSide: const BorderSide(
                            color: Color(0xFF52B788),
                          ),
                        ),
                      ),
                      style: const TextStyle(fontSize: 12),
                    ),
                  ),
                  // Patch groups list
                  Flexible(
                    child: Container(
                      decoration: BoxDecoration(
                        border: Border(
                          top: BorderSide(color: Colors.grey.shade200),
                        ),
                      ),
                      child: filteredZonesByPatch.isEmpty
                          ? Padding(
                              padding: const EdgeInsets.all(16),
                              child: Text(
                                _zoneSearchQuery.isEmpty ? '暂无区域' : '未找到匹配区域',
                                style: const TextStyle(
                                  color: Colors.grey,
                                  fontSize: 12,
                                ),
                              ),
                            )
                          : ListView.builder(
                              padding: const EdgeInsets.symmetric(vertical: 4),
                              itemCount: orderedPatchIds.length,
                              itemBuilder: (context, index) {
                                final patchId = orderedPatchIds[index];
                                final zones = filteredZonesByPatch[patchId]!;
                                final isOrphan = patchId == null;

                                final patchName = isOrphan
                                    ? '未分配片区'
                                    : (patchInfo[patchId]?['name'] ?? '未知片区');
                                final patchCode = isOrphan
                                    ? ''
                                    : (patchInfo[patchId]?['code'] ?? '');

                                final isExpanded = isOrphan
                                    ? _expandedOrphanGroup != null
                                    : _expandedPatchIds.contains(patchId);

                                return _buildPatchGroup(
                                  patchId: patchId,
                                  patchName: patchName,
                                  patchCode: patchCode,
                                  zones: zones,
                                  isExpanded: isExpanded,
                                  isOrphan: isOrphan,
                                );
                              },
                            ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildPatchGroup({
    required int? patchId,
    required String patchName,
    required String patchCode,
    required List<Zone> zones,
    required bool isExpanded,
    required bool isOrphan,
  }) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        // Patch header - clickable to expand/collapse
        InkWell(
          onTap: () {
            setState(() {
              if (isOrphan) {
                _expandedOrphanGroup = isExpanded ? null : -1;
              } else {
                if (isExpanded) {
                  _expandedPatchIds.remove(patchId);
                } else {
                  _expandedPatchIds.add(patchId!);
                }
              }
            });
          },
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: const Color(0xFF52B788).withOpacity(0.1),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Row(
              children: [
                Icon(
                  isExpanded ? Icons.expand_less : Icons.expand_more,
                  size: 16,
                  color: const Color(0xFF52B788),
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    patchCode.isNotEmpty
                        ? '$patchName ($patchCode)'
                        : patchName,
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: const Color(0xFF1B4332),
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 6,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: Colors.grey.shade200,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    '${zones.length}',
                    style: TextStyle(fontSize: 10, color: Colors.grey.shade600),
                  ),
                ),
              ],
            ),
          ),
        ),
        // Zones under this patch (if expanded)
        if (isExpanded) ...zones.map((zone) => _buildZoneItem(zone)),
      ],
    );
  }

  Widget _buildZoneItem(Zone zone) {
    final isSelected = _selectedZone?.id == zone.id;
    final statusColor = _getStatusColor(zone.status);

    return InkWell(
      onTap: () => _selectZone(zone),
      child: Container(
        padding: const EdgeInsets.only(
          left: 24,
          right: 12,
          top: 6,
          bottom: 6,
        ), // Indented under patch
        decoration: BoxDecoration(
          color: isSelected ? const Color(0xFF52B788).withOpacity(0.15) : null,
          border: isSelected
              ? const Border(
                  left: BorderSide(color: Color(0xFF52B788), width: 3),
                )
              : null,
        ),
        child: Row(
          children: [
            Container(
              width: 5,
              height: 5,
              decoration: BoxDecoration(
                color: statusColor,
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    zone.name,
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: isSelected
                          ? FontWeight.w600
                          : FontWeight.w500,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  Text(
                    zone.code,
                    style: TextStyle(fontSize: 9, color: Colors.grey.shade600),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _QuickActionItem {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  const _QuickActionItem(this.icon, this.label, this.onTap);
}
