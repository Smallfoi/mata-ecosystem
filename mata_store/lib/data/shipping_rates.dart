import 'package:flutter/foundation.dart';

import '../models/order.dart';
import 'api/api_client.dart';

/// Цена одного способа получения заказа — как её считает сервер (D-110).
class ShippingRate {
  final double price;

  /// Сумма товаров, с которой способ бесплатный; null — порога нет.
  final double? freeFrom;

  const ShippingRate({required this.price, this.freeFrom});

  double costFor(double goods) =>
      freeFrom != null && goods >= freeFrom! ? 0 : price;
}

/// Цены доставки с сервера (`GET /v1/shipping-options`, D-110).
///
/// Способы и их цены ведёт владелец в админке, итог заказа считает сервер.
/// Приложение лишь показывает ту же цену, что сервер потом спишет. Пока цены
/// не загружены (нет сети, mock-режим) — 0 ₽, как было раньше (D-92); если
/// сервер насчитает больше, он откажет в заказе, а не спишет лишнее.
class ShippingRates {
  static Map<String, ShippingRate> _byCode = const {};

  static Future<void> load(ApiClient api) async {
    try {
      final data = await api.get('/shipping-options');
      final options = (data as Map<String, dynamic>)['options'] as List? ?? [];
      _byCode = {
        for (final o in options.cast<Map<String, dynamic>>())
          (o['code'] ?? '').toString(): ShippingRate(
            price: (o['price'] as num?)?.toDouble() ?? 0,
            freeFrom: (o['freeFrom'] as num?)?.toDouble(),
          ),
      };
    } catch (_) {
      // Нет сети — остаются прежние цены; сервер всё равно сверит итог.
    }
  }

  static double costFor(DeliveryType type, double goods) =>
      _byCode[type.name]?.costFor(goods) ?? 0;

  @visibleForTesting
  static void debugSet(Map<String, ShippingRate> rates) => _byCode = rates;
}
