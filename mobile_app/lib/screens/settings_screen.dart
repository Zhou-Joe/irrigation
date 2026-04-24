import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../services/api_service.dart';
import '../widgets/modern_ui.dart';

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
    final result = await api.checkConnection();
    if (mounted) {
      setState(() {
        _isConnected = result.$1;
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

    return AppBackground(
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 120),
        children: [
          AppHeroCard(
            title: user?.fullName ?? '未知用户',
            subtitle:
                '${user?.roleDisplay ?? '未知角色'} · ${user?.username ?? '-'}',
            icon: Icons.account_circle_rounded,
            actions: [
              AppStatusBadge(
                label: _isChecking
                    ? '检测中'
                    : _isConnected == true
                    ? '在线'
                    : '离线',
                color: _isConnected == true
                    ? const Color(0xFF9EE6BD)
                    : const Color(0xFFFFD7D7),
              ),
            ],
          ),
          const SizedBox(height: 18),
          AppCard(
            child: Row(
              children: [
                CircleAvatar(
                  radius: 28,
                  backgroundColor: roleColor.withOpacity(0.16),
                  child: Text(
                    user?.fullName.substring(0, 1) ?? '?',
                    style: TextStyle(
                      fontSize: 24,
                      fontWeight: FontWeight.w700,
                      color: roleColor,
                    ),
                  ),
                ),
                const SizedBox(width: 14),
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
                        '用户名 ${user?.username ?? '-'}',
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: AppColors.muted,
                        ),
                      ),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 8,
                  ),
                  decoration: BoxDecoration(
                    color: roleColor.withOpacity(0.14),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    user?.roleDisplay ?? '未知角色',
                    style: TextStyle(
                      color: roleColor,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
          ),
          if (user?.isFieldWorker ?? false) ...[
            const SizedBox(height: 18),
            const AppSectionTitle(title: '工作信息'),
            const SizedBox(height: 10),
            AppCard(
              child: ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.badge_outlined),
                title: const Text('工号'),
                subtitle: Text(user?.employeeId ?? '-'),
              ),
            ),
          ],
          if (user?.isDeptUser ?? false) ...[
            const SizedBox(height: 18),
            const AppSectionTitle(title: '部门信息'),
            const SizedBox(height: 10),
            AppCard(
              child: ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.apartment_rounded),
                title: const Text('部门'),
                subtitle: Text(user?.departmentDisplay ?? '-'),
              ),
            ),
          ],
          const SizedBox(height: 18),
          const AppSectionTitle(title: '功能权限', subtitle: '根据当前角色展示可用能力'),
          const SizedBox(height: 10),
          AppCard(
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
            child: Column(
              children: [
                _buildPermissionTile(
                  icon: Icons.map_rounded,
                  title: '查看区域地图',
                  enabled: true,
                ),
                _buildPermissionTile(
                  icon: Icons.water_drop_rounded,
                  title: '浇水协调需求',
                  enabled: true,
                  subtitle: '查看和提交',
                ),
                _buildPermissionTile(
                  icon: Icons.build_circle_outlined,
                  title: '维护与维修',
                  enabled: !(user?.isDeptUser ?? false),
                  subtitle: user?.isDeptUser == true ? '部门用户无此权限' : '查看和提交',
                ),
                _buildPermissionTile(
                  icon: Icons.support_agent_rounded,
                  title: '项目支持',
                  enabled: !(user?.isDeptUser ?? false),
                  subtitle: user?.isDeptUser == true ? '部门用户无此权限' : '查看和提交',
                ),
                _buildPermissionTile(
                  icon: Icons.approval_rounded,
                  title: '审批工单',
                  enabled: user?.isAdmin ?? false,
                  subtitle: user?.isAdmin == true ? '批准或拒绝' : '仅管理员可用',
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          AppSectionTitle(
            title: '服务器设置',
            subtitle: '管理接口连接与环境地址',
            trailing: IconButton(
              onPressed: _isChecking ? null : _checkConnection,
              icon: const Icon(Icons.refresh_rounded),
            ),
          ),
          const SizedBox(height: 10),
          AppCard(
            child: Column(
              children: [
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: _isChecking
                      ? const SizedBox(
                          width: 22,
                          height: 22,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Icon(
                          _isConnected == true
                              ? Icons.cloud_done_rounded
                              : Icons.cloud_off_rounded,
                          color: _isConnected == true
                              ? const Color(0xFF40916C)
                              : Theme.of(context).colorScheme.error,
                        ),
                  title: const Text('服务器连接'),
                  subtitle: Text(
                    _isChecking
                        ? '检测中...'
                        : _isConnected == true
                        ? '当前网络与接口连接正常'
                        : '暂时无法连接服务器',
                    style: TextStyle(
                      color: _isConnected == true
                          ? const Color(0xFF40916C)
                          : Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
                const Divider(height: 20),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.dns_rounded),
                  title: const Text('服务器地址'),
                  subtitle: Text(ApiService.baseUrl),
                  trailing: const Icon(Icons.edit_outlined, size: 20),
                  onTap: () => _showServerDialog(context),
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          const AppSectionTitle(title: '应用设置', subtitle: '当前客户端的基础偏好'),
          const SizedBox(height: 10),
          AppCard(
            child: Column(
              children: [
                const ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.language_rounded),
                  title: Text('语言'),
                  subtitle: Text('简体中文'),
                ),
                const Divider(height: 20),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.location_on_outlined),
                  title: const Text('位置服务'),
                  subtitle: const Text('用于记录工作位置'),
                  trailing: Switch(value: true, onChanged: null),
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          const AppSectionTitle(title: '关于'),
          const SizedBox(height: 10),
          const AppCard(
            child: ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.info_outline_rounded),
              title: Text('版本'),
              subtitle: Text('1.1.0'),
            ),
          ),
          const SizedBox(height: 20),
          OutlinedButton.icon(
            onPressed: () => _logout(context),
            icon: const Icon(Icons.logout_rounded),
            label: const Text('退出登录'),
            style: OutlinedButton.styleFrom(
              foregroundColor: Theme.of(context).colorScheme.error,
              side: BorderSide(
                color: Theme.of(context).colorScheme.error.withOpacity(0.25),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPermissionTile({
    required IconData icon,
    required String title,
    required bool enabled,
    String? subtitle,
  }) {
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      leading: Icon(
        icon,
        color: enabled ? const Color(0xFF40916C) : Colors.grey,
      ),
      title: Text(title, style: TextStyle(color: enabled ? null : Colors.grey)),
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
            hintText: 'https://www.zctestbench.asia/api',
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
                ScaffoldMessenger.of(
                  context,
                ).showSnackBar(const SnackBar(content: Text('已更新服务器地址')));
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
