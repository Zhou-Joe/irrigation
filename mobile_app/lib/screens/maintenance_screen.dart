import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'dart:io';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../models/zone.dart';
import '../providers/auth_provider.dart';

class MaintenanceScreen extends StatefulWidget {
  final Zone zone;

  const MaintenanceScreen({super.key, required this.zone});

  @override
  State<MaintenanceScreen> createState() => _MaintenanceScreenState();
}

class _MaintenanceScreenState extends State<MaintenanceScreen> {
  final _formKey = GlobalKey<FormState>();
  late DateTime _date;
  late TimeOfDay _startTime;
  late TimeOfDay _endTime;
  final _participantsController = TextEditingController();
  final _workContentController = TextEditingController();
  final _materialsController = TextEditingController();
  final _feedbackController = TextEditingController();
  final List<File> _photos = [];
  final ImagePicker _picker = ImagePicker();
  bool _isLoading = false;
  bool _includeLocation = true;
  Position? _currentPosition;

  @override
  void initState() {
    super.initState();
    _date = DateTime.now();
    _startTime = TimeOfDay.now();
    _endTime = TimeOfDay.now().replacing(hour: (TimeOfDay.now().hour + 1) % 24);

    // Auto-fill current user name
    final user = context.read<AuthProvider>().user;
    if (user != null) {
      _participantsController.text = user.fullName;
    }

    if (_includeLocation) _getCurrentLocation();
  }

  Future<void> _getCurrentLocation() async {
    try {
      final position = await Geolocator.getCurrentPosition();
      setState(() => _currentPosition = position);
    } catch (e) {
      debugPrint('获取位置失败: $e');
    }
  }

  Future<void> _selectDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _date,
      firstDate: DateTime.now().subtract(const Duration(days: 30)),
      lastDate: DateTime.now().add(const Duration(days: 7)),
    );
    if (picked != null) setState(() => _date = picked);
  }

  Future<void> _selectStartTime() async {
    final picked = await showTimePicker(context: context, initialTime: _startTime);
    if (picked != null) setState(() => _startTime = picked);
  }

  Future<void> _selectEndTime() async {
    final picked = await showTimePicker(context: context, initialTime: _endTime);
    if (picked != null) setState(() => _endTime = picked);
  }

  Future<void> _takePhoto() async {
    if (_photos.length >= 5) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('最多5张照片')));
      return;
    }
    final XFile? photo = await _picker.pickImage(source: ImageSource.camera, maxWidth: 1920);
    if (photo != null) setState(() => _photos.add(File(photo.path)));
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _isLoading = true);

    try {
      final api = context.read<AuthProvider>().api;
      await api.submitMaintenanceRequest(
        zoneId: widget.zone.id,
        date: DateFormat('yyyy-MM-dd').format(_date),
        startTime: '${_startTime.hour.toString().padLeft(2, '0')}:${_startTime.minute.toString().padLeft(2, '0')}:00',
        endTime: '${_endTime.hour.toString().padLeft(2, '0')}:${_endTime.minute.toString().padLeft(2, '0')}:00',
        participants: _participantsController.text.trim(),
        workContent: _workContentController.text.trim(),
        materials: _materialsController.text.trim(),
        feedback: _feedbackController.text.trim(),
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('提交成功'), backgroundColor: Colors.green),
        );
        Navigator.pop(context, true);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('提交失败: $e')));
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('维护与维修')),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text('区域: ${widget.zone.name}', style: const TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 16),

            Row(
              children: [
                Expanded(
                  child: InkWell(
                    onTap: _selectDate,
                    child: InputDecorator(
                      decoration: const InputDecoration(labelText: '日期', border: OutlineInputBorder()),
                      child: Text(DateFormat('yyyy-MM-dd').format(_date)),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: InkWell(
                    onTap: _selectStartTime,
                    child: InputDecorator(
                      decoration: const InputDecoration(labelText: '开始时间', border: OutlineInputBorder()),
                      child: Text(_startTime.format(context)),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: InkWell(
                    onTap: _selectEndTime,
                    child: InputDecorator(
                      decoration: const InputDecoration(labelText: '结束时间', border: OutlineInputBorder()),
                      child: Text(_endTime.format(context)),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),

            TextFormField(
              controller: _participantsController,
              decoration: const InputDecoration(
                labelText: '参与人员',
                prefixIcon: Icon(Icons.people),
                border: OutlineInputBorder(),
                hintText: '多人用逗号分隔',
              ),
            ),
            const SizedBox(height: 16),

            TextFormField(
              controller: _workContentController,
              decoration: const InputDecoration(
                labelText: '工作内容',
                prefixIcon: Icon(Icons.work),
                border: OutlineInputBorder(),
              ),
              maxLines: 3,
              validator: (v) => v?.trim().isEmpty == true ? '请填写工作内容' : null,
            ),
            const SizedBox(height: 16),

            TextFormField(
              controller: _materialsController,
              decoration: const InputDecoration(
                labelText: '材料损耗',
                prefixIcon: Icon(Icons.inventory),
                border: OutlineInputBorder(),
              ),
              maxLines: 2,
            ),
            const SizedBox(height: 16),

            TextFormField(
              controller: _feedbackController,
              decoration: const InputDecoration(
                labelText: '问题反馈',
                prefixIcon: Icon(Icons.feedback),
                border: OutlineInputBorder(),
              ),
              maxLines: 2,
            ),
            const SizedBox(height: 16),

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
                      ? const Text('暂无照片', style: TextStyle(color: Colors.grey))
                      : SizedBox(
                          height: 60,
                          child: ListView.builder(
                            scrollDirection: Axis.horizontal,
                            itemCount: _photos.length,
                            itemBuilder: (_, i) => Padding(
                              padding: const EdgeInsets.only(right: 8),
                              child: Stack(
                                children: [
                                  Image.file(_photos[i], width: 60, height: 60, fit: BoxFit.cover),
                                  Positioned(
                                    top: 0, right: 0,
                                    child: GestureDetector(
                                      onTap: () => setState(() => _photos.removeAt(i)),
                                      child: const CircleAvatar(radius: 10, backgroundColor: Colors.red, child: Icon(Icons.close, size: 12, color: Colors.white)),
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
              icon: _isLoading ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.send),
              label: Text(_isLoading ? '提交中...' : '提交'),
              style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 16)),
            ),
          ],
        ),
      ),
    );
  }
}