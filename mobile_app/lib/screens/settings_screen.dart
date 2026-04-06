import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../services/api_service.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final worker = auth.worker;

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
                  worker?.fullName.substring(0, 1) ?? '?',
                  style: const TextStyle(
                    fontSize: 28,
                    color: Colors.white,
                  ),
                ),
              ),
              const SizedBox(width: 16),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    worker?.fullName ?? '未知用户',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '工号: ${worker?.employeeId ?? '-'}',
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                ],
              ),
            ],
          ),
        ),

        // Server settings
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 24, 16, 8),
          child: Text('服务器设置', style: TextStyle(fontWeight: FontWeight.bold)),
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
          subtitle: Text('1.0.0'),
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
            onPressed: () {
              ApiService.baseUrl = controller.text.trim();
              Navigator.pop(context);
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('已更新服务器地址')),
              );
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