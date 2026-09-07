import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../auth/data/auth_provider.dart';
import '../../data/legal_provider.dart';

/// Правовые документы экосистемы МАТА — пункт в Настройках (как «Уведомления»,
/// «Конфиденциальность»). Тексты приходят с backend и редактируются в админ-панели:
/// изменил в админке → приложение показывает новую версию. Отдельной «фичи» нет.
class LegalDocumentsScreen extends ConsumerWidget {
  const LegalDocumentsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(legalDocumentsProvider);
    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: AppColors.bgDark,
        title: const Text('Документы'),
      ),
      body: SafeArea(
        child: async.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => _Message(
            icon: CupertinoIcons.wifi_slash,
            text: 'Не удалось загрузить документы.\nПроверьте соединение.',
            onRetry: () => ref.refresh(legalDocumentsProvider),
          ),
          data: (docs) {
            if (docs.isEmpty) {
              return const _Message(
                icon: CupertinoIcons.doc_text,
                text: 'Документы пока не опубликованы.',
              );
            }
            return RefreshIndicator(
              onRefresh: () async => ref.refresh(legalDocumentsProvider.future),
              child: ListView.builder(
                padding: const EdgeInsets.all(16),
                itemCount: docs.length,
                itemBuilder: (_, i) => _DocTile(doc: docs[i]),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _DocTile extends StatelessWidget {
  final LegalDoc doc;
  const _DocTile({required this.doc});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.separator),
      ),
      child: ListTile(
        leading: Icon(CupertinoIcons.doc_text,
            color: AppColors.accentBlue, size: 20),
        title: Text(
          doc.title,
          style: Theme.of(context)
              .textTheme
              .bodyMedium
              ?.copyWith(color: AppColors.textPrimary),
        ),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 3),
          child: Row(
            children: [
              Text('ред. ${doc.version}',
                  style: TextStyle(
                      fontSize: 12, color: AppColors.textSecondary)),
              if (doc.required) ...[
                const SizedBox(width: 8),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                  decoration: BoxDecoration(
                    color: AppColors.accentBlue.withValues(alpha: 0.16),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text('обязательный',
                      style: TextStyle(
                          fontSize: 10, color: AppColors.accentBlue)),
                ),
              ],
            ],
          ),
        ),
        trailing: Icon(CupertinoIcons.chevron_right,
            color: AppColors.textDisabled, size: 16),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute(builder: (_) => _LegalDocView(doc: doc)),
        ),
      ),
    );
  }
}

/// Просмотр текста документа. Тело хранится в backend (Markdown), рендерим
/// лёгким форматированием — без внешних зависимостей.
class _LegalDocView extends StatelessWidget {
  final LegalDoc doc;
  const _LegalDocView({required this.doc});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: AppColors.bgDark,
        title: Text(doc.title, style: const TextStyle(fontSize: 16)),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 40),
          children: [
            Text('Редакция ${doc.version}',
                style: TextStyle(
                    fontSize: 12, color: AppColors.textSecondary)),
            const SizedBox(height: 12),
            ..._renderMarkdown(doc.body),
          ],
        ),
      ),
    );
  }

  List<Widget> _renderMarkdown(String md) {
    // Убираем первый заголовок (# Название) — он дублирует заголовок экрана (AppBar).
    md = md
        .replaceAll('\r\n', '\n')
        .replaceFirst(RegExp(r'^\s*#{1,6}[^\n]*\n?'), '');
    final widgets = <Widget>[];
    for (final rawLine in md.split('\n')) {
      final line = rawLine.trimRight();
      if (line.trim().isEmpty) {
        widgets.add(const SizedBox(height: 10));
        continue;
      }
      if (line.startsWith('### ')) {
        widgets.add(_h(line.substring(4), 15));
      } else if (line.startsWith('## ')) {
        widgets.add(_h(line.substring(3), 17));
      } else if (line.startsWith('# ')) {
        widgets.add(_h(line.substring(2), 20));
      } else if (line.startsWith('> ')) {
        widgets.add(Container(
          margin: const EdgeInsets.symmetric(vertical: 4),
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
          decoration: BoxDecoration(
            color: AppColors.bgSurface,
            border: Border(
                left: BorderSide(color: AppColors.accentBlue, width: 3)),
          ),
          child: SelectableText(_stripInline(line.substring(2)),
              style: TextStyle(
                  fontSize: 13, color: AppColors.textSecondary, height: 1.4)),
        ));
      } else if (RegExp(r'^[-*] ').hasMatch(line)) {
        widgets.add(Padding(
          padding: const EdgeInsets.only(left: 4, top: 2, bottom: 2),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: EdgeInsets.only(top: 7, right: 8),
                child: Icon(Icons.circle, size: 5, color: AppColors.accentBlue),
              ),
              Expanded(
                child: SelectableText(_stripInline(line.substring(2)),
                    style: TextStyle(
                        fontSize: 14, color: AppColors.textPrimary, height: 1.45)),
              ),
            ],
          ),
        ));
      } else {
        widgets.add(Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: SelectableText(_stripInline(line),
              style: TextStyle(
                  fontSize: 14, color: AppColors.textPrimary, height: 1.5)),
        ));
      }
    }
    return widgets;
  }

  Widget _h(String text, double size) => Padding(
        padding: const EdgeInsets.only(top: 14, bottom: 4),
        child: SelectableText(_stripInline(text),
            style: TextStyle(
                fontSize: size,
                fontWeight: FontWeight.w700,
                color: AppColors.textPrimary)),
      );

  /// Убираем простую inline-разметку (**жирный**, `код`, таблицы |).
  String _stripInline(String s) =>
      s.replaceAll('**', '').replaceAll('`', '').replaceAll('|', '  ');
}

class _Message extends StatelessWidget {
  final IconData icon;
  final String text;
  final VoidCallback? onRetry;
  const _Message({required this.icon, required this.text, this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 44, color: AppColors.textDisabled),
          const SizedBox(height: 12),
          Text(text,
              textAlign: TextAlign.center,
              style: TextStyle(color: AppColors.textSecondary)),
          if (onRetry != null) ...[
            const SizedBox(height: 16),
            OutlinedButton(onPressed: onRetry, child: const Text('Повторить')),
          ],
        ],
      ),
    );
  }
}

/// Экран-гейт согласия: показывается ПОСЛЕ входа, если у пользователя есть
/// обязательные документы, которые он ещё не принял. Одна галочка → согласие
/// пишется на сервер (`POST /legal/consent`, аудит 152-ФЗ) → в приложение.
/// Fail-open: если проверить не удалось — пускаем дальше (не запираем вход).
class ConsentGateScreen extends ConsumerStatefulWidget {
  const ConsentGateScreen({super.key});

  @override
  ConsumerState<ConsentGateScreen> createState() => _ConsentGateScreenState();
}

class _ConsentGateScreenState extends ConsumerState<ConsentGateScreen> {
  late Future<List<LegalDoc>> _future;
  bool _accepted = false;
  bool _submitting = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<List<LegalDoc>> _load() async {
    final token = ref.read(authProvider).token;
    if (token == null) {
      _leave();
      return const [];
    }
    final docs = await fetchLegalDocs(token: token);
    final pending = pendingRequired(docs);
    if (pending.isEmpty) _leave();
    return pending;
  }

  void _leave() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) context.go('/map');
    });
  }

  Future<void> _submit(List<LegalDoc> pending) async {
    final token = ref.read(authProvider).token;
    if (token == null) {
      _leave();
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await acceptLegalDocs(
        token: token,
        types: pending.map((d) => d.type).toList(),
        source: 'kvartal',
      );
      if (mounted) context.go('/map');
    } catch (_) {
      if (mounted) {
        setState(() {
          _submitting = false;
          _error = 'Не удалось сохранить согласие. Проверьте соединение.';
        });
      }
    }
  }

  Future<void> _logout() async {
    await ref.read(authProvider.notifier).logout();
    if (mounted) context.go('/auth/phone');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bgDark,
      appBar: AppBar(
        backgroundColor: AppColors.bgDark,
        automaticallyImplyLeading: false,
        title: const Text('Подтверждение'),
      ),
      body: SafeArea(
        child: FutureBuilder<List<LegalDoc>>(
          future: _future,
          builder: (context, snap) {
            if (snap.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            final pending = snap.data ?? const <LegalDoc>[];
            if (snap.hasError) {
              // Fail-open: не удалось проверить — не запираем, уводим в приложение.
              _leave();
              return const Center(child: CircularProgressIndicator());
            }
            if (pending.isEmpty) {
              return const Center(child: CircularProgressIndicator());
            }
            return Column(
              children: [
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
                    children: [
                      Text(
                        'Чтобы продолжить, ознакомьтесь и примите обязательные документы:',
                        style: TextStyle(
                            fontSize: 15,
                            color: AppColors.textPrimary,
                            height: 1.4),
                      ),
                      const SizedBox(height: 12),
                      ...pending.map((d) => Container(
                            margin: const EdgeInsets.only(bottom: 8),
                            decoration: BoxDecoration(
                              color: AppColors.bgCard,
                              borderRadius: BorderRadius.circular(12),
                              border:
                                  Border.all(color: AppColors.separator),
                            ),
                            child: ListTile(
                              leading: Icon(CupertinoIcons.doc_text,
                                  color: AppColors.accentBlue, size: 20),
                              title: Text(d.title,
                                  style: TextStyle(
                                      color: AppColors.textPrimary,
                                      fontSize: 14)),
                              subtitle: Text('нажмите, чтобы прочитать',
                                  style: TextStyle(
                                      color: AppColors.textSecondary,
                                      fontSize: 12)),
                              trailing: Icon(
                                  CupertinoIcons.chevron_right,
                                  color: AppColors.textDisabled,
                                  size: 16),
                              onTap: () => Navigator.of(context).push(
                                MaterialPageRoute(
                                    builder: (_) => _LegalDocView(doc: d)),
                              ),
                            ),
                          )),
                      if (_error != null) ...[
                        const SizedBox(height: 4),
                        Text(_error!,
                            style: TextStyle(
                                color: AppColors.error, fontSize: 13)),
                      ],
                    ],
                  ),
                ),
                _AcceptBar(
                  accepted: _accepted,
                  submitting: _submitting,
                  onToggle: (v) => setState(() => _accepted = v),
                  onAccept:
                      _accepted && !_submitting ? () => _submit(pending) : null,
                  onLogout: _submitting ? null : _logout,
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _AcceptBar extends StatelessWidget {
  final bool accepted;
  final bool submitting;
  final ValueChanged<bool> onToggle;
  final VoidCallback? onAccept;
  final VoidCallback? onLogout;

  const _AcceptBar({
    required this.accepted,
    required this.submitting,
    required this.onToggle,
    required this.onAccept,
    required this.onLogout,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
      decoration: BoxDecoration(
        color: AppColors.bgSurface,
        border: Border(top: BorderSide(color: AppColors.separator)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          InkWell(
            onTap: () => onToggle(!accepted),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Checkbox(
                    value: accepted,
                    onChanged: (v) => onToggle(v ?? false),
                    activeColor: AppColors.accentBlue,
                    materialTapTargetSize:
                        MaterialTapTargetSize.shrinkWrap,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Padding(
                      padding: EdgeInsets.only(top: 10),
                      child: Text(
                        'Я ознакомился(-ась) и принимаю перечисленные документы',
                        style: TextStyle(
                            color: AppColors.textPrimary, fontSize: 13),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 4),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: onAccept,
              child: submitting
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Принять и продолжить'),
            ),
          ),
          TextButton(
            onPressed: onLogout,
            child: Text('Выйти',
                style: TextStyle(color: AppColors.textSecondary)),
          ),
        ],
      ),
    );
  }
}
