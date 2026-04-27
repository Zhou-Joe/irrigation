import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/auth_provider.dart';
import '../models/zone.dart';
import 'work_report_form_screen.dart';
import '../theme/app_theme.dart';
import '../widgets/modern_ui.dart';

class WorkReportListScreen extends StatefulWidget {
  final bool isAdmin;
  const WorkReportListScreen({super.key, this.isAdmin = false});

  @override
  State<WorkReportListScreen> createState() => _WorkReportListScreenState();
}

class _WorkReportListScreenState extends State<WorkReportListScreen> {
  List<Map<String, dynamic>> _reports = [];
  List<Map<String, dynamic>> _workCategories = [];
  List<Zone> _zones = [];
  List<Map<String, dynamic>> _patches = [];
  List<Map<String, dynamic>> _workers = [];
  bool _isLoading = true;
  String? _error;

  DateTime? _dateFrom;
  DateTime? _dateTo;
  int? _filterPatch;
  int? _filterWorkCategory;
  int? _filterZone;
  int? _filterWorker;
  bool _filterDifficult = false;

  void _derivePatchesFromZones() {
    final Map<int, Map<String, dynamic>> patchMap = {};
    for (final zone in _zones) {
      if (zone.patchId != null) {
        patchMap[zone.patchId!] = {
          'id': zone.patchId,
          'name': zone.patchName ?? '未知区域',
          'code': zone.patchCode ?? '',
        };
      }
    }
    _patches = patchMap.values.toList()
      ..sort((a, b) => (a['name'] as String).compareTo(b['name'] as String));
  }

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _dateFrom = DateTime(now.year, now.month, 1);
    _dateTo = now;
    _loadFilters().then((_) => _loadReports());
  }

  Future<void> _loadFilters() async {
    final api = context.read<AuthProvider>().api;
    final auth = context.read<AuthProvider>();

    if (auth.isFieldWorker && auth.user != null) {
      _filterWorker = auth.user!.id;
    }

    try {
      final results = await Future.wait([
        api.getWorkCategories().catchError((_) => <Map<String, dynamic>>[]),
        api.getZones().catchError((_) => <Zone>[]),
        auth.isAdmin ? api.getWorkers().catchError((_) => <Map<String, dynamic>>[]) : Future.value(<Map<String, dynamic>>[]),
      ]);
      if (mounted) {
        setState(() {
          _workCategories = results[0] as List<Map<String, dynamic>>;
          _zones = results[1] as List<Zone>;
          if (auth.isAdmin) _workers = results[2] as List<Map<String, dynamic>>;
        });
        _derivePatchesFromZones();
      }
    } catch (e) {
      debugPrint('Error loading filters: $e');
    }
  }

  Future<void> _loadReports() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final api = context.read<AuthProvider>().api;
      final reports = await api.getWorkReports(
        dateFrom: _dateFrom != null ? DateFormat('yyyy-MM-dd').format(_dateFrom!) : null,
        dateTo: _dateTo != null ? DateFormat('yyyy-MM-dd').format(_dateTo!) : null,
        patch: _filterPatch,
        workCategory: _filterWorkCategory,
        zone: _filterZone,
        worker: _filterWorker,
        isDifficult: _filterDifficult ? true : null,
      );
      if (mounted) {
        setState(() {
          _reports = reports;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = '加载失败: $e';
          _isLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('维修日志'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh_rounded), onPressed: _loadReports),
          IconButton(icon: const Icon(Icons.filter_list), onPressed: _showFilterSheet),
        ],
      ),
      body: Stack(
        children: [
          AppBackground(
            child: _isLoading
                ? const AppSkeletonList()
                : _error != null
                    ? AppErrorState(message: _error!, onRetry: _loadReports)
                    : _reports.isEmpty
                        ? const AppEmptyState(
                            icon: Icons.assignment_outlined,
                            title: '暂无维修日志',
                            subtitle: '新建日报后会在这里展示。',
                          )
                        : RefreshIndicator(
                            onRefresh: _loadReports,
                            child: ListView.builder(
                              padding: const EdgeInsets.fromLTRB(
                                AppTheme.pagePadding, 12, AppTheme.pagePadding, 100,
                              ),
                              itemCount: _reports.length,
                              itemBuilder: (context, index) => Padding(
                                padding: const EdgeInsets.only(bottom: AppTheme.itemGap),
                                child: _buildReportCard(_reports[index]),
                              ),
                            ),
                          ),
          ),
          Positioned(
            right: 16,
            bottom: 16,
            child: FloatingActionButton.small(
              heroTag: 'work-report-new',
              onPressed: () async {
                final result = await Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const WorkReportFormScreen()),
                );
                if (result == true) _loadReports();
              },
              child: const Icon(Icons.add),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildReportCard(Map<String, dynamic> report) {
    final totalFaults = report['total_faults'] ?? 0;
    final isDifficult = report['is_difficult'] ?? false;
    final isDifficultResolved = report['is_difficult_resolved'] ?? false;
    final locationName = report['location_name'] ?? '-';
    final workCategoryName = report['work_category_name'] ?? '-';
    final workerName = report['worker_name'] ?? '-';
    final remark = report['remark'] ?? '';

    return AppCard(
      padding: const EdgeInsets.all(AppTheme.pagePadding),
      child: InkWell(
        onTap: () => _showReportDetail(report),
        borderRadius: BorderRadius.circular(AppTheme.cardRadius),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // ID + date row
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                  decoration: BoxDecoration(
                    color: AppTheme.greenMedium,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    '#${report['id']}',
                    style: AppTheme.tsBadge.copyWith(color: Colors.white),
                  ),
                ),
                const SizedBox(width: 8),
                Icon(Icons.calendar_today, size: 14, color: AppTheme.textSecondary),
                const SizedBox(width: 4),
                Text(report['date'] ?? '-', style: AppTheme.tsLabel),
                const Spacer(),
                AppStatusBadge(
                  label: '故障 $totalFaults',
                  color: totalFaults > 0 ? AppTheme.greenMedium : AppTheme.textSecondary,
                ),
              ],
            ),
            const SizedBox(height: 8),
            // Location + category
            Row(
              children: [
                Icon(Icons.location_on, size: 14, color: AppTheme.textSecondary),
                const SizedBox(width: 2),
                Text(locationName, style: AppTheme.tsCaption),
                const SizedBox(width: 12),
                Icon(Icons.category, size: 14, color: AppTheme.textSecondary),
                const SizedBox(width: 2),
                Expanded(
                  child: Text(workCategoryName,
                      style: AppTheme.tsCaption, overflow: TextOverflow.ellipsis),
                ),
              ],
            ),
            const SizedBox(height: 6),
            // Worker + zone location
            Row(
              children: [
                Icon(Icons.person, size: 14, color: AppTheme.textSecondary),
                const SizedBox(width: 4),
                Text(workerName, style: AppTheme.tsCaption),
                if ((report['zone_location_display'] ?? '').isNotEmpty) ...[
                  const SizedBox(width: 12),
                  Icon(Icons.place, size: 14, color: AppTheme.textSecondary),
                  const SizedBox(width: 2),
                  Expanded(
                    child: Text(report['zone_location_display'],
                        style: AppTheme.tsCaption, overflow: TextOverflow.ellipsis),
                  ),
                ],
              ],
            ),
            // Remark preview
            if (remark.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(remark, maxLines: 1, overflow: TextOverflow.ellipsis, style: AppTheme.tsOverline),
            ],
            // Difficult badges
            if (isDifficult) ...[
              const SizedBox(height: 8),
              Row(
                children: [
                  _MiniBadge(label: '疑难', color: AppTheme.statusInProgress),
                  if (isDifficultResolved) ...[
                    const SizedBox(width: 4),
                    _MiniBadge(label: '已处理', color: AppTheme.statusCompleted),
                  ],
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  void _showReportDetail(Map<String, dynamic> report) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.7,
        minChildSize: 0.4,
        maxChildSize: 0.9,
        expand: false,
        builder: (context, scrollController) =>
            _buildDetailSheet(report, scrollController),
      ),
    );
  }

  Widget _buildDetailSheet(Map<String, dynamic> report, ScrollController controller) {
    final locationName = report['location_name'] ?? '-';
    final workCategoryName = report['work_category_name'] ?? '-';
    final workerName = report['worker_name'] ?? '-';
    final infoSourceName = report['info_source_name'] ?? '-';
    final faultEntries = report['fault_entries'] as List? ?? [];
    final isDifficult = report['is_difficult'] ?? false;
    final isDifficultResolved = report['is_difficult_resolved'] ?? false;
    final totalFaults = faultEntries.fold<int>(0, (sum, e) => sum + (e['count'] as int? ?? 0));
    final photoUrls = report['photo_urls'] as List? ?? [];

    return SingleChildScrollView(
      controller: controller,
      padding: const EdgeInsets.all(AppTheme.pagePadding),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Center(
            child: Container(
              width: 40, height: 4,
              decoration: BoxDecoration(
                color: Colors.grey.shade300,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          const SizedBox(height: 16),

          // Header
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: AppTheme.greenMedium,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text('#${report['id']}',
                    style: AppTheme.tsBadge.copyWith(color: Colors.white, fontSize: 13)),
              ),
              const SizedBox(width: 8),
              Text(report['date'] ?? '-', style: AppTheme.tsSectionTitle),
              const Spacer(),
              if (isDifficult)
                _MiniBadge(
                  label: isDifficultResolved ? '疑难已处理' : '疑难问题',
                  color: isDifficultResolved ? AppTheme.greenLight : AppTheme.accent,
                  icon: isDifficultResolved ? Icons.check_circle : Icons.warning,
                ),
              const SizedBox(width: 8),
              IconButton(
                icon: const Icon(Icons.edit_note, color: AppTheme.greenMedium),
                onPressed: () async {
                  Navigator.pop(context);
                  final result = await Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => WorkReportFormScreen(existingReport: report),
                    ),
                  );
                  if (result == true) _loadReports();
                },
                tooltip: '编辑',
              ),
            ],
          ),
          const SizedBox(height: AppTheme.sectionGap),

          // Basic info
          _DetailSection(
            icon: Icons.info_outline,
            title: '基本信息',
            rows: [
              _DetailSectionRow(Icons.calendar_today, '日期', report['date'] ?? '-'),
              _DetailSectionRow(Icons.wb_cloudy, '天气', report['weather'] ?? '未记录'),
              _DetailSectionRow(Icons.person_outline, '处理人', workerName),
            ],
          ),
          const SizedBox(height: AppTheme.itemGap),

          // Work info
          _DetailSection(
            icon: Icons.work_outline,
            title: '工作信息',
            rows: [
              _DetailSectionRow(Icons.location_on_outlined, '位置/CCU', locationName),
              _DetailSectionRow(Icons.category_outlined, '工作分类', workCategoryName),
              _DetailSectionRow(Icons.place_outlined, '故障位置', report['zone_location_display'] ?? '未指定'),
              _DetailSectionRow(Icons.source_outlined, '信息来源', infoSourceName.isNotEmpty ? infoSourceName : '未记录'),
            ],
          ),
          const SizedBox(height: AppTheme.itemGap),

          // Fault counts
          _DetailSection(
            icon: Icons.bug_report_outlined,
            title: '故障计数',
            trailing: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: AppTheme.greenDark,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text('总计 $totalFaults',
                  style: AppTheme.tsBadge.copyWith(color: Colors.white, fontSize: 13)),
            ),
            children: faultEntries.isEmpty
                ? [
                    Center(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Text('暂无故障记录', style: AppTheme.tsCaption),
                      ),
                    ),
                  ]
                : faultEntries.map((entry) {
                    final subName = entry['fault_subtype_name'] ?? '-';
                    final catName = entry['fault_category_name'] ?? '';
                    final count = entry['count'] ?? 0;
                    return _FaultRow(catName, subName, count);
                  }).toList(),
          ),
          const SizedBox(height: AppTheme.itemGap),

          // Remark
          _DetailSection(
            icon: Icons.notes_outlined,
            title: '备注/工作内容',
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: AppTheme.background,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(report['remark'] ?? '未填写备注',
                    style: AppTheme.tsBody.copyWith(height: 1.5)),
              ),
            ],
          ),

          // Photos
          if (photoUrls.isNotEmpty) ...[
            const SizedBox(height: AppTheme.itemGap),
            _DetailSection(
              icon: Icons.photo_library_outlined,
              title: '现场照片',
              trailing: Text('${photoUrls.length} 张',
                  style: AppTheme.tsCaption.copyWith(color: AppTheme.greenMedium, fontWeight: FontWeight.w600)),
              children: [
                SizedBox(
                  height: 100,
                  child: ListView.builder(
                    scrollDirection: Axis.horizontal,
                    itemCount: photoUrls.length,
                    itemBuilder: (context, index) => Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(10),
                        child: Image.network(
                          photoUrls[index],
                          width: 100, height: 100,
                          fit: BoxFit.cover,
                          errorBuilder: (_, __, ___) => Container(
                            width: 100, height: 100,
                            color: AppTheme.surfaceAlt,
                            child: const Icon(Icons.broken_image, color: AppTheme.textSecondary),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ],

          const SizedBox(height: 24),
        ],
      ),
    );
  }

  void _showFilterSheet() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (context) => StatefulBuilder(
        builder: (context, setSheetState) => SingleChildScrollView(
          padding: const EdgeInsets.all(AppTheme.pagePadding),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Center(
                child: Container(
                  width: 40, height: 4,
                  decoration: BoxDecoration(
                    color: Colors.grey.shade300,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Text('筛选', style: AppTheme.tsSectionTitle),
              const SizedBox(height: AppTheme.sectionGap),

              // Date range
              InkWell(
                onTap: () async {
                  final picked = await showDateRangePicker(
                    context: context,
                    firstDate: DateTime(2024, 1, 1),
                    lastDate: DateTime.now().add(const Duration(days: 7)),
                    initialDateRange: _dateFrom != null && _dateTo != null
                        ? DateTimeRange(start: _dateFrom!, end: _dateTo!)
                        : null,
                  );
                  if (picked != null) {
                    setSheetState(() {
                      _dateFrom = picked.start;
                      _dateTo = picked.end;
                    });
                    setState(() {
                      _dateFrom = picked.start;
                      _dateTo = picked.end;
                    });
                  }
                },
                child: InputDecorator(
                  decoration: const InputDecoration(
                    labelText: '日期范围',
                    suffixIcon: Icon(Icons.calendar_today_rounded),
                    border: OutlineInputBorder(),
                  ),
                  child: Text(
                    _dateFrom != null && _dateTo != null
                        ? '${DateFormat('yyyy-MM-dd').format(_dateFrom!)} ~ ${DateFormat('yyyy-MM-dd').format(_dateTo!)}'
                        : '--',
                    style: AppTheme.tsBody,
                  ),
                ),
              ),
              const SizedBox(height: AppTheme.fieldGap),

              DropdownButtonFormField<int>(
                value: _filterPatch,
                decoration: const InputDecoration(labelText: '分区', border: OutlineInputBorder()),
                items: [
                  const DropdownMenuItem<int>(value: null, child: Text('全部')),
                  ..._patches.map((p) => DropdownMenuItem<int>(
                      value: p['id'],
                      child: Text(p['name']))),
                ],
                onChanged: (v) {
                  setSheetState(() => _filterPatch = v);
                  setState(() => _filterPatch = v);
                },
              ),
              const SizedBox(height: AppTheme.fieldGap),

              DropdownButtonFormField<int>(
                value: _filterWorkCategory,
                decoration: const InputDecoration(labelText: '工作分类', border: OutlineInputBorder()),
                items: [
                  const DropdownMenuItem<int>(value: null, child: Text('全部')),
                  ..._workCategories.map((cat) => DropdownMenuItem<int>(
                      value: cat['id'], child: Text(cat['name']))),
                ],
                onChanged: (v) {
                  setSheetState(() => _filterWorkCategory = v);
                  setState(() => _filterWorkCategory = v);
                },
              ),
              const SizedBox(height: AppTheme.fieldGap),

              DropdownButtonFormField<int>(
                value: _filterZone,
                decoration: const InputDecoration(labelText: '区域', border: OutlineInputBorder()),
                items: [
                  const DropdownMenuItem<int>(value: null, child: Text('全部')),
                  ..._zones.map((z) => DropdownMenuItem<int>(
                      value: z.id, child: Text('${z.name} (${z.code})'))),
                ],
                onChanged: (v) {
                  setSheetState(() => _filterZone = v);
                  setState(() => _filterZone = v);
                },
              ),
              const SizedBox(height: AppTheme.fieldGap),

              if (widget.isAdmin && _workers.isNotEmpty) ...[
                DropdownButtonFormField<int>(
                  value: _filterWorker,
                  decoration: const InputDecoration(labelText: '处理人', border: OutlineInputBorder()),
                  items: [
                    const DropdownMenuItem<int>(value: null, child: Text('全部')),
                    ..._workers.map((w) => DropdownMenuItem<int>(
                        value: w['id'], child: Text(w['full_name'] ?? w['employee_id'] ?? '-'))),
                  ],
                  onChanged: (v) {
                    setSheetState(() => _filterWorker = v);
                    setState(() => _filterWorker = v);
                  },
                ),
                const SizedBox(height: AppTheme.fieldGap),
              ],

              CheckboxListTile(
                value: _filterDifficult,
                onChanged: (v) {
                  setSheetState(() => _filterDifficult = v ?? false);
                  setState(() => _filterDifficult = v ?? false);
                },
                title: const Text('仅疑难'),
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                dense: true,
              ),
              const SizedBox(height: AppTheme.fieldGap),

              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () {
                        final auth = context.read<AuthProvider>();
                        setState(() {
                          _dateFrom = DateTime(DateTime.now().year, DateTime.now().month, 1);
                          _dateTo = DateTime.now();
                          _filterPatch = null;
                          _filterWorkCategory = null;
                          _filterZone = null;
                          _filterWorker =
                              auth.isFieldWorker && auth.user != null ? auth.user!.id : null;
                          _filterDifficult = false;
                        });
                        Navigator.pop(context);
                        _loadReports();
                      },
                      child: const Text('重置'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton(
                      onPressed: () {
                        Navigator.pop(context);
                        _loadReports();
                      },
                      child: const Text('筛选'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ── Detail section card ─────────────────────────────────────────
class _DetailSection extends StatelessWidget {
  final IconData icon;
  final String title;
  final Widget? trailing;
  final List<Widget> children;
  final List<_DetailSectionRow>? rows;

  const _DetailSection({
    required this.icon,
    required this.title,
    this.trailing,
    this.children = const [],
    this.rows,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.outline),
        boxShadow: [
          BoxShadow(
            color: AppTheme.greenDarkest.withOpacity(0.06),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: AppTheme.surfaceAlt)),
            ),
            child: Row(
              children: [
                Container(
                  width: 28, height: 28,
                  decoration: BoxDecoration(
                    color: AppTheme.greenPrimary.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Icon(icon, size: 16, color: AppTheme.greenDark),
                ),
                const SizedBox(width: 10),
                Text(title, style: AppTheme.tsLabel),
                if (trailing != null) ...[const Spacer(), trailing!],
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (rows != null)
                  ...rows!.map((r) => Padding(
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        child: Row(
                          children: [
                            Icon(r.icon, size: 18, color: AppTheme.textSecondary),
                            const SizedBox(width: 8),
                            SizedBox(
                              width: 80,
                              child: Text(r.label, style: AppTheme.tsCaption),
                            ),
                            Expanded(
                              child: Text(r.value,
                                  style: AppTheme.tsBody.copyWith(fontWeight: FontWeight.w500)),
                            ),
                          ],
                        ),
                      )),
                ...children,
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _DetailSectionRow {
  final IconData icon;
  final String label;
  final String value;
  const _DetailSectionRow(this.icon, this.label, this.value);
}

// ── Mini badge ──────────────────────────────────────────────────
class _MiniBadge extends StatelessWidget {
  final String label;
  final Color color;
  final IconData? icon;

  const _MiniBadge({required this.label, required this.color, this.icon});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 13, color: color),
            const SizedBox(width: 3),
          ],
          Text(label, style: AppTheme.tsOverline.copyWith(color: color, fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}

// ── Fault entry row ─────────────────────────────────────────────
class _FaultRow extends StatelessWidget {
  final String categoryName;
  final String subTypeName;
  final int count;

  const _FaultRow(this.categoryName, this.subTypeName, this.count);

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppTheme.background,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.outline),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (categoryName.isNotEmpty)
                  Text(categoryName, style: AppTheme.tsOverline),
                Text(subTypeName, style: AppTheme.tsBody.copyWith(fontWeight: FontWeight.w500)),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
            decoration: BoxDecoration(
              color: AppTheme.greenMedium,
              borderRadius: BorderRadius.circular(20),
            ),
            child: Text('$count',
                style: AppTheme.tsBadge.copyWith(color: Colors.white, fontSize: 14)),
          ),
        ],
      ),
    );
  }
}
