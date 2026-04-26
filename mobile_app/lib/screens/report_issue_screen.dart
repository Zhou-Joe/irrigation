import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'dart:io';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../models/zone.dart';
import '../providers/auth_provider.dart';
import '../theme/app_theme.dart';

class ReportIssueScreen extends StatefulWidget {
  final List<Zone> zones;
  final Zone? selectedZone;

  const ReportIssueScreen({super.key, required this.zones, this.selectedZone});

  @override
  State<ReportIssueScreen> createState() => _ReportIssueScreenState();
}

class _ReportIssueScreenState extends State<ReportIssueScreen> {
  final _formKey = GlobalKey<FormState>();
  Zone? _selectedZone;
  String _issueType = '设备故障';
  final _descriptionController = TextEditingController();
  final List<File> _photos = [];
  final ImagePicker _picker = ImagePicker();
  bool _isLoading = false;
  bool _includeLocation = true;
  Position? _currentPosition;
  DateTime _reportDateTime = DateTime.now();

  final List<String> _issueTypes = [
    '设备故障',
    '管道漏水',
    '阀门损坏',
    '水质异常',
    '植物病虫害',
    '土壤问题',
    '其他',
  ];

  @override
  void initState() {
    super.initState();
    _selectedZone = widget.selectedZone ?? (widget.zones.isNotEmpty ? widget.zones.first : null);
    if (_includeLocation) {
      _getCurrentLocation();
    }
  }

  @override
  void dispose() {
    _descriptionController.dispose();
    super.dispose();
  }

  Future<void> _getCurrentLocation() async {
    try {
      final position = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high,
      );
      setState(() {
        _currentPosition = position;
      });
    } catch (e) {
      debugPrint('获取位置失败: $e');
    }
  }

  Future<void> _selectDateTime() async {
    final date = await showDatePicker(
      context: context,
      initialDate: _reportDateTime,
      firstDate: DateTime.now().subtract(const Duration(days: 30)),
      lastDate: DateTime.now(),
    );

    if (date != null && mounted) {
      final time = await showTimePicker(
        context: context,
        initialTime: TimeOfDay.fromDateTime(_reportDateTime),
      );

      if (time != null) {
        setState(() {
          _reportDateTime = DateTime(
            date.year,
            date.month,
            date.day,
            time.hour,
            time.minute,
          );
        });
      }
    }
  }

  Future<void> _takePhoto() async {
    if (_photos.length >= 5) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('最多上传5张照片')),
      );
      return;
    }

    final XFile? photo = await _picker.pickImage(
      source: ImageSource.camera,
      maxWidth: 1920,
      maxHeight: 1080,
      imageQuality: 85,
    );

    if (photo != null) {
      setState(() {
        _photos.add(File(photo.path));
      });
    }
  }

  Future<void> _pickFromGallery() async {
    if (_photos.length >= 5) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('最多上传5张照片')),
      );
      return;
    }

    final List<XFile> images = await _picker.pickMultiImage(
      maxWidth: 1920,
      maxHeight: 1080,
      imageQuality: 85,
    );

    setState(() {
      for (var img in images) {
        if (_photos.length < 5) {
          _photos.add(File(img.path));
        }
      }
    });
  }

  void _removePhoto(int index) {
    setState(() {
      _photos.removeAt(index);
    });
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    if (_selectedZone == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请选择区域')),
      );
      return;
    }

    setState(() => _isLoading = true);

    try {
      // TODO: Implement actual API call
      await Future.delayed(const Duration(seconds: 1));

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('异常报告已提交'),
            backgroundColor: Colors.green,
          ),
        );
        Navigator.pop(context, true);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('提交失败: $e')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('报告异常'),
      ),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // Zone selector
            DropdownButtonFormField<Zone>(
              value: _selectedZone,
              decoration: const InputDecoration(
                labelText: '区域',
                prefixIcon: Icon(Icons.location_on),
                border: OutlineInputBorder(),
              ),
              items: widget.zones.map((zone) {
                return DropdownMenuItem(
                  value: zone,
                  child: Text('${zone.name} (${zone.code})'),
                );
              }).toList(),
              onChanged: (zone) => setState(() => _selectedZone = zone),
              validator: (value) {
                if (value == null) return '请选择区域';
                return null;
              },
            ),
            const SizedBox(height: 16),

            // Issue type
            DropdownButtonFormField<String>(
              value: _issueType,
              decoration: const InputDecoration(
                labelText: '异常类型',
                prefixIcon: Icon(Icons.warning),
                border: OutlineInputBorder(),
              ),
              items: _issueTypes.map((type) {
                return DropdownMenuItem(value: type, child: Text(type));
              }).toList(),
              onChanged: (type) => setState(() => _issueType = type!),
            ),
            const SizedBox(height: 16),

            // Date Time
            InkWell(
              onTap: _selectDateTime,
              child: InputDecorator(
                decoration: const InputDecoration(
                  labelText: '发现时间',
                  prefixIcon: Icon(Icons.access_time),
                  border: OutlineInputBorder(),
                ),
                child: Text(
                  DateFormat('yyyy-MM-dd HH:mm').format(_reportDateTime),
                  style: const TextStyle(fontSize: 16),
                ),
              ),
            ),
            const SizedBox(height: 16),

            // Description
            TextFormField(
              controller: _descriptionController,
              decoration: const InputDecoration(
                labelText: '问题描述',
                prefixIcon: Icon(Icons.description),
                border: OutlineInputBorder(),
                alignLabelWithHint: true,
              ),
              maxLines: 3,
              validator: (value) {
                if (value == null || value.trim().isEmpty) {
                  return '请描述问题';
                }
                return null;
              },
            ),
            const SizedBox(height: 16),

            // Photo section
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.photo_camera, size: 20),
                        const SizedBox(width: 8),
                        Text(
                          '照片 (${_photos.length}/5)',
                          style: const TextStyle(fontWeight: FontWeight.w600),
                        ),
                        const Spacer(),
                        TextButton.icon(
                          onPressed: _takePhoto,
                          icon: const Icon(Icons.camera_alt, size: 18),
                          label: const Text('拍照'),
                        ),
                        TextButton.icon(
                          onPressed: _pickFromGallery,
                          icon: const Icon(Icons.photo_library, size: 18),
                          label: const Text('相册'),
                        ),
                      ],
                    ),
                    if (_photos.isNotEmpty) ...[
                      const Divider(),
                      SizedBox(
                        height: 100,
                        child: ListView.builder(
                          scrollDirection: Axis.horizontal,
                          itemCount: _photos.length,
                          itemBuilder: (context, index) {
                            return Stack(
                              children: [
                                Container(
                                  margin: const EdgeInsets.only(right: 8),
                                  width: 100,
                                  height: 100,
                                  decoration: BoxDecoration(
                                    borderRadius: BorderRadius.circular(8),
                                    image: DecorationImage(
                                      image: FileImage(_photos[index]),
                                      fit: BoxFit.cover,
                                    ),
                                  ),
                                ),
                                Positioned(
                                  top: 0,
                                  right: 0,
                                  child: GestureDetector(
                                    onTap: () => _removePhoto(index),
                                    child: Container(
                                      padding: const EdgeInsets.all(4),
                                      decoration: const BoxDecoration(
                                        color: Colors.red,
                                        shape: BoxShape.circle,
                                      ),
                                      child: const Icon(Icons.close, color: Colors.white, size: 16),
                                    ),
                                  ),
                                ),
                              ],
                            );
                          },
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),

            // Location toggle
            SwitchListTile(
              title: const Text('包含位置信息'),
              subtitle: Text(
                _includeLocation && _currentPosition != null
                    ? '已获取位置'
                    : _includeLocation
                        ? '正在获取位置...'
                        : '不包含位置',
              ),
              secondary: const Icon(Icons.location_on),
              value: _includeLocation,
              onChanged: (value) {
                setState(() {
                  _includeLocation = value;
                  if (value && _currentPosition == null) {
                    _getCurrentLocation();
                  }
                });
              },
            ),
            const SizedBox(height: 32),

            // Submit button
            FilledButton.icon(
              onPressed: _isLoading ? null : _submit,
              icon: _isLoading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.send),
              label: Text(_isLoading ? '提交中...' : '提交报告'),
              style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 16),
                backgroundColor: AppTheme.statusInProgress,
              ),
            ),
          ],
        ),
      ),
    );
  }
}