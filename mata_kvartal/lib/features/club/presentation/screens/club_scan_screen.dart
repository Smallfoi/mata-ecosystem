import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../../../core/theme/app_colors.dart';
import '../../data/club_provider.dart';

/// Полноэкранный сканер QR-кода приглашения в клуб (как в Тинькофф/Taobao):
/// навёл штатную камеру на QR → вступаем в клуб и возвращаемся назад.
class ClubScanScreen extends ConsumerStatefulWidget {
  const ClubScanScreen({super.key});

  @override
  ConsumerState<ClubScanScreen> createState() => _ClubScanScreenState();
}

class _ClubScanScreenState extends ConsumerState<ClubScanScreen> {
  final MobileScannerController _controller = MobileScannerController(
    detectionSpeed: DetectionSpeed.noDuplicates,
    formats: const [BarcodeFormat.qrCode],
  );
  bool _handled = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  /// QR должен быть приглашением клуба: ссылка с 'club' / схема kvartal|quartal /
  /// короткий код. Прочие QR игнорируем, чтобы не пытаться вступать в мусор.
  bool _looksLikeInvite(String raw) {
    final v = raw.trim().toLowerCase();
    if (v.isEmpty) return false;
    if (v.contains('club') || v.contains('kvartal') || v.contains('quartal')) {
      return true;
    }
    return RegExp(r'^[a-z0-9_-]{2,40}$').hasMatch(v);
  }

  void _onDetect(BarcodeCapture capture) {
    if (_handled) return;
    final raw = capture.barcodes.isNotEmpty
        ? (capture.barcodes.first.rawValue ?? '')
        : '';
    if (!_looksLikeInvite(raw)) return; // не приглашение — продолжаем искать
    _handled = true;
    // joinByInvite сам разберёт код/ссылку и покажет результат снекбаром на
    // экране клуба (там слушается clubProvider.message/error).
    ref.read(clubProvider.notifier).joinByInvite(raw.trim());
    if (mounted) context.pop();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          MobileScanner(controller: _controller, onDetect: _onDetect),
          // затемнение + рамка-видоискатель
          const _ScannerOverlay(),
          SafeArea(
            child: Column(
              children: [
                Row(
                  children: [
                    IconButton(
                      tooltip: 'Назад',
                      icon: Icon(Icons.arrow_back, color: AppColors.ink),
                      onPressed: () => context.pop(),
                    ),
                    const Spacer(),
                    IconButton(
                      tooltip: 'Фонарик',
                      icon: Icon(Icons.flash_on, color: AppColors.ink),
                      onPressed: () => _controller.toggleTorch(),
                    ),
                  ],
                ),
                const Spacer(),
                Padding(
                  padding: const EdgeInsets.only(bottom: 48, left: 32, right: 32),
                  child: Text(
                    'Наведите камеру на QR-код приглашения в клуб',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: AppColors.ink,
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ScannerOverlay extends StatelessWidget {
  const _ScannerOverlay();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Container(
        width: 248,
        height: 248,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: AppColors.electricBlue, width: 3),
        ),
      ),
    );
  }
}
