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
  int? _selectedPatch; // Patch ID
  String _selectedPatchName = '';
  int? _selectedZone; // Zone ID (optional, within selected patch)
  String _zoneText = '';
  bool _isGlobalEvent = false;
  int? _selectedCategory;
  String _categoryText = '';
  TimeOfDay? _startTime;
  TimeOfDay? _endTime;
  int? _selectedDepartment;
  String _demandContact = '';

  // Dropdown data
  List<Zone> _allZones = [];
  List<Map<String, dynamic>> _categories = [];
  List<Map<String, dynamic>> _departments = [];

  // Patch grouping
  final Map<int?, List<Zone>> _zonesByPatch = {};
  final Map<int?, String> _patchNames = {};

  @override
  void initState() {
    super.initState();
    _loadDropdowns();
  }

  void _groupByPatches() {
    _zonesByPatch.clear();
    _patchNames.clear();

    for (var zone in _allZones) {
      final patchId = zone.patchId;
      _zonesByPatch.putIfAbsent(patchId, () => []).add(zone);
      if (patchId != null && !_patchNames.containsKey(patchId)) {
        _patchNames[patchId] = zone.patchName ?? '未知片区';
      }
    }
  }

  Future<void> _loadDropdowns() async {
    try {
      final zones = await widget.apiService.getZones();
      final categories = await widget.apiService.getDemandCategories();
      final departments = await widget.apiService.getDemandDepartments();
      setState(() {
        _allZones = zones;
        _categories = categories;
        _departments = departments;
        _groupByPatches();
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
        zoneText: _zoneText.isNotEmpty ? _zoneText : _selectedPatchName,
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

  void _openPatchPicker() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.5,
        minChildSize: 0.3,
        maxChildSize: 0.7,
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
                  const Expanded(
                    child: Text(
                      '选择片区',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                      ),
                      textAlign: TextAlign.center,
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
              child: ListView.builder(
                controller: scrollController,
                itemCount: _patchNames.length + (_zonesByPatch.containsKey(null) ? 1 : 0),
                itemBuilder: (ctx, i) {
                  final keys = _patchNames.keys.toList();
                  if (i < keys.length) {
                    final patchId = keys[i];
                    final patchName = _patchNames[patchId]!;
                    final zoneCount = _zonesByPatch[patchId]?.length ?? 0;
                    final isSelected = _selectedPatch == patchId;
                    return ListTile(
                      selected: isSelected,
                      title: Text(patchName, style: const TextStyle(fontSize: 14)),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 2,
                            ),
                            decoration: BoxDecoration(
                              color: Colors.grey.shade200,
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Text(
                              '$zoneCount 区域',
                              style: TextStyle(
                                fontSize: 11, color: Colors.grey.shade600,
                              ),
                            ),
                          ),
                          if (isSelected)
                            const SizedBox(width: 8),
                          if (isSelected)
                            const Icon(Icons.check, size: 16, color: Color(0xFF40916C)),
                        ],
                      ),
                      onTap: () {
                        Navigator.pop(context);
                        setState(() {
                          _selectedPatch = patchId;
                          _selectedZone = null; // Reset zone when patch changes
                          _selectedPatchName = patchName;
                        });
                      },
                    );
                  } else {
                    // Orphan zones
                    final orphanZones = _zonesByPatch[null] ?? [];
                    final isSelected = _selectedPatch == -1; // Use -1 for orphan
                    return ListTile(
                      selected: isSelected,
                      title: const Text('未分配片区', style: TextStyle(fontSize: 14)),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 2,
                            ),
                            decoration: BoxDecoration(
                              color: Colors.grey.shade200,
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Text(
                              '${orphanZones.length} 区域',
                              style: TextStyle(
                                fontSize: 11, color: Colors.grey.shade600,
                              ),
                            ),
                          ),
                          if (isSelected)
                            const SizedBox(width: 8),
                          if (isSelected)
                            const Icon(Icons.check, size: 16, color: Color(0xFF40916C)),
                        ],
                      ),
                      onTap: () {
                        Navigator.pop(context);
                        setState(() {
                          _selectedPatch = -1;
                          _selectedZone = null;
                          _selectedPatchName = '未分配片区';
                        });
                      },
                    );
                  }
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _openZonePicker() {
    if (_selectedPatch == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请先选择一个片区')),
      );
      return;
    }

    final patchId = _selectedPatch == -1 ? null : _selectedPatch;
    final patchZones = _zonesByPatch[patchId] ?? [];

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.5,
        minChildSize: 0.3,
        maxChildSize: 0.7,
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
                  const Text(
                    '选择区域',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const Spacer(),
                  TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('关闭'),
                  ),
                ],
              ),
            ),
            Expanded(
              child: ListView.builder(
                controller: scrollController,
                itemCount: patchZones.length,
                itemBuilder: (ctx, i) {
                  final zone = patchZones[i];
                  final isSelected = _selectedZone == zone.id;
                  return ListTile(
                    selected: isSelected,
                    leading: Container(
                      width: 8,
                      height: 8,
                      decoration: BoxDecoration(
                        color: zone.status == 'completed'
                            ? const Color(0xFF40916C)
                            : const Color(0xFFCC7722),
                        shape: BoxShape.circle,
                      ),
                    ),
                    title: Text(zone.name, style: const TextStyle(fontSize: 13)),
                    subtitle: Text(zone.code, style: TextStyle(fontSize: 11, color: Colors.grey.shade500)),
                    trailing: isSelected
                        ? const Icon(Icons.check, size: 16, color: Color(0xFF40916C))
                        : null,
                    onTap: () {
                      Navigator.pop(context);
                      setState(() {
                        _selectedZone = zone.id;
                        _zoneText = '${zone.name} (${zone.code})';
                      });
                    },
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('提交需求')),
      body: AppBackground(
        child: Form(
          key: _formKey,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
            children: [
              AppCard(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Date
                    const Text('日期', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: Color(0xFF1B4332))),
                    const SizedBox(height: 8),
                    InkWell(
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
                      child: InputDecorator(
                        decoration: const InputDecoration(
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.calendar_today, size: 18),
                          contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                        ),
                        child: Text(
                          _selectedDate.toString().split(' ')[0],
                          style: const TextStyle(fontSize: 14),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Patch picker
                    const Text('片区', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: Color(0xFF1B4332))),
                    const SizedBox(height: 8),
                    InkWell(
                      onTap: _openPatchPicker,
                      child: InputDecorator(
                        decoration: const InputDecoration(
                          labelText: '选择片区',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.map_outlined, size: 18),
                          contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                        ),
                        child: Text(
                          _selectedPatchName.isNotEmpty
                              ? _selectedPatchName
                              : '选择片区',
                          style: TextStyle(
                            fontSize: 14,
                            color: _selectedPatchName.isNotEmpty ? Colors.black87 : Colors.grey,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Zone picker
                    const Text('区域（可选）', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: Color(0xFF1B4332))),
                    const SizedBox(height: 8),
                    InkWell(
                      onTap: _selectedPatch != null ? _openZonePicker : null,
                      child: InputDecorator(
                        decoration: InputDecoration(
                          border: const OutlineInputBorder(),
                          labelText: _selectedPatch != null ? '选择具体区域' : '请先选择片区',
                          prefixIcon: const Icon(Icons.place_outlined, size: 18),
                          suffixIcon: _selectedZone != null
                              ? IconButton(
                                  icon: const Icon(Icons.clear, size: 18),
                                  onPressed: () {
                                    setState(() {
                                      _selectedZone = null;
                                      _zoneText = '';
                                    });
                                  },
                                )
                              : null,
                          contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                        ),
                        child: Text(
                          _selectedZone != null && _zoneText.isNotEmpty
                              ? _zoneText
                              : (_selectedPatch != null ? '选择具体区域' : '请先选择片区'),
                          style: TextStyle(
                            fontSize: 14,
                            color: _selectedZone != null ? Colors.black87 : Colors.grey,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Global event toggle
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      decoration: BoxDecoration(
                        color: const Color(0xFF40916C).withOpacity(0.06),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: const Color(0xFFB7E4C7)),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.public, size: 20, color: Color(0xFF40916C)),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: const [
                                Text('全局事件', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w500)),
                                Text('如停水停电、项目施工等影响多区域的事件', style: TextStyle(fontSize: 12, color: AppColors.muted)),
                              ],
                            ),
                          ),
                          Switch(
                            value: _isGlobalEvent,
                            onChanged: (v) => setState(() => _isGlobalEvent = v),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Category
                    const Text('需求类别', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: Color(0xFF1B4332))),
                    const SizedBox(height: 8),
                    DropdownButtonFormField<int>(
                      value: _selectedCategory,
                      decoration: const InputDecoration(
                        labelText: '选择类别',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.category_outlined, size: 18),
                        contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      ),
                      items: [
                        const DropdownMenuItem(value: null, child: Text('选择类别')),
                        ..._categories.map(
                          (c) => DropdownMenuItem(value: c['id'], child: Text(c['name'])),
                        ),
                      ],
                      onChanged: (value) {
                        setState(() {
                          _selectedCategory = value;
                          if (value != null) {
                            final cat = _categories.firstWhere((c) => c['id'] == value);
                            _categoryText = cat['name'];
                          }
                        });
                      },
                    ),
                    const SizedBox(height: 16),

                    // Category text
                    const Text('类别名称（可手动填写）', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: Color(0xFF1B4332))),
                    const SizedBox(height: 8),
                    TextFormField(
                      initialValue: _categoryText,
                      decoration: const InputDecoration(
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.edit_note_outlined, size: 18),
                        contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      ),
                      onChanged: (value) => _categoryText = value,
                    ),
                    const SizedBox(height: 16),

                    // Time range
                    const Text('时间段（可选）', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: Color(0xFF1B4332))),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Expanded(
                          child: InkWell(
                            onTap: () async {
                              final picked = await showTimePicker(
                                context: context,
                                initialTime: _startTime ?? TimeOfDay.now(),
                              );
                              if (picked != null) setState(() => _startTime = picked);
                            },
                            child: InputDecorator(
                              decoration: const InputDecoration(
                                labelText: '开始时间',
                                border: OutlineInputBorder(),
                                prefixIcon: Icon(Icons.access_time, size: 18),
                                contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                              ),
                              child: Text(
                                _startTime != null
                                    ? '${_startTime!.hour.toString().padLeft(2, '0')}:${_startTime!.minute.toString().padLeft(2, '0')}'
                                    : '选择',
                                style: TextStyle(
                                  fontSize: 14,
                                  color: _startTime != null ? Colors.black87 : Colors.grey,
                                ),
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        const Icon(Icons.arrow_forward, size: 20, color: Colors.grey),
                        const SizedBox(width: 12),
                        Expanded(
                          child: InkWell(
                            onTap: () async {
                              final picked = await showTimePicker(
                                context: context,
                                initialTime: _endTime ?? TimeOfDay.now(),
                              );
                              if (picked != null) setState(() => _endTime = picked);
                            },
                            child: InputDecorator(
                              decoration: const InputDecoration(
                                labelText: '结束时间',
                                border: OutlineInputBorder(),
                                prefixIcon: Icon(Icons.access_time, size: 18),
                                contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                              ),
                              child: Text(
                                _endTime != null
                                    ? '${_endTime!.hour.toString().padLeft(2, '0')}:${_endTime!.minute.toString().padLeft(2, '0')}'
                                    : '选择',
                                style: TextStyle(
                                  fontSize: 14,
                                  color: _endTime != null ? Colors.black87 : Colors.grey,
                                ),
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),

                    // Demand department (for dept_user)
                    if (widget.user.role == 'dept_user') ...[
                      const Text('提出部门', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: Color(0xFF1B4332))),
                      const SizedBox(height: 8),
                      DropdownButtonFormField<int>(
                        value: _selectedDepartment,
                        decoration: const InputDecoration(
                          labelText: '选择部门',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.apartment_outlined, size: 18),
                          contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                        ),
                        items: [
                          const DropdownMenuItem(value: null, child: Text('选择部门')),
                          ..._departments.map(
                            (d) => DropdownMenuItem(value: d['id'], child: Text(d['name'])),
                          ),
                        ],
                        onChanged: (value) => setState(() => _selectedDepartment = value),
                      ),
                      const SizedBox(height: 16),
                    ],

                    // Contact
                    const Text('联系人', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: Color(0xFF1B4332))),
                    const SizedBox(height: 8),
                    TextFormField(
                      initialValue: widget.user.fullName,
                      decoration: const InputDecoration(
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.person_outline_rounded, size: 18),
                        contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      ),
                      onChanged: (value) => _demandContact = value,
                    ),
                    const SizedBox(height: 16),

                    // Content
                    const Text('需求内容', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: Color(0xFF1B4332))),
                    const SizedBox(height: 8),
                    TextFormField(
                      maxLines: 5,
                      decoration: const InputDecoration(
                        border: OutlineInputBorder(),
                        labelText: '详细描述需求内容，如时间段、具体要求等',
                        prefixIcon: Icon(Icons.description_outlined, size: 18),
                        contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
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
                    FilledButton.icon(
                      onPressed: _isLoading ? null : _submitForm,
                      icon: _isLoading
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
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
