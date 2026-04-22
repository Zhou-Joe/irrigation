import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../models/user.dart';
import '../models/zone.dart';
import '../widgets/modern_ui.dart';

class DemandFormScreen extends StatefulWidget {
  final User user;
  final ApiService apiService;

  const DemandFormScreen({
    super.key,
    required this.user,
    required this.apiService,
  });

  @override
  State<DemandFormScreen> createState() => _DemandFormScreenState();
}

class _DemandFormScreenState extends State<DemandFormScreen> {
  final _formKey = GlobalKey<FormState>();
  bool _isLoading = false;

  // Form fields
  DateTime _selectedDate = DateTime.now();
  String _content = '';
  int? _selectedZone;
  String _zoneText = '';
  bool _isGlobalEvent = false;
  int? _selectedCategory;
  String _categoryText = '';
  TimeOfDay? _startTime;
  TimeOfDay? _endTime;
  int? _selectedDepartment;
  String _demandContact = '';

  // Dropdown data
  List<Map<String, dynamic>> _zones = [];
  List<Map<String, dynamic>> _categories = [];
  List<Map<String, dynamic>> _departments = [];

  @override
  void initState() {
    super.initState();
    _loadDropdowns();
  }

  Future<void> _loadDropdowns() async {
    try {
      final zones = await widget.apiService.getZones();
      final categories = await widget.apiService.getDemandCategories();
      final departments = await widget.apiService.getDemandDepartments();
      final zoneMaps = zones
          .map<Map<String, dynamic>>(
            (Zone zone) => {'id': zone.id, 'name': zone.name},
          )
          .toList();
      setState(() {
        _zones = zoneMaps;
        _categories = categories;
        _departments = departments;
      });
    } catch (e) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('加载下拉数据失败: $e')));
    }
  }

  Future<void> _submitForm() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() => _isLoading = true);

    try {
      final startTimeStr = _startTime != null
          ? '${_startTime!.hour.toString().padLeft(2, '0')}:${_startTime!.minute.toString().padLeft(2, '0')}'
          : null;
      final endTimeStr = _endTime != null
          ? '${_endTime!.hour.toString().padLeft(2, '0')}:${_endTime!.minute.toString().padLeft(2, '0')}'
          : null;

      await widget.apiService.createDemandRecord(
        date: _selectedDate.toString().split(' ')[0],
        content: _content,
        zone: _selectedZone,
        zoneText: _zoneText,
        isGlobalEvent: _isGlobalEvent,
        category: _selectedCategory,
        categoryText: _categoryText,
        startTime: startTimeStr,
        endTime: endTimeStr,
        demandDepartment: _selectedDepartment,
        demandContact: _demandContact,
      );

      setState(() => _isLoading = false);
      Navigator.pop(context, true);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('需求提交成功')));
    } catch (e) {
      setState(() => _isLoading = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('提交失败: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('提交需求')),
      body: AppBackground(
        child: Form(
          key: _formKey,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
            children: [
              const AppHeroCard(
                title: '提交需求',
                subtitle: '把时间、区域、类别和联系信息整理成一条更清晰的需求记录。',
                icon: Icons.edit_note_rounded,
              ),
              const SizedBox(height: 16),
              AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const AppSectionTitle(
                      title: '基本信息',
                      subtitle: '先确认日期、区域和需求类别',
                    ),
                    const SizedBox(height: 12),
                    // Date
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text('日期'),
                      trailing: Text(_selectedDate.toString().split(' ')[0]),
                      onTap: () async {
                        final picked = await showDatePicker(
                          context: context,
                          initialDate: _selectedDate,
                          firstDate: DateTime(2020),
                          lastDate: DateTime(2030),
                        );
                        if (picked != null) {
                          setState(() => _selectedDate = picked);
                        }
                      },
                    ),

                    // Zone
                    DropdownButtonFormField<int>(
                      value: _selectedZone,
                      decoration: const InputDecoration(
                        labelText: '区域',
                        prefixIcon: Icon(Icons.location_on_outlined),
                      ),
                      items: [
                        const DropdownMenuItem(
                          value: null,
                          child: Text('选择区域'),
                        ),
                        ..._zones.map(
                          (z) => DropdownMenuItem(
                            value: z['id'],
                            child: Text(z['name']),
                          ),
                        ),
                      ],
                      onChanged: (value) {
                        setState(() {
                          _selectedZone = value;
                          if (value != null) {
                            final zone = _zones.firstWhere(
                              (z) => z['id'] == value,
                            );
                            _zoneText = zone['name'];
                          }
                        });
                      },
                    ),
                    const SizedBox(height: 8),

                    // Zone text (optional override)
                    TextFormField(
                      initialValue: _zoneText,
                      decoration: const InputDecoration(
                        labelText: '区域名称（可手动填写）',
                        prefixIcon: Icon(Icons.edit_location_alt_outlined),
                      ),
                      onChanged: (value) => _zoneText = value,
                    ),
                    const SizedBox(height: 8),

                    // Global event toggle
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text('全局事件'),
                      subtitle: const Text('如停水停电、项目施工等影响多区域的事件'),
                      value: _isGlobalEvent,
                      onChanged: (value) {
                        setState(() => _isGlobalEvent = value);
                      },
                    ),
                    const SizedBox(height: 8),

                    // Category
                    DropdownButtonFormField<int>(
                      value: _selectedCategory,
                      decoration: const InputDecoration(
                        labelText: '需求类别',
                        prefixIcon: Icon(Icons.category_outlined),
                      ),
                      items: [
                        const DropdownMenuItem(
                          value: null,
                          child: Text('选择类别'),
                        ),
                        ..._categories.map(
                          (c) => DropdownMenuItem(
                            value: c['id'],
                            child: Text(c['name']),
                          ),
                        ),
                      ],
                      onChanged: (value) {
                        setState(() {
                          _selectedCategory = value;
                          if (value != null) {
                            final cat = _categories.firstWhere(
                              (c) => c['id'] == value,
                            );
                            _categoryText = cat['name'];
                          }
                        });
                      },
                    ),
                    const SizedBox(height: 8),

                    // Category text (optional override)
                    TextFormField(
                      initialValue: _categoryText,
                      decoration: const InputDecoration(
                        labelText: '类别名称（可手动填写）',
                        prefixIcon: Icon(Icons.edit_note_outlined),
                      ),
                      onChanged: (value) => _categoryText = value,
                    ),
                    const SizedBox(height: 8),

                    // Time range
                    Row(
                      children: [
                        Expanded(
                          child: ListTile(
                            contentPadding: EdgeInsets.zero,
                            title: const Text('开始时间'),
                            trailing: Text(
                              _startTime != null
                                  ? '${_startTime!.hour.toString().padLeft(2, '0')}:${_startTime!.minute.toString().padLeft(2, '0')}'
                                  : '选择',
                            ),
                            onTap: () async {
                              final picked = await showTimePicker(
                                context: context,
                                initialTime: _startTime ?? TimeOfDay.now(),
                              );
                              if (picked != null) {
                                setState(() => _startTime = picked);
                              }
                            },
                          ),
                        ),
                        Expanded(
                          child: ListTile(
                            contentPadding: EdgeInsets.zero,
                            title: const Text('结束时间'),
                            trailing: Text(
                              _endTime != null
                                  ? '${_endTime!.hour.toString().padLeft(2, '0')}:${_endTime!.minute.toString().padLeft(2, '0')}'
                                  : '选择',
                            ),
                            onTap: () async {
                              final picked = await showTimePicker(
                                context: context,
                                initialTime: _endTime ?? TimeOfDay.now(),
                              );
                              if (picked != null) {
                                setState(() => _endTime = picked);
                              }
                            },
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),

                    // Demand department (for dept_user)
                    if (widget.user.role == 'dept_user')
                      DropdownButtonFormField<int>(
                        value: _selectedDepartment,
                        decoration: const InputDecoration(
                          labelText: '提出部门',
                          prefixIcon: Icon(Icons.apartment_outlined),
                        ),
                        items: [
                          const DropdownMenuItem(
                            value: null,
                            child: Text('选择部门'),
                          ),
                          ..._departments.map(
                            (d) => DropdownMenuItem(
                              value: d['id'],
                              child: Text(d['name']),
                            ),
                          ),
                        ],
                        onChanged: (value) {
                          setState(() => _selectedDepartment = value);
                        },
                      ),
                    if (widget.user.role == 'dept_user')
                      const SizedBox(height: 8),

                    // Contact
                    TextFormField(
                      initialValue: widget.user.fullName,
                      decoration: const InputDecoration(
                        labelText: '联系人',
                        prefixIcon: Icon(Icons.person_outline_rounded),
                      ),
                      onChanged: (value) => _demandContact = value,
                    ),
                    const SizedBox(height: 16),

                    // Content
                    TextFormField(
                      maxLines: 5,
                      decoration: const InputDecoration(
                        labelText: '需求内容',
                        prefixIcon: Icon(Icons.description_outlined),
                        hintText: '详细描述需求内容，如时间段、具体要求等',
                      ),
                      validator: (value) {
                        if (value == null || value.isEmpty) {
                          return '请填写需求内容';
                        }
                        return null;
                      },
                      onChanged: (value) => _content = value,
                    ),
                    const SizedBox(height: 24),

                    // Submit button
                    const SizedBox(height: 24),
                    FilledButton.icon(
                      onPressed: _isLoading ? null : _submitForm,
                      icon: _isLoading
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            )
                          : const Icon(Icons.send_rounded),
                      label: Text(_isLoading ? '提交中...' : '提交需求'),
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
