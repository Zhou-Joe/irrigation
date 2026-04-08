import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import 'request_detail_screen.dart';

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
  String _filterType = 'all'; // 'all', 'water', 'maintenance', 'project_support'

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
    switch (status) {
      case 'approved':
        return const Color(0xFF40916C);
      case 'rejected':
        return const Color(0xFF9B2226);
      case 'info_needed':
        return const Color(0xFFCC7722);
      case 'submitted':
        return const Color(0xFF52B788);
      default:
        return Colors.grey;
    }
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
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadRequests,
          ),
        ],
      ),
      body: Column(
        children: [
          // Filter chips (only for non-dept users)
          if (!widget.isDeptUser)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
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
          // Request list
          Expanded(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                    ? Center(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Text(_error!, style: const TextStyle(color: Colors.red)),
                            const SizedBox(height: 16),
                            ElevatedButton(
                              onPressed: _loadRequests,
                              child: const Text('重新加载'),
                            ),
                          ],
                        ),
                      )
                    : _filteredRequests.isEmpty
                        ? Center(
                            child: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(
                                  widget.isDeptUser ? Icons.water_drop_outlined : Icons.article_outlined,
                                  size: 64,
                                  color: Colors.grey,
                                ),
                                const SizedBox(height: 16),
                                Text(
                                  widget.isDeptUser ? '暂无浇水需求记录' : '暂无需求记录',
                                  style: const TextStyle(color: Colors.grey),
                                ),
                              ],
                            ),
                          )
                        : ListView.builder(
                            padding: const EdgeInsets.all(8),
                            itemCount: _filteredRequests.length,
                            itemBuilder: (context, index) {
                              final request = _filteredRequests[index];
                              return _buildRequestCard(request);
                            },
                          ),
          ),
        ],
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
      selectedColor: const Color(0xFF52B788).withOpacity(0.3),
      checkmarkColor: const Color(0xFF1B4332),
    );
  }

  Widget _buildRequestCard(Map<String, dynamic> request) {
    final statusColor = _getStatusColor(request['status']);

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4, horizontal: 8),
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
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(_getTypeIcon(request['type']), size: 20, color: const Color(0xFF1B4332)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      request['type'],
                      style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: statusColor.withOpacity(0.2),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      _getStatusText(request['status']),
                      style: TextStyle(color: statusColor, fontWeight: FontWeight.w500),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  const Icon(Icons.location_on, size: 16, color: Colors.grey),
                  const SizedBox(width: 4),
                  Text(request['zone'], style: TextStyle(color: Colors.grey[700])),
                  const SizedBox(width: 16),
                  const Icon(Icons.person, size: 16, color: Colors.grey),
                  const SizedBox(width: 4),
                  Text(request['user'], style: TextStyle(color: Colors.grey[700])),
                ],
              ),
              const SizedBox(height: 4),
              Row(
                children: [
                  const Icon(Icons.calendar_today, size: 16, color: Colors.grey),
                  const SizedBox(width: 4),
                  Text(request['date'], style: TextStyle(color: Colors.grey[700])),
                  const Spacer(),
                  const Icon(Icons.chevron_right, size: 16, color: Colors.grey),
                ],
              ),
              // Quick actions for admin
              if (widget.isAdmin && request['status'] == 'submitted')
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      TextButton.icon(
                        icon: const Icon(Icons.check, color: Color(0xFF40916C)),
                        label: const Text('批准'),
                        onPressed: () => _handleAction(request['id'], request['type_code'] ?? 'maintenance', 'approved'),
                      ),
                      TextButton.icon(
                        icon: const Icon(Icons.close, color: Color(0xFF9B2226)),
                        label: const Text('拒绝'),
                        onPressed: () => _handleAction(request['id'], request['type_code'] ?? 'maintenance', 'rejected'),
                      ),
                      TextButton.icon(
                        icon: const Icon(Icons.question_mark, color: Color(0xFFCC7722)),
                        label: const Text('补充信息'),
                        onPressed: () => _handleAction(request['id'], request['type_code'] ?? 'maintenance', 'info_needed'),
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
            backgroundColor: const Color(0xFF40916C),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('更新失败: $e')),
        );
      }
    }
  }
}