import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../data/friends_provider.dart';

/// Друзья (D-82, этап 2a): взаимные друзья, заявки, добавление.
/// Карта друзей и приватность — этап 2b/2c. Раздел за флагом kFriends.
class FriendsScreen extends ConsumerStatefulWidget {
  const FriendsScreen({super.key});

  @override
  ConsumerState<FriendsScreen> createState() => _FriendsScreenState();
}

enum _Tab { friends, requests, add }

class _FriendsScreenState extends ConsumerState<FriendsScreen> {
  _Tab _tab = _Tab.friends;
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final data = ref.watch(friendsProvider).valueOrNull ?? const FriendsData();
    final pending = data.incoming.length;

    return Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        backgroundColor: AppColors.bg,
        elevation: 0,
        title: const Text('Друзья',
            style: TextStyle(fontWeight: FontWeight.w800, fontSize: 19)),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 10),
            child: _Segment(
              tab: _tab,
              pending: pending,
              onPick: (t) => setState(() => _tab = t),
            ),
          ),
          Expanded(
            child: switch (_tab) {
              _Tab.friends => _FriendsList(data: data),
              _Tab.requests => _Requests(data: data),
              _Tab.add =>
                _AddPanel(query: _query, onQuery: (q) => setState(() => _query = q)),
            },
          ),
        ],
      ),
    );
  }
}

class _Segment extends StatelessWidget {
  final _Tab tab;
  final int pending;
  final ValueChanged<_Tab> onPick;
  const _Segment({required this.tab, required this.pending, required this.onPick});

  @override
  Widget build(BuildContext context) {
    Widget seg(_Tab t, String label, {int badge = 0}) {
      final active = t == tab;
      return Expanded(
        child: GestureDetector(
          onTap: () => onPick(t),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 150),
            alignment: Alignment.center,
            padding: const EdgeInsets.symmetric(vertical: 9),
            decoration: BoxDecoration(
              color: active ? AppColors.lime : Colors.transparent,
              borderRadius: BorderRadius.circular(9),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(label,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: active ? const Color(0xFF141A08) : AppColors.ink,
                    )),
                if (badge > 0) ...[
                  const SizedBox(width: 6),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                    decoration: BoxDecoration(
                      color: active ? const Color(0xFF141A08) : AppColors.lime,
                      borderRadius: BorderRadius.circular(99),
                    ),
                    child: Text('$badge',
                        style: TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w800,
                          color: active ? AppColors.lime : const Color(0xFF141A08),
                        )),
                  ),
                ],
              ],
            ),
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: AppColors.paper,
        borderRadius: BorderRadius.circular(11),
        border: Border.all(color: AppColors.line),
      ),
      child: Row(
        children: [
          seg(_Tab.friends, 'Друзья'),
          seg(_Tab.requests, 'Заявки', badge: pending),
          seg(_Tab.add, 'Добавить'),
        ],
      ),
    );
  }
}

class _Avatar extends StatelessWidget {
  final FriendSummary f;
  const _Avatar(this.f);
  @override
  Widget build(BuildContext context) {
    return Container(
      width: 44,
      height: 44,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: AppColors.lime,
        border: Border.all(color: AppColors.bg, width: 2),
      ),
      child: Text(f.initial,
          style: const TextStyle(
              color: Color(0xFF141A08), fontWeight: FontWeight.w800, fontSize: 17)),
    );
  }
}

class _Row extends StatelessWidget {
  final FriendSummary f;
  final Widget trailing;
  const _Row({required this.f, required this.trailing});
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
          _Avatar(f),
          const SizedBox(width: 12),
          Expanded(
            child: Text(f.name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                    color: AppColors.ink, fontSize: 15, fontWeight: FontWeight.w700)),
          ),
          trailing,
        ],
      ),
    );
  }
}

Widget _pill(String text, {Color? bg, Color? fg, VoidCallback? onTap, IconData? icon}) {
  final child = Container(
    padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 8),
    decoration: BoxDecoration(
      color: bg ?? Colors.transparent,
      borderRadius: BorderRadius.circular(10),
      border: bg == null ? Border.all(color: AppColors.line) : null,
    ),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      if (icon != null) ...[
        Icon(icon, size: 14, color: fg ?? AppColors.ink),
        const SizedBox(width: 5),
      ],
      Text(text,
          style: TextStyle(
              color: fg ?? AppColors.ink, fontSize: 12.5, fontWeight: FontWeight.w800)),
    ]),
  );
  return onTap == null ? child : GestureDetector(onTap: onTap, child: child);
}

class _Empty extends StatelessWidget {
  final String title;
  final String sub;
  final IconData icon;
  const _Empty({required this.title, required this.sub, required this.icon});
  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: 40, color: AppColors.muted),
          const SizedBox(height: 12),
          Text(title,
              textAlign: TextAlign.center,
              style: TextStyle(
                  color: AppColors.ink, fontSize: 16, fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          Text(sub,
              textAlign: TextAlign.center,
              style: TextStyle(color: AppColors.muted, fontSize: 13, height: 1.4)),
        ]),
      ),
    );
  }
}

class _FriendsList extends ConsumerWidget {
  final FriendsData data;
  const _FriendsList({required this.data});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (data.friends.isEmpty) {
      return const _Empty(
        icon: CupertinoIcons.person_2,
        title: 'Пока нет друзей',
        sub: 'Найди своих на вкладке «Добавить» — по имени, из клуба или по контактам.',
      );
    }
    final act = ref.read(friendsActionsProvider);
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
      children: [
        for (final f in data.friends)
          _Row(
            f: f,
            trailing: _pill('Убрать',
                fg: AppColors.muted, onTap: () => act.remove(f.userId)),
          ),
      ],
    );
  }
}

class _Requests extends ConsumerWidget {
  final FriendsData data;
  const _Requests({required this.data});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (data.incoming.isEmpty && data.outgoing.isEmpty) {
      return const _Empty(
        icon: CupertinoIcons.tray,
        title: 'Заявок нет',
        sub: 'Входящие и отправленные заявки в друзья появятся здесь.',
      );
    }
    final act = ref.read(friendsActionsProvider);
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
      children: [
        if (data.incoming.isNotEmpty) ...[
          _label('Входящие'),
          for (final f in data.incoming)
            _Row(
              f: f,
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                _pill('Принять',
                    bg: AppColors.lime,
                    fg: const Color(0xFF141A08),
                    onTap: () => act.accept(f.userId)),
                const SizedBox(width: 8),
                _pill('Нет',
                    fg: AppColors.muted, onTap: () => act.reject(f.userId)),
              ]),
            ),
        ],
        if (data.outgoing.isNotEmpty) ...[
          _label('Отправленные'),
          for (final f in data.outgoing)
            _Row(
              f: f,
              trailing: _pill('Отменить',
                  fg: AppColors.muted, onTap: () => act.reject(f.userId)),
            ),
        ],
      ],
    );
  }

  Widget _label(String t) => Padding(
        padding: const EdgeInsets.fromLTRB(2, 8, 0, 8),
        child: Text(t.toUpperCase(),
            style: TextStyle(
                color: AppColors.muted,
                fontSize: 11.5,
                fontWeight: FontWeight.w700,
                letterSpacing: .6)),
      );
}

class _AddPanel extends ConsumerWidget {
  final String query;
  final ValueChanged<String> onQuery;
  const _AddPanel({required this.query, required this.onQuery});

  Widget _addTrailing(WidgetRef ref, FriendSummary f) {
    final act = ref.read(friendsActionsProvider);
    return switch (f.status) {
      'friends' => _pill('В друзьях', fg: AppColors.muted, icon: CupertinoIcons.checkmark_alt),
      'outgoing' => _pill('Отправлено', fg: AppColors.muted),
      'incoming' => _pill('Принять',
          bg: AppColors.lime, fg: const Color(0xFF141A08), onTap: () => act.accept(f.userId)),
      _ => _pill('Добавить',
          bg: AppColors.lime, fg: const Color(0xFF141A08), onTap: () => act.request(f.userId)),
    };
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final results = query.trim().length >= 2
        ? (ref.watch(friendSearchProvider(query)).valueOrNull ?? const [])
        : const <FriendSummary>[];
    final suggestions =
        ref.watch(friendSuggestionsProvider).valueOrNull ?? const <FriendSummary>[];

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
      children: [
        // Поиск по имени
        TextField(
          onChanged: onQuery,
          style: TextStyle(color: AppColors.ink, fontSize: 15),
          decoration: InputDecoration(
            hintText: 'Поиск по имени',
            hintStyle: TextStyle(color: AppColors.muted),
            prefixIcon: Icon(CupertinoIcons.search, size: 18, color: AppColors.muted),
            filled: true,
            fillColor: AppColors.paper,
            contentPadding: const EdgeInsets.symmetric(vertical: 4),
            enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: BorderSide(color: AppColors.line)),
            focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: BorderSide(color: AppColors.lime)),
          ),
        ),
        const SizedBox(height: 10),
        // Пригласить ссылкой
        GestureDetector(
          onTap: () {
            Clipboard.setData(const ClipboardData(
                text: 'Бегай со мной в «Квартале» (МАТА): https://mata-club.ru/app.html'));
            ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Ссылка-приглашение скопирована')));
          },
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
            decoration: BoxDecoration(
              color: AppColors.paper,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppColors.line),
            ),
            child: Row(children: [
              Icon(CupertinoIcons.link, size: 17, color: AppColors.lime),
              const SizedBox(width: 10),
              Expanded(
                child: Text('Пригласить по ссылке',
                    style: TextStyle(
                        color: AppColors.ink, fontSize: 14, fontWeight: FontWeight.w700)),
              ),
              Icon(CupertinoIcons.doc_on_doc, size: 16, color: AppColors.muted),
            ]),
          ),
        ),
        const SizedBox(height: 18),

        if (query.trim().length >= 2) ...[
          _hdr('Результаты'),
          if (results.isEmpty)
            _muted('Никого не нашли по «${query.trim()}»')
          else
            for (final f in results) _Row(f: f, trailing: _addTrailing(ref, f)),
          const SizedBox(height: 18),
        ],

        _hdr('Из твоего клуба'),
        if (suggestions.isEmpty)
          _muted('Подсказок пока нет. Вступи в клуб — предложим одноклубников.')
        else
          for (final f in suggestions) _Row(f: f, trailing: _addTrailing(ref, f)),
      ],
    );
  }

  Widget _hdr(String t) => Padding(
        padding: const EdgeInsets.fromLTRB(2, 0, 0, 10),
        child: Text(t.toUpperCase(),
            style: TextStyle(
                color: AppColors.muted,
                fontSize: 11.5,
                fontWeight: FontWeight.w700,
                letterSpacing: .6)),
      );

  Widget _muted(String t) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Text(t, style: TextStyle(color: AppColors.muted, fontSize: 13, height: 1.4)),
      );
}
