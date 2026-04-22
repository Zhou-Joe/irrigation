import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../widgets/modern_ui.dart';

class ZoneDetailScreen extends StatefulWidget {
  final int zoneId;
  final String zoneName;

  const ZoneDetailScreen({
    super.key,
    required this.zoneId,
    required this.zoneName,
  });

  @override
  State<ZoneDetailScreen> createState() => _ZoneDetailScreenState();
}

class _ZoneDetailScreenState extends State<ZoneDetailScreen> {
  Map<String, dynamic>? _detail;
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadDetail();
  }

  Future<void> _loadDetail() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });
    try {
      final api = context.read<AuthProvider>().api;
      final data = await api.getZoneDetail(widget.zoneId);
      if (mounted) {
        setState(() {
          _detail = data;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = '$e';
          _isLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.zoneName),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _loadDetail),
        ],
      ),
      body: AppBackground(
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
            ? AppErrorState(message: _error!, onRetry: _loadDetail)
            : _buildContent(),
      ),
    );
  }

  Widget _buildContent() {
    final d = _detail!;
    final plants = (d['plants'] as List? ?? []).cast<Map<String, dynamic>>();
    final equipment = (d['equipment'] as List? ?? [])
        .cast<Map<String, dynamic>>();

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
      children: [
        // Header card
        _buildHeaderCard(d),
        const SizedBox(height: 16),

        // Stats row
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            _buildStatCard(
              '植物',
              d['plant_count'] ?? 0,
              Icons.local_florist,
              const Color(0xFF52B788),
            ),
            _buildStatCard(
              '设备',
              d['equipment_count'] ?? 0,
              Icons.settings_input_component,
              const Color(0xFF40916C),
            ),
            _buildStatCard(
              '日报',
              d['work_report_count'] ?? 0,
              Icons.assignment,
              const Color(0xFF2D6A4F),
            ),
            _buildStatCard(
              '近30天故障',
              d['recent_fault_count'] ?? 0,
              Icons.warning,
              const Color(0xFFCC7722),
            ),
          ],
        ),
        const SizedBox(height: 16),

        // Plants section
        const AppSectionTitle(title: '植物'),
        const SizedBox(height: 8),
        if (plants.isEmpty)
          const AppCard(
            child: Text(
              '暂无植物记录',
              style: TextStyle(color: Colors.grey, fontSize: 13),
            ),
          )
        else
          ...plants.map((p) => _buildPlantCard(p)),

        const SizedBox(height: 16),

        // Equipment section
        const AppSectionTitle(title: '设备'),
        const SizedBox(height: 8),
        if (equipment.isEmpty)
          const AppCard(
            child: Text(
              '暂无设备记录',
              style: TextStyle(color: Colors.grey, fontSize: 13),
            ),
          )
        else
          ...equipment.map((e) => _buildEquipmentCard(e)),
      ],
    );
  }

  Widget _buildHeaderCard(Map<String, dynamic> d) {
    final statusColor = _getStatusColor(d['status'] ?? 'unarranged');
    return AppCard(
      child: Padding(
        padding: EdgeInsets.zero,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    d['name'] ?? '',
                    style: const TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                      color: Color(0xFF1B4332),
                    ),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 3,
                  ),
                  decoration: BoxDecoration(
                    color: statusColor.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    d['status_display'] ?? '-',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: statusColor,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              '编号: ${d['code'] ?? '-'}',
              style: TextStyle(fontSize: 13, color: Colors.grey.shade600),
            ),
            if ((d['description'] ?? '').isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(d['description'], style: const TextStyle(fontSize: 13)),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildStatCard(String label, int count, IconData icon, Color color) {
    return SizedBox(
      width: 158,
      child: AppCard(
        child: Row(
          children: [
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: color.withOpacity(0.12),
                borderRadius: BorderRadius.circular(16),
              ),
              child: Icon(icon, size: 22, color: color),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '$count',
                    style: TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.w700,
                      color: color,
                    ),
                  ),
                  Text(
                    label,
                    style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildPlantCard(Map<String, dynamic> p) {
    final plantingDate = p['planting_date'];
    final endDate = p['end_date'];

    // Format date range display
    String dateRange = '';
    if (plantingDate != null && plantingDate.isNotEmpty) {
      if (endDate != null && endDate.isNotEmpty) {
        dateRange = '$plantingDate ~ $endDate';
      } else {
        dateRange = '$plantingDate ~ 持续';
      }
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: AppCard(
        child: Padding(
          padding: EdgeInsets.zero,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(
                    Icons.local_florist,
                    color: Color(0xFF52B788),
                    size: 16,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      p['name'] ?? '-',
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                  Text(
                    '数量: ${p['quantity'] ?? 0}',
                    style: const TextStyle(fontSize: 12),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              Row(
                children: [
                  if ((p['scientific_name'] ?? '').isNotEmpty)
                    Expanded(
                      child: Text(
                        p['scientific_name'],
                        style: TextStyle(
                          fontSize: 11,
                          color: Colors.grey.shade500,
                          fontStyle: FontStyle.italic,
                        ),
                      ),
                    ),
                  if (dateRange.isNotEmpty) ...[
                    const Spacer(),
                    Icon(
                      Icons.calendar_today,
                      size: 12,
                      color: Colors.grey.shade500,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      dateRange,
                      style: TextStyle(
                        fontSize: 11,
                        color: Colors.grey.shade600,
                      ),
                    ),
                  ],
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildEquipmentCard(Map<String, dynamic> e) {
    final details = e['equipment_details'] as Map<String, dynamic>?;
    final modelName = details?['model_name'] ?? '-';
    final typeDisplay = details?['equipment_type_display'] ?? '-';
    final status = e['status'] ?? 'working';
    final statusDisplay = e['status_display'] ?? '-';
    final location = e['location_in_zone'] ?? '';
    final installationDate = e['installation_date'];

    final statusColor = status == 'working'
        ? const Color(0xFF40916C)
        : status == 'needs_repair'
        ? const Color(0xFFCC7722)
        : Colors.grey;

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: AppCard(
        child: Padding(
          padding: EdgeInsets.zero,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(
                    Icons.settings_input_component,
                    size: 16,
                    color: Color(0xFF40916C),
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      '$typeDisplay: $modelName',
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 6,
                      vertical: 2,
                    ),
                    decoration: BoxDecoration(
                      color: statusColor.withOpacity(0.12),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      statusDisplay,
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w500,
                        color: statusColor,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              Row(
                children: [
                  Text(
                    '数量: ${e['quantity'] ?? 1}',
                    style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
                  ),
                  if (location.isNotEmpty) ...[
                    const SizedBox(width: 12),
                    Text(
                      '位置: $location',
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.grey.shade600,
                      ),
                    ),
                  ],
                  if (installationDate != null &&
                      installationDate.isNotEmpty) ...[
                    const SizedBox(width: 12),
                    Icon(
                      Icons.calendar_today,
                      size: 12,
                      color: Colors.grey.shade500,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      '安装: $installationDate',
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.grey.shade600,
                      ),
                    ),
                  ],
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Color _getStatusColor(String status) {
    switch (status) {
      case 'watering':
        return const Color(0xFF2D6A4F);
      case 'maintenance':
        return const Color(0xFFCC7722);
      case 'completed':
        return const Color(0xFF40916C);
      default:
        return Colors.grey;
    }
  }
}
