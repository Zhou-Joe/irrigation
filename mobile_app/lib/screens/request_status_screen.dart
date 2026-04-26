import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import 'request_detail_screen.dart';
import '../widgets/modern_ui.dart';

class RequestStatusScreen extends StatefulWidget {
  final bool isAdmin;
  final bool isDeptUser;

  const RequestStatusScreen({
    super.key,
    this.isAdmin = false,
    this.isDeptUser = false,
  });

  @override
  State<RequestStatusScreen> createState() => _RequestStatusScreenState();
}

class _RequestStatusScreenState extends State<RequestStatusScreen> {
  List<Map<String, dynamic>> _requests = [];
  bool _isLoading = true;
  String? _error;
  String _filterType =
      'all'; // 'all', 'water', 'maintenance', 'project_support'

  @override
  void initState() {
    super.initState();
    _loadRequests();
  }

  Future<void> _loadRequests() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final api = context.read<AuthProvider>().api;
      final requests = await api.getAllRequests();
      setState(() {
        _requests = requests;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = '加载失败: $e';
        _isLoading = false;
      });
    }
  }

  List<Map<String, dynamic>> get _filteredRequests {
    if (_filterType == 'all') return _requests;
    return _requests.where((r) => r['type_code'] == _filterType).toList();
  }

  Color _getStatusColor(String status) {
    return AppTheme.statusColor(status);
  }

  String _getStatusText(String status) {
    switch (status) {
      case 'approved':
        return '已批准';
      case 'rejected':
        return '已拒绝';
      case 'info_needed':
        return '需补充信息';
      case 'submitted':
        return '已提交';
      default:
        return status;
    }
  }

  IconData _getTypeIcon(String type) {
    switch (type) {
      case '维护与维修':
        return Icons.build;
      case '项目支持':
        return Icons.support_agent;
      case '浇水协调需求':
        return Icons.water_drop;
      default:
        return Icons.article;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.isDeptUser ? '浇水需求' : '需求状态'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _loadRequests),
        ],
      ),
      body: AppBackground(
        child: Column(
          children: [
            if (!widget.isDeptUser)
              Container(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: [
                      _buildFilterChip('全部', 'all'),
                      const SizedBox(width: 8),
                      _buildFilterChip('浇水协调', 'water'),
                      const SizedBox(width: 8),
                      _buildFilterChip('维护维修', 'maintenance'),
                      const SizedBox(width: 8),
                      _buildFilterChip('项目支持', 'project_support'),
                    ],
                  ),
                ),
              ),
            Expanded(
              child: _isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : _error != null
                  ? AppErrorState(message: _error!, onRetry: _loadRequests)
                  : _filteredRequests.isEmpty
                  ? AppEmptyState(
                      icon: widget.isDeptUser
                          ? Icons.water_drop_outlined
                          : Icons.article_outlined,
                      title: widget.isDeptUser ? '暂无浇水需求记录' : '暂无需求记录',
                      subtitle: '新提交的需求会在这里集中展示。',
                    )
                  : ListView.builder(
                      padding: const EdgeInsets.fromLTRB(16, 8, 16, 110),
                      itemCount: _filteredRequests.length,
                      itemBuilder: (context, index) {
                        final request = _filteredRequests[index];
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: _buildRequestCard(request),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFilterChip(String label, String value) {
    final isSelected = _filterType == value;
    return FilterChip(
      label: Text(label),
      selected: isSelected,
      onSelected: (selected) {
        setState(() => _filterType = value);
      },
      selectedColor: AppTheme.greenLight.withOpacity(0.3),
      checkmarkColor: AppTheme.greenDarkest,
    );
  }

  Widget _buildRequestCard(Map<String, dynamic> request) {
    final statusColor = _getStatusColor(request['status']);

    return AppCard(
      padding: const EdgeInsets.all(16),
      child: InkWell(
        onTap: () async {
          final result = await Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => RequestDetailScreen(
                typeCode: request['type_code'] ?? 'maintenance',
                requestId: request['id'],
                typeName: request['type'],
                zoneName: request['zone'],
              ),
            ),
          );
          if (result == true) _loadRequests();
        },
        borderRadius: BorderRadius.circular(24),
        child: Padding(
          padding: EdgeInsets.zero,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 42,
                    height: 42,
                    decoration: BoxDecoration(
                      color: AppTheme.greenPrimary.withOpacity(0.10),
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: Icon(
                      _getTypeIcon(request['type']),
                      size: 20,
                      color: AppTheme.greenDarkest,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      request['type'],
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                      ),
                    ),
                  ),
                  AppStatusBadge(
                    label: _getStatusText(request['status']),
                    color: statusColor,
                  ),
                ],
              ),
              const SizedBox(height: 14),
              Wrap(
                spacing: 12,
                runSpacing: 8,
                children: [
                  _buildMetaChip(Icons.location_on_outlined, request['zone']),
                  _buildMetaChip(Icons.person_outline_rounded, request['user']),
                  _buildMetaChip(
                    Icons.calendar_today_outlined,
                    request['date'],
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Align(
                alignment: Alignment.centerRight,
                child: Icon(
                  Icons.chevron_right_rounded,
                  color: AppTheme.textSecondary,
                ),
              ),
              // Quick actions for admin
              if (widget.isAdmin && request['status'] == 'submitted')
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Wrap(
                    alignment: WrapAlignment.end,
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      TextButton.icon(
                        icon: const Icon(Icons.check, color: AppTheme.greenMedium),
                        label: const Text('批准'),
                        onPressed: () => _handleAction(
                          request['id'],
                          request['type_code'] ?? 'maintenance',
                          'approved',
                        ),
                      ),
                      TextButton.icon(
                        icon: const Icon(Icons.close, color: AppTheme.statusCanceled),
                        label: const Text('拒绝'),
                        onPressed: () => _handleAction(
                          request['id'],
                          request['type_code'] ?? 'maintenance',
                          'rejected',
                        ),
                      ),
                      TextButton.icon(
                        icon: const Icon(
                          Icons.question_mark,
                          color: AppTheme.statusInProgress,
                        ),
                        label: const Text('补充信息'),
                        onPressed: () => _handleAction(
                          request['id'],
                          request['type_code'] ?? 'maintenance',
                          'info_needed',
                        ),
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

  Widget _buildMetaChip(IconData icon, String text) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.surfaceSoft.withOpacity(0.75),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 15, color: AppColors.muted),
          const SizedBox(width: 6),
          Text(
            text,
            style: const TextStyle(
              color: AppColors.deepGreen,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  void _handleAction(int requestId, String typeCode, String newStatus) async {
    try {
      final api = context.read<AuthProvider>().api;
      await api.updateRequestStatus(
        typeCode: typeCode,
        requestId: requestId,
        status: newStatus,
      );
      await _loadRequests();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('状态已更新为: ${_getStatusText(newStatus)}'),
            backgroundColor: AppTheme.greenMedium,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('更新失败: $e')));
      }
    }
  }
}
