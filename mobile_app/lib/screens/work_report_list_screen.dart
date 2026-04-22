import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/auth_provider.dart';
import '../models/zone.dart';
import 'work_report_form_screen.dart';
import '../widgets/modern_ui.dart';

class WorkReportListScreen extends StatefulWidget {
  final bool isAdmin;

  const WorkReportListScreen({super.key, this.isAdmin = false});

  @override
  State<WorkReportListScreen> createState() => _WorkReportListScreenState();
}

class _WorkReportListScreenState extends State<WorkReportListScreen> {
  List<Map<String, dynamic>> _reports = [];
  List<Map<String, dynamic>> _locations = [];
  List<Map<String, dynamic>> _workCategories = [];
  List<Map<String, dynamic>> _zones = [];
  List<Map<String, dynamic>> _workers = [];
  bool _isLoading = true;
  String? _error;

  // Filter state
  DateTime? _dateFrom;
  DateTime? _dateTo;
  int? _filterLocation;
  int? _filterWorkCategory;
  int? _filterZone;
  int? _filterWorker;
  bool _filterDifficult = false;

  @override
  void initState() {
    super.initState();
    // Default: show current month
    final now = DateTime.now();
    _dateFrom = DateTime(now.year, now.month, 1);
    _dateTo = now;
    _loadFilters().then((_) => _loadReports());
  }

  Future<void> _loadFilters() async {
    try {
      final api = context.read<AuthProvider>().api;
      final auth = context.read<AuthProvider>();

      // For field workers, auto-set worker filter to themselves
      if (auth.isFieldWorker && auth.user != null) {
        _filterWorker = auth.user!.id;
      }

      final futures = <Future>[
        api.getLocations(),
        api.getWorkCategories(),
        api.getZones(),
      ];

      // Only load workers list for admin users
      if (auth.isAdmin) {
        futures.add(api.getWorkers());
      }

      final results = await Future.wait(futures);
      if (mounted) {
        setState(() {
          _locations = results[0];
          _workCategories = results[1];
          _zones = results[2]
              .map<Zone>((z) => z as Zone)
              .map(
                (zone) => {'id': zone.id, 'name': zone.name, 'code': zone.code},
              )
              .toList();
          if (results.length > 3) {
            _workers = results[3];
          }
        });
      }
    } catch (e) {
      // Filters not loaded - dropdowns will be empty
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
        dateFrom: _dateFrom != null
            ? DateFormat('yyyy-MM-dd').format(_dateFrom!)
            : null,
        dateTo: _dateTo != null
            ? DateFormat('yyyy-MM-dd').format(_dateTo!)
            : null,
        location: _filterLocation,
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
        title: const Text('维修工作日报'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _loadReports),
          IconButton(
            icon: const Icon(Icons.filter_list),
            onPressed: _showFilterSheet,
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () async {
          final result = await Navigator.push(
            context,
            MaterialPageRoute(builder: (_) => const WorkReportFormScreen()),
          );
          if (result == true) _loadReports();
        },
        backgroundColor: const Color(0xFF40916C),
        child: const Icon(Icons.add, color: Colors.white),
      ),
      body: AppBackground(
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
            ? AppErrorState(message: _error!, onRetry: _loadReports)
            : _reports.isEmpty
            ? const AppEmptyState(
                icon: Icons.assignment_outlined,
                title: '暂无工作日报记录',
                subtitle: '新建日报后会在这里展示。',
              )
            : RefreshIndicator(
                onRefresh: _loadReports,
                child: ListView.builder(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 96),
                  itemCount: _reports.length,
                  itemBuilder: (context, index) => Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: _buildReportCard(_reports[index]),
                  ),
                ),
              ),
      ),
    );
  }

  Widget _buildReportCard(Map<String, dynamic> report) {
    final totalFaults = report['total_faults'] ?? 0;
    final isDifficult = report['is_difficult'] ?? false;
    final isDifficultResolved = report['is_difficult_resolved'] ?? false;
    final locationName = report['location'] is Map
        ? report['location']['name'] ?? '-'
        : '-';
    final workCategoryName = report['work_category'] is Map
        ? report['work_category']['name'] ?? '-'
        : '-';
    final workerName = report['worker'] is Map
        ? report['worker']['full_name'] ?? '-'
        : '-';
    final remark = report['remark'] ?? '';

    return AppCard(
      padding: const EdgeInsets.all(16),
      child: InkWell(
        onTap: () => _showReportDetail(report),
        borderRadius: BorderRadius.circular(24),
        child: Padding(
          padding: EdgeInsets.zero,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Row 1: date, location, category
              Row(
                children: [
                  Icon(
                    Icons.calendar_today,
                    size: 14,
                    color: Colors.grey.shade600,
                  ),
                  const SizedBox(width: 4),
                  Text(
                    report['date'] ?? '-',
                    style: const TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 14,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Icon(
                    Icons.location_on,
                    size: 14,
                    color: Colors.grey.shade600,
                  ),
                  const SizedBox(width: 2),
                  Text(locationName, style: const TextStyle(fontSize: 13)),
                  const SizedBox(width: 12),
                  Icon(Icons.category, size: 14, color: Colors.grey.shade600),
                  const SizedBox(width: 2),
                  Expanded(
                    child: Text(
                      workCategoryName,
                      style: const TextStyle(fontSize: 13),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              // Row 2: worker, zone location, fault count
              Row(
                children: [
                  Icon(Icons.person, size: 14, color: Colors.grey.shade600),
                  const SizedBox(width: 4),
                  Text(
                    workerName,
                    style: TextStyle(fontSize: 13, color: Colors.grey.shade700),
                  ),
                  if ((report['zone_location_display'] ?? '').isNotEmpty) ...[
                    const SizedBox(width: 12),
                    Icon(Icons.place, size: 14, color: Colors.grey.shade600),
                    const SizedBox(width: 2),
                    Text(
                      report['zone_location_display'],
                      style: TextStyle(
                        fontSize: 13,
                        color: Colors.grey.shade700,
                      ),
                    ),
                  ],
                  const Spacer(),
                  AppStatusBadge(
                    label: '故障 $totalFaults',
                    color: totalFaults > 0
                        ? const Color(0xFF40916C)
                        : Colors.grey,
                  ),
                ],
              ),
              // Remark preview
              if (remark.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text(
                  remark,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
                ),
              ],
              // Difficult indicator
              if (isDifficult) ...[
                const SizedBox(height: 6),
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 6,
                        vertical: 2,
                      ),
                      decoration: BoxDecoration(
                        color: const Color(0xFFCC7722).withOpacity(0.15),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: const Text(
                        '疑难',
                        style: TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                          color: Color(0xFFCC7722),
                        ),
                      ),
                    ),
                    if (isDifficultResolved) ...[
                      const SizedBox(width: 4),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: const Color(0xFF40916C).withOpacity(0.15),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: const Text(
                          '已处理',
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                            color: Color(0xFF40916C),
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  void _showReportDetail(Map<String, dynamic> report) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
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

  Widget _buildDetailSheet(
    Map<String, dynamic> report,
    ScrollController controller,
  ) {
    final locationName = report['location'] is Map
        ? report['location']['name'] ?? '-'
        : '-';
    final workCategoryName = report['work_category'] is Map
        ? report['work_category']['name'] ?? '-'
        : '-';
    final workerName = report['worker'] is Map
        ? report['worker']['full_name'] ?? '-'
        : '-';
    final infoSourceName = report['info_source'] is Map
        ? report['info_source']['name'] ?? '-'
        : '-';
    final faultEntries = report['fault_entries'] as List? ?? [];
    final isDifficult = report['is_difficult'] ?? false;
    final isDifficultResolved = report['is_difficult_resolved'] ?? false;

    return SingleChildScrollView(
      controller: controller,
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Center(
            child: Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: Colors.grey.shade300,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                '日报详情 #${report['id']}',
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                  color: Color(0xFF1B4332),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.edit),
                onPressed: () async {
                  Navigator.pop(context);
                  final result = await Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) =>
                          WorkReportFormScreen(existingReport: report),
                    ),
                  );
                  if (result == true) _loadReports();
                },
              ),
            ],
          ),
          const SizedBox(height: 12),

          _buildInfoGrid([
            _InfoItem(Icons.calendar_today, '日期', report['date'] ?? '-'),
            _InfoItem(Icons.wb_cloudy, '天气', report['weather'] ?? '-'),
            _InfoItem(Icons.person, '处理人', workerName),
            _InfoItem(Icons.location_on, '位置', locationName),
            _InfoItem(Icons.category, '工作分类', workCategoryName),
            _InfoItem(
              Icons.place,
              '故障位置',
              report['zone_location_display'] ?? '-',
            ),
            _InfoItem(Icons.info_outline, '信息来源', infoSourceName),
            _InfoItem(
              isDifficult ? Icons.warning : Icons.check_circle,
              '疑难问题',
              isDifficult ? (isDifficultResolved ? '是 (已处理)' : '是 (未处理)') : '否',
            ),
          ]),

          const SizedBox(height: 16),
          const Text(
            '备注/工作内容',
            style: TextStyle(
              fontWeight: FontWeight.w600,
              color: Color(0xFF1B4332),
            ),
          ),
          const SizedBox(height: 4),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.grey.shade50,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.grey.shade200),
            ),
            child: Text(
              report['remark'] ?? '',
              style: const TextStyle(fontSize: 14),
            ),
          ),

          if (faultEntries.isNotEmpty) ...[
            const SizedBox(height: 16),
            const Text(
              '故障计数',
              style: TextStyle(
                fontWeight: FontWeight.w600,
                color: Color(0xFF1B4332),
              ),
            ),
            const SizedBox(height: 8),
            ...faultEntries.map((entry) {
              final subName = entry['fault_subtype'] is Map
                  ? entry['fault_subtype']['name_zh'] ?? '-'
                  : '-';
              final catName = entry['fault_subtype'] is Map
                  ? (entry['fault_subtype']['category'] is Map
                        ? entry['fault_subtype']['category']['name_zh'] ?? ''
                        : '')
                  : '';
              final count = entry['count'] ?? 0;
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  children: [
                    if (catName.isNotEmpty) ...[
                      Text(
                        catName,
                        style: TextStyle(
                          fontSize: 12,
                          color: Colors.grey.shade600,
                        ),
                      ),
                      const Text(
                        ' / ',
                        style: TextStyle(fontSize: 12, color: Colors.grey),
                      ),
                    ],
                    Expanded(
                      child: Text(
                        subName,
                        style: const TextStyle(fontSize: 13),
                      ),
                    ),
                    Text(
                      '$count',
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 14,
                        color: Color(0xFF40916C),
                      ),
                    ),
                  ],
                ),
              );
            }),
          ],
        ],
      ),
    );
  }

  Widget _buildInfoGrid(List<_InfoItem> items) {
    return Wrap(
      spacing: 16,
      runSpacing: 8,
      children: items.map((item) {
        return Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(item.icon, size: 14, color: Colors.grey.shade600),
            const SizedBox(width: 4),
            Text(
              '${item.label}: ',
              style: TextStyle(fontSize: 13, color: Colors.grey.shade600),
            ),
            Flexible(
              child: Text(
                item.value,
                style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w500,
                ),
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        );
      }).toList(),
    );
  }

  void _showFilterSheet() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => StatefulBuilder(
        builder: (context, setSheetState) => SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Center(
                child: Container(
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: Colors.grey.shade300,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              const Text(
                '筛选',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 16),

              Row(
                children: [
                  Expanded(
                    child: InkWell(
                      onTap: () async {
                        final picked = await showDatePicker(
                          context: context,
                          initialDate: _dateFrom ?? DateTime.now(),
                          firstDate: DateTime(2024, 1, 1),
                          lastDate: DateTime.now().add(const Duration(days: 7)),
                        );
                        if (picked != null) {
                          setSheetState(() => _dateFrom = picked);
                          setState(() => _dateFrom = picked);
                        }
                      },
                      child: InputDecorator(
                        decoration: const InputDecoration(
                          labelText: '起始日期',
                          border: OutlineInputBorder(),
                        ),
                        child: Text(
                          _dateFrom != null
                              ? DateFormat('yyyy-MM-dd').format(_dateFrom!)
                              : '--',
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: InkWell(
                      onTap: () async {
                        final picked = await showDatePicker(
                          context: context,
                          initialDate: _dateTo ?? DateTime.now(),
                          firstDate: DateTime(2024, 1, 1),
                          lastDate: DateTime.now().add(const Duration(days: 7)),
                        );
                        if (picked != null) {
                          setSheetState(() => _dateTo = picked);
                          setState(() => _dateTo = picked);
                        }
                      },
                      child: InputDecorator(
                        decoration: const InputDecoration(
                          labelText: '截止日期',
                          border: OutlineInputBorder(),
                        ),
                        child: Text(
                          _dateTo != null
                              ? DateFormat('yyyy-MM-dd').format(_dateTo!)
                              : '--',
                        ),
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),

              DropdownButtonFormField<int>(
                value: _filterLocation,
                decoration: const InputDecoration(
                  labelText: '位置/CCU',
                  border: OutlineInputBorder(),
                ),
                items: [
                  const DropdownMenuItem<int>(value: null, child: Text('全部')),
                  ..._locations.map(
                    (loc) => DropdownMenuItem<int>(
                      value: loc['id'],
                      child: Text(loc['name']),
                    ),
                  ),
                ],
                onChanged: (v) {
                  setSheetState(() => _filterLocation = v);
                  setState(() => _filterLocation = v);
                },
              ),
              const SizedBox(height: 12),

              DropdownButtonFormField<int>(
                value: _filterWorkCategory,
                decoration: const InputDecoration(
                  labelText: '工作分类',
                  border: OutlineInputBorder(),
                ),
                items: [
                  const DropdownMenuItem<int>(value: null, child: Text('全部')),
                  ..._workCategories.map(
                    (cat) => DropdownMenuItem<int>(
                      value: cat['id'],
                      child: Text(cat['name']),
                    ),
                  ),
                ],
                onChanged: (v) {
                  setSheetState(() => _filterWorkCategory = v);
                  setState(() => _filterWorkCategory = v);
                },
              ),
              const SizedBox(height: 12),

              DropdownButtonFormField<int>(
                value: _filterZone,
                decoration: const InputDecoration(
                  labelText: '区域',
                  border: OutlineInputBorder(),
                ),
                items: [
                  const DropdownMenuItem<int>(value: null, child: Text('全部')),
                  ..._zones.map(
                    (z) => DropdownMenuItem<int>(
                      value: z['id'],
                      child: Text('${z['name']} (${z['code']})'),
                    ),
                  ),
                ],
                onChanged: (v) {
                  setSheetState(() => _filterZone = v);
                  setState(() => _filterZone = v);
                },
              ),
              const SizedBox(height: 12),

              // Worker filter - only for admin
              if (widget.isAdmin && _workers.isNotEmpty)
                DropdownButtonFormField<int>(
                  value: _filterWorker,
                  decoration: const InputDecoration(
                    labelText: '处理人',
                    border: OutlineInputBorder(),
                  ),
                  items: [
                    const DropdownMenuItem<int>(value: null, child: Text('全部')),
                    ..._workers.map(
                      (w) => DropdownMenuItem<int>(
                        value: w['id'],
                        child: Text(w['full_name'] ?? w['employee_id'] ?? '-'),
                      ),
                    ),
                  ],
                  onChanged: (v) {
                    setSheetState(() => _filterWorker = v);
                    setState(() => _filterWorker = v);
                  },
                ),
              if (widget.isAdmin && _workers.isNotEmpty)
                const SizedBox(height: 12),

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
              const SizedBox(height: 12),

              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () {
                        final auth = context.read<AuthProvider>();
                        setState(() {
                          _dateFrom = DateTime(
                            DateTime.now().year,
                            DateTime.now().month,
                            1,
                          );
                          _dateTo = DateTime.now();
                          _filterLocation = null;
                          _filterWorkCategory = null;
                          _filterZone = null;
                          _filterWorker =
                              auth.isFieldWorker && auth.user != null
                              ? auth.user!.id
                              : null;
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
                      style: FilledButton.styleFrom(
                        backgroundColor: const Color(0xFF40916C),
                      ),
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

class _InfoItem {
  final IconData icon;
  final String label;
  final String value;
  _InfoItem(this.icon, this.label, this.value);
}
