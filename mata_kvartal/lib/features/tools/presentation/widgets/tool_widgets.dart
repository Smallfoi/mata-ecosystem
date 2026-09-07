import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';

/// Карточка-секция инструмента: фоновый блок с опциональным заголовком.
class ToolCard extends StatelessWidget {
  final String? title;
  final Widget child;

  const ToolCard({super.key, this.title, required this.child});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.separator),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (title != null) ...[
            Text(
              title!,
              style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    color: AppColors.textSecondary,
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: 8),
          ],
          child,
        ],
      ),
    );
  }
}

/// Строка-заголовок раскрывающегося поля: подпись слева, значение справа, шеврон.
class _FieldHeader extends StatelessWidget {
  final String label;
  final String value;
  final bool open;
  const _FieldHeader({
    required this.label,
    required this.value,
    required this.open,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    color: AppColors.textSecondary,
                    fontWeight: FontWeight.w700,
                  ),
            ),
          ),
          const SizedBox(width: 8),
          Text(
            value,
            style: TextStyle(
              color: open ? AppColors.electricBlue : AppColors.textPrimary,
              fontSize: 19,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(width: 6),
          AnimatedRotation(
            turns: open ? 0.5 : 0.0,
            duration: const Duration(milliseconds: 200),
            child: Icon(
              CupertinoIcons.chevron_down,
              size: 16,
              color: open ? AppColors.electricBlue : AppColors.textTertiary,
            ),
          ),
        ],
      ),
    );
  }
}

/// Поле времени: по умолчанию — простое «м:сс», по тапу красиво разворачивается
/// барабан (только при редактировании), выбрал — снова простое значение.
class ToolTimeField extends StatefulWidget {
  final String label;
  final Duration value;
  final ValueChanged<Duration> onChanged;

  const ToolTimeField({
    super.key,
    required this.label,
    required this.value,
    required this.onChanged,
  });

  @override
  State<ToolTimeField> createState() => _ToolTimeFieldState();
}

class _ToolTimeFieldState extends State<ToolTimeField> {
  bool _open = false;

  static String _fmt(Duration d) {
    final m = d.inMinutes;
    final s = d.inSeconds % 60;
    return '$m:${s.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => setState(() => _open = !_open),
          child: _FieldHeader(
            label: widget.label,
            value: _fmt(widget.value),
            open: _open,
          ),
        ),
        AnimatedSize(
          duration: const Duration(milliseconds: 220),
          curve: Curves.easeOut,
          alignment: Alignment.topCenter,
          child: _open
              ? Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: ToolTimePicker(
                    initial: widget.value,
                    onChanged: widget.onChanged,
                  ),
                )
              : const SizedBox(width: double.infinity),
        ),
      ],
    );
  }
}

/// Поле выбора из списка: по умолчанию — выбранное значение, по тапу — барабан.
class ToolValueField extends StatefulWidget {
  final String label;
  final List<String> items;
  final int index;
  final ValueChanged<int> onChanged;

  const ToolValueField({
    super.key,
    required this.label,
    required this.items,
    required this.index,
    required this.onChanged,
  });

  @override
  State<ToolValueField> createState() => _ToolValueFieldState();
}

class _ToolValueFieldState extends State<ToolValueField> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => setState(() => _open = !_open),
          child: _FieldHeader(
            label: widget.label,
            value: widget.items[widget.index],
            open: _open,
          ),
        ),
        AnimatedSize(
          duration: const Duration(milliseconds: 220),
          curve: Curves.easeOut,
          alignment: Alignment.topCenter,
          child: _open
              ? Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: ToolValuePicker(
                    items: widget.items,
                    index: widget.index,
                    onChanged: widget.onChanged,
                  ),
                )
              : const SizedBox(width: double.infinity),
        ),
      ],
    );
  }
}

/// Барабан-пикер времени (мин : сек) в стиле будильника iOS.
class ToolTimePicker extends StatelessWidget {
  final Duration initial;
  final ValueChanged<Duration> onChanged;
  final double height;

  const ToolTimePicker({
    super.key,
    required this.initial,
    required this.onChanged,
    this.height = 150,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: height,
      child: CupertinoTheme(
        data: CupertinoThemeData(
          brightness: Brightness.dark,
          textTheme: CupertinoTextThemeData(
            pickerTextStyle: TextStyle(
              color: AppColors.textPrimary,
              fontSize: 22,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        child: CupertinoTimerPicker(
          mode: CupertinoTimerPickerMode.ms,
          initialTimerDuration: initial,
          onTimerDurationChanged: onChanged,
        ),
      ),
    );
  }
}

/// Барабан-пикер выбора значения из списка (числа) в стиле iOS.
class ToolValuePicker extends StatefulWidget {
  final List<String> items;
  final int index;
  final ValueChanged<int> onChanged;
  final double height;

  const ToolValuePicker({
    super.key,
    required this.items,
    required this.index,
    required this.onChanged,
    this.height = 150,
  });

  @override
  State<ToolValuePicker> createState() => _ToolValuePickerState();
}

class _ToolValuePickerState extends State<ToolValuePicker> {
  late final FixedExtentScrollController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = FixedExtentScrollController(initialItem: widget.index);
  }

  @override
  void didUpdateWidget(covariant ToolValuePicker old) {
    super.didUpdateWidget(old);
    if (widget.index != old.index &&
        _ctrl.hasClients &&
        _ctrl.selectedItem != widget.index) {
      _ctrl.animateToItem(
        widget.index,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    }
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: widget.height,
      child: CupertinoTheme(
        data: const CupertinoThemeData(brightness: Brightness.dark),
        child: CupertinoPicker(
          scrollController: _ctrl,
          itemExtent: 40,
          onSelectedItemChanged: widget.onChanged,
          selectionOverlay: CupertinoPickerDefaultSelectionOverlay(
            background: AppColors.electricBlue.withValues(alpha: 0.10),
          ),
          children: [
            for (final s in widget.items)
              Center(
                child: Text(
                  s,
                  style: TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 20,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
