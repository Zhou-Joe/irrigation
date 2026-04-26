import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../models/zone.dart';
import '../models/pipeline.dart';
import '../providers/auth_provider.dart';
import 'demand_list_screen.dart';
import 'water_request_screen.dart';
import 'request_detail_screen.dart';
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
  List<Pipeline> _pipelines = [];
  bool _isLoading = true;
  String? _error;
  MapController? _mapController;
  bool _isZoneDrawerExpanded = false;
  LatLng? _currentPosition;
  Zone? _selectedZone;
  Map<String, dynamic>? _weatherResponse;
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
          _weatherResponse = weather;
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
      final pipelines = await api.getPipelines();
      setState(() {
        _zones = zones;
        _pipelines = pipelines;
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
    return AppTheme.statusColor(status);
  }

  void _selectZone(Zone zone) {
    setState(() {
      _selectedZone = zone;
    });
    _popupAnimationController.forward(from: 0);
    _flyToZone(zone);
  }

  // Helper to extract multiple closed-loop LatLng lists from boundary points.
  // Handles: flat array of coords, or array-of-arrays where each inner array is a separate loop.
  List<List<LatLng>> _extractBoundaryLoops(List<dynamic> boundaryPoints) {
    if (boundaryPoints.isEmpty) return [];

    // Detect structure by examining the first element
    final first = boundaryPoints[0];
    if (first is List && first.isNotEmpty && first[0] is num) {
      // Flat structure — all coordinates form one single closed loop
      final List<LatLng> points = [];
      for (var item in boundaryPoints) {
        if (item is List && item.length >= 2 && item[0] is num) {
          points.add(LatLng((item[0] as num).toDouble(), (item[1] as num).toDouble()));
        }
      }
      return points.isEmpty ? [] : [points];
    }

    // Nested structure — each top-level element may be a separate closed loop
    final List<List<LatLng>> loops = [];
    for (var item in boundaryPoints) {
      final List<LatLng> loop = [];
      if (item is List) {
        for (var coord in item) {
          if (coord is List && coord.length >= 2 && coord[0] is num) {
            loop.add(LatLng((coord[0] as num).toDouble(), (coord[1] as num).toDouble()));
          } else if (coord is Map) {
            final lat = coord['lat'];
            final lng = coord['lng'];
            if (lat is num && lng is num) {
              loop.add(LatLng(lat.toDouble(), lng.toDouble()));
            }
          }
        }
        if (loop.isNotEmpty) loops.add(loop);
      } else if (item is Map) {
        final lat = item['lat'];
        final lng = item['lng'];
        if (lat is num && lng is num) {
          loop.add(LatLng(lat.toDouble(), lng.toDouble()));
        }
        if (loop.isNotEmpty) loops.add(loop);
      }
    }
    return loops;
  }

  // Helper to extract LatLng list from pipeline line_points
  List<LatLng> _extractPipelinePoints(List<dynamic> linePoints) {
    final List<LatLng> points = [];
    for (var item in linePoints) {
      if (item is List && item.length >= 2 && item[0] is num) {
        points.add(LatLng((item[0] as num).toDouble(), (item[1] as num).toDouble()));
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

  // Parse hex color string like '#CC3333' to Flutter Color
  Color _parseHexColor(String hex) {
    hex = hex.replaceFirst('#', '');
    if (hex.length == 6) hex = 'FF$hex';
    return Color(int.parse(hex, radix: 16));
  }

  void _flyToZone(Zone zone) {
    if (_mapController == null) return;

    LatLng? target;
    if (zone.center != null) {
      target = LatLng(zone.center!['lat']!, zone.center!['lng']!);
    } else if (zone.boundaryPoints.isNotEmpty) {
      final loops = _extractBoundaryLoops(zone.boundaryPoints);
      final allPoints = loops.expand((l) => l).toList();
      if (allPoints.isNotEmpty) {
        double sumLat = allPoints.fold(0.0, (sum, p) => sum + p.latitude);
        double sumLng = allPoints.fold(0.0, (sum, p) => sum + p.longitude);
        target = LatLng(sumLat / allPoints.length, sumLng / allPoints.length);
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

      final loops = _extractBoundaryLoops(zone.boundaryPoints);

      for (final points in loops) {
        if (points.isEmpty) continue;

        if (_isPointInPolygon(point, points)) {
          _selectZone(zone);
          return;
        }
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
    final zonePatchId = _selectedZone?.patchId;
    final zonePatchName = _selectedZone?.patchName;
    final zonePatchCode = _selectedZone?.patchCode;

    // Build weather summary from current weather data
    String? weatherSummary;
    if (_weatherResponse != null && _weatherResponse!['data'] is List) {
      final data = _weatherResponse!['data'] as List;
      final currentHour = _weatherResponse!['current_hour'];
      final current = data.where((e) => e['hour'] == currentHour).firstOrNull
          ?? (data.isNotEmpty ? data.first : null);
      if (current != null) {
        final temp = current['temperature']?.toStringAsFixed(1) ?? '--';
        final humidity = current['humidity'] ?? '--';
        final desc = current['weather_description'] ?? '';
        weatherSummary = '$desc ${temp}°C 湿度${humidity}%';
      }
    }

    _popupAnimationController.reverse().then((_) {
      setState(() => _selectedZone = null);
    });
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => WorkReportFormScreen(
          initialZoneCode: zoneCode,
          initialPatchId: zonePatchId,
          initialPatchName: zonePatchName,
          initialPatchCode: zonePatchCode,
          initialWeather: weatherSummary,
        ),
      ),
    ).then((result) {
      if (result == true) setState(() {});
    });
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
      body: IndexedStack(
        index: _currentIndex,
        children: [
          _buildMapTab(),
          WorkReportListScreen(isAdmin: isAdmin),
          _buildDemandLogTab(auth),
          const SettingsScreen(),
        ],
      ),
      bottomNavigationBar: _buildBottomNav(),
    );
  }

  Widget _buildBottomNav() {
    return NavigationBar(
      selectedIndex: _currentIndex,
      onDestinationSelected: (i) => setState(() => _currentIndex = i),
      indicatorColor: AppTheme.greenLight.withOpacity(0.12),
      destinations: const [
        NavigationDestination(
          icon: Icon(Icons.map_outlined),
          selectedIcon: Icon(Icons.map),
          label: '地图',
        ),
        NavigationDestination(
          icon: Icon(Icons.assignment_outlined),
          selectedIcon: Icon(Icons.assignment),
          label: '维修日志',
        ),
        NavigationDestination(
          icon: Icon(Icons.event_note_outlined),
          selectedIcon: Icon(Icons.event_note),
          label: '需求日志',
        ),
        NavigationDestination(
          icon: Icon(Icons.settings_outlined),
          selectedIcon: Icon(Icons.settings),
          label: '设置',
        ),
      ],
    );
  }

  Widget _buildDemandLogTab(AuthProvider auth) {
    final user = auth.user;
    if (user == null) return const Center(child: Text('未登录'));
    return DemandListScreen(user: user, apiService: auth.api);
  }

  Widget _buildWeatherWidget() {
    Map<String, dynamic>? current;

    if (_weatherResponse != null && _weatherResponse!['data'] is List) {
      final data = _weatherResponse!['data'] as List;
      final currentHour = _weatherResponse!['current_hour'];
      // Find the entry matching current_hour
      current = data.where((e) => e['hour'] == currentHour).firstOrNull
          ?? (data.isNotEmpty ? data.first : null);
    }

    IconData weatherIcon;
    Color iconColor;

    if (_isLoadingWeather || current == null) {
      weatherIcon = Icons.cloud_outlined;
      iconColor = AppTheme.textHint;
    } else {
      final code = current['weather_code'] ?? -1;
      if (code == 0 || code == 1) {
        weatherIcon = Icons.wb_sunny_outlined;
        iconColor = Colors.amber;
      } else if (code == 2) {
        weatherIcon = Icons.cloud_outlined;
        iconColor = AppTheme.textSecondary;
      } else if (code == 3) {
        weatherIcon = Icons.cloud;
        iconColor = AppTheme.textSecondary;
      } else if (code >= 61 && code <= 67) {
        weatherIcon = Icons.grain_outlined;
        iconColor = Colors.blue;
      } else if (code >= 71 && code <= 77) {
        weatherIcon = Icons.ac_unit;
        iconColor = Colors.lightBlue;
      } else if (code >= 95) {
        weatherIcon = Icons.thunderstorm_outlined;
        iconColor = Colors.purple;
      } else {
        weatherIcon = Icons.cloud_outlined;
        iconColor = AppTheme.textSecondary;
      }
    }

    final temp = current != null
        ? '${current['temperature']?.toStringAsFixed(1) ?? '--'}°C'
        : '--°C';

    final apiTime = _weatherResponse != null
        ? DateFormat('MM-dd HH:mm').format(DateTime.parse(
            '${_weatherResponse!['date']}T${_weatherResponse!['current_hour']}:00'))
        : DateFormat('MM-dd HH:mm').format(DateTime.now());

    return Positioned(
      right: 12,
      top: 12,
      child: SafeArea(
        child: Container(
          margin: const EdgeInsets.all(12),
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.92),
            borderRadius: BorderRadius.circular(10),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.08),
                blurRadius: 8,
              ),
            ],
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (_isLoadingWeather)
                const SizedBox(
                  width: 14, height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              else
                Icon(weatherIcon, size: 16, color: iconColor),
              const SizedBox(width: 4),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(temp,
                      style: const TextStyle(
                          fontSize: 12, fontWeight: FontWeight.w600)),
                  Text(apiTime,
                      style: TextStyle(
                          fontSize: 9, color: AppTheme.textHint)),
                ],
              ),
            ],
          ),
        ),
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
            maxZoom: 19,
            onTap: (tapPosition, point) => _handleMapTap(point),
          ),
          children: [
            TileLayer(
              urlTemplate:
                  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
              userAgentPackageName: 'com.maxicom.horticulture',
              maxNativeZoom: 19,
              maxZoom: 19,
            ),
            PolygonLayer(
              polygons: _zones
                  .where((z) => z.boundaryPoints.isNotEmpty)
                  .expand((zone) {
                    final loops = _extractBoundaryLoops(zone.boundaryPoints);
                    if (loops.isEmpty) return <Polygon>[];

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
                    return loops.map((points) => Polygon(
                      points: points,
                      color: (isSelected ? AppTheme.accent : color)
                          .withOpacity(isSelected ? 0.4 : 0.25),
                      borderColor: isSelected ? AppTheme.accent : color,
                      borderStrokeWidth: isSelected ? 3 : 2,
                    ));
                  })
                  .toList(),
            ),
            // Zone text labels on map canvas
            MarkerLayer(
              markers: _zones.where((z) => z.center != null).map((zone) {
                return Marker(
                  point: LatLng(zone.center!['lat']!, zone.center!['lng']!),
                  width: 120,
                  height: 32,
                  child: Center(
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                      decoration: BoxDecoration(
                        color: Colors.black.withOpacity(0.35),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            zone.name,
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 11,
                              fontWeight: FontWeight.w600,
                              shadows: [Shadow(color: Colors.black45, blurRadius: 3)],
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            textAlign: TextAlign.center,
                          ),
                          const SizedBox(height: 1),
                          Text(
                            zone.code,
                            style: const TextStyle(
                              color: Colors.white70,
                              fontSize: 9,
                              shadows: [Shadow(color: Colors.black45, blurRadius: 3)],
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            textAlign: TextAlign.center,
                          ),
                        ],
                      ),
                    ),
                  ),
                );
              }).toList(),
            ),
            // Pipeline rendering
            if (_pipelines.isNotEmpty)
              PolylineLayer(
                polylines: _pipelines.map((pipeline) {
                  final points = _extractPipelinePoints(pipeline.linePoints);
                  if (points.length < 2) return null;
                  return Polyline(
                    points: points,
                    color: _parseHexColor(pipeline.lineColor),
                    strokeWidth: (pipeline.lineWeight * 0.6).clamp(1.0, 5.0),
                  );
                }).whereType<Polyline>().toList(),
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
                        color: AppTheme.accent,
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
                            color: AppTheme.statusInProgress,
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
                              style: TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.bold,
                                fontSize: AppTheme.tsBody.fontSize,
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

        _buildZoneDrawer(topOffset: 12),

        _buildWeatherWidget(),

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

        Positioned(right: 12, bottom: 16, child: _buildMapFloatingActions(auth)),

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

  Widget _buildMapFloatingActions(AuthProvider auth) {
    final children = <Widget>[];
    if (!auth.isDeptUser) {
      children.add(FloatingActionButton.small(
        heroTag: 'map-new-work',
        onPressed: _goToWorkReport,
        child: const Icon(Icons.post_add_rounded),
      ));
      children.add(const SizedBox(height: 10));
    }
    children.add(FloatingActionButton.small(
      heroTag: 'map-refresh',
      onPressed: _loadData,
      child: const Icon(Icons.refresh_rounded),
    ));
    children.add(const SizedBox(height: 10));
    children.add(FloatingActionButton.small(
      heroTag: 'map-location',
      onPressed: _focusCurrentLocation,
      child: const Icon(Icons.my_location_rounded),
    ));
    return Column(children: children);
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
              borderRadius: BorderRadius.circular(AppTheme.cardRadius),
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
                          color: AppTheme.greenDarkest,
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
                        color: AppTheme.statusInProgress.withOpacity(0.15),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(
                            Icons.water_drop,
                            color: AppTheme.statusInProgress,
                            size: 12,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            '浇水协调需求 (${_selectedZone!.pendingRequests.length})',
                            style: const TextStyle(
                              color: AppTheme.statusInProgress,
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
                  color: AppTheme.greenDarkest,
                ),
                const SizedBox(height: 2),
                // Action buttons - Work Report for non-dept users
                if (!isDeptUser) ...[
                  _buildPopupButton(
                    icon: Icons.assignment,
                    label: '新建工单',
                    onTap: _goToWorkReport,
                    color: AppTheme.greenMedium,
                  ),
                ],
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
    final btnColor = color ?? AppTheme.greenDarkest;
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
          width: 180,
          height: _isZoneDrawerExpanded
              ? (MediaQuery.of(context).size.height - topOffset - 140).clamp(200.0, 400.0)
              : 38,
          margin: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.92),
            borderRadius: BorderRadius.circular(10),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.1),
                blurRadius: 8,
              ),
            ],
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(10),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                // Header - always visible, clickable to toggle
                InkWell(
                  onTap: () => setState(
                    () => _isZoneDrawerExpanded = !_isZoneDrawerExpanded,
                  ),
                  borderRadius: BorderRadius.circular(10),
                  child: Container(
                    height: 38,
                    padding: const EdgeInsets.symmetric(horizontal: 10),
                    child: Row(
                      children: [
                        Icon(
                          Icons.map,
                          size: 16,
                          color: AppTheme.greenDarkest,
                        ),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(
                            '区域 ${_zones.length}',
                            style: const TextStyle(
                              fontWeight: FontWeight.w600,
                              fontSize: 12,
                              color: AppTheme.greenDarkest,
                            ),
                          ),
                        ),
                        Icon(
                          _isZoneDrawerExpanded
                              ? Icons.expand_less
                              : Icons.expand_more,
                          color: AppTheme.greenLight,
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
                      horizontal: 12,
                      vertical: 6,
                    ),
                    decoration: BoxDecoration(
                      border: Border(
                        bottom: BorderSide(color: AppTheme.outline),
                      ),
                    ),
                    child: TextField(
                      onChanged: (val) =>
                          setState(() => _zoneSearchQuery = val),
                      decoration: InputDecoration(
                        hintText: '搜索区域...',
                        hintStyle: TextStyle(
                          fontSize: 13,
                          color: AppTheme.textSecondary,
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
                          borderSide: BorderSide(color: AppTheme.outline),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(16),
                          borderSide: BorderSide(color: AppTheme.outline),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(16),
                          borderSide: const BorderSide(
                            color: AppTheme.greenLight,
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
                          top: BorderSide(color: AppTheme.outline),
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
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: AppTheme.greenLight.withOpacity(0.1),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Row(
              children: [
                Icon(
                  isExpanded ? Icons.expand_less : Icons.expand_more,
                  size: 16,
                  color: AppTheme.greenLight,
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
                      color: AppTheme.greenDarkest,
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
                    color: AppTheme.outline,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    '${zones.length}',
                    style: TextStyle(fontSize: 10, color: AppTheme.textSecondary),
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
          left: 20,
          right: 10,
          top: 5,
          bottom: 5,
        ), // Indented under patch
        decoration: BoxDecoration(
          color: isSelected ? AppTheme.greenLight.withOpacity(0.15) : null,
          border: isSelected
              ? const Border(
                  left: BorderSide(color: AppTheme.greenLight, width: 3),
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
                    style: TextStyle(fontSize: 9, color: AppTheme.textSecondary),
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
