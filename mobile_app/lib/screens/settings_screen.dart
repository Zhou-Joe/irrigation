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
        roleColor = AppTheme.greenDarkest;
        break;
      case 'dept_user':
        roleColor = AppTheme.greenMedium;
        break;
      case 'field_worker':
        roleColor = AppTheme.greenLight;
        break;
      default:
        roleColor = Colors.grey;
    }

    return AppBackground(
      child: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(AppTheme.pagePadding),
          children: [
            // Compact user info card
            AppCard(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            user?.fullName ?? '未知用户',
                            style: AppTheme.tsSubtitle.copyWith(color: AppTheme.greenDarkest),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            '${user?.roleDisplay ?? '未知角色'} · @${user?.username ?? '-'}',
                            style: AppTheme.tsCaption.copyWith(color: AppTheme.textSecondary),
                          ),
                        ],
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 5,
                      ),
                      decoration: BoxDecoration(
                        color: roleColor.withOpacity(0.12),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(
                        user?.roleDisplay ?? '未知角色',
                        style: AppTheme.tsOverline.copyWith(color: roleColor, fontWeight: FontWeight.w700),
                      ),
                    ),
                    const SizedBox(width: 6),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 5,
                      ),
                      decoration: BoxDecoration(
                        color: _isConnected == true
                            ? AppTheme.greenMedium.withOpacity(0.1)
                            : AppTheme.danger.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(
                        _isChecking
                            ? '检测中'
                            : _isConnected == true
                            ? '在线'
                            : '离线',
                        style: AppTheme.tsOverline.copyWith(
                          color: _isConnected == true
                              ? AppTheme.greenMedium
                              : AppTheme.danger,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
                if (user?.isFieldWorker ?? false) ...[
                  const Divider(height: 16),
                  Row(
                    children: [
                      const Icon(Icons.badge_outlined, size: 16, color: AppTheme.textSecondary),
                      const SizedBox(width: 4),
                      Text('工号: ${user?.employeeId ?? '-'}',
                        style: AppTheme.tsCaption.copyWith(color: AppTheme.textSecondary),
                      ),
                    ],
                  ),
                ],
                if (user?.isDeptUser ?? false) ...[
                  const Divider(height: 16),
                  Row(
                    children: [
                      const Icon(Icons.apartment_rounded, size: 16, color: AppTheme.textSecondary),
                      const SizedBox(width: 4),
                      Text('部门: ${user?.departmentDisplay ?? '-'}',
                        style: AppTheme.tsCaption.copyWith(color: AppTheme.textSecondary),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: AppTheme.itemGap),
          const AppSectionTitle(title: '功能权限', subtitle: '根据当前角色展示可用能力'),
          const SizedBox(height: 6),
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
          const SizedBox(height: AppTheme.itemGap),
          AppSectionTitle(
            title: '服务器设置',
            subtitle: '管理接口连接与环境地址',
            trailing: IconButton(
              onPressed: _isChecking ? null : _checkConnection,
              icon: const Icon(Icons.refresh_rounded, size: 20),
            ),
          ),
          const SizedBox(height: 6),
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
                              ? AppTheme.greenMedium
                              : Theme.of(context).colorScheme.error,
                        ),
                  title: Text('服务器连接', style: AppTheme.tsBody),
                  subtitle: Text(
                    _isChecking
                        ? '检测中...'
                        : _isConnected == true
                        ? '当前网络与接口连接正常'
                        : '暂时无法连接服务器',
                    style: AppTheme.tsCaption.copyWith(
                      color: _isConnected == true
                          ? AppTheme.greenMedium
                          : Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
                const Divider(height: 20),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.dns_rounded),
                  title: Text('服务器地址', style: AppTheme.tsBody),
                  subtitle: Text(ApiService.baseUrl, style: AppTheme.tsCaption),
                  trailing: const Icon(Icons.edit_outlined, size: 20),
                  onTap: () => _showServerDialog(context),
                ),
              ],
            ),
          ),
          const SizedBox(height: AppTheme.itemGap),
          const AppSectionTitle(title: '应用设置', subtitle: '当前客户端的基础偏好'),
          const SizedBox(height: 6),
          AppCard(
            child: Column(
              children: [
                const ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.language_rounded),
                  title: Text('语言', style: AppTheme.tsBody),
                  subtitle: Text('简体中文', style: AppTheme.tsCaption),
                ),
                const Divider(height: 20),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.location_on_outlined),
                  title: Text('位置服务', style: AppTheme.tsBody),
                  subtitle: Text('用于记录工作位置', style: AppTheme.tsCaption),
                  trailing: Switch(value: true, onChanged: null),
                ),
              ],
            ),
          ),
          const SizedBox(height: AppTheme.itemGap),
          const AppSectionTitle(title: '关于'),
          const SizedBox(height: 6),
          const AppCard(
            child: ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.info_outline_rounded),
              title: Text('版本', style: AppTheme.tsBody),
              subtitle: Text('0.1.0', style: AppTheme.tsCaption),
            ),
          ),
          const SizedBox(height: AppTheme.itemGap),
          OutlinedButton.icon(
            onPressed: () => _logout(context),
            icon: const Icon(Icons.logout_rounded, size: 18),
            label: const Text('退出登录'),
            style: OutlinedButton.styleFrom(
              foregroundColor: Theme.of(context).colorScheme.error,
              side: BorderSide(
                color: Theme.of(context).colorScheme.error.withOpacity(0.25),
              ),
              padding: const EdgeInsets.symmetric(vertical: 10),
            ),
          ),
        ],
      ),
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
      contentPadding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      dense: true,
      leading: Icon(
        icon,
        size: 20,
        color: enabled ? AppTheme.greenMedium : Colors.grey,
      ),
      title: Text(title, style: AppTheme.tsBody),
      subtitle: Text(
        subtitle ?? (enabled ? '已启用' : '未启用'),
        style: AppTheme.tsOverline.copyWith(
          color: enabled ? AppTheme.greenMedium : Colors.grey,
        ),
      ),
      trailing: Icon(
        enabled ? Icons.check_circle : Icons.cancel,
        size: 20,
        color: enabled ? AppTheme.greenMedium : Colors.grey,
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
