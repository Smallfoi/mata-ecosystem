import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../data/health_sync.dart';
import '../../data/suunto_provider.dart';

/// «Часы и приложения» — подключение Health Connect.
///
/// Экран сознательно не говорит про «Health Connect» первым делом: человек
/// подключает СВОИ ЧАСЫ, а Health Connect — способ, а не цель. Про него
/// рассказываем ниже, когда нужно объяснить, почему список часов такой широкий.
class WatchSyncScreen extends ConsumerStatefulWidget {
  const WatchSyncScreen({super.key});

  @override
  ConsumerState<WatchSyncScreen> createState() => _WatchSyncScreenState();
}

class _WatchSyncScreenState extends ConsumerState<WatchSyncScreen> {
  @override
  void initState() {
    super.initState();
    // Доступ могли отозвать в системных настройках, пока экран был закрыт.
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => ref.read(healthSyncProvider.notifier).refresh(),
    );
  }

  Future<void> _confirmDisconnect() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.bgCard,
        title: Text(
          'Отключить часы?',
          style: TextStyle(color: AppColors.textPrimary),
        ),
        content: Text(
          'Мы перестанем читать тренировки и удалим те, что уже забрали. '
          'Начисленные баллы останутся — вы их пробежали.',
          style: TextStyle(color: AppColors.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Отмена'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(
              'Отключить',
              style: TextStyle(color: AppColors.error),
            ),
          ),
        ],
      ),
    );
    if (ok == true) await ref.read(healthSyncProvider.notifier).disconnect();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(healthSyncProvider);
    final notifier = ref.read(healthSyncProvider.notifier);

    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: AppColors.bgDark,
        title: const Text('Часы и приложения'),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const _Lead(),
            const SizedBox(height: 16),
            switch (state.availability) {
              HealthAvailability.unsupported => const _Card(
                icon: CupertinoIcons.device_phone_portrait,
                title: 'Пока только на Android',
                text:
                    'На iPhone тренировки будут приходить из «Здоровья» — '
                    'сделаем сразу после выхода в App Store.',
              ),
              HealthAvailability.needsInstall => _Card(
                icon: CupertinoIcons.arrow_down_circle,
                title: 'Нужен Health Connect',
                text:
                    'Это системное приложение Google, через которое часы '
                    'передают тренировки. Устанавливается один раз.',
                action: 'Установить',
                onAction: () async {
                  await notifier.install();
                  await notifier.refresh();
                },
              ),
              HealthAvailability.ready when !state.connected => _Card(
                icon: CupertinoIcons.link,
                title: 'Подключить часы',
                text:
                    'Мы попросим доступ только к тренировкам, пульсу и калориям. '
                    'Шаги за день и сон не читаем.',
                action: 'Подключить',
                busy: state.busy,
                onAction: notifier.connect,
              ),
              HealthAvailability.ready => _ConnectedCard(
                state: state,
                onSync: notifier.sync,
                onDisconnect: _confirmDisconnect,
              ),
            },
            // Suunto — прямое подключение, без Health Connect: партнёрский
            // доступ даёт трек и присылает тренировку сама (D-108).
            const SizedBox(height: 12),
            const _SuuntoCard(),
            if (state.error != null) ...[
              const SizedBox(height: 12),
              Text(
                state.error!,
                style: TextStyle(color: AppColors.error, fontSize: 13),
              ),
            ],
            const SizedBox(height: 24),
            const _Explainer(),
          ],
        ),
      ),
    );
  }
}

class _Lead extends StatelessWidget {
  const _Lead();

  @override
  Widget build(BuildContext context) => Text(
    'Бежали с часами — километры засчитаются, даже если приложение не было '
    'открыто. Забег, записанный и часами, и телефоном, считается один раз.',
    style: TextStyle(color: AppColors.textSecondary, height: 1.45),
  );
}

class _Card extends StatelessWidget {
  final IconData icon;
  final String title;
  final String text;
  final String? action;
  final bool busy;
  final Future<void> Function()? onAction;

  const _Card({
    required this.icon,
    required this.title,
    required this.text,
    this.action,
    this.busy = false,
    this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.separator),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: AppColors.accentInk, size: 22),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  title,
                  style: TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 17,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            text,
            style: TextStyle(
              color: AppColors.textSecondary,
              height: 1.45,
            ),
          ),
          if (action != null) ...[
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: busy ? null : () => onAction?.call(),
                child: busy
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : Text(action!),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _ConnectedCard extends StatelessWidget {
  final HealthSyncState state;
  final Future<void> Function() onSync;
  final Future<void> Function() onDisconnect;

  const _ConnectedCard({
    required this.state,
    required this.onSync,
    required this.onDisconnect,
  });

  String get _lastSyncLabel {
    if (state.lastSyncMs == null) return 'Ещё не синхронизировались';
    final ago = DateTime.now().difference(
      DateTime.fromMillisecondsSinceEpoch(state.lastSyncMs!),
    );
    if (ago.inMinutes < 2) return 'Только что';
    if (ago.inHours < 1) return '${ago.inMinutes} мин назад';
    if (ago.inDays < 1) return '${ago.inHours} ч назад';
    return '${ago.inDays} дн назад';
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.separator),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                CupertinoIcons.checkmark_seal_fill,
                color: AppColors.success,
                size: 22,
              ),
              SizedBox(width: 10),
              Expanded(
                child: Text(
                  'Часы подключены',
                  style: TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 17,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              Text(
                _lastSyncLabel,
                style: TextStyle(
                  color: AppColors.textDisabled,
                  fontSize: 12,
                ),
              ),
            ],
          ),
          if (state.lastImported > 0) ...[
            SizedBox(height: 12),
            Text(
              state.lastPoints > 0
                  ? 'В прошлый раз забрали ${state.lastImported} '
                        '${_plural(state.lastImported)} и начислили ${state.lastPoints} баллов'
                  : 'В прошлый раз забрали ${state.lastImported} '
                        '${_plural(state.lastImported)}',
              style: TextStyle(
                color: AppColors.textSecondary,
                height: 1.45,
              ),
            ),
          ],
          SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: FilledButton(
                  onPressed: state.busy ? null : () => onSync(),
                  child: state.busy
                      ? SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Text('Обновить'),
                ),
              ),
              SizedBox(width: 10),
              TextButton(
                onPressed: state.busy ? null : () => onDisconnect(),
                child: Text(
                  'Отключить',
                  style: TextStyle(color: AppColors.error),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  static String _plural(int n) {
    final last2 = n % 100;
    final last = n % 10;
    if (last2 >= 11 && last2 <= 14) return 'тренировок';
    if (last == 1) return 'тренировку';
    if (last >= 2 && last <= 4) return 'тренировки';
    return 'тренировок';
  }
}

/// Прямое подключение часов Suunto: без Health Connect и без телефона на бегу.
class _SuuntoCard extends ConsumerStatefulWidget {
  const _SuuntoCard();

  @override
  ConsumerState<_SuuntoCard> createState() => _SuuntoCardState();
}

class _SuuntoCardState extends ConsumerState<_SuuntoCard>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState lifecycle) {
    // Разрешение выдают во внешнем браузере — узнать о нём можно только когда
    // человек вернулся в приложение. Поэтому перечитываем состояние на возврате.
    if (lifecycle == AppLifecycleState.resumed) {
      ref.read(suuntoProvider.notifier).refresh();
    }
  }

  String _lastSync(DateTime? at) {
    if (at == null) return 'тренировок ещё не приходило';
    final ago = DateTime.now().difference(at);
    if (ago.inMinutes < 60) return 'последняя тренировка ${ago.inMinutes} мин назад';
    if (ago.inHours < 24) return 'последняя тренировка ${ago.inHours} ч назад';
    return 'последняя тренировка ${ago.inDays} дн назад';
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(suuntoProvider);
    // Ключей на сервере нет — кнопка привела бы в тупик, карточку не показываем.
    if (!state.available) return const SizedBox.shrink();

    if (!state.connected) {
      return _Card(
        icon: CupertinoIcons.link,
        title: 'Подключить Suunto',
        text: 'Тренировки с часов придут сами, с маршрутом и пульсом — '
            'даже если телефон остался дома.',
        action: 'Подключить',
        busy: state.busy,
        onAction: () => ref.read(suuntoProvider.notifier).connect(),
      );
    }
    return _Card(
      icon: CupertinoIcons.check_mark_circled_solid,
      title: 'Suunto подключена',
      text: _lastSync(state.lastSyncAt),
      action: 'Отключить',
      busy: state.busy,
      onAction: () => ref.read(suuntoProvider.notifier).disconnect(),
    );
  }
}

class _Explainer extends StatelessWidget {
  const _Explainer();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Какие часы подойдут',
          style: TextStyle(
            color: AppColors.textPrimary,
            fontSize: 15,
            fontWeight: FontWeight.w600,
          ),
        ),
        SizedBox(height: 8),
        Text(
          'Любые, чьё приложение пишет тренировки в Health Connect: Garmin, '
          'COROS, Samsung, Amazfit, Zepp, Polar, Suunto, Huawei и другие. '
          'Передачу нужно один раз включить в приложении самих часов — '
          'ищите там раздел «Health Connect».',
          style: TextStyle(color: AppColors.textSecondary, height: 1.45),
        ),
        SizedBox(height: 16),
        Text(
          'Что мы читаем',
          style: TextStyle(
            color: AppColors.textPrimary,
            fontSize: 15,
            fontWeight: FontWeight.w600,
          ),
        ),
        SizedBox(height: 8),
        Text(
          'Только сами тренировки: время, дистанцию, пульс и калории внутри них. '
          'Шаги за день, вес, сон и давление не запрашиваем. Отключите доступ — '
          'и всё, что мы забрали, удалится с сервера.',
          style: TextStyle(color: AppColors.textSecondary, height: 1.45),
        ),
      ],
    );
  }
}
