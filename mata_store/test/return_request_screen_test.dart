import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:sport_store/data/api/api_client.dart';
import 'package:sport_store/providers/remote_content_provider.dart';
import 'package:sport_store/screens/profile/return_request_screen.dart';

/// Экран «Отмена и возврат» (D-123): всё решает сервер, экран собирает заявку.
class _Server {
  Map<String, dynamic> options;
  List<Map<String, dynamic>> requests;
  final posts = <String, Object?>{};
  _Server(this.options, [this.requests = const []]);

  http.Client get client => MockClient((req) async {
        final path = req.url.path;
        if (req.method == 'GET' && path.endsWith('/return-options')) {
          return _json(options);
        }
        if (req.method == 'GET' && path.endsWith('/return-requests')) {
          return _json(requests);
        }
        posts[path] = req.body.isEmpty ? null : jsonDecode(req.body);
        return _json(const {});
      });

  static http.Response _json(Object body) => http.Response(
        jsonEncode(body),
        200,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
}

Map<String, dynamic> _base({bool canCancel = false}) => {
      'canReturn': false,
      'lines': <Object>[],
      'reasons': {
        'size': 'Не подошёл размер',
        'defect': 'Брак или дефект',
        'other': 'Другое',
      },
      'maxPhotos': 6,
      'standardNote': '',
      'canCancel': canCancel,
      'cancelRequested': false,
      'cancelNote': '',
      'reason': 'Заказ ещё не получен',
    };

Future<void> _pump(WidgetTester tester, _Server server) async {
  tester.view.physicalSize = const Size(840, 4000);
  tester.view.devicePixelRatio = 2;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MultiProvider(
    providers: [
      Provider<ApiClient?>.value(value: ApiClient(client: server.client)),
      ChangeNotifierProvider(create: (_) => RemoteContentProvider(null)),
    ],
    child: const MaterialApp(home: ReturnRequestScreen(orderId: 'A1')),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('заказ до курьера: отмена с подтверждением', (tester) async {
    final server = _Server(_base(canCancel: true));
    await _pump(tester, server);

    // Пока заказ не получен, «вернуть нельзя» не пугает покупателя.
    expect(find.text('Заказ ещё не получен'), findsNothing);
    await tester.tap(find.widgetWithText(OutlinedButton, 'Отменить заказ'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, 'Отменить заказ'));
    await tester.pumpAndSettle();

    expect(server.posts.keys, contains('/v1/orders/A1/cancel'));
  });

  testWidgets('после 7 дней — только брак, и без фото заявку не шлём',
      (tester) async {
    final server = _Server({
      ..._base(),
      'canReturn': true,
      'standardOpen': false,
      'standardNote': 'Срок возврата вещи надлежащего качества истёк',
      'lines': [
        {'index': 0, 'name': 'Майка', 'paid': 2990, 'available': true,
         'status': 'available'},
      ],
      'store': {'description': 'ул. Ленина, 1'},
    });
    await _pump(tester, server);

    expect(find.text('Срок возврата вещи надлежащего качества истёк'),
        findsOneWidget);
    await tester.tap(find.text('Майка'));
    await tester.pumpAndSettle();
    // Причина сразу «брак»; «размер» после срока не предлагаем.
    expect(find.text('Брак или дефект'), findsOneWidget);
    expect(find.text('Не подошёл размер'), findsNothing);

    await tester.enterText(find.byType(TextField), 'Разошёлся шов');
    await tester.tap(find.text('Оформить заявку'));
    await tester.pumpAndSettle();

    expect(find.text('Приложите фото брака'), findsOneWidget);
    expect(server.posts, isEmpty);
  });

  testWidgets('заявка: трек-номер и выбор, как забрать вещи после отказа',
      (tester) async {
    final server = _Server(_base(), [
      {
        'id': 7,
        'number': 'A1-В1',
        'status': 'partial',
        'statusLabel': 'Принята частично',
        'method': 'parcel',
        'lines': [
          {'name': 'Майка', 'reasonLabel': 'Не подошёл размер',
           'rejectReasonLabels': ['Есть следы носки или эксплуатации']},
        ],
        'bringUntil': '2026-11-20T00:00:00Z',
        'trackNumber': '',
        'canCancel': false,
        'needsTrack': false,
        'decisionNote': '',
        'goodsBack': '',
        'goodsBackDone': false,
        'needsGoodsBack': true,
        'refundRub': 1500.0,
        'inspectionPhotos': <Object>[],
      },
    ]);
    await _pump(tester, server);

    expect(find.text('Заявка A1-В1'), findsOneWidget);
    expect(find.text('Отказ: Есть следы носки или эксплуатации'), findsOneWidget);
    await tester.tap(find.text('Заберу в магазине'));
    await tester.pumpAndSettle();

    expect(server.posts['/v1/return-requests/7/goods-back'], {'way': 'pickup'});
  });
}
