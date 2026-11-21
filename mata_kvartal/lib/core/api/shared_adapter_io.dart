import 'dart:io';

import 'package:dio/dio.dart';
import 'package:dio/io.dart';

/// Один пул соединений на всё приложение (Android/iOS).
///
/// [idleTimeout] короче, чем держит соединение сервер (nginx — 75 с, dev-сервер
/// Django — меньше): простаивающее соединение закрываем мы сами, раньше сервера,
/// и не натыкаемся на «Connection closed before full header» (PITFALLS).
HttpClientAdapter createSharedAdapter() => IOHttpClientAdapter(
      createHttpClient: () => HttpClient()
        ..idleTimeout = const Duration(seconds: 10)
        ..maxConnectionsPerHost = 6,
    );
