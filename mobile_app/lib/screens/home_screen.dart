import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';
import '../models/zone.dart';
import '../providers/auth_provider.dart';
import '../services/api_service.dart';
import 'work_log_screen.dart';
import 'report_issue_screen.dart';
import 'maintenance_screen.dart';
import 'project_support_screen.dart';
import 'request_status_screen.dart';
import 'request_detail_screen.dart';
import 'settings_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with SingleTickerProviderStateMixin {
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

  late AnimationController _popupAnimationController;
  late Animation<double> _popupScaleAnimation;
  late Animation<double> _popupFadeAnimation;

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
        return const Color(0xFF40916C);  // 已完成 - 绿色
      case 'in_progress':
        return const Color(0xFFCC7722);  // 处理中 - 橙色
      case 'canceled':
        return const Color(0xFF9B2226);  // 已取消 - 红色
      case 'delayed':
        return const Color(0xFF7B5544);  // 已延期 - 深棕色
      case 'unarranged':
        return const Color(0xFF888888);  // 未安排 - 灰色
      default:
        return const Color(0xFF52B788);
    }
  }

  void _selectZone(Zone zone) {
    setState(() {
      _selectedZone = zone;
    });
    _popupAnimationController.forward(from: 0);
  }

  void _handleMapTap(LatLng point) {
    for (final zone in _zones) {
      if (zone.boundaryPoints.isEmpty) continue;

      final points = zone.boundaryPoints.map((p) {
        if (p is List && p.length >= 2) {
          return LatLng((p[0] as num).toDouble(), (p[1] as num).toDouble());
        } else if (p is Map) {
          return LatLng(
            (p['lat'] as num).toDouble(),
            (p['lng'] as num).toDouble(),
          );
        }
        return null;
      }).whereType<LatLng>().toList();

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
      if (((polygon[i].latitude > point.latitude) != (polygon[j].latitude > point.latitude)) &&
          (point.longitude < (polygon[j].longitude - polygon[i].longitude) * (point.latitude - polygon[i].latitude) /
                  (polygon[j].latitude - polygon[i].latitude) + polygon[i].longitude)) {
        inside = !inside;
      }
    }

    return inside;
  }

  void _goToMaintenance() {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => MaintenanceScreen(zone: _selectedZone!),
      ),
    );
  }

  void _goToProjectSupport() {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => ProjectSupportScreen(zone: _selectedZone!),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: _currentIndex == 0
          ? _buildMapTab()
          : _currentIndex == 1
              ? const RequestStatusScreen()
              : const SettingsScreen(),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (index) => setState(() => _currentIndex = index),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.map), label: '地图'),
          NavigationDestination(icon: Icon(Icons.list_alt), label: '需求状态'),
          NavigationDestination(icon: Icon(Icons.settings), label: '设置'),
        ],
      ),
    );
  }

  Widget _buildMapTab() {
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
              urlTemplate: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
              userAgentPackageName: 'com.maxicom.horticulture',
            ),
            PolygonLayer(
              polygons: _zones
                  .where((z) => z.boundaryPoints.isNotEmpty)
                  .map((zone) {
                final points = zone.boundaryPoints.map((p) {
                  if (p is List && p.length >= 2) {
                    return LatLng((p[0] as num).toDouble(), (p[1] as num).toDouble());
                  } else if (p is Map) {
                    return LatLng(
                      (p['lat'] as num).toDouble(),
                      (p['lng'] as num).toDouble(),
                    );
                  }
                  return const LatLng(0, 0);
                }).where((p) => p.latitude != 0 || p.longitude != 0).toList();

                if (points.isEmpty) return null;

                // Use custom boundary color if set, otherwise use status color
                Color color;
                if (zone.boundaryColor != null && zone.boundaryColor!.isNotEmpty) {
                  try {
                    color = Color(int.parse(zone.boundaryColor!.replaceFirst('#', '0xFF')));
                  } catch (_) {
                    color = _getStatusColor(zone.status);
                  }
                } else {
                  color = _getStatusColor(zone.status);
                }

                final isSelected = _selectedZone?.id == zone.id;
                return Polygon(
                  points: points,
                  color: (isSelected ? const Color(0xFFD4A574) : color).withOpacity(isSelected ? 0.4 : 0.25),
                  borderColor: isSelected ? const Color(0xFFD4A574) : color,
                  borderStrokeWidth: isSelected ? 3 : 2,
                );
              }).whereType<Polygon>().toList(),
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
                  .where((z) => z.pendingRequests.isNotEmpty && z.center != null)
                  .map((zone) => Marker(
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
                      ))
                  .toList(),
            ),
            // Zone popup marker - on top layer
            if (_selectedZone != null && _selectedZone!.center != null)
              MarkerLayer(
                markers: [
                  Marker(
                    point: LatLng(_selectedZone!.center!['lat']!, _selectedZone!.center!['lng']!),
                    width: 135,
                    height: _selectedZone!.pendingRequests.isNotEmpty ? 100 : 85,
                    child: _buildZonePopup(),
                  ),
                ],
              ),
          ],
        ),

        _buildZoneDrawer(),

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
                    Icon(Icons.error, color: Theme.of(context).colorScheme.error),
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

        // Weather widget at top right
        if (_weatherData.isNotEmpty)
          Positioned(
            top: 0,
            right: 0,
            child: _buildWeatherPanel(),
          ),

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

  Widget _buildWeatherPanel() {
    final current = _weatherData.firstWhere(
      (w) => w['hour'] == DateTime.now().hour,
      orElse: () => _weatherData.first,
    );
    final temp = current['temperature']?.toStringAsFixed(0) ?? '--';
    final description = current['weather_description'] ?? '';

    return SafeArea(
      child: Container(
        margin: const EdgeInsets.all(8),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: Colors.white.withOpacity(0.95),
          borderRadius: BorderRadius.circular(20),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.15),
              blurRadius: 8,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              current['weather_code'] == 0 ? Icons.wb_sunny :
              current['weather_code'] != null && current['weather_code'] < 50
                  ? Icons.cloud : Icons.water_drop,
              size: 18,
              color: const Color(0xFF52B788),
            ),
            const SizedBox(width: 6),
            Text(
              '$temp°C',
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
            ),
            if (description.isNotEmpty) ...[
              const SizedBox(width: 4),
              Text(
                description,
                style: const TextStyle(fontSize: 12, color: Colors.grey),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildZonePopup() {
    final statusColor = _getStatusColor(_selectedZone!.status);
    final hasPendingWater = _selectedZone!.pendingRequests.isNotEmpty;

    return Material(
      color: Colors.transparent,
      child: FadeTransition(
        opacity: _popupFadeAnimation,
        child: ScaleTransition(
          scale: _popupScaleAnimation,
          child: Container(
            width: 135,
            padding: const EdgeInsets.all(5),
            decoration: BoxDecoration(
              color: Colors.white.withOpacity(0.92),
              borderRadius: BorderRadius.circular(12),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.2),
                  blurRadius: 8,
                  offset: const Offset(0, 2),
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
                          fontSize: 11,
                          color: Color(0xFF1B4332),
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    Container(
                      margin: const EdgeInsets.only(left: 3),
                      padding: const EdgeInsets.symmetric(horizontal: 3, vertical: 1),
                      decoration: BoxDecoration(
                        color: statusColor.withOpacity(0.2),
                        borderRadius: BorderRadius.circular(3),
                      ),
                      child: Text(
                        _selectedZone!.statusDisplay,
                        style: TextStyle(color: statusColor, fontSize: 8, fontWeight: FontWeight.w500),
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
                      margin: const EdgeInsets.only(top: 3),
                      padding: const EdgeInsets.symmetric(vertical: 2, horizontal: 4),
                      decoration: BoxDecoration(
                        color: const Color(0xFFCC7722).withOpacity(0.15),
                        borderRadius: BorderRadius.circular(3),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(Icons.water_drop, color: Color(0xFFCC7722), size: 9),
                          const SizedBox(width: 2),
                          Text(
                            '浇水协调需求 (${_selectedZone!.pendingRequests.length})',
                            style: const TextStyle(
                              color: Color(0xFFCC7722),
                              fontSize: 8,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                const SizedBox(height: 3),
                // Action buttons
                _buildPopupButton(
                  icon: Icons.build,
                  label: '维护与维修',
                  onTap: _goToMaintenance,
                ),
                const SizedBox(height: 2),
                _buildPopupButton(
                  icon: Icons.support_agent,
                  label: '项目支持',
                  onTap: _goToProjectSupport,
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
  }) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 5),
        decoration: BoxDecoration(
          color: const Color(0xFF1B4332).withOpacity(0.08),
          borderRadius: BorderRadius.circular(4),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, color: const Color(0xFF1B4332), size: 11),
            const SizedBox(width: 3),
            Text(
              label,
              style: const TextStyle(
                color: Color(0xFF1B4332),
                fontSize: 9,
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildZoneDrawer() {
    return Positioned(
      left: 0,
      top: 0,
      child: SafeArea(
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
          width: 180,
          height: _isZoneDrawerExpanded ? 400 : 56,
          margin: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.95),
            borderRadius: BorderRadius.circular(12),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.15),
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
                  onTap: () => setState(() => _isZoneDrawerExpanded = !_isZoneDrawerExpanded),
                  borderRadius: BorderRadius.circular(12),
                  child: Container(
                    height: 56,
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: Row(
                      children: [
                        Icon(Icons.map, size: 20, color: const Color(0xFF1B4332)),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            '灌溉区域',
                            style: const TextStyle(
                              fontWeight: FontWeight.w600,
                              fontSize: 14,
                              color: const Color(0xFF1B4332),
                            ),
                          ),
                        ),
                        Icon(
                          _isZoneDrawerExpanded ? Icons.expand_less : Icons.expand_more,
                          color: const Color(0xFF52B788),
                        ),
                      ],
                    ),
                  ),
                ),
                // Expandable list
                if (_isZoneDrawerExpanded)
                  Flexible(
                    child: Container(
                      decoration: BoxDecoration(
                        border: Border(top: BorderSide(color: Colors.grey.shade200)),
                      ),
                      child: _zones.isEmpty
                          ? const Padding(
                              padding: EdgeInsets.all(16),
                              child: Text('暂无区域', style: TextStyle(color: Colors.grey)),
                            )
                          : ListView.builder(
                              padding: const EdgeInsets.symmetric(vertical: 4),
                              itemCount: _zones.length,
                              itemBuilder: (context, index) => _buildZoneItem(_zones[index]),
                            ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildZoneItem(Zone zone) {
    final isSelected = _selectedZone?.id == zone.id;
    final statusColor = _getStatusColor(zone.status);

    return InkWell(
      onTap: () => _selectZone(zone),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: isSelected ? const Color(0xFF52B788).withOpacity(0.15) : null,
          border: isSelected
              ? const Border(left: BorderSide(color: Color(0xFF52B788), width: 3))
              : null,
        ),
        child: Row(
          children: [
            Container(
              width: 6,
              height: 6,
              decoration: BoxDecoration(
                color: statusColor,
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                zone.name,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: isSelected ? FontWeight.w600 : FontWeight.normal,
                ),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
      ),
    );
  }
}