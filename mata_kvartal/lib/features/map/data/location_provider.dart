import 'package:geolocator/geolocator.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

// Координаты центра Якутска
const yakutskCenter = LatLng(62.0280, 129.7325);

final locationPermissionProvider = FutureProvider<LocationPermission>((
  ref,
) async {
  bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
  if (!serviceEnabled) return LocationPermission.denied;

  LocationPermission permission = await Geolocator.checkPermission();
  if (permission == LocationPermission.denied) {
    permission = await Geolocator.requestPermission();
  }
  return permission;
});

final currentPositionProvider = FutureProvider<Position?>((ref) async {
  final permission = await ref.watch(locationPermissionProvider.future);
  if (permission == LocationPermission.denied ||
      permission == LocationPermission.deniedForever) {
    return null;
  }
  return Geolocator.getCurrentPosition(
    locationSettings: const LocationSettings(accuracy: LocationAccuracy.high),
  );
});

final positionStreamProvider = StreamProvider<Position?>((ref) async* {
  final permission = await ref.watch(locationPermissionProvider.future);
  if (permission == LocationPermission.denied ||
      permission == LocationPermission.deniedForever) {
    yield null;
    return;
  }

  yield await Geolocator.getCurrentPosition(
    locationSettings: const LocationSettings(accuracy: LocationAccuracy.high),
  );

  yield* Geolocator.getPositionStream(
    locationSettings: const LocationSettings(
      accuracy: LocationAccuracy.bestForNavigation,
      // Поток нужен только метке на карте (трек забега пишет свой поток в
      // run_provider). Раньше distanceFilter: 0 — событие на каждый фикс даже
      // стоя на месте, и карта перестраивалась ~раз в секунду (аудит 21.11.2026).
      distanceFilter: 3,
    ),
  );
});

extension PositionToLatLng on Position {
  LatLng get toLatLng => LatLng(latitude, longitude);
}
