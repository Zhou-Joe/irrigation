import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../services/api_service.dart';
import '../widgets/modern_ui.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _isLoading = false;
  String? _error;
  bool _obscurePassword = true;
  bool _isTestingConnection = false;
  String? _connectionStatus; // null = not tested, 'ok', 'fail'
  String? _connectionError;

  @override
  void initState() {
    super.initState();
    _loadSavedUrl();
  }

  Future<void> _loadSavedUrl() async {
    await ApiService.loadSavedBaseUrl();
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  void _showServerSettings() {
    final controller = TextEditingController(text: ApiService.baseUrl);
    _connectionStatus = null;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheetState) => Padding(
          padding: EdgeInsets.fromLTRB(
            20,
            20,
            20,
            MediaQuery.of(ctx).viewInsets.bottom + 20,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Center(
                child: Container(
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: Colors.grey.shade300,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Text('服务器设置', style: Theme.of(ctx).textTheme.titleLarge),
              const SizedBox(height: 6),
              Text(
                '切换接口地址并测试当前连接状态',
                style: Theme.of(
                  ctx,
                ).textTheme.bodyMedium?.copyWith(color: AppColors.muted),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: controller,
                decoration: const InputDecoration(
                  labelText: '服务器地址',
                  hintText: 'https://www.zctestbench.asia/api',
                  prefixIcon: Icon(Icons.dns),
                  border: OutlineInputBorder(),
                ),
                keyboardType: TextInputType.url,
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: _isTestingConnection
                          ? null
                          : () async {
                              // Save URL first so test uses the new address
                              final url = controller.text.trim();
                              if (url.isNotEmpty) {
                                await ApiService.setBaseUrl(url);
                              }
                              setSheetState(() => _isTestingConnection = true);
                              final api = context.read<AuthProvider>().api;
                              final result = await api.checkConnection();
                              setSheetState(() {
                                _isTestingConnection = false;
                                _connectionStatus = result.$1 ? 'ok' : 'fail';
                                _connectionError = result.$2;
                              });
                              setState(() {});
                            },
                      icon: _isTestingConnection
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.wifi_tethering, size: 18),
                      label: const Text('测试连接'),
                    ),
                  ),
                  if (_connectionStatus != null) ...[
                    const SizedBox(width: 8),
                    Icon(
                      _connectionStatus == 'ok'
                          ? Icons.check_circle
                          : Icons.cancel,
                      color: _connectionStatus == 'ok'
                          ? const Color(0xFF40916C)
                          : Colors.red,
                      size: 24,
                    ),
                    Text(
                      _connectionStatus == 'ok' ? '连接成功' : '连接失败',
                      style: TextStyle(
                        color: _connectionStatus == 'ok'
                            ? const Color(0xFF40916C)
                            : Colors.red,
                        fontWeight: FontWeight.w600,
                        fontSize: 13,
                      ),
                    ),
                  ],
                ],
              ),
              if (_connectionStatus == 'fail' && _connectionError != null) ...[
                const SizedBox(height: 8),
                Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: Colors.red.shade50,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    _connectionError!,
                    style: TextStyle(fontSize: 11, color: Colors.red.shade700),
                  ),
                ),
              ],
              const SizedBox(height: 16),
              FilledButton(
                onPressed: () async {
                  final url = controller.text.trim();
                  if (url.isNotEmpty) {
                    await ApiService.setBaseUrl(url);
                  }
                  if (mounted) {
                    setState(() => _connectionStatus = null);
                    Navigator.pop(ctx);
                  }
                },
                style: FilledButton.styleFrom(
                  backgroundColor: const Color(0xFF40916C),
                  padding: const EdgeInsets.symmetric(vertical: 14),
                ),
                child: const Text('保存'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _login() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isLoading = true;
      _error = null;
    });

    final success = await context.read<AuthProvider>().login(
      _usernameController.text.trim(),
      _passwordController.text,
    );

    if (!mounted) return;

    setState(() {
      _isLoading = false;
      if (!success) {
        _error = '登录失败，请检查用户名和密码';
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: AppBackground(
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 440),
                child: Column(
                  children: [
                    const SizedBox(height: 12),
                    const AppHeroCard(
                      title: '园艺管理',
                      subtitle: '把区域、需求、日报和现场协作放在同一张清晰的工作界面里。',
                      icon: Icons.park_rounded,
                    ),
                    const SizedBox(height: 22),
                    AppCard(
                      child: Form(
                        key: _formKey,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Text(
                              '欢迎回来',
                              style: Theme.of(context).textTheme.headlineSmall
                                  ?.copyWith(color: AppColors.deepGreen),
                            ),
                            const SizedBox(height: 6),
                            Text(
                              '登录后继续处理区域巡检、浇水协调和维修日报。',
                              style: Theme.of(context).textTheme.bodyMedium
                                  ?.copyWith(color: AppColors.muted),
                            ),
                            if (_error != null) ...[
                              const SizedBox(height: 20),
                              Container(
                                padding: const EdgeInsets.all(14),
                                decoration: BoxDecoration(
                                  color: Theme.of(
                                    context,
                                  ).colorScheme.errorContainer,
                                  borderRadius: BorderRadius.circular(18),
                                ),
                                child: Row(
                                  children: [
                                    Icon(
                                      Icons.error_outline,
                                      color: Theme.of(
                                        context,
                                      ).colorScheme.error,
                                    ),
                                    const SizedBox(width: 10),
                                    Expanded(
                                      child: Text(
                                        _error!,
                                        style: TextStyle(
                                          color: Theme.of(
                                            context,
                                          ).colorScheme.error,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                            const SizedBox(height: 20),
                            TextFormField(
                              controller: _usernameController,
                              decoration: const InputDecoration(
                                labelText: '用户名',
                                prefixIcon: Icon(Icons.person_outline_rounded),
                              ),
                              keyboardType: TextInputType.text,
                              textInputAction: TextInputAction.next,
                              validator: (value) {
                                if (value == null || value.trim().isEmpty) {
                                  return '请输入用户名';
                                }
                                return null;
                              },
                            ),
                            const SizedBox(height: 16),
                            TextFormField(
                              controller: _passwordController,
                              decoration: InputDecoration(
                                labelText: '密码',
                                prefixIcon: const Icon(
                                  Icons.lock_outline_rounded,
                                ),
                                suffixIcon: IconButton(
                                  icon: Icon(
                                    _obscurePassword
                                        ? Icons.visibility_outlined
                                        : Icons.visibility_off_outlined,
                                  ),
                                  onPressed: () {
                                    setState(
                                      () =>
                                          _obscurePassword = !_obscurePassword,
                                    );
                                  },
                                ),
                              ),
                              obscureText: _obscurePassword,
                              textInputAction: TextInputAction.done,
                              onFieldSubmitted: (_) => _login(),
                              validator: (value) {
                                if (value == null || value.isEmpty) {
                                  return '请输入密码';
                                }
                                return null;
                              },
                            ),
                            const SizedBox(height: 22),
                            FilledButton.icon(
                              onPressed: _isLoading ? null : _login,
                              icon: _isLoading
                                  ? const SizedBox(
                                      height: 18,
                                      width: 18,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                        color: Colors.white,
                                      ),
                                    )
                                  : const Icon(Icons.login_rounded),
                              label: Text(_isLoading ? '登录中...' : '登录'),
                            ),
                            const SizedBox(height: 12),
                            OutlinedButton.icon(
                              onPressed: _showServerSettings,
                              icon: const Icon(
                                Icons.settings_ethernet_rounded,
                                size: 18,
                              ),
                              label: Text(
                                ApiService.baseUrl,
                                style: const TextStyle(fontSize: 12),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            const SizedBox(height: 18),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 14,
                                vertical: 12,
                              ),
                              decoration: BoxDecoration(
                                color: AppColors.surfaceSoft.withOpacity(0.7),
                                borderRadius: BorderRadius.circular(18),
                              ),
                              child: Row(
                                children: [
                                  const Icon(
                                    Icons.info_outline_rounded,
                                    size: 18,
                                    color: AppColors.primary,
                                  ),
                                  const SizedBox(width: 10),
                                  Expanded(
                                    child: Text(
                                      '请联系管理员注册账户或确认服务器地址无误。',
                                      style: Theme.of(context)
                                          .textTheme
                                          .bodySmall
                                          ?.copyWith(color: AppColors.muted),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
