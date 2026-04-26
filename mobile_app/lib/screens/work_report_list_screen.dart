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
      body: Stack(
        children: [
          AppBackground(
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
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 140),
                      itemCount: _reports.length,
                      itemBuilder: (context, index) => Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: _buildReportCard(_reports[index]),
                      ),
                    ),
                  ),
          ),
          Positioned(
            right: 16,
            bottom: 88,
            child: FloatingActionButton(
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
          ),
        ],
      ),
    );
  }

  Widget _buildReportCard(Map<String, dynamic> report) {
    final totalFaults = report['total_faults'] ?? 0;
    final isDifficult = report['is_difficult'] ?? false;
    final isDifficultResolved = report['is_difficult_resolved'] ?? false;
    // API returns: location (ID), location_name (string)
    final locationName = report['location_name'] ?? '-';
    final workCategoryName = report['work_category_name'] ?? '-';
    final workerName = report['worker_name'] ?? '-';
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
              // ID badge + date row
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                    decoration: BoxDecoration(
                      color: const Color(0xFF40916C),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      '#${report['id']}',
                      style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w700,
                        fontSize: 11,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
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
                  const Spacer(),
                  AppStatusBadge(
                    label: '故障 $totalFaults',
                    color: totalFaults > 0
                        ? const Color(0xFF40916C)
                        : Colors.grey,
                  ),
                ],
              ),
              const SizedBox(height: 6),
              // Row 2: location, category
              Row(
                children: [
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
              // Row 2: worker, zone location
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
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Handle bar
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

          // Header with ID and badges
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: const Color(0xFF40916C),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  '#${report['id']}',
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w700,
                    fontSize: 12,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Text(
                report['date'] ?? '-',
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                  color: Color(0xFF1B4332),
                ),
              ),
              const Spacer(),
              if (isDifficult)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: isDifficultResolved ? const Color(0xFF52B788) : const Color(0xFFE3A85B),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        isDifficultResolved ? Icons.check_circle : Icons.warning,
                        size: 14,
                        color: Colors.white,
                      ),
                      const SizedBox(width: 4),
                      Text(
                        isDifficultResolved ? '疑难已处理' : '疑难问题',
                        style: const TextStyle(color: Colors.white, fontSize: 12),
                      ),
                    ],
                  ),
                ),
              const SizedBox(width: 8),
              IconButton(
                icon: const Icon(Icons.edit_note, color: Color(0xFF40916C)),
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
          const SizedBox(height: 16),

          // 基本信息卡片
          _buildDetailCard(
            title: '基本信息',
            icon: Icons.info_outline,
            children: [
              _buildDetailRow(Icons.calendar_today, '日期', report['date'] ?? '-'),
              _buildDetailRow(Icons.wb_cloudy, '天气', report['weather'] ?? '未记录'),
              _buildDetailRow(Icons.person_outline, '处理人', workerName),
            ],
          ),
          const SizedBox(height: 12),

          // 工作信息卡片
          _buildDetailCard(
            title: '工作信息',
            icon: Icons.work_outline,
            children: [
              _buildDetailRow(Icons.location_on_outlined, '位置/CCU', locationName),
              _buildDetailRow(Icons.category_outlined, '工作分类', workCategoryName),
              _buildDetailRow(Icons.place_outlined, '故障位置', report['zone_location_display'] ?? '未指定'),
              _buildDetailRow(Icons.source_outlined, '信息来源', infoSourceName.isNotEmpty ? infoSourceName : '未记录'),
            ],
          ),
          const SizedBox(height: 12),

          // 故障计数卡片
          _buildDetailCard(
            title: '故障计数',
            icon: Icons.bug_report_outlined,
            trailing: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: const Color(0xFF2D6A4F),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                '总计 $totalFaults',
                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 13),
              ),
            ),
            children: faultEntries.isEmpty
                ? [
                    Center(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Text('暂无故障记录', style: TextStyle(color: Colors.grey.shade500)),
                      ),
                    ),
                  ]
                : faultEntries.map((entry) {
                    final subName = entry['fault_subtype_name'] ?? '-';
                    final catName = entry['fault_category_name'] ?? '';
                    final count = entry['count'] ?? 0;
                    return _buildFaultEntryRow(catName, subName, count);
                  }).toList(),
          ),
          const SizedBox(height: 12),

          // 备注卡片
          _buildDetailCard(
            title: '备注/工作内容',
            icon: Icons.notes_outlined,
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: Colors.grey.shade50,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  report['remark'] ?? '未填写备注',
                  style: const TextStyle(fontSize: 14, height: 1.5),
                ),
              ),
            ],
          ),

          // 照片区域
          if (photoUrls.isNotEmpty) ...[
            const SizedBox(height: 12),
            _buildDetailCard(
              title: '现场照片',
              icon: Icons.photo_library_outlined,
              trailing: Text(
                '${photoUrls.length} 张',
                style: const TextStyle(color: Color(0xFF40916C), fontWeight: FontWeight.w600),
              ),
              children: [
                SizedBox(
                  height: 100,
                  child: ListView.builder(
                    scrollDirection: Axis.horizontal,
                    itemCount: photoUrls.length,
                    itemBuilder: (context, index) {
                      return Container(
                        margin: const EdgeInsets.only(right: 8),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(8),
                          child: Image.network(
                            photoUrls[index],
                            width: 100,
                            height: 100,
                            fit: BoxFit.cover,
                            errorBuilder: (_, __, ___) => Container(
                              width: 100,
                              height: 100,
                              color: Colors.grey.shade200,
                              child: const Icon(Icons.broken_image, color: Colors.grey),
                            ),
                          ),
                        ),
                      );
                    },
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

  Widget _buildDetailCard({
    required String title,
    required IconData icon,
    Widget? trailing,
    required List<Widget> children,
  }) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFD8E8E0)),
        boxShadow: [
          BoxShadow(
            color: const Color(0xFF1B4332).withOpacity(0.06),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Card header
          Container(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: Color(0xFFE8F0EA))),
            ),
            child: Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(6),
                  decoration: BoxDecoration(
                    color: const Color(0xFF40916C).withOpacity(0.12),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Icon(icon, size: 18, color: const Color(0xFF2D6A4F)),
                ),
                const SizedBox(width: 10),
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: Color(0xFF1B4332),
                  ),
                ),
                if (trailing != null) ...[
                  const Spacer(),
                  trailing,
                ],
              ],
            ),
          ),
          // Card content
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: children,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildDetailRow(IconData icon, String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        children: [
          Icon(icon, size: 18, color: const Color(0xFF52796F)),
          const SizedBox(width: 8),
          SizedBox(
            width: 80,
            child: Text(
              label,
              style: const TextStyle(
                fontSize: 13,
                color: Color(0xFF52796F),
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w500,
                color: Color(0xFF1B4332),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildFaultEntryRow(String categoryName, String subTypeName, int count) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFF7FAF8),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFE0EBE5)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (categoryName.isNotEmpty)
                  Text(
                    categoryName,
                    style: TextStyle(
                      fontSize: 11,
                      color: Colors.grey.shade500,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                Text(
                  subTypeName,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w500,
                    color: Color(0xFF1B4332),
                  ),
                ),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
            decoration: BoxDecoration(
              color: const Color(0xFF40916C),
              borderRadius: BorderRadius.circular(20),
            ),
            child: Text(
              '$count',
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w700,
                fontSize: 14,
              ),
            ),
          ),
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
