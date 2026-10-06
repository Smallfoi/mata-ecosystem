// Бонусы программы лояльности v1 за пробежку (ТЗ 30.09.2026, §3, §6).
//
// После пробежки показываем «+10 бонусов» и остаток месячного лимита; при
// исчерпанном лимите — «лимит исчерпан, обновится 1 числа». Поля приходят в
// ответе POST /v1/runs (этап 2 сервера). Пока сервер их не шлёт (прежняя
// программа или старый бэкенд) — [RunBonusInfo.fromRunResponse] даёт null, и
// экран показывает прежние «+N баллов МАТА».
import '../../loyalty/data/loyalty_v1.dart' show bonusWord;

int? _num(Object? v) => v is num ? v.toInt() : null;

Object? _first(Map m, List<String> keys) {
  for (final k in keys) {
    if (m.containsKey(k) && m[k] != null) return m[k];
  }
  return null;
}

class RunBonusInfo {
  final String runId;

  /// Сколько бонусов начислено за пробежку (0 — не начислено).
  final int? awarded;

  /// Сколько бонусов ещё можно получить за активность в этом месяце.
  final int? monthLeft;

  /// Месячный лимит исчерпан: пробежка засчитана, бонусов нет.
  final bool capped;

  /// Текст сервера для человека (причина/пояснение).
  final String text;

  const RunBonusInfo({
    required this.runId,
    this.awarded,
    this.monthLeft,
    this.capped = false,
    this.text = '',
  });

  static const defaultCapText =
      'Лимит бонусов за месяц исчерпан — обновится 1 числа';

  /// Разбор ответа POST /runs. Понимает и вложенный объект (`loyalty` /
  /// `bonus`), и плоские поля. null — бонусных полей v1 в ответе нет.
  static RunBonusInfo? fromRunResponse(String runId, Object? body) {
    if (body is! Map) return null;
    final nested = [body['loyalty'], body['bonus'], body['bonuses']]
        .whereType<Map>()
        .firstOrNull;
    final src = nested ?? body;
    final awarded = _num(_first(src, nested != null
        ? const ['awarded', 'amount', 'bonusAwarded', 'bonus']
        : const ['bonusAwarded', 'bonusesAwarded', 'bonus', 'bonuses']));
    final monthLeft = _num(_first(src, nested != null
        ? const ['monthLeft', 'monthRemaining', 'capLeft', 'remaining',
            'monthCapLeft']
        : const ['bonusMonthLeft', 'monthCapLeft', 'monthLimitLeft',
            'bonusCapLeft', 'monthLeft']));
    final cappedRaw = _first(src, nested != null
        ? const ['capped', 'capReached', 'monthCapReached', 'limitReached']
        : const ['bonusCapped', 'monthCapReached', 'bonusCapReached',
            'monthLimitReached']);
    final text = _first(src, nested != null
        ? const ['text', 'message', 'reason', 'capReason']
        : const ['bonusText', 'bonusMessage', 'monthCapText']);
    if (awarded == null && monthLeft == null && cappedRaw == null) return null;
    return RunBonusInfo(
      runId: runId,
      awarded: awarded,
      monthLeft: monthLeft,
      capped: cappedRaw == true,
      text: text?.toString() ?? '',
    );
  }

  /// «+10 бонусов». null — начисления нет (лимит или пробежка не прошла).
  String? get headline {
    final a = awarded;
    if (a == null || a <= 0) return null;
    return '+$a ${bonusWord(a)}';
  }

  /// Вторая строка: лимит исчерпан / остаток лимита месяца / текст сервера.
  String? get limitLine {
    if (capped) return text.isNotEmpty ? text : defaultCapText;
    final left = monthLeft;
    if (left != null) {
      return left > 0
          ? 'ещё $left ${bonusWord(left)} в лимите этого месяца'
          : defaultCapText;
    }
    return text.isNotEmpty ? text : null;
  }
}
