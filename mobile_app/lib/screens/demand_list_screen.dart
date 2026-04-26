import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../services/api_service.dart';
import '../models/user.dart';
import 'demand_form_screen.dart';
import '../widgets/modern_ui.dart';

class DemandListScreen extends StatefulWidget {
  final User user;
  final ApiService apiService;

  const DemandListScreen({
    super.key,
    required this.user,
    required this.apiService,
  });

  @override
  State<DemandListScreen> createState() => _DemandListScreenState();
}

class _DemandListScreenState extends State<DemandListScreen> {
  List<Map<String, dynamic>> _demands = [];
  bool _isLoading = true;
  String? _error;

  String? _selectedStatus;
  DateTime? _dateFrom;
  DateTime? _dateTo;

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _dateFrom = DateTime(now.year, now.month, 1);
    _dateTo = now;
    _loadDemands();
  }

  Future<void> _loadDemands() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final demands = await widget.apiService.getDemandRecords(
        dateFrom: _dateFrom != null ? DateFormat('yyyy-MM-dd').format(_dateFrom!) : null,
        dateTo: _dateTo != null ? DateFormat('yyyy-MM-dd').format(_dateTo!) : null,
        status: _selectedStatus,
      );
      setState(() {
        _demands = demands;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final canCreate = widget.user.role == 'dept_user' ||
        widget.user.role == 'manager' ||
        widget.user.role == 'super_admin';

    return Scaffold(
      appBar: AppBar(
        title: const Text('需求日志'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            onPressed: _loadDemands,
          ),
        ],
      ),
      body: Stack(
        children: [
          AppBackground(
            child: Column(
              children: [
                // ── Filter bar ─────────────────────────────────────
                Padding(
                  padding: const EdgeInsets.fromLTRB(
                    AppTheme.pagePadding, 12, AppTheme.pagePadding, 8,
                  ),
                  child: AppCard(
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                    child: Row(
                      children: [
                        // Date range picker
                        _FilterChip(
                          icon: Icons.calendar_today_outlined,
                          label: _dateFrom != null && _dateTo != null
                              ? '${DateFormat('MM-dd').format(_dateFrom!)} ~ ${DateFormat('MM-dd').format(_dateTo!)}'
                              : '选择日期',
                          onTap: () async {
                            final picked = await showDateRangePicker(
                              context: context,
                              firstDate: DateTime(2020),
                              lastDate: DateTime(2030),
                              initialDateRange: _dateFrom != null && _dateTo != null
                                  ? DateTimeRange(start: _dateFrom!, end: _dateTo!)
                                  : DateTimeRange(start: DateTime.now().subtract(const Duration(days: 6)), end: DateTime.now()),
                            );
                            if (picked != null) {
                              setState(() {
                                _dateFrom = picked.start;
                                _dateTo = picked.end;
                              });
                              _loadDemands();
                            }
                          },
                        ),
                        const SizedBox(width: 8),
                        // Clear date range
                        if (_dateFrom != null) ...[
                          GestureDetector(
                            onTap: () {
                              setState(() {
                                _dateFrom = null;
                                _dateTo = null;
                              });
                              _loadDemands();
                            },
                            child: const Icon(Icons.close, size: 16, color: AppTheme.textSecondary),
                          ),
                          const SizedBox(width: 8),
                        ],
                        // Status filter
                        _FilterChip(
                          icon: Icons.filter_list_rounded,
                          label: _selectedStatus != null
                              ? _statusLabel(_selectedStatus!)
                              : '全部状态',
                          onTap: () => _showStatusFilter(),
                        ),
                        if (_selectedStatus != null) ...[
                          const SizedBox(width: 6),
                          GestureDetector(
                            onTap: () {
                              setState(() => _selectedStatus = null);
                              _loadDemands();
                            },
                            child: const Icon(Icons.close, size: 16, color: AppTheme.textSecondary),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
                // ── List body ──────────────────────────────────────
                Expanded(
                  child: _isLoading
                      ? const AppSkeletonList()
                      : _error != null
                          ? AppErrorState(message: '错误: $_error', onRetry: _loadDemands)
                          : _demands.isEmpty
                              ? const AppEmptyState(
                                  icon: Icons.event_note_outlined,
                                  title: '暂无需求记录',
                                  subtitle: '新建需求后会出现在这里。',
                                )
                              : RefreshIndicator(
                                  onRefresh: _loadDemands,
                                  child: ListView.builder(
                                    padding: const EdgeInsets.fromLTRB(
                                      AppTheme.pagePadding, 4, AppTheme.pagePadding, 100,
                                    ),
                                    itemCount: _demands.length,
                                    itemBuilder: (context, index) {
                                      final demand = _demands[index];
                                      return Padding(
                                        padding: const EdgeInsets.only(bottom: AppTheme.itemGap),
                                        child: _DemandCard(
                                          demand: demand,
                                          onTap: () => _showDemandDetail(demand),
                                        ),
                                      );
                                    },
                                  ),
                                ),
                ),
              ],
            ),
          ),
          if (canCreate)
            Positioned(
              right: 16,
              bottom: 16,
              child: FloatingActionButton.small(
                heroTag: 'demand-new',
                onPressed: () async {
                  final result = await Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => DemandFormScreen(
                        user: widget.user,
                        apiService: widget.apiService,
                      ),
                    ),
                  );
                  if (result == true) _loadDemands();
                },
                child: const Icon(Icons.add),
              ),
            ),
        ],
      ),
    );
  }

  String _statusLabel(String status) {
    switch (status) {
      case 'submitted': return '已提交';
      case 'approved': return '已批准';
      case 'rejected': return '已拒绝';
      case 'in_progress': return '进行中';
      case 'completed': return '已完成';
      default: return status;
    }
  }

  void _showStatusFilter() {
    final options = [
      ('submitted', '已提交'),
      ('approved', '已批准'),
      ('rejected', '已拒绝'),
      ('in_progress', '进行中'),
      ('completed', '已完成'),
    ];
    showModalBottomSheet(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
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
              child: Text('筛选状态', style: AppTheme.tsSectionTitle),
            ),
            const SizedBox(height: 12),
            ...options.map((o) => ListTile(
              leading: Container(
                width: 10, height: 10,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: AppTheme.statusColor(o.$1),
                ),
              ),
              title: Text(o.$2, style: AppTheme.tsBody),
              trailing: _selectedStatus == o.$1
                  ? const Icon(Icons.check, color: AppTheme.greenMedium)
                  : null,
              onTap: () {
                Navigator.pop(ctx);
                setState(() => _selectedStatus = o.$1);
                _loadDemands();
              },
            )),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }

  void _showDemandDetail(Map<String, dynamic> demand) {
    final status = demand['status'] ?? '';
    final statusColor = AppTheme.statusColor(status);

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.7,
        minChildSize: 0.5,
        maxChildSize: 0.95,
        expand: false,
        builder: (context, scrollController) => SingleChildScrollView(
          controller: scrollController,
          padding: const EdgeInsets.all(AppTheme.pagePadding),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Handle bar
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

              // Header row
              Row(
                children: [
                  Expanded(
                    child: Text(
                      demand['zone_name'] ?? demand['zone_text'] ?? '全局事件',
                      style: AppTheme.tsSectionTitle,
                    ),
                  ),
                  AppStatusBadge(
                    label: demand['status_display'] ?? '-',
                    color: statusColor,
                  ),
                ],
              ),
              const SizedBox(height: AppTheme.sectionGap),

              // Basic info card
              _DetailCard(
                icon: Icons.info_outline_rounded,
                title: '基本信息',
                children: [
                  _DetailRow(Icons.calendar_today, '日期', demand['date'] ?? '-'),
                  _DetailRow(Icons.place_outlined, '区域',
                      demand['zone_name'] ?? demand['zone_text'] ?? '全局事件'),
                  _DetailRow(Icons.category_outlined, '类别',
                      demand['category_name'] ?? demand['category_text'] ?? '-'),
                  _DetailRow(Icons.schedule_outlined, '时间段',
                      demand['time_display'] ?? '-'),
                  _DetailRow(Icons.flag_outlined, '状态',
                      demand['status_display'] ?? '-'),
                ],
              ),
              const SizedBox(height: AppTheme.itemGap),

              // Contact info card
              _DetailCard(
                icon: Icons.people_outline_rounded,
                title: '联系信息',
                children: [
                  _DetailRow(Icons.apartment_outlined, '提出部门',
                      demand['demand_department_name'] ?? demand['demand_department_text'] ?? '-'),
                  _DetailRow(Icons.person_outline, '联系人',
                      demand['demand_contact'] ?? '-'),
                ],
              ),
              const SizedBox(height: AppTheme.itemGap),

              // Content card
              _DetailCard(
                icon: Icons.description_outlined,
                title: '需求内容',
                children: [
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: AppTheme.background,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      demand['content'] ?? demand['original_text'] ?? '-',
                      style: AppTheme.tsBody.copyWith(height: 1.6),
                    ),
                  ),
                ],
              ),

              // Admin status update
              if (widget.user.role == 'manager' ||
                  widget.user.role == 'super_admin') ...[
                const SizedBox(height: AppTheme.sectionGap),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: () => _updateStatus(demand['id']),
                    icon: const Icon(Icons.edit_note_rounded),
                    label: const Text('更新状态'),
                  ),
                ),
              ],

              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _updateStatus(int demandId) async {
    final statuses = [
      ('approved', '已批准'),
      ('rejected', '已拒绝'),
      ('in_progress', '进行中'),
      ('completed', '已完成'),
    ];

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('选择状态'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: statuses
              .map((s) => ListTile(
                    leading: Container(
                      width: 10, height: 10,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: AppTheme.statusColor(s.$1),
                      ),
                    ),
                    title: Text(s.$2),
                    onTap: () async {
                      Navigator.pop(context);
                      try {
                        await widget.apiService.updateDemandRecord(
                          id: demandId,
                          status: s.$1,
                        );
                        if (this.context.mounted) {
                          Navigator.pop(this.context); // Close detail sheet
                          _loadDemands();
                        }
                      } catch (e) {
                        if (this.context.mounted) {
                          ScaffoldMessenger.of(this.context).showSnackBar(
                            SnackBar(content: Text('更新失败: $e')),
                          );
                        }
                      }
                    },
                  ))
              .toList(),
        ),
      ),
    );
  }
}

// ── Filter chip widget ──────────────────────────────────────────
class _FilterChip extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  const _FilterChip({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: BoxDecoration(
            color: AppTheme.surfaceAlt.withOpacity(0.5),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 16, color: AppTheme.greenPrimary),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  label,
                  style: AppTheme.tsCaption,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ── Demand card ─────────────────────────────────────────────────
class _DemandCard extends StatelessWidget {
  final Map<String, dynamic> demand;
  final VoidCallback onTap;

  const _DemandCard({required this.demand, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final statusColor = AppTheme.statusColor(demand['status'] ?? '');

    return AppCard(
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Title row
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(
                  demand['zone_name'] ?? demand['zone_text'] ?? '全局事件',
                  style: AppTheme.tsSubtitle,
                ),
              ),
              const SizedBox(width: 12),
              AppStatusBadge(
                label: demand['status_display'] ?? '-',
                color: statusColor,
              ),
            ],
          ),
          const SizedBox(height: 10),
          // Content preview
          Text(
            demand['content'] ?? '',
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.tsCaption,
          ),
          const SizedBox(height: 12),
          // Meta chips
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              AppMetaChip(
                icon: Icons.calendar_today_outlined,
                text: demand['date'] ?? '-',
              ),
              if (demand['time_display'] != null)
                AppMetaChip(
                  icon: Icons.schedule_outlined,
                  text: demand['time_display'],
                ),
              AppMetaChip(
                icon: Icons.category_outlined,
                text: demand['category_name'] ?? demand['category_text'] ?? '-',
              ),
            ],
          ),
        ],
      ),
    );
  }
}

// ── Detail section card ─────────────────────────────────────────
class _DetailCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final List<Widget> children;

  const _DetailCard({
    required this.icon,
    required this.title,
    required this.children,
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
          // Header
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
              ],
            ),
          ),
          // Content
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(children: children),
          ),
        ],
      ),
    );
  }
}

// ── Detail row ──────────────────────────────────────────────────
class _DetailRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;

  const _DetailRow(this.icon, this.label, this.value);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        children: [
          Icon(icon, size: 18, color: AppTheme.textSecondary),
          const SizedBox(width: 10),
          SizedBox(
            width: 72,
            child: Text(label, style: AppTheme.tsCaption),
          ),
          Expanded(
            child: Text(value, style: AppTheme.tsBody.copyWith(fontWeight: FontWeight.w500)),
          ),
        ],
      ),
    );
  }
}
