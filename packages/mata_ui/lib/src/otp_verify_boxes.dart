import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Цвета ячеек OTP V5 под тему приложения (D-126).
///
/// Хореография (тайминги, кривые, геометрия) общая и в стиль НЕ выносится —
/// это стандарт экосистемы. Различаются только цвета и одна деталь поведения
/// ([cursorRequiresFocus]). Готовые стили — в приложениях: Store
/// (`storeOtpBoxesStyle`) и Квартал (`kvartalOtpBoxesStyle()`).
class OtpBoxesStyle {
  /// Рамка текущей ячейки и мигающий курсор.
  final Color accent;

  /// Тень текущей ячейки (цвет уже с прозрачностью) и её размытие.
  final Color currentShadow;
  final double currentShadowBlur;

  /// Рамка заполненной ячейки.
  final Color filledBorder;

  /// Рамка пустой ячейки.
  final Color emptyBorder;

  /// Фон ячейки.
  final Color cellBackground;

  /// Цвет цифр.
  final Color digit;

  /// Рамка и цифры при ошибке.
  final Color error;

  /// Рамка, галочка и кольца успеха.
  final Color success;

  /// Фон и тень (цвет уже с прозрачностью) финальной ячейки с галочкой.
  final Color verifiedBackground;
  final Color verifiedShadow;

  /// Цвет искр финала.
  final Color spark;

  /// true — курсор/подсветка текущей ячейки только когда скрытое поле в
  /// фокусе (Store); false — всегда, пока не идёт проверка (Квартал).
  final bool cursorRequiresFocus;

  const OtpBoxesStyle({
    required this.accent,
    required this.currentShadow,
    required this.currentShadowBlur,
    required this.filledBorder,
    required this.emptyBorder,
    required this.cellBackground,
    required this.digit,
    required this.error,
    required this.success,
    required this.verifiedBackground,
    required this.verifiedShadow,
    required this.spark,
    this.cursorRequiresFocus = false,
  });
}

/// Ввод кода подтверждения с хореографией «OTP V5» (стандарт экосистемы МАТА
/// для всех верификаций кодом, директива владельца 2026-08-18).
///
/// Фазы одной величины прогресса prog 0..3:
///   0..1  строка ячеек разлетается в окружность (380 мс, easeOutCubic)
///   1..2  связка вращается 2 оборота ЖЁСТКО — цифры крутятся вместе с
///         ячейками (1250 мс, easeInOutCubic); если сервер ещё не ответил,
///         связка докручивает дополнительные обороты (вращение = «загрузка»)
///   2..3  схлопывание в центр с доворотом 40° (420 мс, easeInBack)
/// Успех: рамка зеленеет, два кольца-ripple, 6 искр, галочка прорисовывается.
/// Ошибка: связка возвращается в строку + горизонтальный shake.
///
/// Движение считается в AnimatedBuilder от контроллеров — без setState на кадр.
/// При MediaQuery.disableAnimations состояния меняются мгновенно, без движения.
class OtpVerifyBoxes extends StatefulWidget {
  /// Количество цифр кода (dev-бэкенд — 4; при включении SMSC станет 6).
  final int length;

  /// Фокус на скрытое поле сразу при показе (клавиатура открывается сама).
  final bool autofocus;

  /// Цвета под тему приложения.
  final OtpBoxesStyle style;

  /// Проверка кода на сервере. Виджет играет разлёт+вращение, пока Future не
  /// завершится; true — успех (схлопывание+галочка), false — ошибка (возврат).
  final Future<bool> Function(String code) onSubmit;

  /// Вызывается после завершения анимации успеха — здесь навигация.
  final VoidCallback onSuccess;

  /// Вызывается после возврата из анимации ошибки (показать текст, refocus
  /// делает сам виджет).
  final VoidCallback? onFailed;

  /// Подсветить ячейки красным (ошибка показывается родителем).
  final bool hasError;

  const OtpVerifyBoxes({
    super.key,
    this.length = 4,
    this.autofocus = false,
    required this.style,
    required this.onSubmit,
    required this.onSuccess,
    this.onFailed,
    this.hasError = false,
  });

  @override
  State<OtpVerifyBoxes> createState() => OtpVerifyBoxesState();
}

class OtpVerifyBoxesState extends State<OtpVerifyBoxes>
    with TickerProviderStateMixin {
  static const double _cellW = 60;
  static const double _cellH = 72;
  static const double _gap = 76; // шаг ячеек в строке (60 + 2×8)
  static const double _radius = 62; // радиус орбиты
  static const int _turns = 2; // оборотов за основную фазу вращения

  final _text = TextEditingController();
  final _focus = FocusNode();

  /// prog 0..3 — вся хореография.
  late final AnimationController _phase = AnimationController(
    vsync: this,
    upperBound: 3,
  );

  /// Дополнительные обороты, пока ждём сервер (1 цикл = 1 оборот).
  late final AnimationController _extra = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 800),
  );
  int _extraTurns = 0;

  /// Финал успеха: кольца + искры (0..1) и галочка (0..1).
  late final AnimationController _ring = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1300),
  );
  late final AnimationController _check = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 450),
  );

  /// Shake при ошибке (0..1).
  late final AnimationController _shake = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 320),
  );

  bool _busy = false; // идёт проверка/анимация — ввод заблокирован
  bool _verified = false; // финал успеха показан

  bool get _reduceMotion => MediaQuery.of(context).disableAnimations;

  @override
  void initState() {
    super.initState();
    _extra.addStatusListener((status) {
      if (status == AnimationStatus.completed) {
        _extraTurns++;
        _extra.value = 0;
      }
    });
    _text.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _text.dispose();
    _focus.dispose();
    _phase.dispose();
    _extra.dispose();
    _ring.dispose();
    _check.dispose();
    _shake.dispose();
    super.dispose();
  }

  Future<void> _onChanged(String v) async {
    if (_busy) return;
    if (v.length == widget.length) {
      await _run(v);
    }
  }

  Future<void> _run(String code) async {
    setState(() => _busy = true);
    _focus.unfocus();

    final verifyFuture = widget.onSubmit(code);

    if (_reduceMotion) {
      // Без движения: дождаться результата и мгновенно показать состояние.
      final ok = await verifyFuture;
      if (!mounted) return;
      if (ok) {
        setState(() => _verified = true);
        _phase.value = 3;
        _ring.value = 1;
        _check.value = 1;
        await Future.delayed(const Duration(milliseconds: 900));
        if (mounted) widget.onSuccess();
      } else {
        _resetAfterError();
      }
      return;
    }

    // Пауза 260 мс после последней цифры → разлёт → вращение (2 оборота).
    await Future.delayed(const Duration(milliseconds: 260));
    if (!mounted) return;
    await _phase.animateTo(
      1,
      duration: const Duration(milliseconds: 380),
      curve: Curves.easeOutCubic,
    );
    if (!mounted) return;
    await _phase.animateTo(
      2,
      duration: const Duration(milliseconds: 1250),
      curve: Curves.easeInOutCubic,
    );
    if (!mounted) return;

    // Сервер ещё думает — докручиваем по обороту (вращение = индикатор).
    bool? result;
    unawaited(
      verifyFuture.then((v) => result = v).catchError((_) => result = false),
    );
    while (result == null && mounted) {
      await _extra.animateTo(1, curve: Curves.easeInOutCubic);
      if (!mounted) return;
    }
    if (!mounted) return;
    final ok = result ?? false;

    if (ok) {
      await _phase.animateTo(
        3,
        duration: const Duration(milliseconds: 420),
        curve: Curves.easeInBack,
      );
      if (!mounted) return;
      setState(() => _verified = true);
      _check.forward();
      await _ring.forward();
      if (!mounted) return;
      await Future.delayed(const Duration(milliseconds: 500));
      if (mounted) widget.onSuccess();
    } else {
      // Возврат в строку + shake.
      await _phase.animateBack(
        0,
        duration: const Duration(milliseconds: 420),
        curve: Curves.easeInOutCubic,
      );
      if (!mounted) return;
      _resetAfterError();
      _shake.forward(from: 0);
    }
  }

  void _resetAfterError() {
    _extraTurns = 0;
    _extra.value = 0;
    _phase.value = 0;
    _ring.value = 0;
    _check.value = 0;
    setState(() {
      _busy = false;
      _verified = false;
      _text.clear();
    });
    widget.onFailed?.call();
    _focus.requestFocus();
  }

  /// Угол связки в градусах из prog + доп. оборотов.
  double _spinDeg(double prog) {
    double spin;
    if (prog <= 1) {
      spin = 0;
    } else if (prog <= 2) {
      spin = (prog - 1) * 360.0 * _turns;
    } else {
      spin = 360.0 * _turns + (prog - 2) * 40.0;
    }
    return spin + (_extraTurns + _extra.value) * 360.0;
  }

  @override
  Widget build(BuildContext context) {
    final n = widget.length;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () {
        if (!_busy) _focus.requestFocus();
      },
      child: SizedBox(
        height: 220,
        width: double.infinity,
        child: Stack(
          alignment: Alignment.center,
          clipBehavior: Clip.none,
          children: [
            // Скрытый input — источник значения.
            SizedBox(
              width: 0,
              height: 0,
              child: TextField(
                controller: _text,
                focusNode: _focus,
                keyboardType: TextInputType.number,
                autofillHints: const [AutofillHints.oneTimeCode],
                inputFormatters: [
                  FilteringTextInputFormatter.digitsOnly,
                  LengthLimitingTextInputFormatter(n),
                ],
                autofocus: widget.autofocus,
                enabled: !_busy,
                onChanged: _onChanged,
              ),
            ),
            // Кольца + искры финала.
            AnimatedBuilder(
              animation: _ring,
              builder: (context, _) => _verified
                  ? CustomPaint(
                      size: const Size(220, 220),
                      painter: _RipplePainter(
                        progress: _ring.value,
                        color: widget.style.success,
                        sparkColor: widget.style.spark,
                      ),
                    )
                  : const SizedBox.shrink(),
            ),
            // Ячейки: позиции считаются от контроллеров, без setState на кадр.
            AnimatedBuilder(
              animation: Listenable.merge([_phase, _extra, _shake]),
              builder: (context, _) {
                final prog = _phase.value;
                final p = prog.clamp(0.0, 1.0);
                final shrink = (prog - 2).clamp(0.0, 1.0);
                final spin = _spinDeg(prog);
                final shakeX = _shake.isAnimating || _shake.value > 0
                    ? math.sin(_shake.value * math.pi * 3) *
                          6 *
                          (1 - _shake.value)
                    : 0.0;

                return Stack(
                  alignment: Alignment.center,
                  clipBehavior: Clip.none,
                  children: List.generate(n, (i) {
                    // Финал: как на сайте — первая ячейка СТРОГО РОВНО по
                    // центру (translate(0,0) scale(.92), без доворота +40°,
                    // иначе галочка стоит криво), остальные скрыты.
                    if (_verified) {
                      if (i != 0) return const SizedBox.shrink();
                      return Transform.scale(scale: 0.92, child: _cell(0));
                    }
                    final rowX = (i - (n - 1) / 2) * _gap;
                    final a = (-90 + i * (360 / n) + spin) * math.pi / 180;
                    final orbX = math.cos(a) * _radius;
                    final orbY = math.sin(a) * _radius;

                    final x = (rowX + (orbX - rowX) * p) * (1 - shrink);
                    final y = orbY * p * (1 - shrink);
                    final rotRad = spin * p * math.pi / 180;
                    final sc = 1 - shrink * 0.12;
                    final fade = shrink > 0.75 && i != 0
                        ? 1 - (shrink - 0.75) / 0.25
                        : 1.0;

                    // Порядок: translate → rotate → scale (иначе траектория
                    // поедет — см. спеку OTP V5).
                    final m = Matrix4.identity()
                      ..translate(x + shakeX, y)
                      ..rotateZ(rotRad)
                      ..scale(sc);

                    return Transform(
                      transform: m,
                      alignment: Alignment.center,
                      child: Opacity(
                        opacity: fade.clamp(0.0, 1.0),
                        child: _cell(i),
                      ),
                    );
                  }),
                );
              },
            ),
          ],
        ),
      ),
    );
  }

  Widget _cell(int i) {
    final st = widget.style;
    final value = i < _text.text.length ? _text.text[i] : null;
    final isCurrent =
        !_busy &&
        (!st.cursorRequiresFocus || _focus.hasFocus) &&
        i == _text.text.length;
    final showCheck = _verified && i == 0;

    final Color border;
    double width = 1;
    if (showCheck) {
      border = st.success;
      width = 2;
    } else if (widget.hasError) {
      border = st.error;
      width = 2;
    } else if (isCurrent) {
      border = st.accent;
      width = 2;
    } else if (value != null) {
      border = st.filledBorder;
      width = 2;
    } else {
      border = st.emptyBorder;
    }

    return Container(
      width: _cellW,
      height: _cellH,
      decoration: BoxDecoration(
        color: showCheck ? st.verifiedBackground : st.cellBackground,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: border, width: width),
        boxShadow: showCheck
            ? [
                BoxShadow(
                  color: st.verifiedShadow,
                  blurRadius: 24,
                ),
              ]
            : isCurrent
            ? [
                BoxShadow(
                  color: st.currentShadow,
                  blurRadius: st.currentShadowBlur,
                ),
              ]
            : null,
      ),
      alignment: Alignment.center,
      child: showCheck
          ? AnimatedBuilder(
              animation: _check,
              builder: (context, _) => CustomPaint(
                size: const Size(30, 30),
                painter: _CheckPainter(
                  progress: Curves.easeInOut.transform(_check.value),
                  color: st.success,
                ),
              ),
            )
          : value != null
          ? Text(
              value,
              style: TextStyle(
                fontSize: 30,
                fontWeight: FontWeight.w800,
                color: widget.hasError ? st.error : st.digit,
              ),
            )
          : isCurrent
          ? Container(width: 2, height: 28, color: st.accent)
          : null,
    );
  }
}

/// Два расходящихся кольца (сдвиг второго 220 мс) + 6 искр.
class _RipplePainter extends CustomPainter {
  final double progress; // 0..1
  final Color color;
  final Color sparkColor;

  _RipplePainter({
    required this.progress,
    required this.color,
    required this.sparkColor,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    final stroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5;

    void ringAt(double t) {
      if (t <= 0 || t >= 1) return;
      final eased = Curves.easeOutCubic.transform(t);
      final r = 40 + eased * 95; // scale .55 → 3.4 от базовых 80px
      stroke.color = color.withValues(alpha: 0.9 * (1 - eased));
      canvas.drawCircle(center, r, stroke);
    }

    ringAt(progress);
    ringAt((progress - 0.17).clamp(0.0, 1.0) / 0.83); // второе кольцо, сдвиг

    // Искры: 6 точек, разлёт 20 → 92 px со ступенчатой задержкой.
    final dot = Paint()..style = PaintingStyle.fill;
    for (var i = 0; i < 6; i++) {
      final delay = i * 0.06;
      final t = ((progress - delay) / 0.7).clamp(0.0, 1.0);
      if (t <= 0 || t >= 1) continue;
      final eased = Curves.easeOut.transform(t);
      final angle = (i * 60 + 20) * math.pi / 180;
      final dist = 20 + eased * 72;
      final alpha = t < 0.35 ? t / 0.35 : 1 - (t - 0.35) / 0.65;
      dot.color = sparkColor.withValues(alpha: alpha);
      canvas.drawCircle(
        center + Offset(math.cos(angle), math.sin(angle)) * dist,
        2 * (1 - eased * 0.6),
        dot,
      );
    }
  }

  @override
  bool shouldRepaint(_RipplePainter old) =>
      old.progress != progress || old.color != color;
}

/// Галочка, прорисовывающаяся как stroke-dashoffset 30 → 0.
class _CheckPainter extends CustomPainter {
  final double progress; // 0..1
  final Color color;

  _CheckPainter({required this.progress, required this.color});

  @override
  void paint(Canvas canvas, Size size) {
    if (progress <= 0) return;
    final path = Path()
      ..moveTo(size.width * 0.20, size.height * 0.52)
      ..lineTo(size.width * 0.42, size.height * 0.72)
      ..lineTo(size.width * 0.80, size.height * 0.30);
    final metric = path.computeMetrics().first;
    final partial = metric.extractPath(0, metric.length * progress);
    canvas.drawPath(
      partial,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.8
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round
        ..color = color,
    );
  }

  @override
  bool shouldRepaint(_CheckPainter old) =>
      old.progress != progress || old.color != color;
}
