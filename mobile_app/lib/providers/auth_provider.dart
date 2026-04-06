import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/worker.dart';
import '../services/api_service.dart';

class AuthProvider with ChangeNotifier {
  final ApiService _api = ApiService();

  bool _isLoading = true;
  bool _isAuthenticated = false;
  Worker? _worker;
  String? _token;

  bool get isLoading => _isLoading;
  bool get isAuthenticated => _isAuthenticated;
  Worker? get worker => _worker;
  String? get token => _token;
  ApiService get api => _api;

  Future<void> checkAuth() async {
    _isLoading = true;
    notifyListeners();

    try {
      final prefs = await SharedPreferences.getInstance();
      _token = prefs.getString('auth_token');
      final workerJson = prefs.getString('worker_data');

      if (_token != null && workerJson != null) {
        _api.setToken(_token!);
        _worker = Worker.fromJson(jsonDecode(workerJson));
        _isAuthenticated = true;
      }
    } catch (e) {
      debugPrint('Auth check error: $e');
    }

    _isLoading = false;
    notifyListeners();
  }

  Future<bool> login(String employeeId, String phone) async {
    try {
      _worker = await _api.login(employeeId, phone);
      _token = _api.token;
      _isAuthenticated = true;

      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('auth_token', _token!);
      await prefs.setString('employee_id', employeeId);
      await prefs.setString('worker_data', jsonEncode({
        'id': _worker!.id,
        'employee_id': _worker!.employeeId,
        'full_name': _worker!.fullName,
        'phone': _worker!.phone,
        'active': _worker!.active,
      }));

      notifyListeners();
      return true;
    } catch (e) {
      debugPrint('Login error: $e');
      return false;
    }
  }

  Future<void> logout() async {
    _api.clearToken();
    _token = null;
    _worker = null;
    _isAuthenticated = false;

    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
    await prefs.remove('employee_id');
    await prefs.remove('worker_data');

    notifyListeners();
  }
}