import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:horticulture/models/zone.dart';
import 'package:horticulture/providers/auth_provider.dart';
import 'package:horticulture/screens/work_report_form_screen.dart';
import 'package:horticulture/services/api_service.dart';
import 'package:horticulture/theme/app_theme.dart';

class _FakeApiService extends ApiService {
  _FakeApiService({
    this.failLocations = false,
    this.failWorkCategories = false,
    this.failInfoSources = false,
    this.failFaultCategories = false,
    this.failZones = false,
  });

  final bool failLocations;
  final bool failWorkCategories;
  final bool failInfoSources;
  final bool failFaultCategories;
  final bool failZones;

  Future<T> _respond<T>(T value, {bool shouldFail = false}) async {
    await Future<void>.delayed(const Duration(milliseconds: 10));
    if (shouldFail) {
      throw Exception('mock failure');
    }
    return value;
  }

  @override
  Future<List<Map<String, dynamic>>> getLocations() {
    return _respond(<Map<String, dynamic>>[
      {'id': 1, 'name': '1号位'},
    ], shouldFail: failLocations);
  }

  @override
  Future<List<Map<String, dynamic>>> getWorkCategories() {
    return _respond(<Map<String, dynamic>>[
      {'id': 1, 'name': '维修'},
    ], shouldFail: failWorkCategories);
  }

  @override
  Future<List<Map<String, dynamic>>> getInfoSources() {
    return _respond(<Map<String, dynamic>>[
      {'id': 1, 'name': '巡检'},
    ], shouldFail: failInfoSources);
  }

  @override
  Future<List<Map<String, dynamic>>> getFaultCategories() {
    return _respond(<Map<String, dynamic>>[
      {
        'id': 1,
        'name_zh': '电气',
        'sub_types': [
          {'id': 11, 'name_zh': '断电'},
        ],
      },
    ], shouldFail: failFaultCategories);
  }

  @override
  Future<List<Zone>> getZones() {
    return _respond(<Zone>[
      Zone(
        id: 1,
        code: 'Z-01',
        name: '一区',
        status: 'unarranged',
        statusDisplay: '未安排',
      ),
    ], shouldFail: failZones);
  }
}

Widget _buildTestApp(ApiService api) {
  return ChangeNotifierProvider(
    create: (_) => AuthProvider(api: api),
    child: MaterialApp(
      theme: AppTheme.light(),
      home: const WorkReportFormScreen(),
    ),
  );
}

void main() {
  testWidgets('new work report screen renders without framework exceptions', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(_buildTestApp(_FakeApiService()));

    await tester.pumpAndSettle();

    expect(find.text('新建维修工单'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('failed dropdown load stays on screen without uncaught async exceptions', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      _buildTestApp(
        _FakeApiService(
          failLocations: true,
          failWorkCategories: true,
          failInfoSources: true,
          failFaultCategories: true,
          failZones: true,
        ),
      ),
    );

    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.textContaining('加载数据失败'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
