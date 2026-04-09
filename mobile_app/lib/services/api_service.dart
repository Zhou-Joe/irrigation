import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../models/zone.dart';
import '../models/user.dart';
import '../models/work_log.dart';

class ApiService {
  // 根据实际部署修改这个地址
  // Web需要使用127.0.0.1而不是localhost以避免某些CORS问题
  static String baseUrl = kIsWeb
      ? 'http://127.0.0.1:8000/api'
      : 'http://localhost:8000/api';

  String? _token;
  String? get token => _token;

  void setToken(String token) {
    _token = token;
  }

  void clearToken() {
    _token = null;
  }

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (_token != null) 'Authorization': 'Token $_token',
  };

  /// Check server connectivity
  Future<bool> checkConnection() async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/zones/'), headers: _headers)
          .timeout(const Duration(seconds: 5));
      return response.statusCode == 200 || response.statusCode == 401 || response.statusCode == 403;
    } catch (_) {
      return false;
    }
  }

  /// Login with username and password
  /// Returns user data with role information
  Future<Map<String, dynamic>> login(String username, String password) async {
    final response = await http.post(
      Uri.parse('$baseUrl/auth/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'username': username,
        'password': password,
      }),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      _token = data['token'];
      return data;
    }
    final error = jsonDecode(response.body);
    throw Exception(error['error'] ?? '登录失败');
  }

  /// Get zones list
  Future<List<Zone>> getZones() async {
    final response = await http.get(
      Uri.parse('$baseUrl/zones/'),
      headers: _headers,
    );

    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((json) => Zone.fromJson(json)).toList();
    }
    throw Exception('获取区域失败');
  }

  /// Get single zone
  Future<Zone> getZone(int id) async {
    final response = await http.get(
      Uri.parse('$baseUrl/zones/$id/'),
      headers: _headers,
    );

    if (response.statusCode == 200) {
      return Zone.fromJson(jsonDecode(response.body));
    }
    throw Exception('获取区域失败');
  }

  /// Submit work log
  Future<WorkLog> submitWorkLog(WorkLog log) async {
    final response = await http.post(
      Uri.parse('$baseUrl/work-logs/'),
      headers: _headers,
      body: jsonEncode(log.toJson()),
    );

    if (response.statusCode == 201) {
      return WorkLog.fromJson(jsonDecode(response.body));
    }
    throw Exception('提交失败: ${response.body}');
  }

  /// Get work types list
  Future<List<String>> getWorkTypes() async {
    final response = await http.get(
      Uri.parse('$baseUrl/work-types/'),
      headers: _headers,
    );

    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((e) => e.toString()).toList();
    }
    // 返回默认工作类型
    return ['浇水', '施肥', '修剪', '除草', '喷药', '种植', '收获', '其他'];
  }

  /// Get all requests (filtered by role on server)
  Future<List<Map<String, dynamic>>> getAllRequests() async {
    final response = await http.get(
      Uri.parse('$baseUrl/requests'),
      headers: _headers,
    );

    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((e) => e as Map<String, dynamic>).toList();
    }
    throw Exception('获取需求列表失败');
  }

  /// Submit maintenance request
  Future<Map<String, dynamic>> submitMaintenanceRequest({
    required int zoneId,
    required String date,
    required String startTime,
    required String endTime,
    required String participants,
    required String workContent,
    String? materials,
    String? feedback,
    List<String>? photos,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/maintenance-requests/'),
      headers: _headers,
      body: jsonEncode({
        'zone': zoneId,
        'date': date,
        'start_time': startTime,
        'end_time': endTime,
        'participants': participants,
        'work_content': workContent,
        'materials': materials ?? '',
        'feedback': feedback ?? '',
        'photos': photos ?? [],
      }),
    );

    if (response.statusCode == 201) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('提交失败: ${response.body}');
  }

  /// Submit project support request
  Future<Map<String, dynamic>> submitProjectSupportRequest({
    required int zoneId,
    required String date,
    required String startTime,
    required String endTime,
    required String participants,
    required String workContent,
    String? materials,
    String? feedback,
    List<String>? photos,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/project-support-requests/'),
      headers: _headers,
      body: jsonEncode({
        'zone': zoneId,
        'date': date,
        'start_time': startTime,
        'end_time': endTime,
        'participants': participants,
        'work_content': workContent,
        'materials': materials ?? '',
        'feedback': feedback ?? '',
        'photos': photos ?? [],
      }),
    );

    if (response.statusCode == 201) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('提交失败: ${response.body}');
  }

  /// Submit water request
  Future<Map<String, dynamic>> submitWaterRequest({
    required int zoneId,
    required String userType,
    String? userTypeOther,
    required String requestType,
    String? requestTypeOther,
    required String startDatetime,
    required String endDatetime,
    List<String>? photos,
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/water-requests/'),
      headers: _headers,
      body: jsonEncode({
        'zone': zoneId,
        'user_type': userType,
        'user_type_other': userTypeOther ?? '',
        'request_type': requestType,
        'request_type_other': requestTypeOther ?? '',
        'start_datetime': startDatetime,
        'end_datetime': endDatetime,
        'photos': photos ?? [],
      }),
    );

    if (response.statusCode == 201) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('提交失败: ${response.body}');
  }

  /// Update request status (admin only)
  Future<void> updateRequestStatus({
    required String typeCode,
    required int requestId,
    required String status,
    String? statusNotes,
  }) async {
    String endpoint;
    switch (typeCode) {
      case 'maintenance':
        endpoint = '$baseUrl/maintenance-requests/$requestId/';
        break;
      case 'project_support':
        endpoint = '$baseUrl/project-support-requests/$requestId/';
        break;
      case 'water':
        endpoint = '$baseUrl/water-requests/$requestId/';
        break;
      default:
        throw Exception('未知请求类型');
    }

    final response = await http.patch(
      Uri.parse(endpoint),
      headers: _headers,
      body: jsonEncode({
        'status': status,
        'status_notes': statusNotes ?? '',
      }),
    );

    if (response.statusCode != 200) {
      throw Exception('更新失败: ${response.body}');
    }
  }

  /// Get single request detail
  Future<Map<String, dynamic>> getRequestDetail(String typeCode, int requestId) async {
    String endpoint;
    switch (typeCode) {
      case 'maintenance':
        endpoint = '$baseUrl/maintenance-requests/$requestId/';
        break;
      case 'project_support':
        endpoint = '$baseUrl/project-support-requests/$requestId/';
        break;
      case 'water':
        endpoint = '$baseUrl/water-requests/$requestId/';
        break;
      default:
        throw Exception('未知请求类型');
    }

    final response = await http.get(
      Uri.parse(endpoint),
      headers: _headers,
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('获取详情失败: ${response.body}');
  }

  /// Update request detail
  Future<Map<String, dynamic>> updateRequestDetail({
    required String typeCode,
    required int requestId,
    required Map<String, dynamic> data,
  }) async {
    String endpoint;
    switch (typeCode) {
      case 'maintenance':
        endpoint = '$baseUrl/maintenance-requests/$requestId/';
        break;
      case 'project_support':
        endpoint = '$baseUrl/project-support-requests/$requestId/';
        break;
      case 'water':
        endpoint = '$baseUrl/water-requests/$requestId/';
        break;
      default:
        throw Exception('未知请求类型');
    }

    final response = await http.patch(
      Uri.parse(endpoint),
      headers: _headers,
      body: jsonEncode(data),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('更新失败: ${response.body}');
  }

  /// Get weather data
  Future<List<Map<String, dynamic>>> getWeather() async {
    final response = await http.get(
      Uri.parse('$baseUrl/weather'),
      headers: _headers,
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return List<Map<String, dynamic>>.from(data['data']);
    }
    throw Exception('获取天气失败');
  }
}