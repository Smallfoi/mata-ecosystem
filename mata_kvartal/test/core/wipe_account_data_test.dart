import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:kvartal_app/core/storage/account_scope.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// D-104: удалённый аккаунт не оставляет на телефоне ни треков, ни очередей.
/// Чужой аккаунт на том же телефоне при этом не теряет ничего.
void main() {
  test('стирает историю, идущий забег и свои элементы очередей, чужие оставляет',
      () async {
    SharedPreferences.setMockInitialValues({
      'kvartal.completed_runs.v2.uA': '[{"id":"r1","route":[[62.0,129.7]]}]',
      'kvartal.completed_runs.v2.uB': '[{"id":"r2","route":[[62.1,129.8]]}]',
      'kvartal.active_run.v1': '{"points":[[62.0,129.7]]}',
      'kvartal.loyalty.pending.v1': jsonEncode([
        {'amount': 10, ownerField: 'uA'},
        {'amount': 20, ownerField: 'uB'},
      ]),
      'kvartal.capture_queue.v1': [
        jsonEncode({'points': [[62.0, 129.7]], ownerField: 'uA'}),
        jsonEncode({'points': [[62.1, 129.8]], ownerField: 'uB'}),
      ],
    });
    final prefs = await SharedPreferences.getInstance();

    await wipeAccountData(prefs, 'uA',
        completedRunsKey: 'kvartal.completed_runs.v2.uA',
        activeRunKey: 'kvartal.active_run.v1');

    expect(prefs.getString('kvartal.completed_runs.v2.uA'), isNull);
    expect(prefs.getString('kvartal.active_run.v1'), isNull);
    expect(prefs.getString('kvartal.completed_runs.v2.uB'), isNotNull);
    final loyalty = jsonDecode(prefs.getString('kvartal.loyalty.pending.v1')!) as List;
    expect(loyalty.map((m) => m[ownerField]), ['uB']);
    final captures = prefs.getStringList('kvartal.capture_queue.v1')!;
    expect(captures.length, 1);
    expect(captures.single, contains('uB'));
  });

  test('без id аккаунта ничего не трогает', () async {
    SharedPreferences.setMockInitialValues({
      'kvartal.active_run.v1': '{}',
      'kvartal.capture_queue.v1': [jsonEncode({ownerField: unknownOwner})],
    });
    final prefs = await SharedPreferences.getInstance();
    await wipeAccountData(prefs, '',
        completedRunsKey: 'x', activeRunKey: 'kvartal.active_run.v1');
    expect(prefs.getString('kvartal.active_run.v1'), '{}');
    expect(prefs.getStringList('kvartal.capture_queue.v1')!.length, 1);
  });
}
