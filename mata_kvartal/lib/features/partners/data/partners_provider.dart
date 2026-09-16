import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../../../core/api/api_client.dart';

/// Партнёры программы лояльности на карте (D-81).
///
/// Тап на «Карту» в любом режиме показывает логотипы партнёров, где можно
/// потратить баллы МАТА (спортпитание/витамины, кофе, экипировка). Точки заводит
/// владелец в админке; клиент только показывает список и карточку.
///
/// СТАРТОВЫЙ ФЛАГ: слой выключен, пока не наберём реальных партнёров (за флагом,
/// как «Лига», D-79). Включить = `kPartnersLayer = true` (и пересобрать). Пока
/// false — провайдер даже не ходит на сервер, слой на карте не строится.
const bool kPartnersLayer = false;

class Partner {
  final int id;
  final String name;
  final String category; // nutrition | coffee | gear | food | other
  final String emoji;
  final String? logoUrl;
  final String address;
  final String description;
  final double lat;
  final double lng;
  final int pointsPercent; // до скольких % чека можно оплатить баллами

  const Partner({
    required this.id,
    required this.name,
    required this.category,
    required this.emoji,
    required this.lat,
    required this.lng,
    this.logoUrl,
    this.address = '',
    this.description = '',
    this.pointsPercent = 0,
  });

  LatLng get point => LatLng(lat, lng);

  factory Partner.fromJson(Map<String, dynamic> j) => Partner(
        id: (j['id'] as num?)?.toInt() ?? 0,
        name: j['name']?.toString() ?? '',
        category: j['category']?.toString() ?? 'other',
        emoji: j['emoji']?.toString() ?? '',
        logoUrl: (j['logoUrl'] as String?)?.isNotEmpty == true
            ? j['logoUrl'] as String
            : null,
        address: j['address']?.toString() ?? '',
        description: j['description']?.toString() ?? '',
        lat: (j['lat'] as num?)?.toDouble() ?? 0,
        lng: (j['lng'] as num?)?.toDouble() ?? 0,
        pointsPercent: (j['pointsPercent'] as num?)?.toInt() ?? 0,
      );
}

/// Значок метки: свой эмодзи партнёра или запасной по категории.
String partnerGlyph(Partner p) {
  if (p.emoji.isNotEmpty) return p.emoji;
  return switch (p.category) {
    'nutrition' => '🥗',
    'coffee' => '☕',
    'gear' => '👟',
    'food' => '🥤',
    _ => '📍',
  };
}

String partnerCategoryLabel(String category) => switch (category) {
      'nutrition' => 'Спортпитание',
      'coffee' => 'Кофе',
      'gear' => 'Экипировка',
      'food' => 'Здоровое питание',
      _ => 'Партнёр',
    };

final _partnersDio = ApiClient.create();

/// Список активных партнёров для слоя карты. Публичный эндпоинт (без токена).
/// При выключенном флаге сеть не дёргаем — пустой список, слоя нет.
final partnersProvider = FutureProvider.autoDispose<List<Partner>>((ref) async {
  if (!kPartnersLayer) return const [];
  final res = await _partnersDio.get<Map<String, dynamic>>('/loyalty/partners');
  return ((res.data ?? const {})['partners'] as List? ?? const [])
      .whereType<Map<String, dynamic>>()
      .map(Partner.fromJson)
      .toList();
});
