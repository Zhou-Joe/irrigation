import 'package:flutter/material.dart';

class AppTheme {
  // ── Core palette ──────────────────────────────────────────────
  static const seed = Color(0xFF2E6B55);
  static const accent = Color(0xFFE3A85B);

  static const background = Color(0xFFF4F7F3);
  static const surface = Color(0xFFFCFDF9);
  static const surfaceAlt = Color(0xFFE8F0EA);
  static const outline = Color(0xFFD7E1D8);

  static const textPrimary = Color(0xFF183126);
  static const textSecondary = Color(0xFF607065);
  static const textHint = Color(0xFF9BA89E);

  static const danger = Color(0xFFB84C4C);
  static const dangerLight = Color(0xFFFDE9E7);

  // ── Green scale ───────────────────────────────────────────────
  static const greenDarkest = Color(0xFF1B4332);
  static const greenDark = Color(0xFF2D6A4F);
  static const greenPrimary = Color(0xFF2E6B55);
  static const greenMedium = Color(0xFF40916C);
  static const greenLight = Color(0xFF52B788);
  static const greenPale = Color(0xFFB7E4C7);

  // ── Semantic / status colors ──────────────────────────────────
  static const statusCompleted = Color(0xFF40916C);
  static const statusInProgress = Color(0xFFCC7722);
  static const statusCanceled = Color(0xFF9B2226);
  static const statusDelayed = Color(0xFF7B5544);
  static const statusUnarranged = Color(0xFF888888);
  static const statusSubmitted = Color(0xFFCC7722);
  static const statusApproved = Color(0xFF40916C);
  static const statusRejected = Color(0xFFB84C4C);
  static const statusWatering = Color(0xFF2D6A4F);
  static const statusMaintenance = Color(0xFFCC7722);

  // ── Status helper ─────────────────────────────────────────────
  static Color statusColor(String? status) {
    switch (status) {
      case 'completed':
        return statusCompleted;
      case 'in_progress':
        return statusInProgress;
      case 'canceled':
        return statusCanceled;
      case 'delayed':
        return statusDelayed;
      case 'unarranged':
        return statusUnarranged;
      case 'submitted':
        return statusSubmitted;
      case 'approved':
        return statusApproved;
      case 'rejected':
        return statusRejected;
      case 'watering':
        return statusWatering;
      case 'maintenance':
        return statusMaintenance;
      case 'working':
        return statusCompleted;
      case 'needs_repair':
        return statusInProgress;
      default:
        return statusUnarranged;
    }
  }

  // ── Typography scale (consistent across all pages) ────────────
  /// 22px — Page AppBar titles
  static const TextStyle tsPageTitle = TextStyle(
    fontSize: 22,
    fontWeight: FontWeight.w700,
    color: textPrimary,
    height: 1.3,
  );

  /// 18px — Section card headers, bottom-sheet titles
  static const TextStyle tsSectionTitle = TextStyle(
    fontSize: 18,
    fontWeight: FontWeight.w700,
    color: textPrimary,
    height: 1.3,
  );

  /// 16px — Sub-section titles, card primary text
  static const TextStyle tsSubtitle = TextStyle(
    fontSize: 16,
    fontWeight: FontWeight.w600,
    color: textPrimary,
    height: 1.35,
  );

  /// 15px — Form field labels, prominent body text
  static const TextStyle tsLabel = TextStyle(
    fontSize: 15,
    fontWeight: FontWeight.w600,
    color: textPrimary,
    height: 1.35,
  );

  /// 14px — Standard body text, list item titles
  static const TextStyle tsBody = TextStyle(
    fontSize: 14,
    fontWeight: FontWeight.w400,
    color: textPrimary,
    height: 1.4,
  );

  /// 13px — Secondary text, metadata
  static const TextStyle tsCaption = TextStyle(
    fontSize: 13,
    fontWeight: FontWeight.w400,
    color: textSecondary,
    height: 1.35,
  );

  /// 12px — Badges, chips, tiny labels
  static const TextStyle tsBadge = TextStyle(
    fontSize: 12,
    fontWeight: FontWeight.w700,
    height: 1.2,
  );

  /// 11px — Overlines, footnote
  static const TextStyle tsOverline = TextStyle(
    fontSize: 11,
    fontWeight: FontWeight.w500,
    color: textSecondary,
    height: 1.3,
  );

  // ── Spacing constants ─────────────────────────────────────────
  static const double pagePadding = 16.0;
  static const double cardRadius = 24.0;
  static const double buttonRadius = 20.0;
  static const double chipRadius = 12.0;
  static const double sectionGap = 16.0;
  static const double itemGap = 12.0;
  static const double fieldGap = 8.0;

  // ── Theme builder ─────────────────────────────────────────────
  static ThemeData light() {
    final base = ColorScheme.fromSeed(
      seedColor: seed,
      brightness: Brightness.light,
    );

    final scheme = base.copyWith(
      primary: seed,
      onPrimary: Colors.white,
      secondary: accent,
      onSecondary: const Color(0xFF34200C),
      surface: surface,
      onSurface: textPrimary,
      outline: outline,
      error: danger,
      onError: Colors.white,
      errorContainer: dangerLight,
      onErrorContainer: const Color(0xFF5C1716),
    );

    final outlineBorder = OutlineInputBorder(
      borderRadius: BorderRadius.circular(buttonRadius),
      borderSide: const BorderSide(color: outline),
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      fontFamily: 'SF Pro Display',
      textTheme: Typography.material2021().black.apply(
        bodyColor: textPrimary,
        displayColor: textPrimary,
        fontFamily: 'SF Pro Display',
      ).copyWith(
        headlineLarge: const TextStyle(
          fontSize: 28,
          fontWeight: FontWeight.w700,
          color: textPrimary,
          height: 1.25,
        ),
        headlineMedium: const TextStyle(
          fontSize: 24,
          fontWeight: FontWeight.w700,
          color: textPrimary,
          height: 1.25,
        ),
        headlineSmall: const TextStyle(
          fontSize: 20,
          fontWeight: FontWeight.w700,
          color: textPrimary,
          height: 1.3,
        ),
        titleLarge: const TextStyle(
          fontSize: 18,
          fontWeight: FontWeight.w700,
          color: textPrimary,
          height: 1.3,
        ),
        titleMedium: const TextStyle(
          fontSize: 16,
          fontWeight: FontWeight.w600,
          color: textPrimary,
          height: 1.35,
        ),
        titleSmall: const TextStyle(
          fontSize: 14,
          fontWeight: FontWeight.w600,
          color: textPrimary,
          height: 1.35,
        ),
        bodyLarge: const TextStyle(
          fontSize: 16,
          fontWeight: FontWeight.w400,
          color: textPrimary,
          height: 1.4,
        ),
        bodyMedium: const TextStyle(
          fontSize: 14,
          fontWeight: FontWeight.w400,
          color: textPrimary,
          height: 1.4,
        ),
        bodySmall: const TextStyle(
          fontSize: 13,
          fontWeight: FontWeight.w400,
          color: textSecondary,
          height: 1.35,
        ),
        labelLarge: const TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w600,
          color: textPrimary,
          height: 1.35,
        ),
        labelMedium: const TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w600,
          color: textSecondary,
          height: 1.3,
        ),
        labelSmall: const TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w500,
          color: textSecondary,
          height: 1.3,
        ),
      ),
      scaffoldBackgroundColor: background,
      cardColor: surface,
      dividerColor: outline,
      appBarTheme: const AppBarTheme(
        centerTitle: false,
        elevation: 0,
        scrolledUnderElevation: 0,
        backgroundColor: Colors.transparent,
        foregroundColor: textPrimary,
        titleTextStyle: tsPageTitle,
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: Colors.white.withOpacity(0.92),
        indicatorColor: scheme.primary.withOpacity(0.14),
        height: 78,
        elevation: 0,
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return TextStyle(
            fontSize: 12,
            fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
            color: selected ? scheme.primary : textSecondary,
          );
        }),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return IconThemeData(
            color: selected ? scheme.primary : textSecondary,
            size: 24,
          );
        }),
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: surface,
        shadowColor: const Color(0x1A163222),
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(cardRadius),
          side: const BorderSide(color: outline),
        ),
        margin: EdgeInsets.zero,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white.withOpacity(0.82),
        contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 18),
        labelStyle: const TextStyle(color: textSecondary),
        hintStyle: const TextStyle(color: textHint),
        prefixIconColor: seed,
        suffixIconColor: textSecondary,
        border: outlineBorder,
        enabledBorder: outlineBorder,
        focusedBorder: outlineBorder.copyWith(
          borderSide: const BorderSide(color: seed, width: 1.4),
        ),
        errorBorder: outlineBorder.copyWith(
          borderSide: const BorderSide(color: danger),
        ),
        focusedErrorBorder: outlineBorder.copyWith(
          borderSide: const BorderSide(color: danger, width: 1.4),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          elevation: 0,
          backgroundColor: seed,
          foregroundColor: Colors.white,
          minimumSize: const Size.fromHeight(56),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(buttonRadius),
          ),
          textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: seed,
          minimumSize: const Size(0, 52),
          side: const BorderSide(color: outline),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(18),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
          textStyle: const TextStyle(fontWeight: FontWeight.w600),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          elevation: 0,
          backgroundColor: Colors.white,
          foregroundColor: textPrimary,
          minimumSize: const Size.fromHeight(52),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(18),
          ),
          textStyle: const TextStyle(fontWeight: FontWeight.w600),
        ),
      ),
      floatingActionButtonTheme: const FloatingActionButtonThemeData(
        backgroundColor: seed,
        foregroundColor: Colors.white,
        elevation: 0,
      ),
      chipTheme: ChipThemeData(
        backgroundColor: surfaceAlt,
        selectedColor: seed.withOpacity(0.14),
        secondarySelectedColor: seed.withOpacity(0.14),
        labelStyle: const TextStyle(color: textPrimary, fontWeight: FontWeight.w600),
        secondaryLabelStyle: const TextStyle(
          color: seed,
          fontWeight: FontWeight.w700,
        ),
        side: const BorderSide(color: outline),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: const Color(0xFF203D30),
        contentTextStyle: const TextStyle(color: Colors.white),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      ),
      switchTheme: SwitchThemeData(
        thumbColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) return seed;
          return Colors.white;
        }),
        trackColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) return seed.withOpacity(0.28);
          return outline;
        }),
      ),
      checkboxTheme: CheckboxThemeData(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: surface,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)),
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: surface,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
        ),
      ),
    );
  }
}
