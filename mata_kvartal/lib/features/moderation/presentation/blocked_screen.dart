import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mata_ui/mata_ui.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_states.dart';
import '../data/moderation_provider.dart';

/// Чёрный список: кого я скрыл от себя и от кого скрылся сам.
class BlockedScreen extends ConsumerWidget {
  const BlockedScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final blocked = ref.watch(blockedProvider);

    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        backgroundColor: AppColors.bg,
        title: const Text('Заблокированные'),
      ),
      body: SafeArea(
        child: blocked.when(
          loading: () => MataLoading(color: AppColors.muted),
          error: (_, __) => MataError(
            icon: CupertinoIcons.wifi_slash,
            iconColor: AppStates.icon,
            title: 'Нет связи',
            titleStyle: AppStates.title,
            hint: 'Список не загрузился.',
            hintStyle: AppStates.hint,
            retryLabel: 'Повторить',
            onRetry: () => ref.invalidate(blockedProvider),
            retryBuilder: AppStates.retry,
          ),
          data: (list) => list.isEmpty
              ? MataEmpty(
                  icon: CupertinoIcons.person_crop_circle_badge_xmark,
                  iconColor: AppStates.icon,
                  title: 'Никто не заблокирован',
                  titleStyle: AppStates.title,
                  hint: 'Заблокировать человека можно в его карточке в разделе '
                      '«Друзья». Он перестанет видеть тебя и слать заявки.',
                  hintStyle: AppStates.hint,
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                  children: [
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Text(
                        'Вы не видите друг друга в поиске, подсказках и на карте. '
                        'Разблокировка вернёт видимость, но не дружбу — её нужно '
                        'предложить заново.',
                        style: TextStyle(
                            color: AppColors.muted, fontSize: 13, height: 1.45),
                      ),
                    ),
                    for (final b in list)
                      _BlockedRow(
                        blocked: b,
                        onUnblock: () async {
                          final ok = await ref
                              .read(moderationActionsProvider)
                              .unblock(b.userId);
                          if (!ok && context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                  content: Text('Нет связи — попробуйте позже')),
                            );
                          }
                        },
                      ),
                  ],
                ),
        ),
      ),
    );
  }
}

class _BlockedRow extends StatelessWidget {
  final BlockedUser blocked;
  final VoidCallback onUnblock;
  const _BlockedRow({required this.blocked, required this.onUnblock});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.line),
      ),
      child: Row(
        children: [
          Container(
            width: 38,
            height: 38,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: AppColors.soft,
              shape: BoxShape.circle,
            ),
            child: Text(
              blocked.initial,
              style: TextStyle(
                  color: AppColors.muted,
                  fontSize: 15,
                  fontWeight: FontWeight.w800),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              blocked.name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                  color: AppColors.ink, fontSize: 15, fontWeight: FontWeight.w700),
            ),
          ),
          // Компактная «пилюля» как в списке друзей: кнопка не должна
          // отъедать половину строки у имени.
          GestureDetector(
            onTap: onUnblock,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 8),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: AppColors.line),
              ),
              child: Text(
                'Разблокировать',
                style: TextStyle(
                    color: AppColors.ink,
                    fontSize: 12.5,
                    fontWeight: FontWeight.w800),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
