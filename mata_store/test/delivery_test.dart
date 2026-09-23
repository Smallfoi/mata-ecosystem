// Доставка отложена (D-92): служб у нас нет, договоров тоже — значит магазин не
// вправе брать за неё деньги. Раньше в оформлении стояли СДЭК 200 ₽, Почта 150 ₽
// и курьер 300 ₽; тест держит правило, чтобы они не вернулись случайно.
import 'package:flutter_test/flutter_test.dart';
import 'package:sport_store/models/order.dart';
import 'package:sport_store/providers/order_provider.dart';

void main() {
  test('доставка не берёт денег ни одним способом', () {
    for (final type in DeliveryType.values) {
      expect(OrderProvider.costFor(type), 0,
          reason: 'способ ${OrderProvider.deliveryLabel(type)} берёт деньги за доставку');
    }
  });

  test('способов ровно два: самовывоз и наша доставка', () {
    expect(DeliveryType.values, [DeliveryType.pickup, DeliveryType.courier]);
    expect(OrderProvider.deliveryLabel(DeliveryType.courier), 'Курьер по Якутску');
  });

  test('старый заказ со снятым способом читается, а не падает', () {
    final data = CheckoutData.fromJson({
      'name': 'Иван',
      'phone': '+79148278470',
      'email': 'i@mata.ru',
      'deliveryType': 'cdek',
      'paymentType': 'sbp',
    });
    expect(data.deliveryType, DeliveryType.courier);
  });
}
