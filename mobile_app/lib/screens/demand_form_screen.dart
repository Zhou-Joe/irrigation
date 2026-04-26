import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../models/user.dart';
import '../models/zone.dart';
import '../theme/app_theme.dart';
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

  DateTime _selectedDate = DateTime.now();
  String _content = '';
  int? _selectedPatch;
  String _selectedPatchName = '';
  int? _selectedZone;
  String _zoneText = '';
  bool _isGlobalEvent = false;
  int? _selectedCategory;
  String _categoryText = '';
  TimeOfDay? _startTime;
  TimeOfDay? _endTime;
  int? _selectedDepartment;
  String _demandContact = '';

  List<Zone> _allZones = [];
  List<Map<String, dynamic>> _categories = [];
  List<Map<String, dynamic>> _departments = [];

  final Map<int?, List<Zone>> _zonesByPatch = {};
  final Map<int?, String> _patchNames = {};
  final Map<int?, String> _patchTypeDisplays = {};

  @override
  void initState() {
    super.initState();
    _demandContact = widget.user.fullName;
    _loadDropdowns();
  }

  void _groupByPatches() {
    _zonesByPatch.clear();
    _patchNames.clear();
    _patchTypeDisplays.clear();
    for (var zone in _allZones) {
      final patchId = zone.patchId;
      _zonesByPatch.putIfAbsent(patchId, () => []).add(zone);
      if (patchId != null && !_patchNames.containsKey(patchId)) {
        _patchNames[patchId] = zone.patchName ?? '未知区域';
        _patchTypeDisplays[patchId] = zone.patchTypeDisplay ?? '区域';
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
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('加载数据失败: $e')),
        );
      }
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

      if (mounted) {
        setState(() => _isLoading = false);
        Navigator.pop(context, true);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('需求提交成功')),
        );
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isLoading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('提交失败: $e')),
        );
      }
    }
  }

  void _openPatchPicker() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.5,
        minChildSize: 0.3,
        maxChildSize: 0.7,
        expand: false,
        builder: (ctx, scrollController) => Column(
          children: [
            Center(
              child: Container(
                width: 40, height: 4,
                margin: const EdgeInsets.symmetric(vertical: 12),
                decoration: BoxDecoration(
                  color: Colors.grey.shade300,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppTheme.pagePadding),
              child: Row(
                children: [
                  Text('选择分区', style: AppTheme.tsSectionTitle),
                  const Spacer(),
                  TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('关闭'),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: ListView.builder(
                controller: scrollController,
                padding: const EdgeInsets.symmetric(horizontal: AppTheme.pagePadding),
                itemCount: _patchNames.length + (_zonesByPatch.containsKey(null) ? 1 : 0),
                itemBuilder: (ctx, i) {
                  final keys = _patchNames.keys.toList();
                  if (i < keys.length) {
                    final patchId = keys[i];
                    final patchName = _patchNames[patchId]!;
                    final patchType = _patchTypeDisplays[patchId] ?? '';
                    final zoneCount = _zonesByPatch[patchId]?.length ?? 0;
                    final isSelected = _selectedPatch == patchId;
                    return _PickerItem(
                      title: patchName,
                      typeLabel: patchType,
                      count: zoneCount,
                      isSelected: isSelected,
                      onTap: () {
                        Navigator.pop(context);
                        setState(() {
                          _selectedPatch = patchId;
                          _selectedZone = null;
                          _selectedPatchName = patchName;
                        });
                      },
                    );
                  } else {
                    final orphanZones = _zonesByPatch[null] ?? [];
                    final isSelected = _selectedPatch == -1;
                    return _PickerItem(
                      title: '未分配',
                      typeLabel: '',
                      count: orphanZones.length,
                      isSelected: isSelected,
                      onTap: () {
                        Navigator.pop(context);
                        setState(() {
                          _selectedPatch = -1;
                          _selectedZone = null;
                          _selectedPatchName = '未分配';
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
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.5,
        minChildSize: 0.3,
        maxChildSize: 0.7,
        expand: false,
        builder: (ctx, scrollController) => Column(
          children: [
            Center(
              child: Container(
                width: 40, height: 4,
                margin: const EdgeInsets.symmetric(vertical: 12),
                decoration: BoxDecoration(
                  color: Colors.grey.shade300,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppTheme.pagePadding),
              child: Row(
                children: [
                  Text('选择区域', style: AppTheme.tsSectionTitle),
                  const Spacer(),
                  TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('关闭'),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: ListView.builder(
                controller: scrollController,
                padding: const EdgeInsets.symmetric(horizontal: AppTheme.pagePadding),
                itemCount: patchZones.length,
                itemBuilder: (ctx, i) {
                  final zone = patchZones[i];
                  final isSelected = _selectedZone == zone.id;
                  return ListTile(
                    selected: isSelected,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    leading: Container(
                      width: 8, height: 8,
                      decoration: BoxDecoration(
                        color: AppTheme.statusColor(zone.status),
                        shape: BoxShape.circle,
                      ),
                    ),
                    title: Text(zone.name, style: AppTheme.tsBody),
                    subtitle: Text(zone.code, style: AppTheme.tsOverline),
                    trailing: isSelected
                        ? const Icon(Icons.check, size: 16, color: AppTheme.greenMedium)
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
            padding: const EdgeInsets.fromLTRB(
              AppTheme.pagePadding, 12, AppTheme.pagePadding, 32,
            ),
            children: [
              // ── Section 1: Time & Location ──────────────────
              AppFormSection(
                title: '时间与位置',
                icon: Icons.event_outlined,
                children: [
                  // Date
                  InkWell(
                    onTap: () async {
                      final picked = await showDatePicker(
                        context: context,
                        initialDate: _selectedDate,
                        firstDate: DateTime(2020),
                        lastDate: DateTime(2030),
                      );
                      if (picked != null) setState(() => _selectedDate = picked);
                    },
                    child: InputDecorator(
                      decoration: const InputDecoration(
                        labelText: '日期',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.calendar_today, size: 18),
                        contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      ),
                      child: Text(
                        _selectedDate.toString().split(' ')[0],
                        style: AppTheme.tsBody,
                      ),
                    ),
                  ),
                  const SizedBox(height: AppTheme.fieldGap),

                  // Patch picker
                  InkWell(
                    onTap: _openPatchPicker,
                    child: InputDecorator(
                      decoration: const InputDecoration(
                        labelText: '片区',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.map_outlined, size: 18),
                        contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      ),
                      child: Text(
                        _selectedPatchName.isNotEmpty ? _selectedPatchName : '选择片区',
                        style: _selectedPatchName.isNotEmpty
                            ? AppTheme.tsBody
                            : AppTheme.tsCaption,
                      ),
                    ),
                  ),
                  const SizedBox(height: AppTheme.fieldGap),

                  // Zone picker
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
                                onPressed: () => setState(() {
                                  _selectedZone = null;
                                  _zoneText = '';
                                }),
                              )
                            : null,
                        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      ),
                      child: Text(
                        _zoneText.isNotEmpty
                            ? _zoneText
                            : (_selectedPatch != null ? '选择具体区域' : '请先选择片区'),
                        style: _zoneText.isNotEmpty ? AppTheme.tsBody : AppTheme.tsCaption,
                      ),
                    ),
                  ),
                  const SizedBox(height: AppTheme.fieldGap),

                  // Time range
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
                              style: _startTime != null ? AppTheme.tsBody : AppTheme.tsCaption,
                            ),
                          ),
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 8),
                        child: Icon(Icons.arrow_forward, size: 18, color: AppTheme.textSecondary),
                      ),
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
                              style: _endTime != null ? AppTheme.tsBody : AppTheme.tsCaption,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),

                  // Global event toggle
                  const SizedBox(height: AppTheme.fieldGap),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                    decoration: BoxDecoration(
                      color: AppTheme.greenPrimary.withOpacity(0.06),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: AppTheme.greenPale),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.public, size: 20, color: AppTheme.greenPrimary),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('全局事件', style: AppTheme.tsLabel.copyWith(fontSize: 14)),
                              Text('如停水停电、项目施工等影响多区域的事件', style: AppTheme.tsOverline),
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
                ],
              ),
              const SizedBox(height: AppTheme.itemGap),

              // ── Section 2: Category & Department ────────────
              AppFormSection(
                title: '分类与部门',
                icon: Icons.category_outlined,
                children: [
                  DropdownButtonFormField<int>(
                    value: _selectedCategory,
                    decoration: const InputDecoration(
                      labelText: '需求类别',
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
                  const SizedBox(height: AppTheme.fieldGap),
                  TextFormField(
                    initialValue: _categoryText,
                    decoration: const InputDecoration(
                      labelText: '类别名称（可手动填写）',
                      border: OutlineInputBorder(),
                      prefixIcon: Icon(Icons.edit_note_outlined, size: 18),
                      contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    ),
                    style: AppTheme.tsBody,
                    onChanged: (value) => _categoryText = value,
                  ),
                  if (widget.user.role == 'dept_user') ...[
                    const SizedBox(height: AppTheme.fieldGap),
                    DropdownButtonFormField<int>(
                      value: _selectedDepartment,
                      decoration: const InputDecoration(
                        labelText: '提出部门',
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
                  ],
                ],
              ),
              const SizedBox(height: AppTheme.itemGap),

              // ── Section 3: Content ──────────────────────────
              AppFormSection(
                title: '需求内容',
                icon: Icons.description_outlined,
                children: [
                  TextFormField(
                    initialValue: _demandContact,
                    decoration: const InputDecoration(
                      labelText: '联系人',
                      border: OutlineInputBorder(),
                      prefixIcon: Icon(Icons.person_outline_rounded, size: 18),
                      contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    ),
                    style: AppTheme.tsBody,
                    onChanged: (value) => _demandContact = value,
                  ),
                  const SizedBox(height: AppTheme.fieldGap),
                  TextFormField(
                    maxLines: 5,
                    decoration: const InputDecoration(
                      border: OutlineInputBorder(),
                      labelText: '详细描述需求内容',
                      prefixIcon: Icon(Icons.description_outlined, size: 18),
                      contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    ),
                    style: AppTheme.tsBody,
                    validator: (value) {
                      if (value == null || value.isEmpty) return '请填写需求内容';
                      return null;
                    },
                    onChanged: (value) => _content = value,
                  ),
                ],
              ),
              const SizedBox(height: AppTheme.sectionGap),

              // ── Submit ──────────────────────────────────────
              FilledButton.icon(
                onPressed: _isLoading ? null : _submitForm,
                icon: _isLoading
                    ? const SizedBox(
                        width: 20, height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : const Icon(Icons.send_rounded),
                label: Text(_isLoading ? '提交中...' : '提交需求'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ── Picker list item ────────────────────────────────────────────
class _PickerItem extends StatelessWidget {
  final String title;
  final String typeLabel;
  final int count;
  final bool isSelected;
  final VoidCallback onTap;

  const _PickerItem({
    required this.title,
    required this.typeLabel,
    required this.count,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(
            color: isSelected
                ? AppTheme.greenPrimary.withOpacity(0.08)
                : Colors.transparent,
            borderRadius: BorderRadius.circular(12),
            border: isSelected
                ? Border.all(color: AppTheme.greenMedium)
                : Border.all(color: Colors.transparent),
          ),
          child: Row(
            children: [
              if (typeLabel.isNotEmpty) ...[
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                  decoration: BoxDecoration(
                    color: AppTheme.greenLight.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(typeLabel, style: AppTheme.tsOverline.copyWith(color: AppTheme.greenLight)),
                ),
                const SizedBox(width: 6),
              ],
              Expanded(
                child: Text(title, style: AppTheme.tsBody.copyWith(
                  fontWeight: isSelected ? FontWeight.w600 : FontWeight.w400,
                )),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: AppTheme.surfaceAlt,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text('$count', style: AppTheme.tsOverline),
              ),
              if (isSelected) ...[
                const SizedBox(width: 8),
                const Icon(Icons.check, size: 16, color: AppTheme.greenMedium),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
