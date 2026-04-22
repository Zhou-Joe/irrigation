import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../models/user.dart';
import 'demand_form_screen.dart';

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

  // Filters
  String? _selectedStatus;
  DateTime? _selectedMonth;

  @override
  void initState() {
    super.initState();
    _selectedMonth = DateTime.now();
    _loadDemands();
  }

  Future<void> _loadDemands() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final demands = await widget.apiService.getDemandRecords(
        dateFrom: _selectedMonth != null
            ? '${_selectedMonth!.year}-${_selectedMonth!.month.toString().padLeft(2, '0')}-01'
            : null,
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

  String _getStatusColor(String status) {
    switch (status) {
      case 'submitted':
        return '#FFA500'; // Orange
      case 'approved':
        return '#28A745'; // Green
      case 'rejected':
        return '#DC3545'; // Red
      case 'in_progress':
        return '#007BFF'; // Blue
      case 'completed':
        return '#6C757D'; // Gray
      default:
        return '#888888';
    }
  }

  void _showDemandDetail(Map<String, dynamic> demand) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.7,
        minChildSize: 0.5,
        maxChildSize: 0.95,
        expand: false,
        builder: (context, scrollController) => Container(
          padding: const EdgeInsets.all(16),
          child: ListView(
            controller: scrollController,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    '需求详情',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  IconButton(
                    icon: const Icon(Icons.close),
                    onPressed: () => Navigator.pop(context),
                  ),
                ],
              ),
              const Divider(),
              _buildDetailRow('日期', demand['date'] ?? '-'),
              _buildDetailRow('区域', demand['zone_name'] ?? demand['zone_text'] ?? '全局事件'),
              _buildDetailRow('类别', demand['category_name'] ?? demand['category_text'] ?? '-'),
              _buildDetailRow('时间段', demand['time_display'] ?? '-'),
              _buildDetailRow('状态', demand['status_display'] ?? '-'),
              _buildDetailRow('提出部门', demand['demand_department_name'] ?? demand['demand_department_text'] ?? '-'),
              _buildDetailRow('联系人', demand['demand_contact'] ?? '-'),
              const SizedBox(height: 16),
              Text('需求内容', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              Text(demand['content'] ?? demand['original_text'] ?? '-'),
              if (demand['original_text'] != null && demand['content'] != demand['original_text']) ...[
                const SizedBox(height: 16),
                Text('原始文本', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                Text(demand['original_text'], style: const TextStyle(color: Colors.grey)),
              ],
              // Admin can update status
              if (widget.user.role == 'manager' || widget.user.role == 'super_admin') ...[
                const SizedBox(height: 24),
                ElevatedButton(
                  onPressed: () => _updateStatus(demand['id']),
                  child: const Text('更新状态'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildDetailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 80,
            child: Text(label, style: const TextStyle(fontWeight: FontWeight.bold)),
          ),
          Expanded(child: Text(value)),
        ],
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
          children: statuses.map((s) => ListTile(
            title: Text(s.$2),
            onTap: () async {
              Navigator.pop(context);
              try {
                await widget.apiService.updateDemandRecord(
                  id: demandId,
                  status: s.$1,
                );
                Navigator.pop(this.context); // Close detail modal
                _loadDemands();
              } catch (e) {
                ScaffoldMessenger.of(this.context).showSnackBar(
                  SnackBar(content: Text('更新失败: $e')),
                );
              }
            },
          )).toList(),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('需求周报'),
        actions: [
          if (widget.user.role == 'dept_user' || widget.user.role == 'manager' || widget.user.role == 'super_admin')
            IconButton(
              icon: const Icon(Icons.add),
              onPressed: () async {
                final result = await Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (context) => DemandFormScreen(
                      user: widget.user,
                      apiService: widget.apiService,
                    ),
                  ),
                );
                if (result == true) {
                  _loadDemands();
                }
              },
            ),
        ],
      ),
      body: Column(
        children: [
          // Filters
          Padding(
            padding: const EdgeInsets.all(8),
            child: Row(
              children: [
                // Month filter
                Expanded(
                  child: OutlinedButton(
                    onPressed: () async {
                      final picked = await showDatePicker(
                        context: context,
                        initialDate: _selectedMonth ?? DateTime.now(),
                        firstDate: DateTime(2020),
                        lastDate: DateTime(2030),
                      );
                      if (picked != null) {
                        setState(() => _selectedMonth = picked);
                        _loadDemands();
                      }
                    },
                    child: Text(_selectedMonth != null
                        ? '${_selectedMonth!.year}年${_selectedMonth!.month}月'
                        : '选择月份'),
                  ),
                ),
                const SizedBox(width: 8),
                // Status filter
                Expanded(
                  child: DropdownButton<String>(
                    value: _selectedStatus,
                    isExpanded: true,
                    hint: const Text('状态'),
                    items: const [
                      DropdownMenuItem(value: null, child: Text('全部')),
                      DropdownMenuItem(value: 'submitted', child: Text('已提交')),
                      DropdownMenuItem(value: 'approved', child: Text('已批准')),
                      DropdownMenuItem(value: 'rejected', child: Text('已拒绝')),
                      DropdownMenuItem(value: 'in_progress', child: Text('进行中')),
                      DropdownMenuItem(value: 'completed', child: Text('已完成')),
                    ],
                    onChanged: (value) {
                      setState(() => _selectedStatus = value);
                      _loadDemands();
                    },
                  ),
                ),
              ],
            ),
          ),
          // List
          Expanded(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                    ? Center(child: Text('错误: $_error'))
                    : _demands.isEmpty
                        ? const Center(child: Text('暂无需求记录'))
                        : ListView.builder(
                            itemCount: _demands.length,
                            itemBuilder: (context, index) {
                              final demand = _demands[index];
                              final statusColor = _getStatusColor(demand['status'] ?? '');
                              return Card(
                                child: ListTile(
                                  leading: CircleAvatar(
                                    backgroundColor: Color(
                                      int.parse(statusColor.replaceFirst('#', '0xFF')),
                                    ),
                                    child: Text(
                                      (index + 1).toString(),
                                      style: const TextStyle(color: Colors.white),
                                    ),
                                  ),
                                  title: Text(
                                    demand['zone_name'] ?? demand['zone_text'] ?? '全局事件',
                                    style: const TextStyle(fontWeight: FontWeight.bold),
                                  ),
                                  subtitle: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(demand['date'] ?? '-'),
                                      Text(
                                        demand['content'] ?? '',
                                        maxLines: 2,
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ],
                                  ),
                                  trailing: Column(
                                    mainAxisAlignment: MainAxisAlignment.center,
                                    children: [
                                      Container(
                                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                        decoration: BoxDecoration(
                                          color: Color(
                                            int.parse(statusColor.replaceFirst('#', '0xFF')),
                                          ).withOpacity(0.2),
                                          borderRadius: BorderRadius.circular(12),
                                        ),
                                        child: Text(
                                          demand['status_display'] ?? '-',
                                          style: TextStyle(
                                            color: Color(
                                              int.parse(statusColor.replaceFirst('#', '0xFF')),
                                            ),
                                            fontSize: 12,
                                          ),
                                        ),
                                      ),
                                      if (demand['time_display'] != null)
                                        Text(
                                          demand['time_display'],
                                          style: const TextStyle(fontSize: 12),
                                        ),
                                    ],
                                  ),
                                  onTap: () => _showDemandDetail(demand),
                                ),
                              );
                            },
                          ),
          ),
        ],
      ),
    );
  }
}