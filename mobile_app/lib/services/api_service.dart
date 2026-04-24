import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';
import 'package:http_parser/http_parser.dart';
import 'package:image_picker/image_picker.dart';
import '../models/zone.dart';
import '../models/user.dart';
import '../models/work_log.dart';

class ApiService {
  // Default server address - can be overridden via settings
  static const String _defaultBaseUrl = 'https://www.zctestbench.asia/api';
  static String baseUrl = _defaultBaseUrl;

  // DNS-over-HTTPS cache: hostname -> IP
  static String? _cachedDnsIp;

  /// Normalize URL: ensure it has a scheme and no trailing slash
  static String _normalizeUrl(String url) {
    url = url.trim();
    if (url.isEmpty) return _defaultBaseUrl;
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://$url';
    }
    while (url.endsWith('/')) {
      url = url.substring(0, url.length - 1);
    }
    return url;
  }

  /// Load saved server URL from SharedPreferences
  static Future<void> loadSavedBaseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString('server_base_url');
    if (saved != null && saved.isNotEmpty) {
      baseUrl = _normalizeUrl(saved);
    }
  }

  /// Save server URL to SharedPreferences
  static Future<void> setBaseUrl(String url) async {
    url = _normalizeUrl(url);
    baseUrl = url;
    _cachedDnsIp = null; // reset DNS cache when URL changes
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('server_base_url', url);
  }

  /// Resolve hostname via DNS-over-HTTPS when system DNS fails.
  /// Uses top-level http.get to avoid circular dependency with _client.
  static Future<String?> _resolveViaDoh(String hostname) async {
    for (final dohUrl in [
      'https://dns.alidns.com/resolve?name=$hostname&type=A',
      'https://dns.google/resolve?name=$hostname&type=A',
    ]) {
      try {
        final dohResponse = await http
            .get(Uri.parse(dohUrl))
            .timeout(const Duration(seconds: 5));
        final data = jsonDecode(dohResponse.body);
        if (data['Answer'] != null) {
          for (final answer in data['Answer']) {
            if (answer['type'] == 1) {
              return answer['data'] as String;
            }
          }
        }
      } catch (_) {
        continue;
      }
    }
    return null;
  }

  // Custom HTTP client with DNS-over-HTTPS fallback.
  // Lazily initialized so it's created after the app starts.
  http.Client? _innerClient;
  http.Client get _client => _innerClient ??= _createClient();

  http.Client _createClient() {
    final httpClient = HttpClient();
    httpClient.connectionFactory = (uri, proxyHost, proxyPort) async {
      try {
        return await Socket.startConnect(uri.host, uri.port)
            .timeout(const Duration(seconds: 3));
      } catch (e) {
        // System DNS failed or timed out — try DNS-over-HTTPS
        final ip = _cachedDnsIp ?? await _resolveViaDoh(uri.host);
        if (ip != null) {
          _cachedDnsIp = ip;
          return await Socket.startConnect(ip, uri.port)
              .timeout(const Duration(seconds: 5));
        }
        rethrow;
      }
    };
    return IOClient(httpClient);
  }

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

  /// Check server connectivity - returns (success, errorMessage)
  Future<(bool, String?)> checkConnection() async {
    try {
      final response = await _client
          .get(Uri.parse('$baseUrl/zones/'), headers: _headers)
          .timeout(const Duration(seconds: 15));
      if (response.statusCode == 200 || response.statusCode == 401 || response.statusCode == 403) {
        return (true, _cachedDnsIp != null ? '连接成功 (DNS-over-HTTPS: $_cachedDnsIp)' : null);
      }
      return (false, 'HTTP ${response.statusCode}: ${response.body.substring(0, (response.body.length > 100 ? 100 : response.body.length))}');
    } catch (e) {
      final errStr = e.toString();
      if (errStr.contains('failed host lookup') || errStr.contains('no address associated')) {
        return (false, 'DNS解析失败: 无法连接服务器\n\n请尝试:\n1. 设置 → 网络 → 私人DNS → dns.alidns.com\n2. 切换飞行模式后重试\n3. 更换WiFi/移动网络');
      }
      return (false, errStr);
    }
  }

  /// Login with username and password
  /// Returns user data with role information
  Future<Map<String, dynamic>> login(String username, String password) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/auth/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'username': username,
        'password': password,
      }),
    ).timeout(const Duration(seconds: 10));

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
    final response = await _client.get(
      Uri.parse('$baseUrl/zones/'),
      headers: _headers,
    );

    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data
          .map((json) {
            try {
              return Zone.fromJson(json);
            } catch (_) {
              return null;
            }
          })
          .whereType<Zone>()
          .toList();
    }
    throw Exception('获取区域失败');
  }

  /// Get single zone
  Future<Zone> getZone(int id) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/zones/$id/'),
      headers: _headers,
    );

    if (response.statusCode == 200) {
      return Zone.fromJson(jsonDecode(response.body));
    }
    throw Exception('获取区域失败');
  }

  /// Get equipment for a zone by zone code
  Future<List<Map<String, dynamic>>> getZoneEquipment(String zoneCode) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/zone-equipment/?zone_code=$zoneCode'),
      headers: _headers,
    );

    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((e) => e as Map<String, dynamic>).toList();
    }
    throw Exception('获取设备列表失败');
  }

  /// Get zone detail with plants, equipment, stats
  Future<Map<String, dynamic>> getZoneDetail(int zoneId) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/zones/$zoneId/zone-detail/'),
      headers: _headers,
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('获取区域详情失败');
  }

  /// Submit work log
  Future<WorkLog> submitWorkLog(WorkLog log) async {
    final response = await _client.post(
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
    final response = await _client.get(
      Uri.parse('$baseUrl/work-types/'),
      headers: _headers,
    );

    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((e) => e.toString()).toList();
    }
    return ['浇水', '施肥', '修剪', '除草', '喷药', '种植', '收获', '其他'];
  }

  /// Get all requests (filtered by role on server)
  Future<List<Map<String, dynamic>>> getAllRequests() async {
    final response = await _client.get(
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
    final response = await _client.post(
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
    final response = await _client.post(
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
    final response = await _client.post(
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

    final response = await _client.patch(
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

    final response = await _client.get(
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

    final response = await _client.patch(
      Uri.parse(endpoint),
      headers: _headers,
      body: jsonEncode(data),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('更新失败: ${response.body}');
  }

  // ==================== Work Report System ====================

  /// Get locations (CCU list)
  Future<List<Map<String, dynamic>>> getLocations() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/locations/'),
      headers: _headers,
    );
    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((e) => e as Map<String, dynamic>).toList();
    }
    throw Exception('获取位置列表失败');
  }

  /// Get work categories
  Future<List<Map<String, dynamic>>> getWorkCategories() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/work-categories/'),
      headers: _headers,
    );
    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((e) => e as Map<String, dynamic>).toList();
    }
    throw Exception('获取工作分类失败');
  }

  /// Get workers list (for admin filter)
  Future<List<Map<String, dynamic>>> getWorkers() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/workers/'),
      headers: _headers,
    );
    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((e) => e as Map<String, dynamic>).toList();
    }
    throw Exception('获取工人列表失败');
  }

  /// Get info sources
  Future<List<Map<String, dynamic>>> getInfoSources() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/info-sources/'),
      headers: _headers,
    );
    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((e) => e as Map<String, dynamic>).toList();
    }
    throw Exception('获取信息来源失败');
  }

  /// Get fault categories with nested sub_types
  Future<List<Map<String, dynamic>>> getFaultCategories() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/fault-categories/'),
      headers: _headers,
    );
    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((e) => e as Map<String, dynamic>).toList();
    }
    throw Exception('获取故障分类失败');
  }

  /// Get work reports list
  Future<List<Map<String, dynamic>>> getWorkReports({
    String? dateFrom,
    String? dateTo,
    int? location,
    int? workCategory,
    int? worker,
    int? zone,
    bool? isDifficult,
  }) async {
    final params = <String, String>{};
    if (dateFrom != null) params['date_from'] = dateFrom;
    if (dateTo != null) params['date_to'] = dateTo;
    if (location != null) params['location'] = location.toString();
    if (workCategory != null) params['work_category'] = workCategory.toString();
    if (worker != null) params['worker'] = worker.toString();
    if (zone != null) params['zone'] = zone.toString();
    if (isDifficult == true) params['is_difficult'] = 'true';

    final query = params.entries.map((e) => '${e.key}=${e.value}').join('&');
    final url = query.isNotEmpty ? '$baseUrl/work-reports/?$query' : '$baseUrl/work-reports/';

    final response = await _client.get(Uri.parse(url), headers: _headers);
    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((e) => e as Map<String, dynamic>).toList();
    }
    throw Exception('获取工作日报失败');
  }

  /// Get single work report
  Future<Map<String, dynamic>> getWorkReport(int id) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/work-reports/$id/'),
      headers: _headers,
    );
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('获取日报详情失败');
  }

  /// Submit work report
  Future<Map<String, dynamic>> submitWorkReport({
    required String date,
    String weather = '',
    required int location,
    required int workCategory,
    String zoneLocation = '',
    required String remark,
    int? infoSource,
    bool isDifficult = false,
    bool isDifficultResolved = false,
    required List<Map<String, dynamic>> faultEntries,
  }) async {
    final response = await _client.post(
      Uri.parse('$baseUrl/work-reports/'),
      headers: _headers,
      body: jsonEncode({
        'date': date,
        'weather': weather,
        'location': location,
        'work_category': workCategory,
        'zone_location_code': zoneLocation,
        'remark': remark,
        if (infoSource != null) 'info_source': infoSource,
        'is_difficult': isDifficult,
        'is_difficult_resolved': isDifficultResolved,
        'fault_entries': faultEntries,
      }),
    );
    if (response.statusCode == 201) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('提交失败: ${response.body}');
  }

  /// Update work report
  Future<Map<String, dynamic>> updateWorkReport({
    required int id,
    required String date,
    String weather = '',
    required int location,
    required int workCategory,
    String zoneLocation = '',
    required String remark,
    int? infoSource,
    bool isDifficult = false,
    bool isDifficultResolved = false,
    required List<Map<String, dynamic>> faultEntries,
  }) async {
    final response = await _client.put(
      Uri.parse('$baseUrl/work-reports/$id/'),
      headers: _headers,
      body: jsonEncode({
        'date': date,
        'weather': weather,
        'location': location,
        'work_category': workCategory,
        'zone_location_code': zoneLocation,
        'remark': remark,
        if (infoSource != null) 'info_source': infoSource,
        'is_difficult': isDifficult,
        'is_difficult_resolved': isDifficultResolved,
        'fault_entries': faultEntries,
      }),
    );
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('更新失败: ${response.body}');
  }

  /// Delete work report
  Future<void> deleteWorkReport(int id) async {
    final response = await _client.delete(
      Uri.parse('$baseUrl/work-reports/$id/'),
      headers: _headers,
    );
    if (response.statusCode != 204) {
      throw Exception('删除失败: ${response.body}');
    }
  }

  /// Upload photos for a work report
  Future<Map<String, dynamic>> uploadWorkReportPhotos({
    required int reportId,
    required List<XFile> files,
  }) async {
    final request = http.MultipartRequest(
      'POST',
      Uri.parse('$baseUrl/work-reports/$reportId/upload-photos/'),
    );
    request.headers['Authorization'] = 'Token $_token';

    for (int i = 0; i < files.length; i++) {
      final file = files[i];
      final ext = file.name.split('.').last.toLowerCase();
      final mimeType = ext == 'png' ? 'image/png' : 'image/jpeg';
      final bytes = await file.readAsBytes();
      request.files.add(http.MultipartFile.fromBytes(
        'files',
        bytes,
        filename: file.name.isNotEmpty ? file.name : 'photo_$i.$ext',
        contentType: MediaType(mimeType.split('/')[0], mimeType.split('/')[1]),
      ));
    }

    // Use custom client to send (gets DNS-over-HTTPS fallback)
    final streamed = await _client.send(request);
    final response = await http.Response.fromStream(streamed);
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('上传照片失败: ${response.body}');
  }

  /// Remove a photo from a work report
  Future<void> removeWorkReportPhoto({
    required int reportId,
    required String photoPath,
  }) async {
    final response = await _client.delete(
      Uri.parse('$baseUrl/work-reports/$reportId/remove-photo/?photo=${Uri.encodeComponent(photoPath)}'),
      headers: _headers,
    );
    if (response.statusCode != 200) {
      throw Exception('删除照片失败');
    }
  }

  // ==================== End Work Report System ====================

  // ==================== Demand Record System ====================

  /// Get demand categories
  Future<List<Map<String, dynamic>>> getDemandCategories() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/demand-categories/'),
      headers: _headers,
    );
    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((e) => e as Map<String, dynamic>).toList();
    }
    throw Exception('获取需求类别失败');
  }

  /// Get demand departments
  Future<List<Map<String, dynamic>>> getDemandDepartments() async {
    final response = await _client.get(
      Uri.parse('$baseUrl/demand-departments/'),
      headers: _headers,
    );
    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((e) => e as Map<String, dynamic>).toList();
    }
    throw Exception('获取需求部门失败');
  }

  /// Get demand records list
  Future<List<Map<String, dynamic>>> getDemandRecords({
    String? dateFrom,
    String? dateTo,
    int? zone,
    int? category,
    int? department,
    String? status,
    bool? isGlobal,
  }) async {
    final params = <String, String>{};
    if (dateFrom != null) params['date_from'] = dateFrom;
    if (dateTo != null) params['date_to'] = dateTo;
    if (zone != null) params['zone'] = zone.toString();
    if (category != null) params['category'] = category.toString();
    if (department != null) params['department'] = department.toString();
    if (status != null) params['status'] = status;
    if (isGlobal == true) params['is_global'] = 'true';

    final query = params.entries.map((e) => '${e.key}=${e.value}').join('&');
    final url = query.isNotEmpty ? '$baseUrl/demand-records/?$query' : '$baseUrl/demand-records/';

    final response = await _client.get(Uri.parse(url), headers: _headers);
    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((e) => e as Map<String, dynamic>).toList();
    }
    throw Exception('获取需求记录失败');
  }

  /// Get single demand record
  Future<Map<String, dynamic>> getDemandRecord(int id) async {
    final response = await _client.get(
      Uri.parse('$baseUrl/demand-records/$id/'),
      headers: _headers,
    );
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('获取需求详情失败');
  }

  /// Create demand record (dept_user or admin)
  Future<Map<String, dynamic>> createDemandRecord({
    required String date,
    required String content,
    int? zone,
    String? zoneText,
    bool isGlobalEvent = false,
    int? category,
    String? categoryText,
    String? startTime,
    String? endTime,
    int? demandDepartment,
    String? demandDepartmentText,
    String? demandContact,
    String status = 'submitted',
  }) async {
    final body = <String, dynamic>{
      'date': date,
      'content': content,
      'is_global_event': isGlobalEvent,
      'status': status,
    };
    if (zone != null) body['zone'] = zone;
    if (zoneText != null) body['zone_text'] = zoneText;
    if (category != null) body['category'] = category;
    if (categoryText != null) body['category_text'] = categoryText;
    if (startTime != null) body['start_time'] = startTime;
    if (endTime != null) body['end_time'] = endTime;
    if (demandDepartment != null) body['demand_department'] = demandDepartment;
    if (demandDepartmentText != null) body['demand_department_text'] = demandDepartmentText;
    if (demandContact != null) body['demand_contact'] = demandContact;

    final response = await _client.post(
      Uri.parse('$baseUrl/demand-records/'),
      headers: _headers,
      body: jsonEncode(body),
    );
    if (response.statusCode == 201) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('提交需求失败: ${response.body}');
  }

  /// Update demand record
  Future<Map<String, dynamic>> updateDemandRecord({
    required int id,
    String? status,
    String? statusNotes,
    String? content,
  }) async {
    final body = <String, dynamic>{};
    if (status != null) body['status'] = status;
    if (statusNotes != null) body['status_notes'] = statusNotes;
    if (content != null) body['content'] = content;

    final response = await _client.patch(
      Uri.parse('$baseUrl/demand-records/$id/'),
      headers: _headers,
      body: jsonEncode(body),
    );
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('更新需求失败: ${response.body}');
  }

  /// Get demand statistics (admin only)
  Future<Map<String, dynamic>> getDemandStats({
    String? startDate,
    String? endDate,
    String groupBy = 'day',
    String dimension = 'zone',
  }) async {
    final params = <String, String>{
      'group_by': groupBy,
      'dimension': dimension,
    };
    if (startDate != null) params['start_date'] = startDate;
    if (endDate != null) params['end_date'] = endDate;

    final query = params.entries.map((e) => '${e.key}=${e.value}').join('&');
    final response = await _client.get(
      Uri.parse('$baseUrl/demand-stats?$query'),
      headers: _headers,
    );
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('获取统计数据失败');
  }

  /// Get demand calendar
  Future<Map<String, dynamic>> getDemandCalendar({
    int? year,
    int? month,
  }) async {
    final params = <String, String>{};
    if (year != null) params['year'] = year.toString();
    if (month != null) params['month'] = month.toString();

    final query = params.entries.map((e) => '${e.key}=${e.value}').join('&');
    final url = query.isNotEmpty ? '$baseUrl/demand-calendar?$query' : '$baseUrl/demand-calendar';

    final response = await _client.get(Uri.parse(url), headers: _headers);
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception('获取日历数据失败');
  }

  // ==================== End Demand Record System ====================

  /// Get weather data
  Future<List<Map<String, dynamic>>> getWeather() async {
    final response = await _client.get(
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
