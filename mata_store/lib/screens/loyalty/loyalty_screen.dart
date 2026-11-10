import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:provider/provider.dart';
import '../../models/loyalty.dart';
import '../../providers/auth_provider.dart';
import '../../providers/loyalty_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/loyalty_card.dart';
import '../../widgets/remote_text.dart';

class LoyaltyScreen extends StatelessWidget {
  const LoyaltyScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.white,
      body: Consumer<LoyaltyProvider>(
        builder: (context, loyalty, _) {
          return CustomScrollView(
            slivers: [
              SliverToBoxAdapter(child: _Header(loyalty: loyalty)),
              SliverToBoxAdapter(child: _LevelCard(loyalty: loyalty)),
              SliverToBoxAdapter(child: _EarnHint(v1: loyalty.v1)),
              // v1: бонусы на счёте по лотам — у каждого свой срок сгорания.
              if (loyalty.v1 case final w? when w.lots.isNotEmpty) ...[
                SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(20, 8, 20, 8),
                    child: RemoteText(
                      'app.loyalty.lots',
                      'БОНУСЫ НА СЧЁТЕ',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 1.5,
                        color: AppColors.grey600,
                      ),
                    ),
                  ),
                ),
                SliverList.separated(
                  itemCount: w.lots.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (context, i) => _LotTile(lot: w.lots[i]),
                ),
                const SliverToBoxAdapter(child: SizedBox(height: 12)),
              ],
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 8),
                  child: RemoteText(
                    'app.loyalty.history',
                    'ИСТОРИЯ',
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 1.5,
                      color: AppColors.grey600,
                    ),
                  ),
                ),
              ),
              if (loyalty.transactions.isEmpty)
                const SliverToBoxAdapter(
                  child: Padding(
                    padding: EdgeInsets.all(40),
                    child: Center(
                      child: RemoteText('app.loyalty.emptyOps',
                          'Пока нет операций с баллами',
                          style: TextStyle(color: AppColors.grey600)),
                    ),
                  ),
                )
              else
                SliverList.separated(
                  itemCount: loyalty.transactions.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (context, i) => _TxnTile(
                    tx: loyalty.transactions[i],
                  ).animate(delay: (i * 30).ms).fadeIn(duration: 250.ms),
                ),
              const SliverToBoxAdapter(child: SizedBox(height: 24)),
            ],
          );
        },
      ),
    );
  }
}

// ─── Header с балансом ────────────────────────────────────────────────────────

class _Header extends StatelessWidget {
  final LoyaltyProvider loyalty;
  const _Header({required this.loyalty});

  static String _ruleV1(LoyaltyV1 w) {
    final ceiling = w.ceilingChip.isEmpty ? '' : '${w.ceilingChip} заказа · ';
    return '1 бонус = 1 ₽ · $ceiling'
        'от ${w.redeemMin} · нажми карту — QR';
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.black,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 28),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  GestureDetector(
                    onTap: () => Navigator.of(context).pop(),
                    child: const Icon(
                      Icons.arrow_back,
                      color: Colors.white,
                      size: 22,
                    ),
                  ),
                  const SizedBox(width: 12),
                  RemoteText(
                    loyalty.programV1 ? 'app.loyalty.titleV1' : 'app.loyalty.title',
                    loyalty.programV1 ? 'МОИ БОНУСЫ' : 'МОИ БАЛЛЫ',
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                      color: Colors.white,
                      letterSpacing: 2,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 22),
              // Виртуальная карта лояльности: 3D-переворот по эталону —
              // лицо с баллами, оборот с QR для кассы.
              Center(
                child: Consumer<AuthProvider>(
                  builder: (context, auth, _) => LoyaltyCard3D(
                    balance: loyalty.balance,
                    levelLabel: loyalty.level.label,
                    holderName: auth.user?.name ?? 'Гость МАТА',
                    // QR кодирует ПОСТОЯННЫЙ 6-значный код лояльности (не баланс) —
                    // сканирование на кассе даёт эти цифры. Пока не загружен — id (fallback).
                    qrData: loyalty.code.isNotEmpty
                        ? loyalty.code
                        : (auth.user?.id ?? ''),
                    tier: switch (loyalty.level) {
                      LoyaltyLevel.basic => LoyaltyCardTier.basic,
                      LoyaltyLevel.silver => LoyaltyCardTier.silver,
                      LoyaltyLevel.gold => LoyaltyCardTier.gold,
                      LoyaltyLevel.platinum => LoyaltyCardTier.platinum,
                    },
                  ),
                ),
              ).animate().fadeIn(duration: 450.ms).slideY(begin: 0.06),
              const SizedBox(height: 14),
              Center(
                child: switch (loyalty.v1) {
                  // v1: потолок и минимум — настройки сервера, не зашиваем.
                  final w? => Text(
                      _ruleV1(w), // staw-static — числа с сервера
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                          fontSize: 12, color: Color(0xFF888888)),
                    ),
                  null => const RemoteText(
                      'app.loyalty.rule',
                      '1 балл = 1 ₽ скидки · до 30% от заказа · нажми карту — QR',
                      style: TextStyle(fontSize: 12, color: Color(0xFF888888)),
                    ),
                },
              ),
              // Баллы за бег созревают 3 дня / заморожены на проверке (сервер).
              if (loyalty.pendingLine case final line?) ...[
                const SizedBox(height: 6),
                Center(
                  child: Text(
                    line, // staw-static — служебная строка с числом и датой
                    textAlign: TextAlign.center,
                    style:
                        const TextStyle(fontSize: 12, color: Color(0xFF888888)),
                  ),
                ),
              ],
              // v1: ближайшее сгорание и долг после возврата — с сервера.
              for (final line in [
                loyalty.v1?.expiringLine,
                loyalty.v1?.debtLine,
              ])
                if (line != null) ...[
                  const SizedBox(height: 6),
                  Center(
                    child: Text(
                      line, // staw-static — служебная строка с числом и датой
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                          fontSize: 12, color: Color(0xFF888888)),
                    ),
                  ),
                ],
            ],
          ),
        ),
      ),
    );
  }
}

// ─── Карточка уровня ──────────────────────────────────────────────────────────

class _LevelCard extends StatelessWidget {
  final LoyaltyProvider loyalty;
  const _LevelCard({required this.loyalty});

  @override
  Widget build(BuildContext context) {
    if (loyalty.v1 case final w?) return _LevelCardV1(v1: w);
    final level = loyalty.level;
    final next = level.next;
    return Container(
      margin: const EdgeInsets.fromLTRB(20, 20, 20, 8),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(border: Border.all(color: AppColors.grey200)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.workspace_premium_outlined, size: 20),
              const SizedBox(width: 8),
              Text(
                'Уровень: ${level.label}',
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          // Привилегий уровней в прежней программе нет — не обещаем; только
          // правило списания. Текст правится в Конструкторе.
          const RemoteText(
            'app.loyalty.levelPerk',
            '1 балл = 1 ₽ скидки · до 30% от заказа',
            style: TextStyle(fontSize: 12, color: AppColors.grey600),
          ),
          if (next != null) ...[
            const SizedBox(height: 14),
            ClipRRect(
              borderRadius: BorderRadius.circular(3),
              child: LinearProgressIndicator(
                value: loyalty.levelProgress,
                minHeight: 6,
                backgroundColor: AppColors.grey200,
                valueColor: const AlwaysStoppedAnimation(AppColors.black),
              ),
            ),
            const SizedBox(height: 6),
            Text(
              'До уровня «${next.label}» — ${loyalty.pointsToNextLevel} баллов',
              style: const TextStyle(fontSize: 12, color: AppColors.grey600),
            ),
          ],
        ],
      ),
    ).animate().fadeIn(duration: 350.ms, delay: 100.ms).slideY(begin: 0.08);
  }
}

/// Карточка уровня программы v1: привилегии, шкала до минимума списания (пока
/// не накоплен), шкала уровня по статусным; на пути к Платине — ещё покупки.
/// Все числа — с сервера. Оформление — как у прежней карточки.
class _LevelCardV1 extends StatelessWidget {
  final LoyaltyV1 v1;
  const _LevelCardV1({required this.v1});

  Widget _bar(double value) => ClipRRect(
        borderRadius: BorderRadius.circular(3),
        child: LinearProgressIndicator(
          value: value,
          minHeight: 6,
          backgroundColor: AppColors.grey200,
          valueColor: const AlwaysStoppedAnimation(AppColors.black),
        ),
      );

  Widget _caption(String text) => Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Text(
          text, // staw-static — числа с сервера
          style: const TextStyle(fontSize: 12, color: AppColors.grey600),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final perk = v1.perkText;
    return Container(
      margin: const EdgeInsets.fromLTRB(20, 20, 20, 8),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(border: Border.all(color: AppColors.grey200)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.workspace_premium_outlined, size: 20),
              const SizedBox(width: 8),
              Text(
                'Уровень: ${v1.level.label}',
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const Spacer(),
              if (v1.ceilingChip.isNotEmpty)
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  color: AppColors.grey100,
                  child: Text(
                    v1.ceilingChip, // staw-static — потолок с сервера
                    style: const TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
            ],
          ),
          if (perk.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              perk, // staw-static — ставки уровня с сервера
              style: const TextStyle(fontSize: 12, color: AppColors.grey600),
            ),
          ],
          const SizedBox(height: 10),
          Text(
            v1.availableText, // staw-static — баланс
            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
          ),
          if (v1.belowRedeemMin) ...[
            const SizedBox(height: 8),
            _bar(v1.redeemMinProgress),
            _caption(v1.redeemMinText),
          ],
          const SizedBox(height: 14),
          _bar(v1.levelProgress),
          _caption(v1.levelScaleText),
          if (v1.showSpendScale) ...[
            const SizedBox(height: 10),
            _bar(v1.spendProgress),
            _caption(v1.spendScaleText),
          ],
        ],
      ),
    ).animate().fadeIn(duration: 350.ms, delay: 100.ms).slideY(begin: 0.08);
  }
}

/// Строка лота: источник, остаток и срок (доступно с / сгорят).
class _LotTile extends StatelessWidget {
  final LoyaltyLot lot;
  const _LotTile({required this.lot});

  @override
  Widget build(BuildContext context) {
    final debt = lot.remaining < 0;
    final partly = !debt && lot.remaining != lot.amount;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      child: Row(
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: const BoxDecoration(
              shape: BoxShape.circle,
              color: AppColors.grey100,
            ),
            child: Icon(
              lot.held ? Icons.schedule : Icons.stars_rounded,
              size: 18,
              color: AppColors.black,
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  lot.sourceLabel, // staw-static — источник лота
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  partly ? '${lot.dateLine} · из ${lot.amount}' : lot.dateLine,
                  style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.grey400,
                  ),
                ),
              ],
            ),
          ),
          Text(
            '${lot.remaining}',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: debt
                  ? AppColors.red
                  : (lot.held ? AppColors.grey400 : const Color(0xFF2E7D32)),
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Подсказка как зарабатывать ───────────────────────────────────────────────

class _EarnHint extends StatelessWidget {
  final LoyaltyV1? v1;
  const _EarnHint({this.v1});

  @override
  Widget build(BuildContext context) {
    final w = v1;
    final rate = w?.infoFor(w.level)?.purchaseRate ?? 0;
    // v1: за покупку — ставка уровня с сервера; отзывов в программе v1 нет.
    final items = w != null
        ? [
            (
              'app.loyalty.earn1',
              'Бег и территории в «Квартал»',
              Icons.directions_run,
            ),
            (
              '',
              rate > 0
                  ? 'Покупки: ${loyaltyPercent(rate)}% бонусами от оплаченной суммы'
                  : 'Покупки в МАТА Store',
              Icons.shopping_bag_outlined,
            ),
          ]
        : const [
      (
        'app.loyalty.earn1',
        'Бег и территории в «Квартал»',
        Icons.directions_run,
      ),
      (
        'app.loyalty.earn2',
        'Покупки: +1 балл за каждые 10 ₽',
        Icons.shopping_bag_outlined,
      ),
      (
        'app.loyalty.earn3',
        'Отзыв с фото: +10 баллов',
        Icons.rate_review_outlined,
      ),
    ];
    return Container(
      margin: const EdgeInsets.fromLTRB(20, 8, 20, 12),
      padding: const EdgeInsets.all(14),
      color: AppColors.grey100,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          RemoteText(
            v1 != null ? 'app.loyalty.earnTitleV1' : 'app.loyalty.earnTitle',
            v1 != null ? 'КАК ПОЛУЧИТЬ БОНУСЫ' : 'КАК ЗАРАБОТАТЬ БАЛЛЫ',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              letterSpacing: 1,
              color: AppColors.grey600,
            ),
          ),
          const SizedBox(height: 10),
          ...items.map(
            (it) => Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(
                children: [
                  Icon(it.$3, size: 16, color: AppColors.black),
                  const SizedBox(width: 10),
                  Expanded(
                    child: it.$1.isEmpty
                        ? Text(
                            it.$2, // staw-static — ставка уровня с сервера
                            style: const TextStyle(
                              fontSize: 13,
                              color: AppColors.black,
                            ),
                          )
                        : RemoteText(
                            it.$1,
                            it.$2,
                            style: const TextStyle(
                              fontSize: 13,
                              color: AppColors.black,
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

// ─── Строка истории ───────────────────────────────────────────────────────────

class _TxnTile extends StatelessWidget {
  final LoyaltyTransaction tx;
  const _TxnTile({required this.tx});

  IconData get _icon {
    if (tx.source.isRunner) return Icons.directions_run;
    switch (tx.source) {
      case LoyaltySource.purchase:
        return Icons.shopping_bag_outlined;
      case LoyaltySource.redeem:
        return Icons.remove_circle_outline;
      case LoyaltySource.review:
        return Icons.rate_review_outlined;
      default:
        return Icons.card_giftcard_outlined;
    }
  }

  @override
  Widget build(BuildContext context) {
    final positive = tx.amount >= 0;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      child: Row(
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: tx.source.isRunner ? AppColors.black : AppColors.grey100,
            ),
            child: Icon(
              _icon,
              size: 18,
              color: tx.source.isRunner ? Colors.white : AppColors.black,
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  tx.description,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  _date(tx.createdAt),
                  style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.grey400,
                  ),
                ),
              ],
            ),
          ),
          Text(
            '${positive ? '+' : ''}${tx.amount}',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: positive ? const Color(0xFF2E7D32) : AppColors.red,
            ),
          ),
        ],
      ),
    );
  }

  String _date(DateTime dt) {
    const months = [
      '',
      'янв',
      'фев',
      'мар',
      'апр',
      'мая',
      'июн',
      'июл',
      'авг',
      'сен',
      'окт',
      'ноя',
      'дек',
    ];
    return '${dt.day} ${months[dt.month]} ${dt.year}';
  }
}
