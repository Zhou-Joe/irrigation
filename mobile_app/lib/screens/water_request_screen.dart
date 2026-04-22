import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'dart:io';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../models/zone.dart';
import '../providers/auth_provider.dart';
import '../widgets/modern_ui.dart';

class WaterRequestScreen extends StatefulWidget {
  final Zone zone;

  const WaterRequestScreen({super.key, required this.zone});

  @override
  State<WaterRequestScreen> createState() => _WaterRequestScreenState();
}

class _WaterRequestScreenState extends State<WaterRequestScreen> {
  final _formKey = GlobalKey<FormState>();
  String _userType = 'ENT';
  String _requestType = '停水需求';
  late DateTime _startDate;
  late TimeOfDay _startTime;
  late DateTime _endDate;
  late TimeOfDay _endTime;
  final _otherUserTypeController = TextEditingController();
  final _otherRequestTypeController = TextEditingController();
  final List<File> _photos = [];
  final ImagePicker _picker = ImagePicker();
  bool _isLoading = false;

  final List<String> _userTypes = ['ENT', 'FAM', 'FES', '其他'];
  final List<String> _requestTypes = ['停水需求', '新苗程序', '减小水量', '加大水量', '其他需求'];

  @override
  void initState() {
    super.initState();
    _startDate = DateTime.now();
    _startTime = TimeOfDay.now();
    _endDate = DateTime.now().add(const Duration(hours: 2));
    _endTime = TimeOfDay.now().replacing(hour: (_startTime.hour + 2) % 24);
  }

  Future<void> _selectStartDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _startDate,
      firstDate: DateTime.now(),
      lastDate: DateTime.now().add(const Duration(days: 30)),
    );
    if (picked != null) setState(() => _startDate = picked);
  }

  Future<void> _selectStartTime() async {
    final picked = await showTimePicker(
      context: context,
      initialTime: _startTime,
    );
    if (picked != null) setState(() => _startTime = picked);
  }

  Future<void> _selectEndDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _endDate,
      firstDate: _startDate,
      lastDate: DateTime.now().add(const Duration(days: 30)),
    );
    if (picked != null) setState(() => _endDate = picked);
  }

  Future<void> _selectEndTime() async {
    final picked = await showTimePicker(
      context: context,
      initialTime: _endTime,
    );
    if (picked != null) setState(() => _endTime = picked);
  }

  Future<void> _takePhoto() async {
    if (_photos.length >= 5) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('最多5张照片')));
      return;
    }
    final XFile? photo = await _picker.pickImage(
      source: ImageSource.camera,
      maxWidth: 1920,
    );
    if (photo != null) setState(() => _photos.add(File(photo.path)));
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    if (_userType == '其他' && _otherUserTypeController.text.trim().isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('请填写需求用户类型')));
      return;
    }
    if (_requestType == '其他需求' &&
        _otherRequestTypeController.text.trim().isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('请填写需求类别')));
      return;
    }

    setState(() => _isLoading = true);

    try {
      final startDatetime = DateTime(
        _startDate.year,
        _startDate.month,
        _startDate.day,
        _startTime.hour,
        _startTime.minute,
      );
      final endDatetime = DateTime(
        _endDate.year,
        _endDate.month,
        _endDate.day,
        _endTime.hour,
        _endTime.minute,
      );

      final api = context.read<AuthProvider>().api;
      await api.submitWaterRequest(
        zoneId: widget.zone.id,
        userType: _userType,
        userTypeOther: _userType == '其他'
            ? _otherUserTypeController.text.trim()
            : null,
        requestType: _requestType,
        requestTypeOther: _requestType == '其他需求'
            ? _otherRequestTypeController.text.trim()
            : null,
        startDatetime: startDatetime.toIso8601String(),
        endDatetime: endDatetime.toIso8601String(),
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('需求已发出'), backgroundColor: Colors.green),
        );
        Navigator.pop(context, true);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('提交失败: $e')));
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('浇水协调需求')),
      body: AppBackground(
        child: Form(
          key: _formKey,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
            children: [
              AppHeroCard(
                title: '浇水协调需求',
                subtitle: '区域 ${widget.zone.name}',
                icon: Icons.water_drop_rounded,
              ),
              const SizedBox(height: 16),
              AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const AppSectionTitle(
                      title: '需求填写',
                      subtitle: '确认需求类型和生效时间段',
                    ),
                    const SizedBox(height: 12),

                    // 用户类型
                    DropdownButtonFormField<String>(
                      value: _userType,
                      decoration: const InputDecoration(
                        labelText: '需求用户',
                        prefixIcon: Icon(Icons.person),
                        border: OutlineInputBorder(),
                      ),
                      items: _userTypes
                          .map(
                            (t) => DropdownMenuItem(value: t, child: Text(t)),
                          )
                          .toList(),
                      onChanged: (v) => setState(() => _userType = v!),
                    ),
                    if (_userType == '其他')
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: TextFormField(
                          controller: _otherUserTypeController,
                          decoration: const InputDecoration(
                            labelText: '请输入用户类型',
                            border: OutlineInputBorder(),
                          ),
                        ),
                      ),
                    const SizedBox(height: 16),

                    // 需求类别
                    DropdownButtonFormField<String>(
                      value: _requestType,
                      decoration: const InputDecoration(
                        labelText: '需求类别',
                        prefixIcon: Icon(Icons.category),
                        border: OutlineInputBorder(),
                      ),
                      items: _requestTypes
                          .map(
                            (t) => DropdownMenuItem(value: t, child: Text(t)),
                          )
                          .toList(),
                      onChanged: (v) => setState(() => _requestType = v!),
                    ),
                    if (_requestType == '其他需求')
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: TextFormField(
                          controller: _otherRequestTypeController,
                          decoration: const InputDecoration(
                            labelText: '请输入需求类别',
                            border: OutlineInputBorder(),
                          ),
                        ),
                      ),
                    const SizedBox(height: 16),

                    // 起始时间
                    const Text(
                      '需求起始时间',
                      style: TextStyle(fontWeight: FontWeight.w500),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Expanded(
                          child: InkWell(
                            onTap: _selectStartDate,
                            child: InputDecorator(
                              decoration: const InputDecoration(
                                labelText: '日期',
                                border: OutlineInputBorder(),
                              ),
                              child: Text(
                                DateFormat('MM-dd').format(_startDate),
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: InkWell(
                            onTap: _selectStartTime,
                            child: InputDecorator(
                              decoration: const InputDecoration(
                                labelText: '时间',
                                border: OutlineInputBorder(),
                              ),
                              child: Text(_startTime.format(context)),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),

                    // 结束时间
                    const Text(
                      '需求结束时间',
                      style: TextStyle(fontWeight: FontWeight.w500),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Expanded(
                          child: InkWell(
                            onTap: _selectEndDate,
                            child: InputDecorator(
                              decoration: const InputDecoration(
                                labelText: '日期',
                                border: OutlineInputBorder(),
                              ),
                              child: Text(DateFormat('MM-dd').format(_endDate)),
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: InkWell(
                            onTap: _selectEndTime,
                            child: InputDecorator(
                              decoration: const InputDecoration(
                                labelText: '时间',
                                border: OutlineInputBorder(),
                              ),
                              child: Text(_endTime.format(context)),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),

                    // 照片
                    Row(
                      children: [
                        ElevatedButton.icon(
                          onPressed: _takePhoto,
                          icon: const Icon(Icons.camera_alt),
                          label: Text('拍照 (${_photos.length}/5)'),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: _photos.isEmpty
                              ? const Text(
                                  '暂无照片',
                                  style: TextStyle(color: Colors.grey),
                                )
                              : SizedBox(
                                  height: 60,
                                  child: ListView.builder(
                                    scrollDirection: Axis.horizontal,
                                    itemCount: _photos.length,
                                    itemBuilder: (_, i) => Padding(
                                      padding: const EdgeInsets.only(right: 8),
                                      child: Stack(
                                        children: [
                                          Image.file(
                                            _photos[i],
                                            width: 60,
                                            height: 60,
                                            fit: BoxFit.cover,
                                          ),
                                          Positioned(
                                            top: 0,
                                            right: 0,
                                            child: GestureDetector(
                                              onTap: () => setState(
                                                () => _photos.removeAt(i),
                                              ),
                                              child: const CircleAvatar(
                                                radius: 10,
                                                backgroundColor: Colors.red,
                                                child: Icon(
                                                  Icons.close,
                                                  size: 12,
                                                  color: Colors.white,
                                                ),
                                              ),
                                            ),
                                          ),
                                        ],
                                      ),
                                    ),
                                  ),
                                ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 32),

                    FilledButton.icon(
                      onPressed: _isLoading ? null : _submit,
                      icon: _isLoading
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            )
                          : const Icon(Icons.send),
                      label: Text(_isLoading ? '发送中...' : '发出需求'),
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
}
