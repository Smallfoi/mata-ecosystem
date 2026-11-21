import 'package:dio/dio.dart';

/// Веб-сборка: соединениями управляет браузер, общий адаптер — обычный.
HttpClientAdapter createSharedAdapter() => HttpClientAdapter();
