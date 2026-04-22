import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../models/zone.dart';
import '../models/work_log.dart';
import '../providers/auth_provider.dart';
import '../widgets/modern_ui.dart';

class WorkLogScreen extends StatefulWidget {
  final List<Zone> zones;
  final Zone? selectedZone;

  const WorkLogScreen({super.key, required this.zones, this.selectedZone});

  @override
  State<WorkLogScreen> createState() => _WorkLogScreenState();
}

class _WorkLogScreenState extends State<WorkLogScreen> {
  final _formKey = GlobalKey<FormState>();
  Zone? _selectedZone;
  String _workType = '浇水';
  final _notesController = TextEditingController();
  bool _isLoading = false;
  bool _includeLocation = true;
  Position? _currentPosition;
  DateTime _workDateTime = DateTime.now();

  final List<String> _workTypes = [
    '浇水',
    '施肥',
    '修剪',
    '除草',
    '喷药',
    '种植',
    '收获',
    '其他',
  ];

  @override
  void initState() {
    super.initState();
    _selectedZone =
        widget.selectedZone ??
        (widget.zones.isNotEmpty ? widget.zones.first : null);
    if (_includeLocation) {
      _getCurrentLocation();
    }
  }

  @override
  void dispose() {
    _notesController.dispose();
    super.dispose();
  }

  Future<void> _getCurrentLocation() async {
    try {
      final position = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high,
      );
      setState(() {
        _currentPosition = position;
      });
    } catch (e) {
      debugPrint('获取位置失败: $e');
    }
  }

  Future<void> _selectDateTime() async {
    final date = await showDatePicker(
      context: context,
      initialDate: _workDateTime,
      firstDate: DateTime.now().subtract(const Duration(days: 30)),
      lastDate: DateTime.now(),
    );

    if (date != null && mounted) {
      final time = await showTimePicker(
        context: context,
        initialTime: TimeOfDay.fromDateTime(_workDateTime),
      );

      if (time != null) {
        setState(() {
          _workDateTime = DateTime(
            date.year,
            date.month,
            date.day,
            time.hour,
            time.minute,
          );
        });
      }
    }
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    if (_selectedZone == null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('请选择区域')));
      return;
    }

    setState(() => _isLoading = true);

    try {
      final log = WorkLog(
        zoneId: _selectedZone!.id,
        workType: _workType,
        notes: _notesController.text.trim().isEmpty
            ? null
            : _notesController.text.trim(),
        latitude: _includeLocation && _currentPosition != null
            ? _currentPosition!.latitude
            : null,
        longitude: _includeLocation && _currentPosition != null
            ? _currentPosition!.longitude
            : null,
        workTimestamp: _workDateTime,
      );

      final api = context.read<AuthProvider>().api;
      await api.submitWorkLog(log);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('提交成功'), backgroundColor: Colors.green),
        );
        Navigator.pop(context, true);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('提交失败: $e')));
      }
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('记录工作')),
      body: AppBackground(
        child: Form(
          key: _formKey,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
            children: [
              const AppHeroCard(
                title: '记录工作',
                subtitle: '把现场操作、时间和备注整理成可追踪记录。',
                icon: Icons.fact_check_outlined,
              ),
              const SizedBox(height: 16),
              AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const AppSectionTitle(
                      title: '工作信息',
                      subtitle: '选择区域、时间和备注内容',
                    ),
                    const SizedBox(height: 12),
                    // Zone selector
                    DropdownButtonFormField<Zone>(
                      value: _selectedZone,
                      decoration: const InputDecoration(
                        labelText: '区域',
                        prefixIcon: Icon(Icons.location_on),
                        border: OutlineInputBorder(),
                      ),
                      items: widget.zones.map((zone) {
                        return DropdownMenuItem(
                          value: zone,
                          child: Text('${zone.name} (${zone.code})'),
                        );
                      }).toList(),
                      onChanged: (zone) => setState(() => _selectedZone = zone),
                      validator: (value) {
                        if (value == null) return '请选择区域';
                        return null;
                      },
                    ),
                    const SizedBox(height: 16),

                    // Work type
                    DropdownButtonFormField<String>(
                      value: _workType,
                      decoration: const InputDecoration(
                        labelText: '工作类型',
                        prefixIcon: Icon(Icons.work),
                        border: OutlineInputBorder(),
                      ),
                      items: _workTypes.map((type) {
                        return DropdownMenuItem(value: type, child: Text(type));
                      }).toList(),
                      onChanged: (type) => setState(() => _workType = type!),
                    ),
                    const SizedBox(height: 16),

                    // Date Time
                    InkWell(
                      onTap: _selectDateTime,
                      child: InputDecorator(
                        decoration: const InputDecoration(
                          labelText: '工作时间',
                          prefixIcon: Icon(Icons.access_time),
                          border: OutlineInputBorder(),
                        ),
                        child: Text(
                          DateFormat('yyyy-MM-dd HH:mm').format(_workDateTime),
                          style: const TextStyle(fontSize: 16),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Notes
                    TextFormField(
                      controller: _notesController,
                      decoration: const InputDecoration(
                        labelText: '备注',
                        prefixIcon: Icon(Icons.notes),
                        border: OutlineInputBorder(),
                        alignLabelWithHint: true,
                      ),
                      maxLines: 3,
                    ),
                    const SizedBox(height: 16),

                    // Location toggle
                    SwitchListTile(
                      title: const Text('包含位置信息'),
                      subtitle: Text(
                        _includeLocation && _currentPosition != null
                            ? '已获取位置'
                            : _includeLocation
                            ? '正在获取位置...'
                            : '不包含位置',
                      ),
                      secondary: const Icon(Icons.location_on),
                      value: _includeLocation,
                      onChanged: (value) {
                        setState(() {
                          _includeLocation = value;
                          if (value && _currentPosition == null) {
                            _getCurrentLocation();
                          }
                        });
                      },
                    ),
                    const SizedBox(height: 32),

                    // Submit button
                    FilledButton.icon(
                      onPressed: _isLoading ? null : _submit,
                      icon: _isLoading
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.send),
                      label: Text(_isLoading ? '提交中...' : '提交'),
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
}
