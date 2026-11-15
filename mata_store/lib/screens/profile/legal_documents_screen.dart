import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../data/api/api_client.dart';
import '../../providers/auth_provider.dart';
import '../../theme/app_theme.dart';

/// Загрузить опубликованные документы. С токеном (ApiClient его подставляет)
/// у каждого проставлен `accepted` (принят ли пользователем).
Future<List<_LegalDoc>> _fetchLegalDocs(ApiClient? api) async {
  if (api == null) return const [];
  final data = await api.get('/legal/documents');
  if (data is! List) return const [];
  return data
      .whereType<Map>()
      .map((m) => _LegalDoc.fromJson(m.cast<String, dynamic>()))
      .toList();
}

/// Есть ли у пользователя непринятые ОБЯЗАТЕЛЬНЫЕ документы (нужен вход).
/// Fail-open: при ошибке возвращаем false — проверка не должна запирать вход.
Future<bool> hasPendingRequiredLegal(ApiClient? api) async {
  try {
    final docs = await _fetchLegalDocs(api);
    return docs.any((d) => d.required && d.accepted != true);
  } catch (_) {
    return false;
  }
}

/// Правовые документы экосистемы МАТА (соглашения, политика, согласия, оферта,
/// правила баллов/сообщества). Единый источник правды — backend: документы
/// редактируются в админ-панели, приложение всегда показывает актуальную
/// опубликованную версию (`GET /v1/legal/documents`). Отдельной «фичи» нет —
/// это пункт в Настройках, как «Уведомления» и «Конфиденциальность».
class LegalDocumentsScreen extends StatefulWidget {
  const LegalDocumentsScreen({super.key});

  @override
  State<LegalDocumentsScreen> createState() => _LegalDocumentsScreenState();
}

class _LegalDocumentsScreenState extends State<LegalDocumentsScreen> {
  late Future<List<_LegalDoc>> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<List<_LegalDoc>> _load() => _fetchLegalDocs(context.read<ApiClient?>());

  Future<void> _reload() async {
    setState(() => _future = _load());
    await _future;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.white,
      appBar: AppBar(
        title: Text(
          'ДОКУМЕНТЫ',
          style: TextStyle(
            fontSize: 20, fontWeight: FontWeight.w700, letterSpacing: 3,
          ),
        ),
      ),
      body: FutureBuilder<List<_LegalDoc>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return _Message(
              icon: Icons.wifi_off,
              text: 'Не удалось загрузить документы.\nПроверьте соединение.',
              onRetry: _reload,
            );
          }
          final docs = snap.data ?? const <_LegalDoc>[];
          if (docs.isEmpty) {
            return const _Message(
              icon: Icons.description_outlined,
              text: 'Документы пока не опубликованы.',
            );
          }
          return RefreshIndicator(
            onRefresh: _reload,
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(vertical: 8),
              itemCount: docs.length,
              separatorBuilder: (_, __) =>
                  const Divider(height: 1, color: AppColors.grey100),
              itemBuilder: (context, i) => _DocTile(doc: docs[i]),
            ),
          );
        },
      ),
    );
  }
}

class _DocTile extends StatelessWidget {
  final _LegalDoc doc;
  const _DocTile({required this.doc});

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      leading: Container(
        width: 36,
        height: 36,
        decoration: BoxDecoration(
          color: AppColors.grey100,
          borderRadius: BorderRadius.circular(8),
        ),
        child: const Icon(Icons.description_outlined,
            size: 19, color: AppColors.black),
      ),
      title: Text(
        doc.title,
        style: const TextStyle(
            fontSize: 15, fontWeight: FontWeight.w500, color: AppColors.black),
      ),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 3),
        child: Row(
          children: [
            Text('ред. ${doc.version}',
                style: const TextStyle(fontSize: 14, color: AppColors.grey600)),
            if (doc.required) ...[
              const SizedBox(width: 8),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                decoration: BoxDecoration(
                  color: AppColors.black,
                  borderRadius: BorderRadius.circular(3),
                ),
                child: const Text('обязательный',
                    style: TextStyle(fontSize: 11, color: AppColors.white)),
              ),
            ],
            if (doc.accepted == true) ...[
              const SizedBox(width: 8),
              const Icon(Icons.check_circle, size: 14, color: AppColors.grey600),
              const SizedBox(width: 3),
              const Text('принят',
                  style: TextStyle(fontSize: 14, color: AppColors.grey600)),
            ],
          ],
        ),
      ),
      trailing:
          const Icon(Icons.chevron_right, size: 20, color: AppColors.grey400),
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => _LegalDocView(doc: doc)),
      ),
    );
  }
}

/// Просмотр текста документа. Тело хранится в backend (Markdown), рендерим
/// лёгким форматированием — без внешних зависимостей.
class _LegalDocView extends StatelessWidget {
  final _LegalDoc doc;
  const _LegalDocView({required this.doc});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.white,
      appBar: AppBar(
        title: Text(
          doc.title.toUpperCase(),
          style: TextStyle(
            fontSize: 16, fontWeight: FontWeight.w700, letterSpacing: 1.5,
          ),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 40),
        children: [
          Text('Редакция ${doc.version}',
              style: const TextStyle(fontSize: 14, color: AppColors.grey600)),
          const SizedBox(height: 12),
          ..._renderMarkdown(doc.body),
        ],
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
          decoration: const BoxDecoration(
            color: AppColors.grey100,
            border: Border(
                left: BorderSide(color: AppColors.black, width: 3)),
          ),
          child: SelectableText(_stripInline(line.substring(2)),
              style: const TextStyle(
                  fontSize: 14, color: AppColors.grey600, height: 1.4)),
        ));
      } else if (RegExp(r'^[-*] ').hasMatch(line)) {
        widgets.add(Padding(
          padding: const EdgeInsets.only(left: 4, top: 2, bottom: 2),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Padding(
                padding: EdgeInsets.only(top: 6, right: 8),
                child: Icon(Icons.circle, size: 5, color: AppColors.black),
              ),
              Expanded(
                child: SelectableText(_stripInline(line.substring(2)),
                    style: const TextStyle(
                        fontSize: 14, color: AppColors.black, height: 1.45)),
              ),
            ],
          ),
        ));
      } else {
        widgets.add(Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: SelectableText(_stripInline(line),
              style: const TextStyle(
                  fontSize: 14, color: AppColors.black, height: 1.5)),
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
                color: AppColors.black)),
      );

  /// Убираем простую inline-разметку (**жирный**, `код`, таблицы |, ссылки),
  /// чтобы текст читался как обычный, без «звёздочек» и «[текст](url)».
  String _stripInline(String s) {
    s = s.replaceAllMapped(
        RegExp(r'\[([^\]]+)\]\([^)]*\)'), (m) => m[1] ?? '');
    return s.replaceAll('**', '').replaceAll('`', '').replaceAll('|', '  ');
  }
}

class _Message extends StatelessWidget {
  final IconData icon;
  final String text;
  final Future<void> Function()? onRetry;
  const _Message({required this.icon, required this.text, this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 44, color: AppColors.grey400),
          const SizedBox(height: 12),
          Text(text,
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.grey600)),
          if (onRetry != null) ...[
            const SizedBox(height: 16),
            OutlinedButton(
              onPressed: onRetry,
              child: const Text('Повторить'),
            ),
          ],
        ],
      ),
    );
  }
}

class _LegalDoc {
  final String type;
  final String title;
  final String version;
  final String body;
  final bool required;
  final bool? accepted;

  const _LegalDoc({
    required this.type,
    required this.title,
    required this.version,
    required this.body,
    required this.required,
    this.accepted,
  });

  factory _LegalDoc.fromJson(Map<String, dynamic> m) => _LegalDoc(
        type: (m['type'] ?? '').toString(),
        title: (m['title'] ?? 'Документ').toString(),
        version: (m['version'] ?? '').toString(),
        body: (m['body'] ?? '').toString(),
        required: m['required'] == true,
        accepted: m['accepted'] is bool ? m['accepted'] as bool : null,
      );
}

/// Экран-гейт согласия: показывается ПОСЛЕ входа, если есть непринятые
/// обязательные документы. Одна галочка → согласие пишется на сервер
/// (`POST /legal/consent`, аудит 152-ФЗ) → возврат в приложение.
class ConsentGateScreen extends StatefulWidget {
  const ConsentGateScreen({super.key});

  @override
  State<ConsentGateScreen> createState() => _ConsentGateScreenState();
}

class _ConsentGateScreenState extends State<ConsentGateScreen> {
  late Future<List<_LegalDoc>> _future;
  bool _accepted = false;
  bool _submitting = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _future = _loadPending();
  }

  Future<List<_LegalDoc>> _loadPending() async {
    final docs = await _fetchLegalDocs(context.read<ApiClient?>());
    final pending =
        docs.where((d) => d.required && d.accepted != true).toList();
    if (pending.isEmpty) _leave();
    return pending;
  }

  void _leave() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) Navigator.of(context).pop();
    });
  }

  Future<void> _submit(List<_LegalDoc> pending) async {
    final api = context.read<ApiClient?>();
    if (api == null) {
      _leave();
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await api.post('/legal/consent', body: {
        'accept': pending.map((d) => d.type).toList(),
        'source': 'store',
      });
      if (mounted) Navigator.of(context).pop();
    } catch (_) {
      if (mounted) {
        setState(() {
          _submitting = false;
          _error = 'Не удалось сохранить согласие. Проверьте соединение.';
        });
      }
    }
  }

  void _logout() {
    context.read<AuthProvider>().logout();
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false, // назад только через «Принять» или «Выйти»
      child: Scaffold(
        backgroundColor: AppColors.white,
        appBar: AppBar(
          automaticallyImplyLeading: false,
          title: Text(
            'ПОДТВЕРЖДЕНИЕ',
            style: TextStyle(
              fontSize: 18, fontWeight: FontWeight.w700, letterSpacing: 2,
            ),
          ),
        ),
        body: FutureBuilder<List<_LegalDoc>>(
          future: _future,
          builder: (context, snap) {
            if (snap.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snap.hasError) {
              _leave(); // fail-open
              return const Center(child: CircularProgressIndicator());
            }
            final pending = snap.data ?? const <_LegalDoc>[];
            if (pending.isEmpty) {
              return const Center(child: CircularProgressIndicator());
            }
            return Column(
              children: [
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
                    children: [
                      const Text(
                        'Чтобы продолжить, ознакомьтесь и примите обязательные документы:',
                        style: TextStyle(
                            fontSize: 15,
                            color: AppColors.black,
                            height: 1.4),
                      ),
                      const SizedBox(height: 12),
                      ...pending.map((d) => Container(
                            margin: const EdgeInsets.only(bottom: 8),
                            decoration: BoxDecoration(
                              border: Border.all(color: AppColors.grey200),
                            ),
                            child: ListTile(
                              leading: const Icon(Icons.description_outlined,
                                  size: 19, color: AppColors.black),
                              title: Text(d.title,
                                  style: const TextStyle(
                                      fontSize: 14,
                                      fontWeight: FontWeight.w500,
                                      color: AppColors.black)),
                              subtitle: const Text('нажмите, чтобы прочитать',
                                  style: TextStyle(
                                      fontSize: 14,
                                      color: AppColors.grey600)),
                              trailing: const Icon(Icons.chevron_right,
                                  size: 20, color: AppColors.grey400),
                              onTap: () => Navigator.of(context).push(
                                MaterialPageRoute(
                                    builder: (_) => _LegalDocView(doc: d)),
                              ),
                            ),
                          )),
                      if (_error != null) ...[
                        const SizedBox(height: 4),
                        Text(_error!,
                            style: const TextStyle(
                                color: AppColors.red, fontSize: 13)),
                      ],
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                  decoration: const BoxDecoration(
                    color: AppColors.grey100,
                    border: Border(top: BorderSide(color: AppColors.grey200)),
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      InkWell(
                        onTap: () => setState(() => _accepted = !_accepted),
                        child: Padding(
                          padding: const EdgeInsets.symmetric(vertical: 6),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Checkbox(
                                value: _accepted,
                                onChanged: (v) =>
                                    setState(() => _accepted = v ?? false),
                                activeColor: AppColors.black,
                                materialTapTargetSize:
                                    MaterialTapTargetSize.shrinkWrap,
                              ),
                              const SizedBox(width: 6),
                              const Expanded(
                                child: Padding(
                                  padding: EdgeInsets.only(top: 10),
                                  child: Text(
                                    'Я ознакомился(-ась) и принимаю перечисленные документы',
                                    style: TextStyle(
                                        color: AppColors.black, fontSize: 13),
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
                          onPressed: _accepted && !_submitting
                              ? () => _submit(pending)
                              : null,
                          child: _submitting
                              ? const SizedBox(
                                  width: 20,
                                  height: 20,
                                  child: CircularProgressIndicator(
                                      strokeWidth: 2, color: AppColors.white),
                                )
                              : const Text('ПРИНЯТЬ И ПРОДОЛЖИТЬ'),
                        ),
                      ),
                      TextButton(
                        onPressed: _submitting ? null : _logout,
                        child: const Text('Выйти',
                            style: TextStyle(color: AppColors.grey600)),
                      ),
                    ],
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}
