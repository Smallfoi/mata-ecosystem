import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../data/api/api_client.dart';
import '../../theme/app_theme.dart';
import '../../widgets/remote_text.dart';

/// Возврат по заказу (D-112): покупатель сам оформляет заявку, а решение
/// магазин принимает после осмотра вещи. Сдать — в магазин или посылкой за
/// свой счёт; брак подтвердится — вернём и расходы на доставку.
class ReturnRequestScreen extends StatefulWidget {
  final String orderId;
  const ReturnRequestScreen({super.key, required this.orderId});

  @override
  State<ReturnRequestScreen> createState() => _ReturnRequestScreenState();
}

class _ReturnRequestScreenState extends State<ReturnRequestScreen> {
  Map<String, dynamic>? _options;
  List<Map<String, dynamic>> _requests = [];
  String? _error;
  bool _loading = true;
  bool _sending = false;

  /// index позиции → выбранная причина.
  final Map<int, String> _reasons = {};
  final Map<int, TextEditingController> _comments = {};
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
      });
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  bool _needsComment(String reason) => reason == 'defect' || reason == 'other';

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
    setState(() {
      _sending = true;
      _error = null;
    });
    try {
      await api.post('/orders/${widget.orderId}/return-requests', body: {
        'method': _method,
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
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _cancel(int id) async {
    final api = _api;
    if (api == null) return;
    try {
      await api.post('/return-requests/$id/cancel', body: const {});
      await _load();
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.white,
      appBar: AppBar(
        backgroundColor: AppColors.white,
        elevation: 0,
        foregroundColor: AppColors.black,
        title: const RemoteText('app.return.title', 'Возврат'),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  const RemoteText(
                    'app.return.rules',
                    'Вещь без брака можно вернуть в течение 7 дней со дня '
                        'получения: с ярлыками, в упаковке, без следов носки. '
                        'Принесите её в магазин МАТА или отправьте посылкой за '
                        'свой счёт. Решение принимаем после осмотра в магазине. '
                        'Если подтвердится брак — вернём и расходы на доставку.',
                    style: TextStyle(fontSize: 14, height: 1.4),
                  ),
                  const SizedBox(height: 16),
                  for (final r in _requests) _RequestCard(r, onCancel: _cancel),
                  if (_options != null) ..._form(),
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 12),
                      child: Text(_error!,
                          style: const TextStyle(color: Colors.red)),
                    ),
                ],
              ),
            ),
    );
  }

  List<Widget> _form() {
    final opts = _options!;
    if (opts['canReturn'] != true) {
      return [
        Text((opts['reason'] ?? '').toString(),
            style: const TextStyle(color: AppColors.grey600)),
      ];
    }
    final reasons = (opts['reasons'] as Map).cast<String, dynamic>();
    final lines = (opts['lines'] as List).cast<Map<String, dynamic>>();
    final store = (opts['store'] as Map?)?.cast<String, dynamic>() ?? {};
    return [
      const RemoteText('app.return.pick', 'Что возвращаете',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      for (final line in lines) _lineTile(line, reasons),
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
            'Сохраните квитанцию: при подтверждённом браке компенсируем доставку'),
      ),
      const SizedBox(height: 16),
      ElevatedButton(
        onPressed: _reasons.isEmpty || _sending ? null : _submit,
        child: _sending
            ? const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2))
            : const RemoteText('app.return.submit', 'Оформить заявку'),
      ),
    ];
  }

  Widget _lineTile(Map<String, dynamic> line, Map<String, dynamic> reasons) {
    final index = (line['index'] as num).toInt();
    final available = line['available'] == true;
    final selected = _reasons.containsKey(index);
    final reason = _reasons[index];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        CheckboxListTile(
          value: selected,
          onChanged: available
              ? (v) => setState(() {
                    if (v == true) {
                      _reasons[index] = 'size';
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
              value: reason,
              items: [
                for (final e in reasons.entries)
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

class _RequestCard extends StatelessWidget {
  final Map<String, dynamic> request;
  final void Function(int id) onCancel;
  const _RequestCard(this.request, {required this.onCancel});

  @override
  Widget build(BuildContext context) {
    final status = (request['status'] ?? '').toString();
    final note = (request['decisionNote'] ?? '').toString();
    final until = DateTime.tryParse((request['bringUntil'] ?? '').toString());
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${request['number']} · ${request['statusLabel']}',
                style: const TextStyle(fontWeight: FontWeight.w700)),
            if (status == 'awaiting' && until != null)
              Text(
                  'Сдать до ${until.toLocal().day.toString().padLeft(2, '0')}.' // staw-static
                  '${until.toLocal().month.toString().padLeft(2, '0')}'),
            if (note.isNotEmpty) Text(note),
            if (request['refundRub'] != null)
              Text('Возврат: ${(request['refundRub'] as num).toStringAsFixed(2)} ₽'), // staw-static
            if (status == 'awaiting')
              TextButton(
                onPressed: () => onCancel((request['id'] as num).toInt()),
                child: const RemoteText('app.return.cancel', 'Отменить заявку'),
              ),
          ],
        ),
      ),
    );
  }
}
