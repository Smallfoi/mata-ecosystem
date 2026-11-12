import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:qr_flutter/qr_flutter.dart';

import 'brand.dart';
import 'mata_logo.dart';

// Карта не зависит от темы приложения: материалы уровней одинаковы во всей
// экосистеме, лайм — фирменный (MataBrand.lime, D-34).

/// Виртуальная карта лояльности МАТА с 3D-переворотом (эталон владельца
/// «Payment Card Flip») и материалами уровней из дизайн-проекта
/// `brand/loyalty-card-design` v5 (утверждён 2026-08-21).
///
/// Лестница статуса: графит → серебряный сатин → золото → чёрный титан.
/// Каждая карта «живёт» по-своему (анимации не повторяются):
/// базовая — «уголёк» (Т разгорается лаймом), серебро — «лунный блик»,
/// золото — «расплав» (градиент течёт + тёплая волна), платина — аврора
/// под титаном, «сердцебиение» знака и комета по кромке.
/// Тап по QR на обороте — белый полноэкранный QR для кассы.
enum LoyaltyCardTier { basic, silver, gold, platinum }

class LoyaltyCard3D extends StatefulWidget {
  final int balance;
  final String levelLabel;
  final String holderName;
  final String qrData;
  final LoyaltyCardTier tier;

  const LoyaltyCard3D({
    super.key,
    required this.balance,
    required this.levelLabel,
    required this.holderName,
    required this.qrData,
    this.tier = LoyaltyCardTier.basic,
  });

  @override
  State<LoyaltyCard3D> createState() => _LoyaltyCard3DState();
}

class _LoyaltyCard3DState extends State<LoyaltyCard3D>
    with TickerProviderStateMixin {
  // Кривая эталона: перелёт за конечную точку и упругая докрутка.
  static const _flipCurve = Cubic(0.34, 1.4, 0.5, 1.0);

  late final AnimationController _ctrl = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 750),
  );

  // Часы «жизни» карты: один тикер на все идл-циклы (t = value·3600 c).
  late final AnimationController _clock = AnimationController(
    vsync: this,
    duration: const Duration(minutes: 60),
  );
  bool _liveOn = false;
  bool _showingBack = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final off = MediaQuery.of(context).disableAnimations;
    if (!off && !_liveOn) {
      _clock.repeat();
      _liveOn = true;
    } else if (off && _liveOn) {
      _clock.stop();
      _liveOn = false;
    }
  }

  void _flip() {
    if (MediaQuery.of(context).disableAnimations) {
      // Reduced motion: мгновенная смена грани без вращения.
      setState(() {
        _showingBack = !_showingBack;
        _ctrl.value = _showingBack ? 1 : 0;
      });
      return;
    }
    if (_showingBack) {
      _ctrl.reverse();
    } else {
      _ctrl.forward();
    }
    _showingBack = !_showingBack;
  }

  @override
  void dispose() {
    _ctrl.dispose();
    _clock.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final width = math.min(MediaQuery.of(context).size.width - 40, 360.0);
    final height = width / 1.586; // ISO ID-1 — пропорция реальной карты
    final st = _TierStyle.of(widget.tier);

    return Semantics(
      button: true,
      label: _showingBack
          ? 'Карта лояльности, QR-код. Нажми, чтобы вернуть баллы'
          : 'Карта лояльности, ${widget.balance} баллов. Нажми — QR для кассы',
      child: GestureDetector(
        onTap: _flip,
        child: AnimatedBuilder(
          animation: Listenable.merge([_ctrl, _clock]),
          builder: (context, _) {
            final t = _flipCurve.transform(_ctrl.value);
            final angle = t * math.pi;
            final showBack = angle > math.pi / 2;
            final live = _Live(_liveOn, _clock.value * 3600);
            // Свечение — пик в середине переворота (эталон: пульс при действии).
            final glow = 0.35 + 0.45 * math.sin(math.pi * _ctrl.value);

            return Container(
              width: width,
              height: height,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(18),
                boxShadow: [
                  BoxShadow(
                    color: st.glow.withValues(alpha: glow * 0.5),
                    blurRadius: 34,
                    spreadRadius: 1,
                  ),
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.45),
                    blurRadius: 24,
                    offset: const Offset(0, 14),
                  ),
                ],
              ),
              child: Transform(
                alignment: Alignment.center,
                // Перспектива обязана быть в той же матрице (родителя у нас нет).
                transform: Matrix4.identity()
                  ..setEntry(3, 2, 0.0014)
                  ..rotateY(angle),
                child: showBack
                    // Оборот рисуем дозеркаленным, чтобы после rotateY(π)
                    // он читался слева направо.
                    ? Transform(
                        alignment: Alignment.center,
                        transform: Matrix4.identity()..rotateY(math.pi),
                        child: _CardBack(
                          qrData: widget.qrData,
                          holderName: widget.holderName,
                          st: st,
                          tier: widget.tier,
                        ),
                      )
                    : _CardFace(
                        balance: widget.balance,
                        levelLabel: widget.levelLabel,
                        holderName: widget.holderName,
                        st: st,
                        tier: widget.tier,
                        live: live,
                      ),
              ),
            );
          },
        ),
      ),
    );
  }
}

// ─── «Жизнь» карты: фазовые функции идл-циклов (тайминги = дизайн v5) ────────

class _Live {
  final bool on;
  final double t; // секунды с запуска часов
  const _Live(this.on, this.t);

  double _phase(double period, [double delay = 0]) {
    final p = ((t - delay) % period + period) % period;
    return p / period;
  }

  /// «Уголёк» базовой: Т разгорается на 76–86% цикла 4.6 с.
  double get ember {
    if (!on) return 0;
    final p = _phase(4.6);
    if (p < .62) return 0;
    if (p < .76) return Curves.easeInOut.transform((p - .62) / .14);
    if (p < .86) return 1;
    return 1 - Curves.easeInOut.transform((p - .86) / .14);
  }

  /// Волна блика: null — за кадром, иначе смещение -1.4…1.4 ширины.
  double? sweep(double period, double a, double b) {
    if (!on) return null;
    final p = _phase(period);
    if (p < a || p > b) return null;
    return -1.4 + 2.8 * Curves.easeInOut.transform((p - a) / (b - a));
  }

  /// «Дыхание» тиснёного знака: opacity 0.5…1.
  double breath(double period) {
    if (!on) return 1;
    final p = _phase(period);
    if (p < .45) return .5 + .5 * Curves.easeInOut.transform(p / .45);
    if (p < .60) return 1;
    return 1 - .5 * Curves.easeInOut.transform((p - .60) / .40);
  }

  /// «Расплав» золота: положение градиента 0…1 (туда-обратно за 24 с).
  double get goldFlow {
    if (!on) return 0;
    final p = _phase(24);
    return Curves.easeInOut.transform(p < .5 ? p * 2 : 2 - p * 2);
  }

  /// «Сердцебиение» знака платины: свечение луча [i] (задержки 0/.35/.7 с).
  double ray(int i) {
    if (!on) return 0;
    final p = _phase(5.2, i * 0.35);
    if (p < .08) return .75 * (p / .08);
    if (p < .30) return .75;
    if (p < .42) return .75 * (1 - (p - .30) / .12);
    return 0;
  }

  /// Комета по кромке платины: позиция головы 0…1.
  double get comet => _phase(5.2);
}

// ─── Материалы уровней (цвета 1:1 из дизайн-проекта v5) ──────────────────────

const _platMetal = LinearGradient(
  begin: Alignment.topCenter,
  end: Alignment.bottomCenter,
  colors: [
    Color(0xFFF6FAFE),
    Color(0xFFC9D5E2),
    Color(0xFF93A2B3),
    Color(0xFFDCE6F0),
    Color(0xFFAEBCCB),
  ],
  stops: [0, .45, .55, .7, 1],
);

class _TierStyle {
  final List<Color> base;
  final List<double> baseStops;
  final Color highlight; // радиальный блик слева сверху
  final Color innerShade; // внутренняя тень снизу
  final Color border;
  final Color ink;
  final Color pillText;
  final Color pillBorder;
  final Color sheen;
  final Color glow; // внешнее свечение карты
  final List<Color> stripe;
  final Color backCap;
  final bool metal; // платина: словомарка-металл, аврора, комета
  final bool flowing; // золото: градиент «течёт»

  const _TierStyle({
    required this.base,
    required this.baseStops,
    required this.highlight,
    required this.innerShade,
    required this.border,
    required this.ink,
    required this.pillText,
    required this.pillBorder,
    required this.sheen,
    required this.glow,
    required this.stripe,
    required this.backCap,
    this.metal = false,
    this.flowing = false,
  });

  static _TierStyle of(LoyaltyCardTier tier) {
    switch (tier) {
      case LoyaltyCardTier.basic:
        return const _TierStyle(
          base: [Color(0xFF272D34), Color(0xFF1B2026), Color(0xFF12161B)],
          baseStops: [0, .48, 1],
          highlight: Color(0x12FFFFFF),
          innerShade: Color(0x00000000),
          border: Color(0x17FFFFFF),
          ink: Color(0xFFF2F4F6),
          pillText: MataBrand.lime,
          pillBorder: Color(0xB3EEEA83),
          sheen: Color(0x1AFFFFFF),
          glow: MataBrand.lime,
          stripe: [Color(0xFF101317), Color(0xFF101317)],
          backCap: MataBrand.lime,
        );
      case LoyaltyCardTier.silver:
        return const _TierStyle(
          base: [
            Color(0xFFE9EDF2),
            Color(0xFFD4DAE1),
            Color(0xFFC2C9D2),
            Color(0xFFDDE2E9),
            Color(0xFFAFB8C2),
            Color(0xFFCBD2DA),
            Color(0xFFB7BFC9),
          ],
          baseStops: [0, .18, .34, .50, .66, .82, 1],
          highlight: Color(0xA6FFFFFF),
          innerShade: Color(0x47788492),
          border: Color(0xBFFFFFFF),
          ink: Color(0xFF2B323A),
          pillText: Color(0xFF2B323A),
          pillBorder: Color(0x804E5A68),
          sheen: Color(0x66FFFFFF),
          glow: Color(0xFFA0ACBA),
          stripe: [Color(0xFF9AA4B0), Color(0xFF7E8894)],
          backCap: Color(0xFF2B323A),
        );
      case LoyaltyCardTier.gold:
        return const _TierStyle(
          base: [
            Color(0xFFF3DFA0),
            Color(0xFFE5C06E),
            Color(0xFFD3A94F),
            Color(0xFFEDD494),
            Color(0xFFC1943A),
            Color(0xFFE2C177),
            Color(0xFFCBA14A),
          ],
          baseStops: [0, .18, .34, .50, .66, .82, 1],
          highlight: Color(0xB3FFF6D6),
          innerShade: Color(0x598C6820),
          border: Color(0xBFFFF3CD),
          ink: Color(0xFF42300C),
          pillText: Color(0xFF42300C),
          pillBorder: Color(0x8C6E5216),
          sheen: Color(0x80FFF8DC),
          glow: Color(0xFFD8AC4E),
          stripe: [Color(0xFFBE9433), Color(0xFF9C7722)],
          backCap: Color(0xFF42300C),
          flowing: true,
        );
      case LoyaltyCardTier.platinum:
        return const _TierStyle(
          base: [
            Color(0xFF15181D),
            Color(0xFF0B0D11),
            Color(0xFF1B2027),
            Color(0xFF07090C),
            Color(0xFF141820),
          ],
          baseStops: [0, .30, .52, .74, 1],
          highlight: Color(0x52788A9E),
          innerShade: Color(0xB3000000),
          border: Color(0x73CAD6E4),
          ink: Color(0xFFE7ECF3),
          pillText: Color(0xFF10141A),
          pillBorder: Color(0x00000000), // пилюля платины — металл, без рамки
          sheen: Color(0x38D6E4F4),
          glow: Color(0xFF96AAC0),
          stripe: [Color(0xFF0A0C10), Color(0xFF04060A)],
          backCap: Color(0xFFC6D2E0),
          metal: true,
        );
    }
  }
}

// ─── Лицо: словомарка, баллы, уровень, держатель ─────────────────────────────

class _CardFace extends StatelessWidget {
  final int balance;
  final String levelLabel;
  final String holderName;
  final _TierStyle st;
  final LoyaltyCardTier tier;
  final _Live live;

  const _CardFace({
    required this.balance,
    required this.levelLabel,
    required this.holderName,
    required this.st,
    required this.tier,
    required this.live,
  });

  @override
  Widget build(BuildContext context) {
    final faint = st.ink.withValues(alpha: 0.55);
    return _CardChrome(
      st: st,
      tier: tier,
      live: live,
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                MataLogo(
                  width: st.metal ? 84 : 74,
                  color: st.ink,
                  accent: tier == LoyaltyCardTier.basic
                      ? Color.lerp(
                          MataBrand.lime,
                          const Color(0xFFFBF7AE),
                          live.ember,
                        )
                      : st.ink,
                  accentGlow: tier == LoyaltyCardTier.basic ? live.ember : 0,
                  fillGradient: st.metal ? _platMetal : null,
                ),
                const Spacer(),
                _LevelPill(label: levelLabel, st: st),
              ],
            ),
            const Spacer(),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  '$balance',
                  style: TextStyle(
                    fontSize: 40,
                    fontWeight: FontWeight.w700,
                    color: st.ink,
                    height: 1,
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
                const SizedBox(width: 8),
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Text(
                    'баллов',
                    style: TextStyle(fontSize: 14, color: faint),
                  ),
                ),
              ],
            ),
            const Spacer(),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'ДЕРЖАТЕЛЬ',
                        style: TextStyle(
                          fontSize: 8,
                          letterSpacing: 1.6,
                          color: faint,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        holderName.toUpperCase(),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 0.6,
                          color: st.ink,
                        ),
                      ),
                    ],
                  ),
                ),
                Text(
                  'ЕДИНАЯ КАРТА',
                  style: TextStyle(
                    fontSize: 8,
                    letterSpacing: 1.6,
                    color: faint,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _LevelPill extends StatelessWidget {
  final String label;
  final _TierStyle st;
  const _LevelPill({required this.label, required this.st});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: st.metal
          ? BoxDecoration(
              gradient: const LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [Color(0xFFF4F8FC), Color(0xFFB9C6D4)],
              ),
              borderRadius: BorderRadius.circular(99),
              boxShadow: const [
                BoxShadow(
                  color: Color(0x99000000),
                  blurRadius: 3,
                  offset: Offset(0, 1),
                ),
              ],
            )
          : BoxDecoration(
              border: Border.all(color: st.pillBorder, width: 1),
              borderRadius: BorderRadius.circular(99),
            ),
      child: Text(
        label.toUpperCase(),
        style: TextStyle(
          fontSize: 10,
          letterSpacing: 2,
          fontWeight: FontWeight.w600,
          color: st.pillText,
        ),
      ),
    );
  }
}

// ─── Оборот: QR для кассы (тап по QR — во весь экран) ────────────────────────

class _CardBack extends StatelessWidget {
  final String qrData;
  final String holderName;
  final _TierStyle st;
  final LoyaltyCardTier tier;

  const _CardBack({
    required this.qrData,
    required this.holderName,
    required this.st,
    required this.tier,
  });

  @override
  Widget build(BuildContext context) {
    return _CardChrome(
      st: st,
      tier: tier,
      live: const _Live(false, 0),
      back: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: 16),
          Container(
            height: 30,
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: st.stripe,
              ),
            ),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 18),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'ПОКАЖИ НА КАССЕ',
                          style: TextStyle(
                            fontSize: 9,
                            letterSpacing: 1.8,
                            color: st.backCap,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          'Баллы спишутся\nсо счёта $holderName',
                          style: TextStyle(
                            fontSize: 10,
                            height: 1.5,
                            color: st.ink.withValues(alpha: 0.6),
                          ),
                        ),
                      ],
                    ),
                  ),
                  Semantics(
                    button: true,
                    label: 'Открыть QR во весь экран для кассира',
                    child: GestureDetector(
                      onTap: () => Navigator.of(context).push(
                        PageRouteBuilder(
                          transitionDuration: const Duration(milliseconds: 220),
                          reverseTransitionDuration: const Duration(
                            milliseconds: 180,
                          ),
                          pageBuilder: (_, __, ___) =>
                              LoyaltyQrFullscreen(qrData: qrData),
                          transitionsBuilder: (_, a, __, child) =>
                              FadeTransition(opacity: a, child: child),
                        ),
                      ),
                      child: Container(
                        padding: const EdgeInsets.all(6),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: QrImageView(
                          data: qrData,
                          version: QrVersions.auto,
                          size: 96,
                          padding: EdgeInsets.zero,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Белый полноэкранный QR — кассиру удобно сканировать. Тап — закрыть.
class LoyaltyQrFullscreen extends StatelessWidget {
  final String qrData;
  const LoyaltyQrFullscreen({super.key, required this.qrData});

  @override
  Widget build(BuildContext context) {
    final side = math.min(MediaQuery.of(context).size.width * 0.72, 420.0);
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => Navigator.of(context).pop(),
      child: Scaffold(
        backgroundColor: Colors.white,
        body: SafeArea(
          child: Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                QrImageView(
                  data: qrData,
                  version: QrVersions.auto,
                  size: side,
                  padding: EdgeInsets.zero,
                ),
                const SizedBox(height: 22),
                // Код для кассы (совпадает с QR): можно продиктовать, если нет сканера.
                const Text( // staw-static — служебная подпись, не контент
                  'КОД',
                  style: TextStyle(
                    fontSize: 11,
                    letterSpacing: 3,
                    fontWeight: FontWeight.w600,
                    color: Color(0xFF9AA0A8),
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  qrData,
                  style: const TextStyle(
                    fontSize: 30,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 6,
                    color: Color(0xFF20252B),
                    fontFeatures: [FontFeature.tabularFigures()],
                  ),
                ),
                const SizedBox(height: 22),
                const Text(
                  'ПОКАЖИТЕ КАССИРУ',
                  style: TextStyle(
                    fontSize: 13,
                    letterSpacing: 2,
                    fontWeight: FontWeight.w600,
                    color: Color(0xFF3A4048),
                  ),
                ),
                const SizedBox(height: 6),
                const Text(
                  'тап — закрыть',
                  style: TextStyle(fontSize: 11, color: Color(0xFF9AA0A8)),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ─── «Болванка» карты: материал уровня + живые слои ──────────────────────────

class _CardChrome extends StatelessWidget {
  final _TierStyle st;
  final LoyaltyCardTier tier;
  final _Live live;
  final bool back;
  final Widget child;

  const _CardChrome({
    required this.st,
    required this.tier,
    required this.live,
    required this.child,
    this.back = false,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, box) {
        final w = box.maxWidth;
        final h = box.maxHeight;
        final s = w / 340; // масштаб от макета дизайн-проекта (карта 340 px)
        final baseGradient = LinearGradient(
          begin: const Alignment(-1, -0.6),
          end: const Alignment(1, 0.6),
          colors: st.base,
          stops: st.baseStops,
        );

        // Волны блика по тирам (лунный блик / тёплая волна / перелив титана).
        double? sheenX;
        if (!back) {
          switch (tier) {
            case LoyaltyCardTier.basic:
              sheenX = null;
            case LoyaltyCardTier.silver:
              sheenX = live.sweep(9.4, .64, .92);
            case LoyaltyCardTier.gold:
              sheenX = live.sweep(7.6, .58, .86);
            case LoyaltyCardTier.platinum:
              sheenX = live.sweep(6.5, .58, .88);
          }
        }

        return Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: st.border),
          ),
          clipBehavior: Clip.antiAlias,
          child: Stack(
            fit: StackFit.expand,
            children: [
              // Основа: у золота градиент «течёт» (окно по увеличенному полотну).
              if (st.flowing && live.on)
                ClipRect(
                  child: OverflowBox(
                    maxWidth: double.infinity,
                    maxHeight: double.infinity,
                    alignment: Alignment.lerp(
                      Alignment.topLeft,
                      Alignment.bottomRight,
                      live.goldFlow,
                    )!,
                    child: SizedBox(
                      width: w * 2.3,
                      height: h * 2.3,
                      child: DecoratedBox(
                        decoration: BoxDecoration(gradient: baseGradient),
                      ),
                    ),
                  ),
                )
              else
                DecoratedBox(
                  decoration: BoxDecoration(gradient: baseGradient),
                ),
              // Радиальный блик металла слева сверху.
              DecoratedBox(
                decoration: BoxDecoration(
                  gradient: RadialGradient(
                    center: const Alignment(-0.7, -1.1),
                    radius: 1.5,
                    colors: [st.highlight, st.highlight.withValues(alpha: 0)],
                    stops: const [0, .62],
                  ),
                ),
              ),
              // Внутренняя тень снизу — объём сатина.
              if (st.innerShade.a > 0)
                Align(
                  alignment: Alignment.bottomCenter,
                  child: Container(
                    height: h * 0.42,
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [
                          st.innerShade.withValues(alpha: 0),
                          st.innerShade,
                        ],
                      ),
                    ),
                  ),
                ),
              // Аврора холодного света под титаном (только платина).
              if (tier == LoyaltyCardTier.platinum && !back)
                CustomPaint(painter: _AuroraPainter(live.on ? live.t : 0)),
              // Тиснёный знак (серебро — угол, золото/платина — через край).
              if (!back) ..._signLayers(s),
              // Двойная платиновая окантовка.
              if (st.metal)
                Padding(
                  padding: const EdgeInsets.all(2),
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(
                        color: const Color(0x38BAC8D8),
                        width: 1.5,
                      ),
                    ),
                  ),
                ),
              child,
              // Волна блика поверх содержимого.
              if (sheenX != null)
                IgnorePointer(
                  child: FractionalTranslation(
                    translation: Offset(sheenX, 0),
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          begin: const Alignment(-1, -0.5),
                          end: const Alignment(1, 0.5),
                          colors: [
                            st.sheen.withValues(alpha: 0),
                            st.sheen,
                            st.sheen.withValues(alpha: 0),
                          ],
                          stops: const [.34, .48, .60],
                        ),
                      ),
                    ),
                  ),
                ),
              // Платиновая комета обегает кромку.
              if (tier == LoyaltyCardTier.platinum && !back && live.on)
                IgnorePointer(
                  child: CustomPaint(painter: _EdgeCometPainter(live.comet)),
                ),
            ],
          ),
        );
      },
    );
  }

  List<Widget> _signLayers(double s) {
    switch (tier) {
      case LoyaltyCardTier.basic:
        return const [];
      case LoyaltyCardTier.silver:
        return [
          Positioned(
            right: -6 * s,
            bottom: -10 * s,
            child: Opacity(
              opacity: live.breath(7.3),
              child: _Sign(
                width: 120 * s,
                fill: const Color(0xFFB6BFC9),
                embossLight: const Color(0xBFFFFFFF),
                embossDark: const Color(0x80606C7A),
              ),
            ),
          ),
        ];
      case LoyaltyCardTier.gold:
        return [
          Positioned(
            right: -28 * s,
            top: 0,
            bottom: 0,
            child: Center(
              child: Opacity(
                opacity: live.breath(8.1),
                child: _Sign(
                  width: 220 * s,
                  fill: const Color(0xFFC79B3F),
                  embossLight: const Color(0xCCFFF4CD),
                  embossDark: const Color(0x8C7A5A18),
                ),
              ),
            ),
          ),
        ];
      case LoyaltyCardTier.platinum:
        return [
          Positioned(
            right: -46 * s,
            top: 0,
            bottom: 0,
            child: Center(
              child: _Sign(
                width: 300 * s,
                fill: const Color(0x0DE4EEFA),
                embossLight: const Color(0x24D6E4F4),
                embossDark: const Color(0xCC000000),
                rays: [live.ray(0), live.ray(1), live.ray(2)],
              ),
            ),
          ),
        ];
    }
  }
}

// ─── Знак МАТА (три луча) с эмбоссом и «сердцебиением» ───────────────────────

class _Sign extends StatelessWidget {
  final double width;
  final Color fill;
  final Color? embossLight;
  final Color? embossDark;
  final List<double>? rays; // платина: свечение лучей 0..1

  const _Sign({
    required this.width,
    required this.fill,
    this.embossLight,
    this.embossDark,
    this.rays,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: width,
      height: width * 336 / 300,
      child: CustomPaint(
        painter: _SignPainter(
          fill: fill,
          embossLight: embossLight,
          embossDark: embossDark,
          rays: rays,
        ),
      ),
    );
  }
}

class _SignPainter extends CustomPainter {
  final Color fill;
  final Color? embossLight;
  final Color? embossDark;
  final List<double>? rays;

  _SignPainter({
    required this.fill,
    this.embossLight,
    this.embossDark,
    this.rays,
  });

  // Три луча знака «brand/logo/svg/Знак черный4.svg» (координаты 300×336).
  static final List<Path> _rays = [
    Path()
      ..moveTo(12.371, 28.66)
      ..lineTo(88.165, 160.29)
      ..lineTo(109.723, 160.311)
      ..lineTo(72.451, 95.578)
      ..lineTo(23.177, 10.0)
      ..close(),
    Path()
      ..moveTo(279.167, 160.534)
      ..lineTo(127.277, 160.359)
      ..lineTo(116.477, 179.019)
      ..lineTo(191.175, 179.109)
      ..lineTo(289.925, 179.221)
      ..close(),
    Path()
      ..moveTo(31.563, 325.65)
      ..lineTo(107.66, 194.195)
      ..lineTo(96.902, 175.509)
      ..lineTo(59.471, 240.156)
      ..lineTo(10.0, 325.623)
      ..close(),
  ];

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width / 300;
    canvas.scale(s);
    // Эмбосс: светлая грань снизу, тёмная сверху — тиснение в металле.
    if (embossDark != null) {
      final p = Paint()..color = embossDark!;
      canvas.save();
      canvas.translate(0, -1 / s);
      for (final r in _rays) {
        canvas.drawPath(r, p);
      }
      canvas.restore();
    }
    if (embossLight != null) {
      final p = Paint()..color = embossLight!;
      canvas.save();
      canvas.translate(0, 1 / s);
      for (final r in _rays) {
        canvas.drawPath(r, p);
      }
      canvas.restore();
    }
    final fp = Paint()..color = fill;
    for (final r in _rays) {
      canvas.drawPath(r, fp);
    }
    // «Сердцебиение»: лучи по очереди наполняются платиновым светом.
    final g = rays;
    if (g != null) {
      for (var i = 0; i < _rays.length && i < g.length; i++) {
        if (g[i] <= 0) continue;
        canvas.drawPath(
          _rays[i],
          Paint()
            ..color = const Color(0xFFBED6F0).withValues(alpha: .9 * g[i])
            ..maskFilter = MaskFilter.blur(BlurStyle.normal, 8 / s),
        );
        canvas.drawPath(
          _rays[i],
          Paint()
            ..color = Color.lerp(
              const Color(0xFFC9D5E2),
              const Color(0xFFF6FAFE),
              g[i],
            )!.withValues(alpha: g[i]),
        );
      }
    }
  }

  @override
  bool shouldRepaint(_SignPainter old) =>
      old.fill != fill ||
      old.embossLight != embossLight ||
      old.embossDark != embossDark ||
      !_listEq(old.rays, rays);

  static bool _listEq(List<double>? a, List<double>? b) {
    if (identical(a, b)) return true;
    if (a == null || b == null || a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }
}

// ─── Аврора: холодный свет дрейфует под чёрным титаном ───────────────────────

class _AuroraPainter extends CustomPainter {
  final double t;
  _AuroraPainter(this.t);

  // (цвет, центр x/y, радиусы x/y, период, амплитуда дрейфа x/y)
  static const _blobs = [
    (Color(0x48608CBE), .30, .40, .34, .42, 13.0, .16, .10),
    (Color(0x349678CD), .78, .72, .30, .38, 17.0, -.14, -.12),
    (Color(0x2E78BEC8), .55, .50, .24, .30, 21.0, .12, .08),
  ];

  @override
  void paint(Canvas canvas, Size size) {
    for (final (c, cx, cy, rx, ry, period, ax, ay) in _blobs) {
      final ph = math.sin(2 * math.pi * t / period - math.pi / 2) * .5 + .5;
      final scale = 1 + .25 * ph;
      final rect = Rect.fromCenter(
        center: Offset(
          (cx + ax * ph) * size.width,
          (cy + ay * ph) * size.height,
        ),
        width: rx * 2 * size.width * scale,
        height: ry * 2 * size.height * scale,
      );
      canvas.drawOval(
        rect,
        Paint()
          ..shader = RadialGradient(
            colors: [c, c.withValues(alpha: 0)],
          ).createShader(rect)
          ..blendMode = BlendMode.plus,
      );
    }
  }

  @override
  bool shouldRepaint(_AuroraPainter old) => old.t != t;
}

// ─── Платиновая комета по кромке карты ───────────────────────────────────────

class _EdgeCometPainter extends CustomPainter {
  final double f; // позиция головы 0..1 по периметру
  _EdgeCometPainter(this.f);

  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()
      ..addRRect(
        RRect.fromRectAndRadius(
          (Offset.zero & size).deflate(1.6),
          const Radius.circular(16.4),
        ),
      );
    final metrics = path.computeMetrics().toList();
    if (metrics.isEmpty) return;
    final metric = metrics.first;
    final len = metric.length;
    final head = f * len;
    final tail = .16 * len;

    // СПЛОШНОЙ штрих хвоста (раньше рисовали 72 точками-кружками → на телефоне
    // читалось «пунктиром/зубчато»). extractPath даёт непрерывную линию; хвост
    // может пересекать шов пути (голова у начала) — тогда режем на два куска.
    void streak(double from, double to, double w, double alpha, double blur) {
      final p = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = w
        ..strokeCap = StrokeCap.round
        ..color = const Color(0xFFEAF4FF).withValues(alpha: alpha);
      if (blur > 0) p.maskFilter = MaskFilter.blur(BlurStyle.normal, blur);
      var a = from % len, b = to % len;
      if (a < 0) a += len;
      if (b < 0) b += len;
      if (a <= b) {
        canvas.drawPath(metric.extractPath(a, b), p);
      } else {
        canvas.drawPath(metric.extractPath(a, len), p);
        canvas.drawPath(metric.extractPath(0, b), p);
      }
    }

    // Сужающийся световой след: широкая тусклая база → яркое ядро у головы.
    streak(head - tail, head, 3.0, .10, 3);
    streak(head - tail * .6, head, 2.2, .34, 1.4);
    streak(head - tail * .25, head, 1.7, .8, 0);
    final hp = metric.getTangentForOffset(head % len)?.position;
    if (hp != null) {
      canvas.drawCircle(
        hp,
        2.6,
        Paint()
          ..color = const Color(0xCCE8F2FC)
          ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 3),
      );
    }
  }

  @override
  bool shouldRepaint(_EdgeCometPainter old) => old.f != f;
}
