import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

export '../theme/app_theme.dart' show AppTheme;

// ── Re-export semantic aliases for convenience ──────────────────
class AppColors {
  static const deepGreen = AppTheme.greenDarkest;
  static const primary = AppTheme.greenPrimary;
  static const accent = AppTheme.accent;
  static const surface = AppTheme.surface;
  static const surfaceSoft = AppTheme.surfaceAlt;
  static const outline = AppTheme.outline;
  static const background = AppTheme.background;
  static const muted = AppTheme.textSecondary;
}

// ── Status helper (single source of truth) ──────────────────────
Color appStatusColor(String? status) => AppTheme.statusColor(status);

// ── Background gradient ─────────────────────────────────────────
class AppBackground extends StatelessWidget {
  final Widget child;
  const AppBackground({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Color(0xFFF7FAF6), Color(0xFFF0F5EF), AppTheme.background],
        ),
      ),
      child: child,
    );
  }
}

// ── Card ────────────────────────────────────────────────────────
class AppCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry? padding;
  final Color? color;
  final VoidCallback? onTap;

  const AppCard({
    super.key,
    required this.child,
    this.padding,
    this.color,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final card = Container(
      decoration: BoxDecoration(
        color: color ?? Colors.white.withOpacity(0.88),
        borderRadius: BorderRadius.circular(AppTheme.cardRadius),
        border: Border.all(color: AppTheme.outline),
        boxShadow: const [
          BoxShadow(
            color: Color(0x141A2E1F),
            blurRadius: 30,
            offset: Offset(0, 12),
          ),
        ],
      ),
      child: Padding(
        padding: padding ?? const EdgeInsets.all(20),
        child: child,
      ),
    );

    if (onTap == null) return card;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppTheme.cardRadius),
        child: card,
      ),
    );
  }
}

// ── Icon badge (decorative) ─────────────────────────────────────
class AppIconBadge extends StatelessWidget {
  final IconData icon;
  final double size;
  final Color color;
  final Color? backgroundColor;

  const AppIconBadge({
    super.key,
    required this.icon,
    this.size = 56,
    this.color = AppTheme.greenPrimary,
    this.backgroundColor,
  });

  @override
  Widget build(BuildContext context) {
    final bg = backgroundColor ?? color.withOpacity(0.14);
    final lightIcon = color == Colors.white;
    return SizedBox(
      width: size + 22,
      height: size + 22,
      child: Stack(
        alignment: Alignment.center,
        children: [
          Container(
            width: size + 22,
            height: size + 22,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: LinearGradient(
                colors: [
                  color.withOpacity(0.16),
                  AppTheme.accent.withOpacity(0.12),
                ],
              ),
            ),
          ),
          Container(
            width: size + 8,
            height: size + 8,
            decoration: BoxDecoration(shape: BoxShape.circle, color: bg),
          ),
          Container(
            width: size,
            height: size,
            decoration: BoxDecoration(
              color: lightIcon
                  ? Colors.white.withOpacity(0.18)
                  : Colors.white.withOpacity(0.92),
              borderRadius: BorderRadius.circular(size * 0.34),
              boxShadow: [
                BoxShadow(
                  color: color.withOpacity(0.18),
                  blurRadius: 16,
                  offset: const Offset(0, 8),
                ),
              ],
            ),
            child: Icon(icon, color: color, size: size * 0.48),
          ),
        ],
      ),
    );
  }
}

// ── Hero card (login) ───────────────────────────────────────────
class AppHeroCard extends StatelessWidget {
  final String title;
  final String? subtitle;
  final TextAlign? subtitleAlign;
  final IconData icon;
  final List<Widget> actions;

  const AppHeroCard({
    super.key,
    required this.title,
    this.subtitle,
    this.subtitleAlign,
    required this.icon,
    this.actions = const [],
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(30),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppTheme.greenDarkest,
            AppTheme.greenPrimary,
            AppTheme.greenLight,
          ],
        ),
        boxShadow: [
          BoxShadow(
            color: AppTheme.greenPrimary.withOpacity(0.20),
            blurRadius: 34,
            offset: const Offset(0, 18),
          ),
        ],
      ),
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                AppIconBadge(
                  icon: icon,
                  size: 54,
                  color: Colors.white,
                  backgroundColor: Colors.white.withOpacity(0.12),
                ),
                const Spacer(),
                ...actions,
              ],
            ),
            const SizedBox(height: 18),
            Text(
              title,
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                color: Colors.white,
                fontWeight: FontWeight.w700,
              ),
            ),
            if (subtitle != null) ...[
              const SizedBox(height: 8),
              Text(
                subtitle!,
                textAlign: subtitleAlign,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Colors.white.withOpacity(0.86),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ── Section title ───────────────────────────────────────────────
class AppSectionTitle extends StatelessWidget {
  final String title;
  final String? subtitle;
  final Widget? trailing;

  const AppSectionTitle({
    super.key,
    required this.title,
    this.subtitle,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: AppTheme.tsSectionTitle),
              if (subtitle != null) ...[
                const SizedBox(height: 4),
                Text(subtitle!, style: AppTheme.tsCaption),
              ],
            ],
          ),
        ),
        if (trailing != null) trailing!,
      ],
    );
  }
}

// ── Status badge (pill) ─────────────────────────────────────────
class AppStatusBadge extends StatelessWidget {
  final String label;
  final Color color;

  const AppStatusBadge({super.key, required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
        color: color.withOpacity(0.13),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(label, style: AppTheme.tsBadge.copyWith(color: color)),
    );
  }
}

// ── Info row ────────────────────────────────────────────────────
class AppInfoRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;

  const AppInfoRow({
    super.key,
    required this.icon,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    if (value.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: AppTheme.textSecondary),
          const SizedBox(width: 10),
          Expanded(
            child: RichText(
              text: TextSpan(
                style: AppTheme.tsBody,
                children: [
                  TextSpan(
                    text: '$label  ',
                    style: const TextStyle(
                      color: AppTheme.textSecondary,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                  TextSpan(
                    text: value,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ── Empty state ─────────────────────────────────────────────────
class AppEmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String? subtitle;
  final Widget? action;

  const AppEmptyState({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle,
    this.action,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: TweenAnimationBuilder<double>(
          tween: Tween(begin: 0.92, end: 1),
          duration: const Duration(milliseconds: 500),
          curve: Curves.easeOutBack,
          builder: (context, value, child) =>
              Transform.scale(scale: value, child: child),
          child: AppCard(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                SizedBox(
                  width: 160,
                  height: 132,
                  child: Stack(
                    alignment: Alignment.center,
                    children: [
                      Positioned(
                        top: 8,
                        left: 22,
                        child: Container(
                          width: 30,
                          height: 30,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: AppTheme.accent.withOpacity(0.16),
                          ),
                        ),
                      ),
                      Positioned(
                        top: 18,
                        right: 20,
                        child: Container(
                          width: 18,
                          height: 18,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: AppTheme.greenPrimary.withOpacity(0.16),
                          ),
                        ),
                      ),
                      Positioned(
                        bottom: 18,
                        child: Container(
                          width: 114,
                          height: 18,
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(999),
                            color: AppTheme.greenPrimary.withOpacity(0.08),
                          ),
                        ),
                      ),
                      AppIconBadge(
                        icon: icon,
                        size: 72,
                        color: AppTheme.greenPrimary,
                        backgroundColor: AppTheme.surfaceAlt,
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 6),
                Text(title, style: AppTheme.tsSubtitle, textAlign: TextAlign.center),
                if (subtitle != null) ...[
                  const SizedBox(height: 8),
                  Text(
                    subtitle!,
                    style: AppTheme.tsCaption,
                    textAlign: TextAlign.center,
                  ),
                ],
                if (action != null) ...[const SizedBox(height: 18), action!],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ── Error state ─────────────────────────────────────────────────
class AppErrorState extends StatelessWidget {
  final String message;
  final VoidCallback? onRetry;

  const AppErrorState({super.key, required this.message, this.onRetry});

  @override
  Widget build(BuildContext context) {
    return AppEmptyState(
      icon: Icons.error_outline,
      title: '加载失败',
      subtitle: message,
      action: onRetry == null
          ? null
          : FilledButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('重新加载'),
            ),
    );
  }
}

// ── Stat pill ───────────────────────────────────────────────────
class AppStatPill extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color color;

  const AppStatPill({
    super.key,
    required this.icon,
    required this.label,
    required this.value,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: color.withOpacity(0.10),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 8),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(value, style: TextStyle(color: color, fontWeight: FontWeight.w700)),
              Text(label, style: AppTheme.tsOverline),
            ],
          ),
        ],
      ),
    );
  }
}

// ── Quick action button ─────────────────────────────────────────
class AppQuickActionButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final String? subtitle;
  final Color color;
  final VoidCallback onTap;

  const AppQuickActionButton({
    super.key,
    required this.icon,
    required this.label,
    required this.onTap,
    this.subtitle,
    this.color = AppTheme.greenPrimary,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: Ink(
          width: 148,
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.12),
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: Colors.white.withOpacity(0.14)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: color.withOpacity(0.16),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(icon, color: Colors.white, size: 20),
              ),
              const SizedBox(height: 12),
              Text(
                label,
                style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                ),
              ),
              if (subtitle != null) ...[
                const SizedBox(height: 4),
                Text(
                  subtitle!,
                  style: TextStyle(
                    fontSize: 12,
                    color: Colors.white.withOpacity(0.74),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

// ── Form section card ───────────────────────────────────────────
class AppFormSection extends StatelessWidget {
  final String title;
  final IconData icon;
  final List<Widget> children;

  const AppFormSection({
    super.key,
    required this.title,
    required this.icon,
    required this.children,
  });

  @override
  Widget build(BuildContext context) {
    return AppCard(
      padding: const EdgeInsets.all(AppTheme.pagePadding),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: AppTheme.greenPrimary.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(icon, size: 18, color: AppTheme.greenDark),
              ),
              const SizedBox(width: 10),
              Text(title, style: AppTheme.tsLabel),
            ],
          ),
          const SizedBox(height: AppTheme.sectionGap),
          ...children,
        ],
      ),
    );
  }
}

// ── Skeleton loading ────────────────────────────────────────────
class AppSkeletonBox extends StatefulWidget {
  final double width;
  final double height;
  final BorderRadius borderRadius;

  const AppSkeletonBox({
    super.key,
    this.width = double.infinity,
    this.height = 16,
    this.borderRadius = const BorderRadius.all(Radius.circular(6)),
  });

  @override
  State<AppSkeletonBox> createState() => _AppSkeletonBoxState();
}

class _AppSkeletonBoxState extends State<AppSkeletonBox>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        final t = _controller.value;
        return ShaderMask(
          blendMode: BlendMode.srcATop,
          shaderCallback: (bounds) {
            final w = bounds.width;
            return LinearGradient(
              colors: const [
                Color(0xFFE8F0EA),
                Color(0xFFF4F7F3),
                Color(0xFFE8F0EA),
              ],
              stops: [
                (t - 0.3).clamp(0.0, 1.0),
                t.clamp(0.0, 1.0),
                (t + 0.3).clamp(0.0, 1.0),
              ],
            ).createShader(Rect.fromLTWH(0, 0, w, bounds.height));
          },
          child: child,
        );
      },
      child: Container(
        width: widget.width,
        height: widget.height,
        decoration: BoxDecoration(
          color: AppTheme.surfaceAlt,
          borderRadius: widget.borderRadius,
        ),
      ),
    );
  }
}

/// A pre-built skeleton card that mimics a list item.
class AppSkeletonCard extends StatelessWidget {
  const AppSkeletonCard({super.key});

  @override
  Widget build(BuildContext context) {
    return AppCard(
      padding: const EdgeInsets.all(AppTheme.pagePadding),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const AppSkeletonBox(width: 48, height: 20, borderRadius: BorderRadius.all(Radius.circular(6))),
              const SizedBox(width: 12),
              const AppSkeletonBox(width: 80, height: 14),
              const Spacer(),
              AppSkeletonBox(width: 60, height: 26, borderRadius: BorderRadius.all(Radius.circular(12))),
            ],
          ),
          const SizedBox(height: 12),
          const AppSkeletonBox(height: 14),
          const SizedBox(height: 8),
          const AppSkeletonBox(width: 200, height: 14),
          const SizedBox(height: 12),
          Row(
            children: [
              AppSkeletonBox(width: 90, height: 28, borderRadius: BorderRadius.all(Radius.circular(14))),
              const SizedBox(width: 8),
              AppSkeletonBox(width: 70, height: 28, borderRadius: BorderRadius.all(Radius.circular(14))),
            ],
          ),
        ],
      ),
    );
  }
}

/// Shows a column of skeleton cards for list loading states.
class AppSkeletonList extends StatelessWidget {
  final int count;
  const AppSkeletonList({super.key, this.count = 5});

  @override
  Widget build(BuildContext context) {
    return ListView.builder(
      physics: const NeverScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(
        AppTheme.pagePadding, 12, AppTheme.pagePadding, 140,
      ),
      itemCount: count,
      itemBuilder: (_, __) => const Padding(
        padding: EdgeInsets.only(bottom: AppTheme.itemGap),
        child: AppSkeletonCard(),
      ),
    );
  }
}

// ── Meta chip (reusable tag) ────────────────────────────────────
class AppMetaChip extends StatelessWidget {
  final IconData icon;
  final String text;
  const AppMetaChip({super.key, required this.icon, required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppTheme.surfaceAlt.withOpacity(0.7),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: AppTheme.textSecondary),
          const SizedBox(width: 6),
          Text(text, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
        ],
      ),
    );
  }
}
