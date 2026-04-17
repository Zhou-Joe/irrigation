import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../services/api_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool? _isConnected;
  bool _isChecking = false;

  @override
  void initState() {
    super.initState();
    _checkConnection();
  }

  Future<void> _checkConnection() async {
    setState(() => _isChecking = true);
    final api = context.read<AuthProvider>().api;
    final connected = await api.checkConnection();
    if (mounted) {
      setState(() {
        _isConnected = connected;
        _isChecking = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final user = auth.user;

    // Role-specific colors
    Color roleColor;
    switch (user?.role) {
      case 'super_admin':
      case 'manager':
        roleColor = const Color(0xFF1B4332);
        break;
      case 'dept_user':
        roleColor = const Color(0xFF40916C);
        break;
      case 'field_worker':
        roleColor = const Color(0xFF52B788);
        break;
      default:
        roleColor = Colors.grey;
    }

    return ListView(
      children: [
        // User info header
        Container(
          padding: const EdgeInsets.all(24),
          color: Theme.of(context).colorScheme.primaryContainer,
          child: Row(
            children: [
              CircleAvatar(
                radius: 32,
                backgroundColor: Theme.of(context).colorScheme.primary,
                child: Text(
                  user?.fullName.substring(0, 1) ?? '?',
                  style: const TextStyle(
                    fontSize: 28,
                    color: Colors.white,
                  ),
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      user?.fullName ?? '未知用户',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '用户名: ${user?.username ?? '-'}',
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                    const SizedBox(height: 4),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: roleColor.withOpacity(0.2),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(
                        user?.roleDisplay ?? '未知角色',
                        style: TextStyle(color: roleColor, fontSize: 12, fontWeight: FontWeight.w500),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),

        // Role-specific info
        if (user?.isFieldWorker ?? false) ...[
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 24, 16, 8),
            child: Text('工作信息', style: TextStyle(fontWeight: FontWeight.bold)),
          ),
          ListTile(
            leading: const Icon(Icons.badge),
            title: const Text('工号'),
            subtitle: Text(user?.employeeId ?? '-'),
          ),
        ],

        if (user?.isDeptUser ?? false) ...[
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 24, 16, 8),
            child: Text('部门信息', style: TextStyle(fontWeight: FontWeight.bold)),
          ),
          ListTile(
            leading: const Icon(Icons.business),
            title: const Text('部门'),
            subtitle: Text(user?.departmentDisplay ?? '-'),
          ),
        ],

        // Permissions info
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 24, 16, 8),
          child: Text('功能权限', style: TextStyle(fontWeight: FontWeight.bold)),
        ),
        _buildPermissionTile(
          icon: Icons.map,
          title: '查看区域地图',
          enabled: true,
        ),
        _buildPermissionTile(
          icon: Icons.water_drop,
          title: '浇水协调需求',
          enabled: true,
          subtitle: '查看和提交',
        ),
        _buildPermissionTile(
          icon: Icons.build,
          title: '维护与维修',
          enabled: !(user?.isDeptUser ?? false),
          subtitle: user?.isDeptUser == true ? '部门用户无此权限' : '查看和提交',
        ),
        _buildPermissionTile(
          icon: Icons.support_agent,
          title: '项目支持',
          enabled: !(user?.isDeptUser ?? false),
          subtitle: user?.isDeptUser == true ? '部门用户无此权限' : '查看和提交',
        ),
        _buildPermissionTile(
          icon: Icons.approval,
          title: '审批工单',
          enabled: user?.isAdmin ?? false,
          subtitle: user?.isAdmin == true ? '批准或拒绝' : '仅管理员可用',
        ),

        // Server settings
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 24, 16, 8),
          child: Text('服务器设置', style: TextStyle(fontWeight: FontWeight.bold)),
        ),
        // Connection status
        ListTile(
          leading: _isChecking
              ? const SizedBox(
                  width: 24,
                  height: 24,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : Icon(
                  _isConnected == true ? Icons.cloud_done : Icons.cloud_off,
                  color: _isConnected == true ? const Color(0xFF40916C) : Colors.red,
                ),
          title: const Text('服务器连接'),
          subtitle: Text(
            _isChecking
                ? '检测中...'
                : _isConnected == true
                    ? '已连接'
                    : '未连接',
            style: TextStyle(
              color: _isConnected == true ? const Color(0xFF40916C) : Colors.red,
            ),
          ),
          trailing: IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _isChecking ? null : _checkConnection,
          ),
        ),
        ListTile(
          leading: const Icon(Icons.dns),
          title: const Text('服务器地址'),
          subtitle: Text(ApiService.baseUrl),
          trailing: const Icon(Icons.edit, size: 20),
          onTap: () => _showServerDialog(context),
        ),

        // App settings
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 24, 16, 8),
          child: Text('应用设置', style: TextStyle(fontWeight: FontWeight.bold)),
        ),
        const ListTile(
          leading: Icon(Icons.language),
          title: Text('语言'),
          subtitle: Text('简体中文'),
        ),
        ListTile(
          leading: const Icon(Icons.location_on),
          title: const Text('位置服务'),
          subtitle: const Text('用于记录工作位置'),
          trailing: Switch(
            value: true,
            onChanged: null,
          ),
        ),

        // About
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 24, 16, 8),
          child: Text('关于', style: TextStyle(fontWeight: FontWeight.bold)),
        ),
        const ListTile(
          leading: Icon(Icons.info),
          title: Text('版本'),
          subtitle: Text('1.1.0'),
        ),

        // Logout
        const SizedBox(height: 24),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: OutlinedButton.icon(
            onPressed: () => _logout(context),
            icon: const Icon(Icons.logout),
            label: const Text('退出登录'),
            style: OutlinedButton.styleFrom(
              foregroundColor: Theme.of(context).colorScheme.error,
              side: BorderSide(color: Theme.of(context).colorScheme.error),
              padding: const EdgeInsets.symmetric(vertical: 12),
            ),
          ),
        ),
        const SizedBox(height: 32),
      ],
    );
  }

  Widget _buildPermissionTile({
    required IconData icon,
    required String title,
    required bool enabled,
    String? subtitle,
  }) {
    return ListTile(
      leading: Icon(
        icon,
        color: enabled ? const Color(0xFF40916C) : Colors.grey,
      ),
      title: Text(
        title,
        style: TextStyle(
          color: enabled ? null : Colors.grey,
        ),
      ),
      subtitle: Text(
        subtitle ?? (enabled ? '已启用' : '未启用'),
        style: TextStyle(
          color: enabled ? const Color(0xFF40916C) : Colors.grey,
          fontSize: 12,
        ),
      ),
      trailing: Icon(
        enabled ? Icons.check_circle : Icons.cancel,
        color: enabled ? const Color(0xFF40916C) : Colors.grey,
      ),
    );
  }

  void _showServerDialog(BuildContext context) {
    final controller = TextEditingController(text: ApiService.baseUrl);

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('服务器地址'),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(
            hintText: 'http://example.com/api',
            border: OutlineInputBorder(),
          ),
          keyboardType: TextInputType.url,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () async {
              await ApiService.setBaseUrl(controller.text.trim());
              if (context.mounted) {
                Navigator.pop(context);
                _checkConnection();
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('已更新服务器地址')),
                );
              }
            },
            child: const Text('保存'),
          ),
        ],
      ),
    );
  }

  void _logout(BuildContext context) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('退出登录'),
        content: const Text('确定要退出登录吗？'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () {
              context.read<AuthProvider>().logout();
              Navigator.pop(context);
            },
            child: const Text('退出'),
          ),
        ],
      ),
    );
  }
}
