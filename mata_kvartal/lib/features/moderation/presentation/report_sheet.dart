import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mata_ui/mata_ui.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_states.dart';
import '../data/moderation_provider.dart';

/// Форма жалобы: причина списком + необязательный комментарий.
///
/// Причины тянем с сервера, а не держим копию в приложении: модератор разбирает
/// жалобу по тем же словам, которые видел человек, иначе разговор о решении
/// превращается в сверку двух разных списков.
Future<void> showReportSheet(
  BuildContext context, {
  required String targetType, // user | club
  required String targetId,
  required String targetName,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (_) => _ReportSheet(
      targetType: targetType,
      targetId: targetId,
      targetName: targetName,
    ),
  );
}

class _ReportSheet extends ConsumerStatefulWidget {
  final String targetType;
  final String targetId;
  final String targetName;
  const _ReportSheet({
    required this.targetType,
    required this.targetId,
    required this.targetName,
  });

  @override
  ConsumerState<_ReportSheet> createState() => _ReportSheetState();
}

class _ReportSheetState extends ConsumerState<_ReportSheet> {
  String? _reason;
  final _comment = TextEditingController();
  bool _sending = false;

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final reason = _reason;
    if (reason == null || _sending) return;
    setState(() => _sending = true);
    final err = await ref.read(moderationActionsProvider).report(
          targetType: widget.targetType,
          targetId: widget.targetId,
          reason: reason,
          comment: _comment.text,
        );
    if (!mounted) return;
    Navigator.of(context).pop();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(err ?? 'Жалоба отправлена — разберёмся')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final reasons = ref.watch(reportReasonsProvider);
    final bottom = MediaQuery.of(context).viewInsets.bottom;

    return Padding(
      padding: EdgeInsets.only(bottom: bottom),
      child: Container(
        decoration: BoxDecoration(
          color: AppColors.paper,
          borderRadius: const BorderRadius.vertical(top: Radius.circular(22)),
        ),
        padding: const EdgeInsets.fromLTRB(20, 10, 20, 20),
        child: SafeArea(
          top: false,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Center(
                child: Container(
                  width: 38,
                  height: 4,
                  decoration: BoxDecoration(
                    color: AppColors.line,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Text(
                'Пожаловаться',
                style: TextStyle(
                    color: AppColors.ink, fontSize: 18, fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 4),
              Text(
                widget.targetName,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(color: AppColors.muted, fontSize: 13.5),
              ),
              const SizedBox(height: 14),
              reasons.when(
                loading: () => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 24),
                  child: MataLoading(color: AppColors.muted),
                ),
                error: (_, __) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Text('Нет связи — попробуйте позже',
                      style: AppStates.hint),
                ),
                data: (list) => Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final r in list)
                      _ReasonRow(
                        title: r.title,
                        selected: _reason == r.code,
                        onTap: () => setState(() => _reason = r.code),
                      ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: _comment,
                      maxLines: 3,
                      maxLength: 2000,
                      style: TextStyle(color: AppColors.ink, fontSize: 14),
                      decoration: InputDecoration(
                        hintText: 'Что случилось? Необязательно',
                        hintStyle: TextStyle(color: AppColors.faint, fontSize: 14),
                        counterText: '',
                        filled: true,
                        fillColor: AppColors.soft,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide.none,
                        ),
                      ),
                    ),
                    const SizedBox(height: 14),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed: _reason == null || _sending ? null : _send,
                        child: Text(_sending ? 'Отправляем…' : 'Отправить'),
                      ),
                    ),
                    const SizedBox(height: 8),
                    // Обещать «историю обращения» нельзя: экрана с ответом
                    // модератора в приложении пока нет. Решение хранится на
                    // сервере, но человеку оно ещё не показывается.
                    Text(
                      'Жалобу читает модератор. Если правила нарушены — '
                      'примем меры. Имя заявителя тому, на кого жалуются, '
                      'не показываем.',
                      style: TextStyle(
                          color: AppColors.muted, fontSize: 12.5, height: 1.4),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ReasonRow extends StatelessWidget {
  final String title;
  final bool selected;
  final VoidCallback onTap;
  const _ReasonRow({
    required this.title,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 11),
        child: Row(
          children: [
            Icon(
              selected ? Icons.radio_button_checked : Icons.radio_button_unchecked,
              size: 20,
              color: selected ? AppColors.ink : AppColors.faint,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                title,
                style: TextStyle(
                  color: AppColors.ink,
                  fontSize: 14.5,
                  fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
