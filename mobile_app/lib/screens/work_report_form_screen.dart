import 'dart:typed_data';
import 'dart:math';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import 'package:image_picker/image_picker.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';
import '../providers/auth_provider.dart';
import '../models/zone.dart';
import '../widgets/modern_ui.dart';

class WorkReportFormScreen extends StatefulWidget {
  final Map<String, dynamic>? existingReport;
  final String? initialZoneCode;

  const WorkReportFormScreen({
    super.key,
    this.existingReport,
    this.initialZoneCode,
  });

  @override
  State<WorkReportFormScreen> createState() => _WorkReportFormScreenState();
}

class _WorkReportFormScreenState extends State<WorkReportFormScreen> {
  final _formKey = GlobalKey<FormState>();
  final _weatherController = TextEditingController();
  final _zoneLocationController = TextEditingController();
  final _remarkController = TextEditingController();
  bool _isLoading = false;
  bool _isSaving = false;
  bool _isDifficult = false;
  bool _isDifficultResolved = false;
  bool _isLoadingEquipment = false;

  late DateTime _date;

  // Dropdown data
  List<Map<String, dynamic>> _locations = [];
  List<Map<String, dynamic>> _workCategories = [];
  List<Map<String, dynamic>> _infoSources = [];
  List<Map<String, dynamic>> _faultCategories = [];
  List<Map<String, dynamic>> _zoneEquipment = [];

  int? _selectedLocation;
  int? _selectedWorkCategory;
  int? _selectedInfoSource;

  // Fault counts: subTypeId -> count
  final Map<int, int> _faultCounts = {};
  // Equipment per fault: subTypeId -> equipmentId (nullable)
  final Map<int, int?> _faultEquipment = {};
  // Subtype info cache: subTypeId -> {name_zh, catName}
  final Map<int, Map<String, String>> _subtypeInfo = {};

  // Photos
  final List<XFile> _selectedPhotos = [];
  List<String> _existingPhotoUrls = [];
  final ImagePicker _imagePicker = ImagePicker();

  // Zone picker data
  List<Zone> _allZones = [];
  Zone? _selectedZone;
  LatLng? _userLocation;
  bool get _isEditing => widget.existingReport != null;

  @override
  void initState() {
    super.initState();
    _date = DateTime.now();

    if (_isEditing) {
      final r = widget.existingReport!;
      _date = DateTime.tryParse(r['date'] ?? '') ?? DateTime.now();
      _weatherController.text = r['weather'] ?? '';
      _zoneLocationController.text = r['zone_location_display'] ?? '';
      _remarkController.text = r['remark'] ?? '';
      _isDifficult = r['is_difficult'] ?? false;
      _isDifficultResolved = r['is_difficult_resolved'] ?? false;
      _selectedLocation = r['location'] is Map
          ? r['location']['id']
          : r['location'];
      _selectedWorkCategory = r['work_category'] is Map
          ? r['work_category']['id']
          : r['work_category'];
      if (r['info_source'] != null) {
        _selectedInfoSource = r['info_source'] is Map
            ? r['info_source']['id']
            : r['info_source'];
      }
      // Load existing fault entries
      if (r['fault_entries'] is List) {
        for (var entry in r['fault_entries']) {
          final subId = entry['fault_subtype'] is Map
              ? entry['fault_subtype']['id']
              : entry['fault_subtype'];
          final count = entry['count'] ?? 0;
          if (count > 0) {
            _faultCounts[subId] = count;
            // Load equipment if present
            final equipId = entry['equipment'] is Map
                ? entry['equipment']['id']
                : entry['equipment'];
            _faultEquipment[subId] = equipId;
          }
        }
      }
      // Load existing photo URLs
      _existingPhotoUrls = List<String>.from(r['photo_urls'] ?? []);
    } else if (widget.initialZoneCode != null) {
      _zoneLocationController.text = widget.initialZoneCode!;
    }

    _loadDropdownData();
  }

  Future<void> _loadDropdownData() async {
    setState(() => _isLoading = true);
    try {
      final api = context.read<AuthProvider>().api;
      final locFuture = api.getLocations();
      final wcFuture = api.getWorkCategories();
      final isFuture = api.getInfoSources();
      final fcFuture = api.getFaultCategories();
      final zoneFuture = api.getZones();

      final locations = await locFuture;
      final workCategories = await wcFuture;
      final infoSources = await isFuture;
      final faultCategories = await fcFuture;
      final zones = await zoneFuture;

      // Try to get user location for distance sorting
      _getUserLocation();

      if (mounted) {
        setState(() {
          _locations = locations;
          _workCategories = workCategories;
          _infoSources = infoSources;
          _faultCategories = faultCategories;
          _allZones = zones;
          _isLoading = false;
        });

        // Pre-select zone if initialZoneCode is set
        if (!_isEditing && widget.initialZoneCode != null) {
          final match = _allZones
              .where((z) => z.code == widget.initialZoneCode)
              .firstOrNull;
          if (match != null) {
            _selectedZone = match;
            _zoneLocationController.text = match.code;
          }
        }
        // Pre-select zone when editing
        if (_isEditing && _zoneLocationController.text.isNotEmpty) {
          final match = _allZones
              .where((z) => z.code == _zoneLocationController.text)
              .firstOrNull;
          if (match != null) _selectedZone = match;
        }

        // Build subtype info cache
        for (var cat in _faultCategories) {
          final catName = cat['name_zh'] ?? '';
          for (var sub in (cat['sub_types'] as List? ?? [])) {
            _subtypeInfo[sub['id']] = {
              'name_zh': sub['name_zh'] ?? '',
              'catName': catName,
            };
          }
        }

        // Load equipment if zone code is set
        if (_zoneLocationController.text.isNotEmpty) {
          _loadZoneEquipment(_zoneLocationController.text);
        }
      }
    } catch (e) {
      if (mounted) setState(() => _isLoading = false);
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('加载数据失败: $e')));
      }
    }
  }

  Future<void> _loadZoneEquipment(String zoneCode) async {
    if (zoneCode.isEmpty) {
      setState(() => _zoneEquipment = []);
      return;
    }

    setState(() => _isLoadingEquipment = true);
    try {
      final api = context.read<AuthProvider>().api;
      final equipment = await api.getZoneEquipment(zoneCode);
      if (mounted) {
        setState(() {
          _zoneEquipment = equipment;
          _isLoadingEquipment = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _zoneEquipment = [];
          _isLoadingEquipment = false;
        });
      }
    }
  }

  Future<void> _selectDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _date,
      firstDate: DateTime.now().subtract(const Duration(days: 90)),
      lastDate: DateTime.now().add(const Duration(days: 7)),
    );
    if (picked != null) setState(() => _date = picked);
  }

  List<Map<String, dynamic>> _getFaultEntries() {
    return _faultCounts.entries
        .where((e) => e.value > 0)
        .map(
          (e) => {
            'fault_subtype': e.key,
            'count': e.value,
            if (_faultEquipment[e.key] != null)
              'equipment': _faultEquipment[e.key],
          },
        )
        .toList();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    if (_selectedLocation == null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('请选择位置/CCU')));
      return;
    }
    if (_selectedWorkCategory == null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('请选择工作分类')));
      return;
    }

    final faultEntries = _getFaultEntries();
    if (faultEntries.isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('请至少填写一个故障计数')));
      return;
    }

    setState(() => _isSaving = true);

    try {
      final api = context.read<AuthProvider>().api;
      final dateStr = DateFormat('yyyy-MM-dd').format(_date);
      final params = (
        date: dateStr,
        weather: _weatherController.text.trim(),
        location: _selectedLocation!,
        workCategory: _selectedWorkCategory!,
        zoneLocation: _zoneLocationController.text.trim(),
        remark: _remarkController.text.trim(),
        infoSource: _selectedInfoSource,
        isDifficult: _isDifficult,
        isDifficultResolved: _isDifficultResolved,
        faultEntries: faultEntries,
      );

      if (_isEditing) {
        await api.updateWorkReport(
          id: widget.existingReport!['id'],
          date: params.date,
          weather: params.weather,
          location: params.location,
          workCategory: params.workCategory,
          zoneLocation: params.zoneLocation,
          remark: params.remark,
          infoSource: params.infoSource,
          isDifficult: params.isDifficult,
          isDifficultResolved: params.isDifficultResolved,
          faultEntries: params.faultEntries,
        );
        // Upload new photos
        if (_selectedPhotos.isNotEmpty) {
          await api.uploadWorkReportPhotos(
            reportId: widget.existingReport!['id'],
            files: _selectedPhotos,
          );
        }
      } else {
        final result = await api.submitWorkReport(
          date: params.date,
          weather: params.weather,
          location: params.location,
          workCategory: params.workCategory,
          zoneLocation: params.zoneLocation,
          remark: params.remark,
          infoSource: params.infoSource,
          isDifficult: params.isDifficult,
          isDifficultResolved: params.isDifficultResolved,
          faultEntries: params.faultEntries,
        );
        // Upload photos after creation
        if (_selectedPhotos.isNotEmpty) {
          await api.uploadWorkReportPhotos(
            reportId: result['id'],
            files: _selectedPhotos,
          );
        }
      }

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(_isEditing ? '保存成功' : '提交成功'),
            backgroundColor: const Color(0xFF40916C),
          ),
        );
        Navigator.pop(context, true);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(_isEditing ? '保存失败: $e' : '提交失败: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _isSaving = false);
    }
  }

  String _getEquipmentName(int? equipId) {
    if (equipId == null) return '-- 不选 --';
    final equip = _zoneEquipment.where((e) => e['id'] == equipId).firstOrNull;
    if (equip == null) return '设备 #$equipId';
    final details = equip['equipment_details'] as Map<String, dynamic>?;
    final modelName = details?['model_name'] ?? '';
    final type =
        details?['equipment_type_display'] ?? details?['equipment_type'] ?? '';
    return '$type: $modelName';
  }

  Widget _buildAddedFaultChips() {
    final entries = _faultCounts.entries.where((e) => e.value > 0).toList();
    if (entries.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 8),
        child: Text(
          '暂无故障记录，点击下方按钮添加',
          style: TextStyle(color: Colors.grey, fontSize: 13),
        ),
      );
    }
    return Column(
      children: entries.map((entry) {
        final info =
            _subtypeInfo[entry.key] ?? {'name_zh': '?', 'catName': '?'};
        final equipId = _faultEquipment[entry.key];
        return Container(
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: const Color(0xFF40916C).withOpacity(0.06),
            border: Border.all(color: const Color(0xFFB7E4C7)),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          info['catName']!,
                          style: const TextStyle(
                            fontSize: 10,
                            color: Colors.grey,
                          ),
                        ),
                        Text(
                          info['name_zh']!,
                          style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ],
                    ),
                  ),
                  SizedBox(
                    width: 50,
                    child: TextFormField(
                      initialValue: entry.value.toString(),
                      keyboardType: TextInputType.number,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: Color(0xFF40916C),
                      ),
                      decoration: const InputDecoration(
                        isDense: true,
                        contentPadding: EdgeInsets.symmetric(vertical: 4),
                        border: OutlineInputBorder(),
                        focusedBorder: OutlineInputBorder(
                          borderSide: BorderSide(color: Color(0xFF40916C)),
                        ),
                      ),
                      onChanged: (val) {
                        final parsed = int.tryParse(val) ?? 0;
                        setState(() {
                          if (parsed > 0) {
                            _faultCounts[entry.key] = parsed;
                          } else {
                            _faultCounts.remove(entry.key);
                            _faultEquipment.remove(entry.key);
                          }
                        });
                      },
                    ),
                  ),
                  const SizedBox(width: 4),
                  GestureDetector(
                    onTap: () => setState(() {
                      _faultCounts.remove(entry.key);
                      _faultEquipment.remove(entry.key);
                    }),
                    child: const Icon(
                      Icons.close,
                      size: 18,
                      color: Colors.grey,
                    ),
                  ),
                ],
              ),
              if (_zoneEquipment.isNotEmpty || _isLoadingEquipment) ...[
                const SizedBox(height: 8),
                Row(
                  children: [
                    const Icon(
                      Icons.settings_input_component,
                      size: 14,
                      color: Colors.grey,
                    ),
                    const SizedBox(width: 4),
                    Expanded(
                      child: DropdownButton<int?>(
                        value: equipId,
                        isExpanded: true,
                        hint: const Text(
                          '关联设备',
                          style: TextStyle(fontSize: 12, color: Colors.grey),
                        ),
                        style: const TextStyle(
                          fontSize: 12,
                          color: Colors.black87,
                        ),
                        underline: Container(
                          height: 1,
                          color: Colors.grey.shade300,
                        ),
                        items: [
                          const DropdownMenuItem<int?>(
                            value: null,
                            child: Text(
                              '-- 不选 --',
                              style: TextStyle(fontSize: 12),
                            ),
                          ),
                          ..._zoneEquipment.map(
                            (e) => DropdownMenuItem<int?>(
                              value: e['id'],
                              child: Text(
                                _getEquipmentName(e['id']),
                                style: const TextStyle(fontSize: 12),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ),
                        ],
                        onChanged: (v) =>
                            setState(() => _faultEquipment[entry.key] = v),
                      ),
                    ),
                    if (_isLoadingEquipment)
                      const SizedBox(
                        width: 12,
                        height: 12,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                  ],
                ),
              ],
            ],
          ),
        );
      }).toList(),
    );
  }

  Future<void> _getUserLocation() async {
    try {
      bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) return;
      LocationPermission permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
        if (permission == LocationPermission.denied) return;
      }
      if (permission == LocationPermission.deniedForever) return;
      final pos = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.medium,
      );
      if (mounted) {
        setState(() => _userLocation = LatLng(pos.latitude, pos.longitude));
      }
    } catch (_) {}
  }

  double? _zoneDistance(Zone zone) {
    if (_userLocation == null) return null;
    final center = zone.center;
    if (center == null) return null;
    final lat1 = _userLocation!.latitude * pi / 180;
    final lng1 = _userLocation!.longitude * pi / 180;
    final lat2 = center['lat']! * pi / 180;
    final lng2 = center['lng']! * pi / 180;
    final dLat = lat2 - lat1;
    final dLng = lng2 - lng1;
    final a =
        sin(dLat / 2) * sin(dLat / 2) +
        cos(lat1) * cos(lat2) * sin(dLng / 2) * sin(dLng / 2);
    return 6371000 * 2 * atan2(sqrt(a), sqrt(1 - a)); // meters
  }

  void _openZonePicker() {
    // Group zones by patch
    final Map<int?, List<Zone>> zonesByPatch = {};
    final Map<int?, String> patchNames = {};

    for (var zone in _allZones) {
      final patchId = zone.patchId;
      zonesByPatch.putIfAbsent(patchId, () => []).add(zone);
      if (patchId != null && !patchNames.containsKey(patchId)) {
        patchNames[patchId] = zone.patchName ?? '未知片区';
      }
    }

    // Sort zones within each patch by distance
    for (var zones in zonesByPatch.values) {
      zones.sort((a, b) {
        final da = _zoneDistance(a);
        final db = _zoneDistance(b);
        if (da == null && db == null) return 0;
        if (da == null) return 1;
        if (db == null) return -1;
        return da.compareTo(db);
      });
    }

    // Order: patches first, orphan last
    final orderedKeys = zonesByPatch.keys.toList()
      ..sort((a, b) {
        if (a == null) return 1;
        if (b == null) return -1;
        return (patchNames[a] ?? '').compareTo(patchNames[b] ?? '');
      });

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => _ZonePickerSheet(
        zonesByPatch: zonesByPatch,
        patchNames: patchNames,
        orderedKeys: orderedKeys,
        userLocation: _userLocation,
        selectedZone: _selectedZone,
        onSelected: (zone) {
          Navigator.pop(context);
          setState(() {
            _selectedZone = zone;
            _zoneLocationController.text = zone.code;
          });
          _loadZoneEquipment(zone.code);
        },
      ),
    );
  }

  void _openFaultPicker() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => _FaultPickerSheet(
        faultCategories: _faultCategories,
        faultCounts: Map.from(_faultCounts),
        onSelected: (subId, catName, subName) {
          setState(() {
            _faultCounts[subId] = (_faultCounts[subId] ?? 0) + 1;
            _subtypeInfo[subId] = {'name_zh': subName, 'catName': catName};
          });
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(
          _isEditing ? '编辑日报 #${widget.existingReport!['id']}' : '新建维修工作日报',
        ),
      ),
      body: AppBackground(
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : Form(
                key: _formKey,
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
                  children: [
                    AppHeroCard(
                      title: _isEditing ? '编辑维修工作日报' : '新建维修工作日报',
                      subtitle: '把基础信息、故障计数和照片整理成更清晰的日报。',
                      icon: Icons.assignment_turned_in_outlined,
                    ),
                    const SizedBox(height: 16),
                    AppCard(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const AppSectionTitle(
                            title: '基本信息',
                            subtitle: '先确认日期、位置、分类与工作内容',
                          ),
                          const SizedBox(height: 12),

                          // Date + Weather
                          Row(
                            children: [
                              Expanded(
                                child: InkWell(
                                  onTap: _selectDate,
                                  child: InputDecorator(
                                    decoration: const InputDecoration(
                                      labelText: '日期 *',
                                      border: OutlineInputBorder(),
                                      prefixIcon: Icon(
                                        Icons.calendar_today,
                                        size: 18,
                                      ),
                                    ),
                                    child: Text(
                                      DateFormat('yyyy-MM-dd').format(_date),
                                    ),
                                  ),
                                ),
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: TextFormField(
                                  controller: _weatherController,
                                  decoration: const InputDecoration(
                                    labelText: '天气',
                                    border: OutlineInputBorder(),
                                    prefixIcon: Icon(Icons.wb_cloudy, size: 18),
                                  ),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 12),

                          // Location + Work Category
                          Row(
                            children: [
                              Expanded(
                                child: DropdownButtonFormField<int>(
                                  value: _selectedLocation,
                                  decoration: const InputDecoration(
                                    labelText: '位置/CCU *',
                                    border: OutlineInputBorder(),
                                    prefixIcon: Icon(
                                      Icons.location_on,
                                      size: 18,
                                    ),
                                  ),
                                  items: _locations
                                      .map<DropdownMenuItem<int>>(
                                        (loc) => DropdownMenuItem<int>(
                                          value: loc['id'],
                                          child: Text(
                                            loc['name'],
                                            overflow: TextOverflow.ellipsis,
                                          ),
                                        ),
                                      )
                                      .toList(),
                                  onChanged: (v) =>
                                      setState(() => _selectedLocation = v),
                                ),
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: DropdownButtonFormField<int>(
                                  value: _selectedWorkCategory,
                                  decoration: const InputDecoration(
                                    labelText: '工作分类 *',
                                    border: OutlineInputBorder(),
                                    prefixIcon: Icon(Icons.category, size: 18),
                                  ),
                                  items: _workCategories
                                      .map<DropdownMenuItem<int>>(
                                        (cat) => DropdownMenuItem<int>(
                                          value: cat['id'],
                                          child: Text(
                                            cat['name'],
                                            overflow: TextOverflow.ellipsis,
                                          ),
                                        ),
                                      )
                                      .toList(),
                                  onChanged: (v) =>
                                      setState(() => _selectedWorkCategory = v),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 12),

                          // Zone Location + Info Source
                          Row(
                            children: [
                              Expanded(
                                child: InkWell(
                                  onTap: _allZones.isEmpty
                                      ? null
                                      : _openZonePicker,
                                  child: InputDecorator(
                                    decoration: const InputDecoration(
                                      labelText: '故障/事件位置',
                                      border: OutlineInputBorder(),
                                      prefixIcon: Icon(Icons.place, size: 18),
                                    ),
                                    child: Text(
                                      _selectedZone != null
                                          ? '${_selectedZone!.name} (${_selectedZone!.code})'
                                          : '点击选择区域',
                                      style: TextStyle(
                                        fontSize: 14,
                                        color: _selectedZone != null
                                            ? Colors.black87
                                            : Colors.grey,
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: DropdownButtonFormField<int>(
                                  value: _selectedInfoSource,
                                  decoration: const InputDecoration(
                                    labelText: '信息来源',
                                    border: OutlineInputBorder(),
                                    prefixIcon: Icon(
                                      Icons.info_outline,
                                      size: 18,
                                    ),
                                  ),
                                  items: [
                                    const DropdownMenuItem<int>(
                                      value: null,
                                      child: Text('-- 不选 --'),
                                    ),
                                    ..._infoSources.map<DropdownMenuItem<int>>(
                                      (src) => DropdownMenuItem<int>(
                                        value: src['id'],
                                        child: Text(
                                          src['name'],
                                          overflow: TextOverflow.ellipsis,
                                        ),
                                      ),
                                    ),
                                  ],
                                  onChanged: (v) =>
                                      setState(() => _selectedInfoSource = v),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 12),

                          // Remark
                          TextFormField(
                            controller: _remarkController,
                            decoration: const InputDecoration(
                              labelText: '备注/工作内容 *',
                              border: OutlineInputBorder(),
                              prefixIcon: Icon(Icons.description, size: 18),
                            ),
                            maxLines: 3,
                            validator: (v) =>
                                v?.trim().isEmpty == true ? '请填写工作内容' : null,
                          ),
                          const SizedBox(height: 12),

                          // Difficult toggles
                          Row(
                            children: [
                              Expanded(
                                child: CheckboxListTile(
                                  value: _isDifficult,
                                  onChanged: (v) => setState(() {
                                    _isDifficult = v ?? false;
                                    if (!_isDifficult)
                                      _isDifficultResolved = false;
                                  }),
                                  title: const Text(
                                    '疑难问题',
                                    style: TextStyle(fontSize: 14),
                                  ),
                                  contentPadding: EdgeInsets.zero,
                                  controlAffinity:
                                      ListTileControlAffinity.leading,
                                  dense: true,
                                ),
                              ),
                              Expanded(
                                child: CheckboxListTile(
                                  value: _isDifficultResolved,
                                  onChanged: _isDifficult
                                      ? (v) => setState(
                                          () =>
                                              _isDifficultResolved = v ?? false,
                                        )
                                      : null,
                                  title: const Text(
                                    '疑难已处理',
                                    style: TextStyle(fontSize: 14),
                                  ),
                                  contentPadding: EdgeInsets.zero,
                                  controlAffinity:
                                      ListTileControlAffinity.leading,
                                  dense: true,
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 20),

                          // Fault counts section
                          _buildSectionTitle('故障计数'),
                          const SizedBox(height: 8),

                          // Added fault chips
                          _buildAddedFaultChips(),

                          const SizedBox(height: 8),

                          // Add fault button
                          OutlinedButton.icon(
                            onPressed: _openFaultPicker,
                            icon: const Icon(Icons.add, size: 18),
                            label: const Text('添加故障'),
                            style: OutlinedButton.styleFrom(
                              foregroundColor: const Color(0xFF40916C),
                              side: const BorderSide(color: Color(0xFFB7E4C7)),
                              padding: const EdgeInsets.symmetric(vertical: 12),
                            ),
                          ),

                          const SizedBox(height: 24),

                          // Photos section
                          _buildSectionTitle('照片'),
                          const SizedBox(height: 8),
                          _buildPhotoSection(),

                          const SizedBox(height: 24),

                          // Submit button
                          FilledButton.icon(
                            onPressed: _isSaving ? null : _submit,
                            icon: _isSaving
                                ? const SizedBox(
                                    width: 20,
                                    height: 20,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: Colors.white,
                                    ),
                                  )
                                : Icon(_isEditing ? Icons.save : Icons.send),
                            label: Text(
                              _isSaving
                                  ? (_isEditing ? '保存中...' : '提交中...')
                                  : (_isEditing ? '保存修改' : '创建日报'),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
      ),
    );
  }

  Widget _buildPhotoSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Existing photos (when editing)
        if (_existingPhotoUrls.isNotEmpty)
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: _existingPhotoUrls
                .map((url) => _buildExistingPhotoThumb(url))
                .toList(),
          ),
        // Newly selected photos
        if (_selectedPhotos.isNotEmpty)
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: _selectedPhotos
                .asMap()
                .entries
                .map((e) => _buildNewPhotoThumb(e.key, e.value))
                .toList(),
          ),
        const SizedBox(height: 8),
        // Add photo buttons
        Row(
          children: [
            OutlinedButton.icon(
              onPressed: _pickFromCamera,
              icon: const Icon(Icons.camera_alt, size: 18),
              label: const Text('拍照'),
              style: OutlinedButton.styleFrom(
                foregroundColor: const Color(0xFF40916C),
                side: const BorderSide(color: Color(0xFFB7E4C7)),
              ),
            ),
            const SizedBox(width: 8),
            OutlinedButton.icon(
              onPressed: _pickFromGallery,
              icon: const Icon(Icons.photo_library, size: 18),
              label: const Text('相册'),
              style: OutlinedButton.styleFrom(
                foregroundColor: const Color(0xFF40916C),
                side: const BorderSide(color: Color(0xFFB7E4C7)),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildExistingPhotoThumb(String url) {
    return Stack(
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: Image.network(
            url,
            width: 80,
            height: 80,
            fit: BoxFit.cover,
            errorBuilder: (_, __, ___) => Container(
              width: 80,
              height: 80,
              color: Colors.grey.shade200,
              child: const Icon(Icons.broken_image, color: Colors.grey),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildNewPhotoThumb(int index, XFile file) {
    return Stack(
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: FutureBuilder<Uint8List>(
            future: file.readAsBytes(),
            builder: (_, snapshot) {
              if (snapshot.hasData) {
                return Image.memory(
                  snapshot.data!,
                  width: 80,
                  height: 80,
                  fit: BoxFit.cover,
                );
              }
              return Container(
                width: 80,
                height: 80,
                color: Colors.grey.shade200,
                child: const Center(
                  child: SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                ),
              );
            },
          ),
        ),
        Positioned(
          top: -4,
          right: -4,
          child: GestureDetector(
            onTap: () => setState(() => _selectedPhotos.removeAt(index)),
            child: Container(
              padding: const EdgeInsets.all(2),
              decoration: const BoxDecoration(
                color: Colors.red,
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.close, size: 14, color: Colors.white),
            ),
          ),
        ),
      ],
    );
  }

  Future<void> _pickFromCamera() async {
    try {
      final photo = await _imagePicker.pickImage(
        source: ImageSource.camera,
        maxWidth: 1920,
        maxHeight: 1920,
        imageQuality: 85,
      );
      if (photo != null) {
        setState(() => _selectedPhotos.add(photo));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('无法访问相机: $e')));
      }
    }
  }

  Future<void> _pickFromGallery() async {
    try {
      final photos = await _imagePicker.pickMultiImage(
        maxWidth: 1920,
        maxHeight: 1920,
        imageQuality: 85,
      );
      if (photos.isNotEmpty) {
        setState(() => _selectedPhotos.addAll(photos));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('无法访问相册: $e')));
      }
    }
  }

  Widget _buildSectionTitle(String title) {
    return Text(
      title,
      style: const TextStyle(
        fontSize: 16,
        fontWeight: FontWeight.bold,
        color: Color(0xFF1B4332),
      ),
    );
  }

  @override
  void dispose() {
    _weatherController.dispose();
    _zoneLocationController.dispose();
    _remarkController.dispose();
    super.dispose();
  }
}

class _FaultPickerSheet extends StatefulWidget {
  final List<Map<String, dynamic>> faultCategories;
  final Map<int, int> faultCounts;
  final void Function(int subId, String catName, String subName) onSelected;

  const _FaultPickerSheet({
    required this.faultCategories,
    required this.faultCounts,
    required this.onSelected,
  });

  @override
  State<_FaultPickerSheet> createState() => _FaultPickerSheetState();
}

class _FaultPickerSheetState extends State<_FaultPickerSheet> {
  Map<String, dynamic>? _selectedCategory;

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.6,
      maxChildSize: 0.85,
      minChildSize: 0.3,
      expand: false,
      builder: (ctx, scrollController) => Column(
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: Color(0xFFE8E8E8))),
            ),
            child: Row(
              children: [
                if (_selectedCategory != null)
                  TextButton(
                    onPressed: () => setState(() => _selectedCategory = null),
                    child: const Text('← 返回'),
                  ),
                Expanded(
                  child: Text(
                    _selectedCategory?['name_zh'] ?? '选择故障大类',
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                    ),
                    textAlign: _selectedCategory == null
                        ? TextAlign.left
                        : TextAlign.center,
                  ),
                ),
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('关闭'),
                ),
              ],
            ),
          ),
          Expanded(
            child: _selectedCategory == null
                ? _buildCategoryList(scrollController)
                : _buildSubtypeList(scrollController),
          ),
        ],
      ),
    );
  }

  Widget _buildCategoryList(ScrollController controller) {
    return ListView.builder(
      controller: controller,
      itemCount: widget.faultCategories.length,
      itemBuilder: (ctx, i) {
        final cat = widget.faultCategories[i];
        final subs = cat['sub_types'] as List? ?? [];
        int catTotal = 0;
        for (var sub in subs) {
          catTotal += widget.faultCounts[sub['id']] ?? 0;
        }
        return ListTile(
          title: Text(
            cat['name_zh'] ?? '',
            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500),
          ),
          subtitle:
              cat['name_en'] != null && (cat['name_en'] as String).isNotEmpty
              ? Text(
                  cat['name_en'],
                  style: TextStyle(fontSize: 11, color: Colors.grey.shade500),
                )
              : null,
          trailing: catTotal > 0
              ? Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFF40916C).withOpacity(0.15),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    '$catTotal',
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: Color(0xFF40916C),
                    ),
                  ),
                )
              : null,
          onTap: () => setState(() => _selectedCategory = cat),
        );
      },
    );
  }

  Widget _buildSubtypeList(ScrollController controller) {
    final subs = (_selectedCategory!['sub_types'] as List? ?? []);
    final catName = _selectedCategory!['name_zh'] ?? '';
    return ListView.builder(
      controller: controller,
      itemCount: subs.length,
      itemBuilder: (ctx, i) {
        final sub = subs[i];
        final subId = sub['id'];
        final count = widget.faultCounts[subId] ?? 0;
        return ListTile(
          title: Text(
            sub['name_zh'] ?? '',
            style: const TextStyle(fontSize: 14),
          ),
          subtitle:
              sub['name_en'] != null && (sub['name_en'] as String).isNotEmpty
              ? Text(
                  sub['name_en'],
                  style: TextStyle(fontSize: 11, color: Colors.grey.shade500),
                )
              : null,
          trailing: count > 0
              ? Text(
                  'x$count ✓',
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: Color(0xFF40916C),
                  ),
                )
              : null,
          onTap: () {
            widget.onSelected(subId, catName, sub['name_zh'] ?? '');
            Navigator.pop(context);
          },
        );
      },
    );
  }
}

// Zone picker bottom sheet with search, patch grouping, distance sorting
class _ZonePickerSheet extends StatefulWidget {
  final Map<int?, List<Zone>> zonesByPatch;
  final Map<int?, String> patchNames;
  final List<int?> orderedKeys;
  final LatLng? userLocation;
  final Zone? selectedZone;
  final void Function(Zone) onSelected;

  const _ZonePickerSheet({
    required this.zonesByPatch,
    required this.patchNames,
    required this.orderedKeys,
    this.userLocation,
    this.selectedZone,
    required this.onSelected,
  });

  @override
  State<_ZonePickerSheet> createState() => _ZonePickerSheetState();
}

class _ZonePickerSheetState extends State<_ZonePickerSheet> {
  String _search = '';
  final Set<int?> _expanded = {};

  String _fmtDist(double meters) {
    if (meters < 1000) return '${meters.round()}m';
    return '${(meters / 1000).toStringAsFixed(1)}km';
  }

  List<int?> get _filteredKeys {
    if (_search.isEmpty) return widget.orderedKeys;
    final q = _search.toLowerCase();
    return widget.orderedKeys.where((key) {
      final zones = widget.zonesByPatch[key]!;
      return zones.any(
        (z) =>
            z.name.toLowerCase().contains(q) ||
            z.code.toLowerCase().contains(q) ||
            (z.patchName?.toLowerCase().contains(q) ?? false),
      );
    }).toList();
  }

  List<Zone> _filteredZones(List<Zone> zones) {
    if (_search.isEmpty) return zones;
    final q = _search.toLowerCase();
    return zones
        .where(
          (z) =>
              z.name.toLowerCase().contains(q) ||
              z.code.toLowerCase().contains(q) ||
              (z.patchName?.toLowerCase().contains(q) ?? false),
        )
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    final keys = _filteredKeys;

    return DraggableScrollableSheet(
      initialChildSize: 0.7,
      minChildSize: 0.4,
      maxChildSize: 0.9,
      expand: false,
      builder: (context, scrollController) => Column(
        children: [
          // Handle
          Center(
            child: Container(
              width: 40,
              height: 4,
              margin: const EdgeInsets.symmetric(vertical: 12),
              decoration: BoxDecoration(
                color: Colors.grey.shade300,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          // Title
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              children: [
                const Text(
                  '选择区域',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    color: Color(0xFF1B4332),
                  ),
                ),
                const Spacer(),
                Text(
                  '${widget.zonesByPatch.values.fold(0, (s, l) => s + l.length)} 个区域',
                  style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
                ),
              ],
            ),
          ),
          // Search
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
            child: TextField(
              onChanged: (v) => setState(() => _search = v),
              decoration: InputDecoration(
                hintText: '搜索区域名称或编号...',
                hintStyle: TextStyle(fontSize: 13, color: Colors.grey.shade500),
                prefixIcon: const Icon(
                  Icons.search,
                  size: 18,
                  color: Colors.grey,
                ),
                isDense: true,
                contentPadding: const EdgeInsets.symmetric(vertical: 10),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
              style: const TextStyle(fontSize: 13),
            ),
          ),
          // List
          Expanded(
            child: ListView.builder(
              controller: scrollController,
              padding: const EdgeInsets.symmetric(vertical: 4),
              itemCount: keys.length,
              itemBuilder: (context, index) {
                final key = keys[index];
                final zones = _filteredZones(widget.zonesByPatch[key]!);
                if (zones.isEmpty) return const SizedBox.shrink();

                final isOrphan = key == null;
                final patchName = isOrphan
                    ? '未分配片区'
                    : (widget.patchNames[key] ?? '未知片区');
                final isExpanded = _expanded.contains(key);

                return Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    // Patch header
                    InkWell(
                      onTap: () => setState(() {
                        isExpanded ? _expanded.remove(key) : _expanded.add(key);
                      }),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 8,
                        ),
                        child: Row(
                          children: [
                            Icon(
                              isExpanded
                                  ? Icons.expand_less
                                  : Icons.expand_more,
                              size: 18,
                              color: const Color(0xFF52B788),
                            ),
                            const SizedBox(width: 4),
                            Expanded(
                              child: Text(
                                patchName,
                                style: const TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                  color: Color(0xFF1B4332),
                                ),
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
                                style: TextStyle(
                                  fontSize: 10,
                                  color: Colors.grey.shade600,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    // Zones
                    if (isExpanded)
                      ...zones.map((zone) {
                        final isSelected = widget.selectedZone?.id == zone.id;
                        final dist = widget.userLocation != null
                            ? _zoneDist(zone)
                            : null;

                        return InkWell(
                          onTap: () => widget.onSelected(zone),
                          child: Container(
                            padding: const EdgeInsets.only(
                              left: 36,
                              right: 16,
                              top: 6,
                              bottom: 6,
                            ),
                            decoration: BoxDecoration(
                              color: isSelected
                                  ? const Color(0xFF52B788).withOpacity(0.12)
                                  : null,
                            ),
                            child: Row(
                              children: [
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        zone.name,
                                        style: TextStyle(
                                          fontSize: 13,
                                          fontWeight: isSelected
                                              ? FontWeight.w600
                                              : FontWeight.w500,
                                        ),
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                      Text(
                                        zone.code,
                                        style: TextStyle(
                                          fontSize: 10,
                                          color: Colors.grey.shade600,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                if (dist != null)
                                  Text(
                                    _fmtDist(dist),
                                    style: TextStyle(
                                      fontSize: 11,
                                      color: Colors.grey.shade500,
                                    ),
                                  ),
                                if (isSelected)
                                  const Icon(
                                    Icons.check,
                                    size: 16,
                                    color: Color(0xFF40916C),
                                  ),
                              ],
                            ),
                          ),
                        );
                      }),
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  double? _zoneDist(Zone zone) {
    if (widget.userLocation == null || zone.center == null) return null;
    final lat1 = widget.userLocation!.latitude * pi / 180;
    final lng1 = widget.userLocation!.longitude * pi / 180;
    final lat2 = zone.center!['lat']! * pi / 180;
    final lng2 = zone.center!['lng']! * pi / 180;
    final dLat = lat2 - lat1;
    final dLng = lng2 - lng1;
    final a =
        sin(dLat / 2) * sin(dLat / 2) +
        cos(lat1) * cos(lat2) * sin(dLng / 2) * sin(dLng / 2);
    return 6371000 * 2 * atan2(sqrt(a), sqrt(1 - a));
  }
}
