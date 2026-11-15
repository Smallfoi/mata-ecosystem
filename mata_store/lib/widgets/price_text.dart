import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

class PriceText extends StatelessWidget {
  final double price;
  final double? oldPrice;
  final TextStyle? priceStyle;
  final bool showDiscount;

  const PriceText({
    super.key,
    required this.price,
    this.oldPrice,
    this.priceStyle,
    this.showDiscount = true,
  });

  @override
  Widget build(BuildContext context) {
    final isOnSale = oldPrice != null && oldPrice! > price;
    final discountPercent = isOnSale
        ? (((oldPrice! - price) / oldPrice!) * 100).round()
        : 0;

    return Wrap(
      crossAxisAlignment: WrapCrossAlignment.center,
      spacing: 6,
      children: [
        Text(
          '${price.toInt()} ₽',
          style: priceStyle ??
              const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: AppColors.black,
              ),
        ),
        if (isOnSale) ...[
          Text(
            '${oldPrice!.toInt()} ₽',
            style: const TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w400,
              color: AppColors.lavenderText,
              decoration: TextDecoration.lineThrough,
            ),
          ),
          if (showDiscount)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: AppColors.lime,
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                '−$discountPercent%',
                style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: AppColors.black,
                ),
              ),
            ),
        ],
      ],
    );
  }
}
