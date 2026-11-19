import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mata_ui/mata_ui.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_states.dart';
import '../data/appeals_provider.dart';

/// «Модерация» (§10 готовности): меры ко мне — с правом возразить — и чем
/// кончились мои жалобы. Сюда ведут уведомления «Решение модерации»,
/// «Жалоба рассмотрена» и «Ответ на возражение».
class AppealsScreen extends ConsumerWidget {
  const AppealsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final measures = ref.watch(myMeasuresProvider);
    final reports = ref.watch(myReportsProvider);
    Future<void> refresh() async {
      ref.invalidate(myMeasuresProvider);
      ref.invalidate(myReportsProvider);
    }

    final loading = measures.isLoading || reports.isLoading;
    final failed = measures.hasError || reports.hasError;

    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        backgroundColor: AppColors.bg,
        surfaceTintColor: Colors.transparent,
        title: const Text('Модерация'),
      ),
      body: RefreshIndicator(
        onRefresh: refresh,
        child: loading
            ? const MataLoading()
            : failed
                ? ListView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    children: [
                      const SizedBox(height: 60),
                      MataError(
                        icon: CupertinoIcons.wifi_slash,
                        iconColor: AppStates.icon,
                        title: 'Нет связи',
                        titleStyle: AppStates.title,
                        hint: 'Обращения не загрузились.',
                        hintStyle: AppStates.hint,
                        retryLabel: 'Повторить',
                        onRetry: refresh,
                        retryBuilder: AppStates.retry,
                      ),
                    ],
                  )
                : _Body(
                    measures: measures.valueOrNull ?? const [],
                    reports: reports.valueOrNull ?? const [],
                  ),
      ),
    );
  }
}

class _Body extends StatelessWidget {
  final List<MyMeasure> measures;
  final List<MyReport> reports;
  const _Body({required this.measures, required this.reports});

  @override
  Widget build(BuildContext context) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 120),
      children: [
        const _Title(
          'Меры ко мне',
          'Если модератор ограничил вас или ваш клуб, здесь видно за что. '
              'Не согласны — один раз напишите возражение, его разберёт человек.',
        ),
        const SizedBox(height: 10),
        if (measures.isEmpty)
          const _Note('Мер нет.')
        else
          for (final m in measures) ...[
            _MeasureCard(m: m),
            const SizedBox(height: 10),
          ],
        const SizedBox(height: 20),
        const _Title(
          'Мои жалобы',
          'Что стало с жалобами, которые вы отправили. Подробности о мерах к '
              'другому человеку не показываем — это решение о нём.',
        ),
        const SizedBox(height: 10),
        if (reports.isEmpty)
          const _Note('Вы не отправляли жалоб.')
        else
          for (final r in reports) ...[
            _ReportCard(r: r),
            const SizedBox(height: 10),
          ],
      ],
    );
  }
}

class _MeasureCard extends ConsumerStatefulWidget {
  final MyMeasure m;
  const _MeasureCard({required this.m});

  @override
  ConsumerState<_MeasureCard> createState() => _MeasureCardState();
}

class _MeasureCardState extends ConsumerState<_MeasureCard> {
  bool _writing = false;
  bool _sending = false;
  final _text = TextEditingController();

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _text.text.trim();
    if (text.isEmpty) return;
    setState(() => _sending = true);
    final error = await ref.read(appealActionsProvider).appeal(widget.m.id, text);
    if (!mounted) return;
    setState(() => _sending = false);
    if (error == null) {
      setState(() => _writing = false);
      _toast('Возражение отправлено. Ответ придёт уведомлением.');
    } else {
      _toast(error);
    }
  }

  void _toast(String text) => ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(text)));

  String get _appealLine => switch (widget.m.appealStatus) {
    'new' => 'Возражение на разборе',
    'accepted' => 'Возражение принято, мера снята',
    'rejected' => 'Возражение отклонено, мера в силе',
    _ => '',
  };

  @override
  Widget build(BuildContext context) {
    final m = widget.m;
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  m.aboutClub ? '${m.kindTitle} · клуб' : m.kindTitle,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: AppColors.ink,
                  ),
                ),
              ),
              Text(
                m.active ? 'действует' : 'снята',
                style: TextStyle(
                  fontSize: 13,
                  color: m.active ? AppColors.warning : AppColors.muted,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(m.summary, style: TextStyle(fontSize: 14, color: AppColors.ink, height: 1.4)),
          if (_appealLine.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(_appealLine, style: TextStyle(fontSize: 13, color: AppColors.muted)),
            if (m.appealReply.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                'Ответ модератора: ${m.appealReply}',
                style: TextStyle(fontSize: 13, color: AppColors.ink, height: 1.4),
              ),
            ],
          ],
          if (m.canAppeal && !_writing) ...[
            const SizedBox(height: 6),
            TextButton(
              style: TextButton.styleFrom(
                padding: EdgeInsets.zero,
                minimumSize: const Size(0, 36),
              ),
              onPressed: () => setState(() => _writing = true),
              child: const Text('Возразить'),
            ),
          ],
          if (_writing) ...[
            const SizedBox(height: 10),
            TextField(
              controller: _text,
              autofocus: true,
              minLines: 3,
              maxLines: 6,
              maxLength: 2000,
              onChanged: (_) => setState(() {}),
              decoration: const InputDecoration(
                hintText: 'С чем вы не согласны и почему',
                border: OutlineInputBorder(),
              ),
            ),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed: _sending ? null : () => setState(() => _writing = false),
                  child: const Text('Отмена'),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _sending || _text.text.trim().isEmpty ? null : _send,
                  child: Text(_sending ? 'Отправляем…' : 'Отправить'),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _ReportCard extends StatelessWidget {
  final MyReport r;
  const _ReportCard({required this.r});

  @override
  Widget build(BuildContext context) {
    final answer = switch (r.status) {
      'accepted' => 'Меры приняты. Спасибо, что сообщили.',
      'rejected' => 'Нарушения правил не нашли.',
      _ => 'На разборе. Ответ придёт уведомлением.',
    };
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            r.targetName,
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.ink),
          ),
          const SizedBox(height: 2),
          Text(r.reasonTitle, style: TextStyle(fontSize: 13, color: AppColors.muted)),
          const SizedBox(height: 8),
          Text(answer, style: TextStyle(fontSize: 14, color: AppColors.ink, height: 1.4)),
        ],
      ),
    );
  }
}

class _Title extends StatelessWidget {
  final String title;
  final String hint;
  const _Title(this.title, this.hint);

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(title, style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: AppColors.ink)),
      const SizedBox(height: 2),
      Text(hint, style: TextStyle(fontSize: 13, color: AppColors.muted, height: 1.35)),
    ],
  );
}

class _Note extends StatelessWidget {
  final String text;
  const _Note(this.text);

  @override
  Widget build(BuildContext context) =>
      Text(text, style: TextStyle(fontSize: 14, color: AppColors.muted));
}

class _Panel extends StatelessWidget {
  final Widget child;
  const _Panel({required this.child});

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: AppColors.panel,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: AppColors.separator),
    ),
    child: child,
  );
}
