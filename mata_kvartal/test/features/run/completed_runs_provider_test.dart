import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/core/storage/account_scope.dart';
import 'package:kvartal_app/features/auth/data/auth_provider.dart';
import 'package:kvartal_app/features/loyalty/data/loyalty_provider.dart';
import 'package:kvartal_app/features/notifications/data/notifications_provider.dart';
import 'package:kvartal_app/features/run/data/completed_runs_provider.dart';
import 'package:latlong2/latlong.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Поддельный сервер: записывает запросы, умеет «пропасть» целиком или только
/// на отправке трека.
class _FakeServer implements HttpClientAdapter {
  final requests = <RequestOptions>[];
  bool offline = false;
  bool trackFails = false;
  List<Map<String, dynamic>> serverRuns = [];

  List<RequestOptions> posts(String path) => requests
      .where((r) => r.method == 'POST' && r.path == path)
      .toList();

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    if (offline || (trackFails && options.path == '/runs/track')) {
      throw const SocketException('нет сети');
    }
    Object body = const {};
    if (options.method == 'POST' && options.path == '/runs') {
      body = {'ok': true, 'duplicate': false, 'pointsAwarded': 10};
    } else if (options.path == '/runs/track') {
      body = {'attempts': []};
    } else if (options.method == 'GET' && options.path == '/runs') {
      body = serverRuns;
    }
    return ResponseBody.fromString(
      jsonEncode(body),
      200,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

class _FakeAuth extends AuthNotifier {
  void signIn(String id, String token) => state = AuthState(
    status: AuthStatus.authenticated,
    token: token,
    user: AuthUser(id: id, name: 'Бегун', email: ''),
  );

  void signOut() => state = const AuthState();
}

class _QuietLoyalty extends LoyaltyNotifier {
  _QuietLoyalty(super.ref);
  @override
  Future<void> refresh() async {}
}

class _QuietNotifications extends NotificationsNotifier {
  _QuietNotifications(super.ref);
  @override
  Future<void> refresh() async {}
}

CompletedRun _run(String id) => CompletedRun(
  id: id,
  finishedAt: DateTime(2026, 9, 27, 7, 30),
  route: const [LatLng(62.03, 129.73), LatLng(62.031, 129.731)],
  routeTimes: const [0, 5000],
  elapsed: const Duration(minutes: 5),
  distanceMeters: 1000,
  capturedZones: 0,
  capturedTerritory: false,
);

/// Дать отработать всем отложенным future (prefs, поддельная сеть).
Future<void> _settle() async {
  for (var i = 0; i < 50; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

String? _bearer(RequestOptions r) => r.headers['Authorization']?.toString();

bool _mentionsRun(RequestOptions r, String runId) {
  final data = r.data;
  return data is Map && (data['id'] == runId || data['runId'] == runId);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late _FakeServer server;
  late _FakeAuth auth;
  late ProviderContainer container;

  Future<void> start([Map<String, Object> prefs = const {}]) async {
    SharedPreferences.setMockInitialValues(prefs);
    server = _FakeServer();
    auth = _FakeAuth();
    final dio = Dio(BaseOptions(baseUrl: 'http://test'))
      ..httpClientAdapter = server;
    container = ProviderContainer(
      overrides: [
        authProvider.overrideWith((ref) => auth),
        loyaltyProvider.overrideWith((ref) => _QuietLoyalty(ref)),
        notificationsProvider.overrideWith((ref) => _QuietNotifications(ref)),
        completedRunsDioProvider.overrideWithValue(dio),
      ],
    );
    await _settle();
  }

  tearDown(() => container.dispose());

  CompletedRunsNotifier runs() => container.read(completedRunsProvider.notifier);
  List<CompletedRun> history() => container.read(completedRunsProvider);

  group('C03: забеги принадлежат аккаунту', () {
    test('A бегал офлайн → вышел → вошёл B: B не видит и не отправляет забег A',
        () async {
      await start();
      auth.signIn('A', 'token-A');
      history(); // создать провайдер
      await _settle();

      server.offline = true; // на улице без сети
      await runs().add(_run('run-A'));
      await _settle();
      expect(history().map((r) => r.id), ['run-A']);

      auth.signOut();
      await _settle();
      expect(history(), isEmpty, reason: 'после выхода история скрыта');

      server.offline = false;
      auth.signIn('B', 'token-B');
      await _settle();
      await runs().syncPending();
      await _settle();

      expect(history(), isEmpty, reason: 'B не видит забег A');
      expect(
        server.requests.where(
          (r) => _mentionsRun(r, 'run-A') && _bearer(r) == 'Bearer token-B',
        ),
        isEmpty,
        reason: 'забег A не уходит под токеном B',
      );

      // A вернулся — забег его, и доставляется под ЕГО токеном.
      auth.signOut();
      await _settle();
      auth.signIn('A', 'token-A');
      await _settle();

      expect(history().map((r) => r.id), ['run-A']);
      final sent = server.requests.where((r) => _mentionsRun(r, 'run-A'));
      expect(sent.map((r) => r.path).toSet(), {'/runs', '/runs/track'});
      expect(sent.map(_bearer).toSet(), {'Bearer token-A'});
    });

    test('новый забег B не попадает в историю A', () async {
      await start();
      auth.signIn('A', 'token-A');
      history();
      await _settle();
      await runs().add(_run('run-A'));
      await _settle();

      auth.signOut();
      auth.signIn('B', 'token-B');
      await _settle();
      await runs().add(_run('run-B'));
      await _settle();
      expect(history().map((r) => r.id), ['run-B']);

      auth.signOut();
      auth.signIn('A', 'token-A');
      await _settle();
      expect(history().map((r) => r.id), ['run-A']);
    });

    test('миграция: старые забеги достаются тому, кто был в приложении', () async {
      await start({
        legacyCompletedRunsKey: jsonEncode([
          _run('old-sent').toJson(),
          _run('old-unsent').toJson(),
        ]),
        legacyRunsSyncedKey: ['old-sent'],
        authUserIdPrefsKey: 'A',
      });
      final prefs = await SharedPreferences.getInstance();
      await CompletedRunsNotifier.migrateLegacyStorage(prefs);
      expect(prefs.getString(legacyCompletedRunsKey), isNull);
      expect(prefs.getStringList(legacyRunsSyncedKey), isNull);

      auth.signIn('A', 'token-A');
      history();
      await _settle();
      expect(history().map((r) => r.id).toSet(), {'old-sent', 'old-unsent'});
      // Досылается только недоставленный — и под своим токеном.
      final summaries = server.posts('/runs');
      expect(summaries.map((r) => (r.data as Map)['id']), ['old-unsent']);
      expect(summaries.map(_bearer).toSet(), {'Bearer token-A'});
    });

    test('миграция без сессии: владелец неизвестен — не отправляем под чужим, '
        'забираем только доказанное сервером', () async {
      await start({
        legacyCompletedRunsKey: jsonEncode([
          _run('orphan-sent').toJson(),
          _run('orphan-unsent').toJson(),
        ]),
        legacyRunsSyncedKey: ['orphan-sent'],
      });
      final prefs = await SharedPreferences.getInstance();
      await CompletedRunsNotifier.migrateLegacyStorage(prefs);

      server.serverRuns = [
        {'id': 'orphan-sent', 'finishedAtMs': 1, 'distanceMeters': 1000},
      ];
      auth.signIn('B', 'token-B');
      history();
      await _settle();

      // orphan-sent сервер приписал B — это его; orphan-unsent — неизвестно чей.
      expect(history().map((r) => r.id), ['orphan-sent']);
      expect(history().single.route, isNotEmpty, reason: 'локальный маршрут');
      expect(
        server.requests.where((r) => _mentionsRun(r, 'orphan-unsent')),
        isEmpty,
      );
      expect(server.posts('/runs'), isEmpty, reason: 'сводки не пересылаются');
    });
  });

  group('C04: сводка и трек доставляются независимо', () {
    test('сбой трека → повтор при восстановлении сети без второй сводки',
        () async {
      await start();
      auth.signIn('A', 'token-A');
      history();
      await _settle();

      server.trackFails = true;
      await runs().add(_run('run-1'));
      await _settle();

      expect(server.posts('/runs'), hasLength(1));
      expect(server.posts('/runs/track'), hasLength(1));
      var run = history().single;
      expect(run.summarySynced, isTrue);
      expect(run.trackPending, isTrue, reason: 'трек не потерян');

      // Состояние доставки переживает перезапуск.
      final prefs = await SharedPreferences.getInstance();
      final stored = jsonDecode(prefs.getString(completedRunsKeyFor('A'))!);
      expect((stored as List).single['trackPending'], isTrue);

      server.trackFails = false; // сеть вернулась
      await runs().syncPending();
      await _settle();

      expect(server.posts('/runs'), hasLength(1), reason: 'без повторного начисления');
      expect(server.posts('/runs/track'), hasLength(2));
      run = history().single;
      expect(run.trackPending, isFalse);

      await runs().syncPending();
      await _settle();
      expect(server.requests.where((r) => r.method == 'POST'), hasLength(3),
          reason: 'доставленное больше не шлём');
    });

    test('офлайн целиком: сводка и трек уходят вместе, когда сеть вернулась',
        () async {
      await start();
      auth.signIn('A', 'token-A');
      history();
      await _settle();

      server.offline = true;
      await runs().add(_run('run-1'));
      await _settle();
      expect(history().single.summarySynced, isFalse);

      server.offline = false;
      await runs().syncPending();
      await _settle();
      expect(
        server.requests
            .where((r) => r.method == 'POST' && _mentionsRun(r, 'run-1'))
            .map((r) => r.path),
        ['/runs', '/runs', '/runs/track'], // 1-я попытка офлайн, потом обе
      );
      expect(history().single.summarySynced, isTrue);
      expect(history().single.trackPending, isFalse);
    });
  });

  group('C03: офлайн-очереди', () {
    test('миграция помечает старые элементы тем, кто был в приложении', () async {
      SharedPreferences.setMockInitialValues({
        'kvartal.shoes.pending.v1': jsonEncode([
          {'shoeId': 's1', 'km': 5, 'runId': 'r1'},
        ]),
        'kvartal.capture_queue.v1': [jsonEncode({'captureId': 'c1'})],
        authUserIdPrefsKey: 'A',
      });
      final prefs = await SharedPreferences.getInstance();
      await migrateOwnerlessQueues(prefs);

      final shoes = (jsonDecode(prefs.getString('kvartal.shoes.pending.v1')!)
          as List).cast<Map>();
      expect(isOwnedBy(shoes.single, 'A'), isTrue);
      expect(isOwnedBy(shoes.single, 'B'), isFalse);
      final capture =
          jsonDecode(prefs.getStringList('kvartal.capture_queue.v1')!.single)
              as Map;
      expect(isOwnedBy(capture, 'A'), isTrue);
      expect(withoutOwner(capture), {'captureId': 'c1'});
    });

    test('без сессии владелец неизвестен — ничей аккаунт его не отправит',
        () async {
      SharedPreferences.setMockInitialValues({
        'kvartal.capture_queue.v1': [jsonEncode({'captureId': 'c1'})],
      });
      final prefs = await SharedPreferences.getInstance();
      await migrateOwnerlessQueues(prefs);
      final capture =
          jsonDecode(prefs.getStringList('kvartal.capture_queue.v1')!.single)
              as Map;
      expect(isOwnedBy(capture, 'A'), isFalse);
      expect(isOwnedBy(capture, unknownOwner), isTrue);
      expect(isOwnedBy(capture, null), isFalse);
    });
  });
}
