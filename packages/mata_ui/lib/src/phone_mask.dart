import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

// Маска телефона РФ: несъёмный «+7», пользователь вводит 10 цифр. Образец
// «912 345-67-89» ВИДЕН СРАЗУ и остаётся до последней цифры: введённые цифры —
// обычным цветом, незаполненный «хвост» образца — прозрачным (тот же шрифт/размер).
// Общий модуль для экрана входа/регистрации. Ведущие «7»/«8» отбрасываются.
const String _tpl = '### ###-##-##'; // # — слот цифры
const String _ex = '9123456789'; // пример-образец → «912 345-67-89»

/// «Сырые» цифры (до 10) → сгруппированный ввод, например «912 345».
String formatPhoneTyped(String digits) {
  final b = StringBuffer();
  var di = 0;
  for (var i = 0; i < _tpl.length && di < digits.length; i++) {
    final ch = _tpl[i];
    if (ch == '#') {
      b.write(digits[di++]);
    } else {
      b.write(ch);
    }
  }
  return b.toString();
}

/// Прозрачный «хвост» образца для незаполненных позиций (цифры примера + разделители).
String phoneExampleTail(String digits) {
  final b = StringBuffer();
  var di = 0;
  for (var i = 0; i < _tpl.length; i++) {
    final ch = _tpl[i];
    if (ch == '#') {
      if (di >= digits.length) b.write(_ex[di]);
      di++;
    } else {
      if (di >= digits.length) b.write(ch);
    }
  }
  return b.toString();
}

/// Отбрасывает ведущие «7»/«8», ограничивает 10 цифрами, группирует ввод.
class PhoneMaskFormatter extends TextInputFormatter {
  const PhoneMaskFormatter();

  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    var digits = newValue.text.replaceAll(RegExp(r'\D'), '');
    if (digits.startsWith('7') || digits.startsWith('8')) {
      digits = digits.substring(1);
    }
    if (digits.length > 10) digits = digits.substring(0, 10);
    final t = formatPhoneTyped(digits);
    return TextEditingValue(
      text: t,
      selection: TextSelection.collapsed(offset: t.length),
    );
  }
}

/// Контроллер: дорисовывает прозрачный хвост-образец ПОСЛЕ введённого текста
/// (ghost-text через buildTextSpan). Введённое — style поля, образец — hintColor.
/// Хвост идёт за позицией курсора, поэтому не мешает вводу/каретке.
class PhoneMaskController extends TextEditingController {
  PhoneMaskController({required this.hintColor});
  final Color hintColor;

  @override
  TextSpan buildTextSpan({
    required BuildContext context,
    TextStyle? style,
    required bool withComposing,
  }) {
    final digits = text.replaceAll(RegExp(r'\D'), '');
    final tail = phoneExampleTail(digits);
    return TextSpan(
      style: style,
      children: [
        TextSpan(text: text),
        if (tail.isNotEmpty)
          TextSpan(
            text: tail,
            style: (style ?? const TextStyle()).copyWith(color: hintColor),
          ),
      ],
    );
  }
}
