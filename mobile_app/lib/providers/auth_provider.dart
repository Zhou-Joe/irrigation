import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/user.dart';
import '../services/api_service.dart';

class AuthProvider with ChangeNotifier {
  final ApiService _api = ApiService();

  bool _isLoading = true;
  bool _isAuthenticated = false;
  User? _user;
  String? _token;

  bool get isLoading => _isLoading;
  bool get isAuthenticated => _isAuthenticated;
  User? get user => _user;
  String? get token => _token;
  ApiService get api => _api;

  /// Check if user is admin/manager
  bool get isAdmin => _user?.isAdmin ?? false;

  /// Check if user is field worker
  bool get isFieldWorker => _user?.isFieldWorker ?? false;

  /// Check if user is department user
  bool get isDeptUser => _user?.isDeptUser ?? false;

  /// Get user role
  String get role => _user?.role ?? '';

  Future<void> checkAuth() async {
    _isLoading = true;
    notifyListeners();

    try {
      // Load saved server URL first
      await ApiService.loadSavedBaseUrl();

      final prefs = await SharedPreferences.getInstance();
      _token = prefs.getString('auth_token');
      final userJson = prefs.getString('user_data');

      if (_token != null && userJson != null) {
        _api.setToken(_token!);
        _user = User.fromJson(jsonDecode(userJson));
        _isAuthenticated = true;
      }
    } catch (e) {
      debugPrint('Auth check error: $e');
    }

    _isLoading = false;
    notifyListeners();
  }

  Future<bool> login(String username, String password) async {
    try {
      final response = await _api.login(username, password);
      _token = response['token'];
      _user = User.fromJson(response['user']);
      _isAuthenticated = true;

      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('auth_token', _token!);
      await prefs.setString('user_data', jsonEncode(response['user']));

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
    _user = null;
    _isAuthenticated = false;

    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
    await prefs.remove('user_data');

    notifyListeners();
  }
}