import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../../data/api/api_client.dart';
import '../../theme/app_theme.dart';
import '../../widgets/remote_text.dart';

/// Отмена и возврат по заказу (D-112, D-123). Решает сервер МАТА: что можно
/// вернуть, до какого срока, нужна ли фотография. Экран только показывает его
/// ответ и собирает заявку.
///
/// Ход заявки: ждём вещь → в пути (трек-номер) → получено → решение
/// (принято / частично / отказ). По отказу покупатель выбирает, как забрать
/// вещи. Пока заказ не передан курьеру — его можно отменить целиком.
class ReturnRequestScreen extends StatefulWidget {
  final String orderId;
  const ReturnRequestScreen({super.key, required this.orderId});

  @override
  State<ReturnRequestScreen> createState() => _ReturnRequestScreenState();
}

/// Причины «не надлежащего качества» — срок по ним 2 года, а не 7 дней.
const _qualityReasons = {'defect', 'wrong_item', 'not_as_described'};

class _Photo {
  final String path;
  int? id;
  bool failed = false;
  _Photo(this.path);
}

class _ReturnRequestScreenState extends State<ReturnRequestScreen> {
  Map<String, dynamic>? _options;
  List<Map<String, dynamic>> _requests = [];
  String? _error;
  bool _loading = true;
  bool _sending = false;
  bool _canceling = false;

  /// index позиции → выбранная причина.
  final Map<int, String> _reasons = {};
  final Map<int, TextEditingController> _comments = {};
  final List<_Photo> _photos = [];
  String _method = 'store';

  ApiClient? get _api => context.read<ApiClient?>();

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in _comments.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    final api = _api;
    if (api == null) return;
    setState(() => _loading = true);
    try {
      final opts = await api.get('/orders/${widget.orderId}/return-options');
      final reqs = await api.get('/orders/${widget.orderId}/return-requests');
      if (!mounted) return;
      setState(() {
        _options = opts as Map<String, dynamic>;
        _requests = (reqs as List).cast<Map<String, dynamic>>();
        _error = null;
        _reasons.clear();
        _photos.clear();
      });
    } catch (e) {
      if (mounted) setState(() => _error = _errText(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  bool get _standardOpen => _options?['standardOpen'] != false;
  int get _maxPhotos => (_options?['maxPhotos'] as num?)?.toInt() ?? 6;
  bool get _needsPhoto => _reasons.values.contains('defect');
  bool get _uploading => _photos.any((p) => p.id == null && !p.failed);

  bool _needsComment(String reason) => reason == 'defect' || reason == 'other';

  // ── Фото ────────────────────────────────────────────────────────────────

  Future<void> _addPhoto(ImageSource source) async {
    final api = _api;
    if (api == null || _photos.length >= _maxPhotos) return;
    final x = await ImagePicker()
        .pickImage(source: source, maxWidth: 2000, imageQuality: 85);
    if (x == null || !mounted) return;
    final photo = _Photo(x.path);
    setState(() {
      _photos.add(photo);
      _error = null;
    });
    try {
      final r = await api.uploadImage('/return-photos', x.path);
      photo.id = ((r as Map)['id'] as num).toInt();
    } catch (e) {
      photo.failed = true;
      if (mounted) setState(() => _error = _errText(e));
    }
    if (mounted) setState(() {});
  }

  Future<void> _pickSource() async {
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined),
              title: const RemoteText('app.return.photo_camera', 'Сфотографировать'),
              onTap: () => Navigator.pop(ctx, ImageSource.camera),
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: const RemoteText('app.return.photo_gallery', 'Выбрать из галереи'),
              onTap: () => Navigator.pop(ctx, ImageSource.gallery),
            ),
          ],
        ),
      ),
    );
    if (source != null) await _addPhoto(source);
  }

  // ── Действия ────────────────────────────────────────────────────────────

  Future<void> _submit() async {
    final api = _api;
    if (api == null || _reasons.isEmpty) return;
    for (final e in _reasons.entries) {
      final text = _comments[e.key]?.text.trim() ?? '';
      if (_needsComment(e.value) && text.length < 5) {
        setState(() => _error = 'Опишите, что не так с вещью'); // staw-static
        return;
      }
    }
    final ids = [for (final p in _photos) if (p.id != null) p.id!];
    if (_needsPhoto && ids.isEmpty) {
      setState(() => _error = 'Приложите фото брака'); // staw-static
      return;
    }
    setState(() {
      _sending = true;
      _error = null;
    });
    try {
      await api.post('/orders/${widget.orderId}/return-requests', body: {
        'method': _method,
        // Ключ шлём всегда: так сервер знает, что приложение умеет фото,
        // и требует снимок при браке (старые сборки его не присылают).
        'photos': ids,
        'lines': [
          for (final e in _reasons.entries)
            {
              'index': e.key,
              'reason': e.value,
              'comment': _comments[e.key]?.text.trim() ?? '',
            }
        ],
      });
      await _load();
    } catch (e) {
      if (mounted) setState(() => _error = _errText(e));
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _post(String path, [Map<String, dynamic> body = const {}]) async {
    final api = _api;
    if (api == null) return;
    try {
      await api.post(path, body: body);
      await _load();
    } catch (e) {
      if (mounted) setState(() => _error = _errText(e));
    }
  }

  Future<void> _cancelOrder() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const RemoteText('app.return.cancel_order_q', 'Отменить заказ?'),
        content: const RemoteText(
          'app.return.cancel_order_hint',
          'Деньги вернутся на карту или счёт, с которых платили, списанные '
              'баллы — на баланс. Если склад уже собрал заказ, проверим, что '
              'он ещё не у курьера, и сообщим.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const RemoteText('app.return.cancel_order_no', 'Не отменять'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const RemoteText('app.return.cancel_order_yes', 'Отменить заказ'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _canceling = true);
    await _post('/orders/${widget.orderId}/cancel');
    if (mounted) setState(() => _canceling = false);
  }

  Future<void> _enterTrack(int id, String current) async {
    final ctrl = TextEditingController(text: current);
    final track = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const RemoteText('app.return.track_title', 'Трек-номер посылки'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          textCapitalization: TextCapitalization.characters,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const RemoteText('app.return.track_cancel', 'Отмена'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
            child: const RemoteText('app.return.track_save', 'Сохранить'),
          ),
        ],
      ),
    );
    ctrl.dispose();
    if (track == null || track.isEmpty) return;
    await _post('/return-requests/$id/sent', {'trackNumber': track});
  }

  // ── Экран ───────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.white,
      appBar: AppBar(
        backgroundColor: AppColors.white,
        elevation: 0,
        foregroundColor: AppColors.black,
        title: const RemoteText('app.return.title', 'Отмена и возврат'),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  if (_options != null) ..._cancelBlock(),
                  for (final r in _requests)
                    _RequestCard(
                      r,
                      onCancel: (id) => _post('/return-requests/$id/cancel'),
                      onTrack: _enterTrack,
                      onGoodsBack: (id, way) =>
                          _post('/return-requests/$id/goods-back', {'way': way}),
                    ),
                  if (_options != null) ..._form(),
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 12),
                      child: Text(_error!,
                          style: const TextStyle(color: AppColors.red)),
                    ),
                ],
              ),
            ),
    );
  }

  List<Widget> _cancelBlock() {
    final opts = _options!;
    final note = (opts['cancelNote'] ?? '').toString();
    if (opts['canCancel'] == true) {
      return [
        const RemoteText(
          'app.return.cancel_order_lead',
          'Заказ ещё не передан курьеру — его можно отменить целиком.',
          style: TextStyle(fontSize: 14, height: 1.4),
        ),
        const SizedBox(height: 8),
        OutlinedButton(
          onPressed: _canceling ? null : _cancelOrder,
          child: _canceling
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2))
              : const RemoteText('app.return.cancel_order', 'Отменить заказ'),
        ),
        const SizedBox(height: 24),
      ];
    }
    if (opts['cancelRequested'] == true && note.isNotEmpty) {
      return [
        Text(note, style: const TextStyle(fontSize: 14, height: 1.4)),
        const SizedBox(height: 24),
      ];
    }
    return const [];
  }

  List<Widget> _form() {
    final opts = _options!;
    if (opts['canReturn'] != true) {
      final reason = (opts['reason'] ?? '').toString();
      // Отменяемый заказ ещё не получен — «вернуть нельзя» тут лишнее.
      if (opts['canCancel'] == true || opts['cancelRequested'] == true) {
        return const [];
      }
      return [
        if (reason.isNotEmpty)
          Text(reason, style: const TextStyle(color: AppColors.grey600)),
      ];
    }
    final reasons = (opts['reasons'] as Map).cast<String, dynamic>();
    final lines = (opts['lines'] as List).cast<Map<String, dynamic>>();
    final store = (opts['store'] as Map?)?.cast<String, dynamic>() ?? {};
    final standardNote = (opts['standardNote'] ?? '').toString();
    return [
      const RemoteText(
        'app.return.rules',
        'Вещь без брака можно вернуть в течение 7 дней со дня получения: с '
            'ярлыками, в упаковке, без следов носки. Брак — в течение 2 лет. '
            'Принесите вещь в магазин МАТА или отправьте посылкой за свой '
            'счёт. Решение принимаем после осмотра. Если подтвердится брак — '
            'вернём и расходы на доставку.',
        style: TextStyle(fontSize: 14, height: 1.4),
      ),
      if (standardNote.isNotEmpty) ...[
        const SizedBox(height: 12),
        Text(standardNote,
            style: const TextStyle(fontSize: 14, height: 1.4, color: AppColors.grey600)),
      ],
      const SizedBox(height: 16),
      const RemoteText('app.return.pick', 'Что возвращаете',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      for (final line in lines) _lineTile(line, reasons),
      const SizedBox(height: 16),
      ..._photoBlock(),
      const SizedBox(height: 16),
      const RemoteText('app.return.method', 'Как сдадите',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
      RadioListTile<String>(
        value: 'store',
        groupValue: _method,
        onChanged: (v) => setState(() => _method = v!),
        title: const RemoteText('app.return.method_store', 'Принесу в магазин'),
        subtitle: Text((store['description'] ?? '').toString()),
      ),
      RadioListTile<String>(
        value: 'parcel',
        groupValue: _method,
        onChanged: (v) => setState(() => _method = v!),
        title: const RemoteText(
            'app.return.method_parcel', 'Отправлю посылкой за свой счёт'),
        subtitle: const RemoteText('app.return.method_parcel_hint',
            'После отправки впишите здесь трек-номер. Сохраните квитанцию: '
                'при подтверждённом браке компенсируем доставку'),
      ),
      const SizedBox(height: 16),
      ElevatedButton(
        onPressed: _reasons.isEmpty || _sending || _uploading ? null : _submit,
        child: _sending
            ? const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2))
            : const RemoteText('app.return.submit', 'Оформить заявку'),
      ),
    ];
  }

  List<Widget> _photoBlock() {
    return [
      const RemoteText('app.return.photos', 'Фото',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
      const SizedBox(height: 4),
      _needsPhoto
          ? const RemoteText('app.return.photos_need',
              'При браке нужно фото: сам дефект крупно и вещь целиком.',
              style: TextStyle(fontSize: 13, color: AppColors.grey600))
          : const RemoteText('app.return.photos_hint',
              'Необязательно, но так быстрее разберёмся.',
              style: TextStyle(fontSize: 13, color: AppColors.grey600)),
      const SizedBox(height: 8),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          for (final p in _photos) _thumb(p),
          if (_photos.length < _maxPhotos)
            InkWell(
              onTap: _pickSource,
              borderRadius: BorderRadius.circular(8),
              child: Container(
                width: 72,
                height: 72,
                decoration: BoxDecoration(
                  border: Border.all(color: AppColors.grey200),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(Icons.add_a_photo_outlined,
                    color: AppColors.grey600),
              ),
            ),
        ],
      ),
    ];
  }

  Widget _thumb(_Photo p) {
    return Stack(
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: Image.file(File(p.path), width: 72, height: 72, fit: BoxFit.cover),
        ),
        if (p.id == null)
          Positioned.fill(
            child: Container(
              decoration: BoxDecoration(
                color: AppColors.white.withValues(alpha: 0.6),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Center(
                child: p.failed
                    ? const Icon(Icons.error_outline, color: AppColors.red)
                    : const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2)),
              ),
            ),
          ),
        Positioned(
          top: 0,
          right: 0,
          child: GestureDetector(
            onTap: () => setState(() => _photos.remove(p)),
            child: Container(
              padding: const EdgeInsets.all(2),
              decoration: const BoxDecoration(
                  color: AppColors.black, shape: BoxShape.circle),
              child: const Icon(Icons.close, size: 14, color: AppColors.white),
            ),
          ),
        ),
      ],
    );
  }

  Widget _lineTile(Map<String, dynamic> line, Map<String, dynamic> reasons) {
    final index = (line['index'] as num).toInt();
    final available = line['available'] == true;
    final selected = _reasons.containsKey(index);
    final reason = _reasons[index];
    // После 7 дней сервер примет только претензию по качеству — остальные
    // причины не предлагаем, чтобы не получить отказ после отправки.
    final allowed = {
      for (final e in reasons.entries)
        if (_standardOpen || _qualityReasons.contains(e.key)) e.key: e.value,
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        CheckboxListTile(
          value: selected,
          onChanged: available
              ? (v) => setState(() {
                    if (v == true) {
                      _reasons[index] = _standardOpen ? 'size' : 'defect';
                      _comments.putIfAbsent(index, TextEditingController.new);
                    } else {
                      _reasons.remove(index);
                    }
                  })
              : null,
          title: Text((line['name'] ?? '').toString()),
          subtitle: Text(available
              ? '${(line['paid'] as num).toStringAsFixed(0)} ₽'
              : line['status'] == 'returned'
                  ? 'Уже возвращено' // staw-static
                  : 'По вещи уже есть заявка'), // staw-static
        ),
        if (selected) ...[
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: DropdownButton<String>(
              isExpanded: true,
              value: allowed.containsKey(reason) ? reason : null,
              items: [
                for (final e in allowed.entries)
                  DropdownMenuItem(value: e.key, child: Text('${e.value}')),
              ],
              onChanged: (v) => setState(() => _reasons[index] = v!),
            ),
          ),
          if (_needsComment(reason!))
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: TextField(
                controller: _comments[index],
                maxLines: 2,
                decoration: const InputDecoration(
                  hintText: 'Что не так с вещью', // staw-static
                ),
              ),
            ),
        ],
      ],
    );
  }
}

/// Текст ошибки сервера: `{"detail": "..."}` → "...".
String _errText(Object e) {
  if (e is ApiException) {
    try {
      final body = jsonDecode(e.message);
      var detail = body is Map ? (body['detail'] ?? '').toString() : '';
      // Ответ без charset пакет http читает как latin1 — чиним кириллицу.
      if (detail.contains('Ð') || detail.contains('Ñ')) {
        try {
          detail = utf8.decode(latin1.encode(detail));
        } catch (_) {}
      }
      if (detail.isNotEmpty) return detail;
    } catch (_) {}
    return 'Не получилось — попробуйте ещё раз'; // staw-static
  }
  return 'Нет связи с сервером — попробуйте ещё раз'; // staw-static
}

String _ddmm(String iso) {
  final d = DateTime.tryParse(iso)?.toLocal();
  if (d == null) return '';
  return '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}';
}

class _RequestCard extends StatelessWidget {
  final Map<String, dynamic> request;
  final void Function(int id) onCancel;
  final void Function(int id, String current) onTrack;
  final void Function(int id, String way) onGoodsBack;
  const _RequestCard(this.request,
      {required this.onCancel, required this.onTrack, required this.onGoodsBack});

  @override
  Widget build(BuildContext context) {
    final id = (request['id'] as num).toInt();
    final status = (request['status'] ?? '').toString();
    final note = (request['decisionNote'] ?? '').toString();
    final until = _ddmm((request['bringUntil'] ?? '').toString());
    final track = (request['trackNumber'] ?? '').toString();
    final lines = ((request['lines'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
    final inspection = ((request['inspectionPhotos'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
    final goodsBack = (request['goodsBack'] ?? '').toString();
    const muted = TextStyle(fontSize: 13, color: AppColors.grey600);

    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        border: Border.all(color: AppColors.grey200),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Заявка ${request['number']}', // staw-static
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          const SizedBox(height: 2),
          Text('${request['statusLabel']}'),
          const SizedBox(height: 8),
          for (final l in lines) ...[
            Text('${l['name']} — ${l['reasonLabel']}', style: muted),
            for (final r in ((l['rejectReasonLabels'] as List?) ?? const []))
              Text('Отказ: $r', // staw-static
                  style: const TextStyle(fontSize: 13, color: AppColors.red)),
          ],
          if (status == 'awaiting' && until.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                  request['method'] == 'parcel'
                      ? 'Отправьте посылку до $until' // staw-static
                      : 'Принесите вещь до $until', // staw-static
                  style: muted),
            ),
          if (track.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text('Трек-номер: $track', style: muted), // staw-static
            ),
          if (note.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(note),
            ),
          if (request['refundRub'] != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                  'Возвращено: ${(request['refundRub'] as num).toStringAsFixed(2)} ₽', // staw-static
                  style: const TextStyle(fontWeight: FontWeight.w700)),
            ),
          if (inspection.isNotEmpty) ...[
            const SizedBox(height: 8),
            const RemoteText('app.return.inspection_photos', 'Фото с осмотра',
                style: muted),
            const SizedBox(height: 4),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final p in inspection)
                  ClipRRect(
                    borderRadius: BorderRadius.circular(6),
                    child: Image.network(
                      (p['url'] ?? '').toString(),
                      width: 64,
                      height: 64,
                      fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) =>
                          const SizedBox(width: 64, height: 64),
                    ),
                  ),
              ],
            ),
          ],
          if (request['needsGoodsBack'] == true) ...[
            const SizedBox(height: 10),
            const RemoteText('app.return.goods_back_q',
                'Как вернуть вам вещи, по которым отказано?'),
            const SizedBox(height: 6),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                OutlinedButton(
                  onPressed: () => onGoodsBack(id, 'pickup'),
                  child: const RemoteText(
                      'app.return.goods_back_pickup', 'Заберу в магазине'),
                ),
                OutlinedButton(
                  onPressed: () => onGoodsBack(id, 'ship'),
                  child: const RemoteText('app.return.goods_back_ship',
                      'Отправьте за мой счёт'),
                ),
              ],
            ),
          ] else if (goodsBack.isNotEmpty && request['goodsBackDone'] != true)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                  goodsBack == 'pickup'
                      ? 'Вещи ждут вас в магазине' // staw-static
                      : 'Отправим вещи за ваш счёт — сообщим трек-номер', // staw-static
                  style: muted),
            ),
          if (request['needsTrack'] == true || request['canCancel'] == true)
            Wrap(
              spacing: 8,
              children: [
                if (request['needsTrack'] == true)
                  TextButton(
                    onPressed: () => onTrack(id, track),
                    child: track.isEmpty
                        ? const RemoteText(
                            'app.return.track_enter', 'Вписать трек-номер')
                        : const RemoteText(
                            'app.return.track_edit', 'Изменить трек-номер'),
                  ),
                if (request['canCancel'] == true)
                  TextButton(
                    onPressed: () => onCancel(id),
                    child: const RemoteText(
                        'app.return.cancel', 'Отменить заявку'),
                  ),
              ],
            ),
        ],
      ),
    );
  }
}
