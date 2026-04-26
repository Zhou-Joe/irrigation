import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/auth_provider.dart';
import '../widgets/modern_ui.dart';

class RequestDetailScreen extends StatefulWidget {
  final String typeCode;
  final int requestId;
  final String typeName;
  final String zoneName;

  const RequestDetailScreen({
    super.key,
    required this.typeCode,
    required this.requestId,
    required this.typeName,
    required this.zoneName,
  });

  @override
  State<RequestDetailScreen> createState() => _RequestDetailScreenState();
}

class _RequestDetailScreenState extends State<RequestDetailScreen> {
  Map<String, dynamic>? _detail;
  bool _isLoading = true;
  bool _isEditing = false;
  bool _isSaving = false;
  String? _error;

  // Form controllers
  final _participantsController = TextEditingController();
  final _workContentController = TextEditingController();
  final _materialsController = TextEditingController();
  final _feedbackController = TextEditingController();
  final _statusNotesController = TextEditingController();
  final _userTypeOtherController = TextEditingController();
  final _requestTypeOtherController = TextEditingController();

  late DateTime _date;
  late TimeOfDay _startTime;
  late TimeOfDay _endTime;
  late DateTime _startDateTime;
  late DateTime _endDateTime;
  String _userType = 'ENT';
  String _requestType = '停水需求';
  String _status = 'submitted';

  @override
  void initState() {
    super.initState();
    _date = DateTime.now();
    _startTime = TimeOfDay.now();
    _endTime = TimeOfDay.now();
    _startDateTime = DateTime.now();
    _endDateTime = DateTime.now().add(const Duration(hours: 1));
    _loadDetail();
  }

  Future<void> _loadDetail() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final api = context.read<AuthProvider>().api;
      final detail = await api.getRequestDetail(
        widget.typeCode,
        widget.requestId,
      );

      setState(() {
        _detail = detail;
        _status = detail['status'] ?? 'submitted';
        _statusNotesController.text = detail['status_notes'] ?? '';

        if (widget.typeCode == 'maintenance' ||
            widget.typeCode == 'project_support') {
          _date = DateTime.tryParse(detail['date'] ?? '') ?? DateTime.now();
          _startTime = _parseTime(detail['start_time']) ?? TimeOfDay.now();
          _endTime = _parseTime(detail['end_time']) ?? TimeOfDay.now();
          _participantsController.text = detail['participants'] ?? '';
          _workContentController.text = detail['work_content'] ?? '';
          _materialsController.text = detail['materials'] ?? '';
          _feedbackController.text = detail['feedback'] ?? '';
        } else if (widget.typeCode == 'water') {
          _userType = detail['user_type'] ?? 'ENT';
          _userTypeOtherController.text = detail['user_type_other'] ?? '';
          _requestType = detail['request_type'] ?? '停水需求';
          _requestTypeOtherController.text = detail['request_type_other'] ?? '';
          _startDateTime =
              DateTime.tryParse(detail['start_datetime'] ?? '') ??
              DateTime.now();
          _endDateTime =
              DateTime.tryParse(detail['end_datetime'] ?? '') ?? DateTime.now();
        }

        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = '加载失败: $e';
        _isLoading = false;
      });
    }
  }

  TimeOfDay? _parseTime(String? timeStr) {
    if (timeStr == null) return null;
    try {
      final parts = timeStr.split(':');
      return TimeOfDay(hour: int.parse(parts[0]), minute: int.parse(parts[1]));
    } catch (_) {
      return null;
    }
  }

  Future<void> _save() async {
    setState(() => _isSaving = true);

    try {
      final api = context.read<AuthProvider>().api;
      Map<String, dynamic> data;

      if (widget.typeCode == 'maintenance' ||
          widget.typeCode == 'project_support') {
        data = {
          'date': DateFormat('yyyy-MM-dd').format(_date),
          'start_time':
              '${_startTime.hour.toString().padLeft(2, '0')}:${_startTime.minute.toString().padLeft(2, '0')}:00',
          'end_time':
              '${_endTime.hour.toString().padLeft(2, '0')}:${_endTime.minute.toString().padLeft(2, '0')}:00',
          'participants': _participantsController.text.trim(),
          'work_content': _workContentController.text.trim(),
          'materials': _materialsController.text.trim(),
          'feedback': _feedbackController.text.trim(),
        };
      } else {
        data = {
          'user_type': _userType,
          'user_type_other': _userTypeOtherController.text.trim(),
          'request_type': _requestType,
          'request_type_other': _requestTypeOtherController.text.trim(),
          'start_datetime': _startDateTime.toIso8601String(),
          'end_datetime': _endDateTime.toIso8601String(),
        };
      }

      await api.updateRequestDetail(
        typeCode: widget.typeCode,
        requestId: widget.requestId,
        data: data,
      );

      setState(() {
        _isEditing = false;
        _isSaving = false;
      });

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('保存成功'),
          backgroundColor: AppTheme.greenMedium,
        ),
      );

      _loadDetail();
    } catch (e) {
      setState(() => _isSaving = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('保存失败: $e')));
    }
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
      default:
        return '已提交';
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final isAdmin = auth.isAdmin;
    final canEdit =
        isAdmin || _status == 'submitted' || _status == 'info_needed';

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.typeName),
        actions: [
          if (canEdit && !_isLoading)
            IconButton(
              icon: Icon(_isEditing ? Icons.close : Icons.edit),
              onPressed: () => setState(() => _isEditing = !_isEditing),
            ),
        ],
      ),
      body: AppBackground(
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
            ? AppErrorState(message: _error!, onRetry: _loadDetail)
            : SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 40),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    AppHeroCard(
                      title: widget.typeName,
                      subtitle: '区域 ${widget.zoneName}',
                      icon: _heroIcon,
                      actions: [
                        if (canEdit && !_isLoading)
                          IconButton(
                            style: IconButton.styleFrom(
                              backgroundColor: Colors.white.withOpacity(0.14),
                              foregroundColor: Colors.white,
                            ),
                            icon: Icon(
                              _isEditing
                                  ? Icons.close_rounded
                                  : Icons.edit_rounded,
                            ),
                            onPressed: () =>
                                setState(() => _isEditing = !_isEditing),
                          ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    _buildStatusHeader(),
                    const SizedBox(height: 16),
                    AppCard(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const AppSectionTitle(
                            title: '基础信息',
                            subtitle: '当前工单的提交人与归属区域',
                          ),
                          const SizedBox(height: 12),
                          AppInfoRow(
                            icon: Icons.location_on_outlined,
                            label: '区域',
                            value: widget.zoneName,
                          ),
                          AppInfoRow(
                            icon: Icons.person_outline_rounded,
                            label: '提交人',
                            value: _detail?['submitter_name'] ?? '',
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                    if (widget.typeCode == 'maintenance' ||
                        widget.typeCode == 'project_support')
                      _buildMaintenanceContent()
                    else
                      _buildWaterContent(),
                    const SizedBox(height: 24),
                    if (_isEditing)
                      FilledButton.icon(
                        onPressed: _isSaving ? null : _save,
                        icon: _isSaving
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : const Icon(Icons.save_rounded),
                        label: Text(_isSaving ? '保存中...' : '保存'),
                      ),
                  ],
                ),
              ),
      ),
    );
  }

  IconData get _heroIcon {
    switch (widget.typeCode) {
      case 'maintenance':
        return Icons.build_circle_outlined;
      case 'project_support':
        return Icons.support_agent_rounded;
      case 'water':
        return Icons.water_drop_rounded;
      default:
        return Icons.article_outlined;
    }
  }

  Widget _buildStatusHeader() {
    final statusColor = _getStatusColor(_status);
    final approverName = _detail?['approver_name'] ?? '';
    final processedAt = _detail?['processed_at'] ?? '';

    return AppCard(
      color: statusColor.withOpacity(0.08),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              AppStatusBadge(
                label: _getStatusText(_status),
                color: statusColor,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  '状态追踪',
                  style: Theme.of(
                    context,
                  ).textTheme.titleMedium?.copyWith(color: AppColors.deepGreen),
                ),
              ),
            ],
          ),
          if (_detail?['status_notes']?.toString().isNotEmpty == true)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(
                _detail?['status_notes'],
                style: TextStyle(color: Colors.grey[700]),
              ),
            ),
          if (approverName.isNotEmpty) ...[
            const SizedBox(height: 12),
            Divider(color: statusColor.withOpacity(0.2)),
            const SizedBox(height: 12),
            AppInfoRow(
              icon: Icons.verified_user_outlined,
              label: '审批人',
              value: approverName,
            ),
            if (processedAt.isNotEmpty)
              AppInfoRow(
                icon: Icons.schedule_rounded,
                label: '处理时间',
                value: processedAt.replaceAll('T', ' ').substring(0, 16),
              ),
          ],
        ],
      ),
    );
  }

  Widget _buildMaintenanceContent() {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const AppSectionTitle(title: '时间与工作内容', subtitle: '维护维修 / 项目支持的执行详情'),
          const SizedBox(height: 14),
          _buildSectionTitle('时间信息'),
          const SizedBox(height: 8),
          if (_isEditing)
            Row(
              children: [
                Expanded(
                  child: InkWell(
                    onTap: () async {
                      final picked = await showDatePicker(
                        context: context,
                        initialDate: _date,
                        firstDate: DateTime.now().subtract(
                          const Duration(days: 30),
                        ),
                        lastDate: DateTime.now().add(const Duration(days: 30)),
                      );
                      if (picked != null) setState(() => _date = picked);
                    },
                    child: InputDecorator(
                      decoration: const InputDecoration(
                        labelText: '日期',
                        border: OutlineInputBorder(),
                      ),
                      child: Text(DateFormat('yyyy-MM-dd').format(_date)),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: InkWell(
                    onTap: () async {
                      final picked = await showTimePicker(
                        context: context,
                        initialTime: _startTime,
                      );
                      if (picked != null) setState(() => _startTime = picked);
                    },
                    child: InputDecorator(
                      decoration: const InputDecoration(
                        labelText: '开始时间',
                        border: OutlineInputBorder(),
                      ),
                      child: Text(_startTime.format(context)),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: InkWell(
                    onTap: () async {
                      final picked = await showTimePicker(
                        context: context,
                        initialTime: _endTime,
                      );
                      if (picked != null) setState(() => _endTime = picked);
                    },
                    child: InputDecorator(
                      decoration: const InputDecoration(
                        labelText: '结束时间',
                        border: OutlineInputBorder(),
                      ),
                      child: Text(_endTime.format(context)),
                    ),
                  ),
                ),
              ],
            )
          else
            Text(
              '日期: ${_detail?['date']}  时间: ${_detail?['start_time']} - ${_detail?['end_time']}',
            ),
          const SizedBox(height: 16),

          _buildSectionTitle('工作信息'),
          const SizedBox(height: 8),
          if (_isEditing)
            Column(
              children: [
                TextFormField(
                  controller: _participantsController,
                  decoration: const InputDecoration(
                    labelText: '参与人员',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _workContentController,
                  decoration: const InputDecoration(
                    labelText: '工作内容',
                    border: OutlineInputBorder(),
                  ),
                  maxLines: 3,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _materialsController,
                  decoration: const InputDecoration(
                    labelText: '材料损耗',
                    border: OutlineInputBorder(),
                  ),
                  maxLines: 2,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _feedbackController,
                  decoration: const InputDecoration(
                    labelText: '问题反馈',
                    border: OutlineInputBorder(),
                  ),
                  maxLines: 2,
                ),
              ],
            )
          else
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _buildDetailRow('参与人员', _detail?['participants'] ?? ''),
                _buildDetailRow('工作内容', _detail?['work_content'] ?? ''),
                _buildDetailRow('材料损耗', _detail?['materials'] ?? ''),
                _buildDetailRow('问题反馈', _detail?['feedback'] ?? ''),
              ],
            ),
        ],
      ),
    );
  }

  Widget _buildWaterContent() {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const AppSectionTitle(title: '需求信息', subtitle: '浇水协调需求的用户类型与时间段'),
          const SizedBox(height: 14),
          if (_isEditing)
            Column(
              children: [
                DropdownButtonFormField<String>(
                  value: _userType,
                  decoration: const InputDecoration(
                    labelText: '用户类型',
                    border: OutlineInputBorder(),
                  ),
                  items: const [
                    DropdownMenuItem(value: 'ENT', child: Text('ENT')),
                    DropdownMenuItem(value: 'FAM', child: Text('FAM')),
                    DropdownMenuItem(value: 'FES', child: Text('FES')),
                    DropdownMenuItem(value: '其他', child: Text('其他')),
                  ],
                  onChanged: (v) => setState(() => _userType = v!),
                ),
                if (_userType == '其他')
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: TextFormField(
                      controller: _userTypeOtherController,
                      decoration: const InputDecoration(
                        labelText: '其他用户类型',
                        border: OutlineInputBorder(),
                      ),
                    ),
                  ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  value: _requestType,
                  decoration: const InputDecoration(
                    labelText: '需求类别',
                    border: OutlineInputBorder(),
                  ),
                  items: const [
                    DropdownMenuItem(value: '停水需求', child: Text('停水需求')),
                    DropdownMenuItem(value: '新苗程序', child: Text('新苗程序')),
                    DropdownMenuItem(value: '减小水量', child: Text('减小水量')),
                    DropdownMenuItem(value: '加大水量', child: Text('加大水量')),
                    DropdownMenuItem(value: '其他需求', child: Text('其他需求')),
                  ],
                  onChanged: (v) => setState(() => _requestType = v!),
                ),
                if (_requestType == '其他需求')
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: TextFormField(
                      controller: _requestTypeOtherController,
                      decoration: const InputDecoration(
                        labelText: '其他需求类别',
                        border: OutlineInputBorder(),
                      ),
                    ),
                  ),
                const SizedBox(height: 16),
                InkWell(
                  onTap: () async {
                    final picked = await showDatePicker(
                      context: context,
                      initialDate: _startDateTime,
                      firstDate: DateTime.now().subtract(
                        const Duration(days: 30),
                      ),
                      lastDate: DateTime.now().add(const Duration(days: 30)),
                    );
                    if (picked != null) {
                      final time = await showTimePicker(
                        context: context,
                        initialTime: TimeOfDay.fromDateTime(_startDateTime),
                      );
                      if (time != null) {
                        setState(
                          () => _startDateTime = DateTime(
                            picked.year,
                            picked.month,
                            picked.day,
                            time.hour,
                            time.minute,
                          ),
                        );
                      }
                    }
                  },
                  child: InputDecorator(
                    decoration: const InputDecoration(
                      labelText: '起始时间',
                      border: OutlineInputBorder(),
                    ),
                    child: Text(
                      DateFormat('yyyy-MM-dd HH:mm').format(_startDateTime),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                InkWell(
                  onTap: () async {
                    final picked = await showDatePicker(
                      context: context,
                      initialDate: _endDateTime,
                      firstDate: DateTime.now().subtract(
                        const Duration(days: 30),
                      ),
                      lastDate: DateTime.now().add(const Duration(days: 30)),
                    );
                    if (picked != null) {
                      final time = await showTimePicker(
                        context: context,
                        initialTime: TimeOfDay.fromDateTime(_endDateTime),
                      );
                      if (time != null) {
                        setState(
                          () => _endDateTime = DateTime(
                            picked.year,
                            picked.month,
                            picked.day,
                            time.hour,
                            time.minute,
                          ),
                        );
                      }
                    }
                  },
                  child: InputDecorator(
                    decoration: const InputDecoration(
                      labelText: '结束时间',
                      border: OutlineInputBorder(),
                    ),
                    child: Text(
                      DateFormat('yyyy-MM-dd HH:mm').format(_endDateTime),
                    ),
                  ),
                ),
              ],
            )
          else
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _buildDetailRow(
                  '用户类型',
                  _detail?['user_type_display'] ?? _detail?['user_type'] ?? '',
                ),
                if (_detail?['user_type_other']?.toString().isNotEmpty == true)
                  _buildDetailRow('其他类型', _detail?['user_type_other'] ?? ''),
                _buildDetailRow(
                  '需求类别',
                  _detail?['request_type_display'] ??
                      _detail?['request_type'] ??
                      '',
                ),
                if (_detail?['request_type_other']?.toString().isNotEmpty ==
                    true)
                  _buildDetailRow('其他需求', _detail?['request_type_other'] ?? ''),
                _buildDetailRow('起始时间', _detail?['start_datetime'] ?? ''),
                _buildDetailRow('结束时间', _detail?['end_datetime'] ?? ''),
              ],
            ),
        ],
      ),
    );
  }

  Widget _buildSectionTitle(String title) {
    return Text(
      title,
      style: const TextStyle(
        fontSize: 16,
        fontWeight: FontWeight.bold,
        color: AppTheme.greenDarkest,
      ),
    );
  }

  Widget _buildDetailRow(String label, String value) {
    if (value.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 80,
            child: Text('$label: ', style: const TextStyle(color: AppTheme.textSecondary)),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _participantsController.dispose();
    _workContentController.dispose();
    _materialsController.dispose();
    _feedbackController.dispose();
    _statusNotesController.dispose();
    _userTypeOtherController.dispose();
    _requestTypeOtherController.dispose();
    super.dispose();
  }
}
