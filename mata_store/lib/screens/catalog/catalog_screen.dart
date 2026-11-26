import 'package:flutter/material.dart';
import 'package:mata_ui/mata_ui.dart';
import 'package:provider/provider.dart';
import 'package:reorderable_grid_view/reorderable_grid_view.dart';
import 'package:shimmer/shimmer.dart';
import '../../models/product.dart';
import '../../providers/catalog_provider.dart';
import '../../theme/app_states.dart';
import '../../theme/app_theme.dart';
import '../../util/console_bridge.dart';
import '../../widgets/product_card.dart';
import '../../widgets/remote_text.dart';

// Сетка каталога (2 колонки) — общая для обычного и режима правки конструктора.
const _catalogGrid = SliverGridDelegateWithFixedCrossAxisCount(
  crossAxisCount: 2,
  crossAxisSpacing: 12,
  mainAxisSpacing: 16,
  childAspectRatio: 0.58,
);

// ─── Filter state model ───────────────────────────────────────────────────────

class CatalogFilters {
  final RangeValues? priceRange;
  final Set<String> brands;
  final Set<String> sizes;
  final bool onlySale;
  final bool onlyNew;

  const CatalogFilters({
    this.priceRange,
    this.brands = const {},
    this.sizes = const {},
    this.onlySale = false,
    this.onlyNew = false,
  });

  bool get isActive =>
      priceRange != null ||
      brands.isNotEmpty ||
      sizes.isNotEmpty ||
      onlySale ||
      onlyNew;

  int get activeCount {
    var n = 0;
    if (priceRange != null) n++;
    n += brands.length;
    n += sizes.length;
    if (onlySale) n++;
    if (onlyNew) n++;
    return n;
  }

  bool matches(Product p) {
    if (priceRange != null) {
      if (p.price < priceRange!.start || p.price > priceRange!.end) {
        return false;
      }
    }
    if (brands.isNotEmpty && !brands.contains(p.brand)) return false;
    if (sizes.isNotEmpty && !p.sizes.any(sizes.contains)) return false;
    if (onlySale && !p.isOnSale) return false;
    if (onlyNew && !p.isNew) return false;
    return true;
  }
}

// ─── Catalog screen ───────────────────────────────────────────────────────────

class CatalogScreen extends StatefulWidget {
  final String? initialCategory;

  /// Раздел витрины с главной (плитки категорий): вкладка и группа (D-133).
  final String? initialTab;
  final String? initialGroup;

  const CatalogScreen(
      {super.key, this.initialCategory, this.initialTab, this.initialGroup});

  @override
  State<CatalogScreen> createState() => _CatalogScreenState();
}

class _CatalogScreenState extends State<CatalogScreen> {
  // Вкладка витрины ('all' — всё) и группа внутри неё (D-133). Без вкладок от
  // бэкенда (старый сервер) _selectedTab — это id категории, как раньше.
  String _selectedTab = 'all';
  String? _selectedGroup;
  // Переход в каталог по категории 1С (с главной): раскладываем по вкладке и
  // группе, когда вкладки загрузятся; до этого фильтруем по самой категории.
  String? _pendingCategory;
  String _sortBy = 'default';
  CatalogFilters _filters = const CatalogFilters();

  // Режим правки конструктора: локальный перетаскиваемый порядок товаров.
  List<Product>? _editOrder;

  @override
  void initState() {
    super.initState();
    _applyRoute();
    // Переключение «Просмотр⇄Правка» из конструктора → пересобрать экран
    // (в правке — редактор порядка, в просмотре — обычный каталог).
    consoleEditNotifier.addListener(_onEditToggle);
  }

  /// Параметры перехода. Экран каталога живёт в своей ветке оболочки и не
  /// пересоздаётся — повторный переход с другой плиткой приходит в didUpdateWidget.
  void _applyRoute() {
    final tab = widget.initialTab;
    if (tab != null && tab.isNotEmpty) {
      _selectedTab = tab;
      _selectedGroup = widget.initialGroup;
      _pendingCategory = null;
      return;
    }
    final initial = widget.initialCategory;
    if (initial != null && initial != 'all') _pendingCategory = initial;
  }

  @override
  void didUpdateWidget(covariant CatalogScreen old) {
    super.didUpdateWidget(old);
    if (old.initialTab != widget.initialTab ||
        old.initialGroup != widget.initialGroup ||
        old.initialCategory != widget.initialCategory) {
      _applyRoute();
    }
  }

  void _onEditToggle() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    consoleEditNotifier.removeListener(_onEditToggle);
    super.dispose();
  }

  List<Product> _filtered(CatalogProvider catalog) {
    _resolvePendingCategory(catalog);
    final List<Product> base;
    if (_pendingCategory != null) {
      base = catalog.byCategory(_pendingCategory!);
    } else if (catalog.showcase.isEmpty) {
      base = catalog.byCategory(_selectedTab);
    } else {
      base = catalog.byShowcase(_selectedTab, groupId: _selectedGroup);
    }
    var products = base.where(_filters.matches).toList();
    switch (_sortBy) {
      case 'price_asc':
        products.sort((a, b) => a.price.compareTo(b.price));
      case 'price_desc':
        products.sort((a, b) => b.price.compareTo(a.price));
      case 'new':
        products.sort((a, b) {
          if (a.isNew == b.isNew) return 0;
          return a.isNew ? -1 : 1;
        });
    }
    return products;
  }

  void _resolvePendingCategory(CatalogProvider catalog) {
    final pending = _pendingCategory;
    if (pending == null || catalog.showcase.isEmpty) return;
    final (tab, group) = catalog.placeOfCategory(pending);
    if (tab == null) return;
    _selectedTab = tab.id;
    _selectedGroup = tab.groups.length > 1 ? group?.id : null;
    _pendingCategory = null;
  }

  void _selectTab(String id) => setState(() {
        _selectedTab = id;
        _selectedGroup = null;
        _pendingCategory = null;
      });

  void _selectGroup(String id) => setState(() {
        // Повторное нажатие снимает группу — снова вся вкладка.
        _selectedGroup = _selectedGroup == id ? null : id;
      });

  Future<void> _openFilters() async {
    final catalog = context.read<CatalogProvider>();
    final result = await showModalBottomSheet<CatalogFilters>(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppColors.white,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
      builder: (_) => _FilterSheet(
        initial: _filters,
        brands: catalog.brands,
        sizes: catalog.sizes,
        minPrice: catalog.minPrice,
        maxPrice: catalog.maxPrice,
      ),
    );
    if (result != null) setState(() => _filters = result);
  }

  // Режим правки конструктора: перетаскиваемая сетка товаров (порядок приложения).
  Widget _buildEditor(BuildContext context, CatalogProvider catalog) {
    final all = catalog.byCategory('all');
    if (_editOrder == null || _editOrder!.length != all.length) {
      _editOrder = List.of(all);
    }
    final items = _editOrder!;
    return Scaffold(
      backgroundColor: AppColors.white,
      appBar: AppBar(
          title: const RemoteText('app.catalog.title.edit', 'КАТАЛОГ · правка')),
      body: Column(
        children: [
          Container(
            width: double.infinity,
            color: const Color(0xFFFFF7E6),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            child: const Text(
              'Потяните карточку мышью, чтобы изменить порядок в приложении. '
              'Опубликовать — кнопкой в конструкторе.',
              style: TextStyle(fontSize: 12, color: Color(0xFF8A5A00)),
            ),
          ),
          Expanded(
            child: items.isEmpty
                ? const Center(
                    child: RemoteText('app.catalog.emptyProducts', 'Нет товаров'))
                : ReorderableGridView.builder(
                    padding: const EdgeInsets.all(16),
                    gridDelegate: _catalogGrid,
                    // Тащить сразу по нажатию (без долгого удержания);
                    // прокрутка на десктопе — колёсиком, конфликта нет.
                    dragStartDelay: Duration.zero,
                    itemCount: items.length,
                    itemBuilder: (context, index) => Container(
                      key: ValueKey(items[index].id),
                      child: ProductCard(product: items[index]),
                    ),
                    onReorder: (oldIndex, newIndex) {
                      setState(() {
                        final item = items.removeAt(oldIndex);
                        items.insert(newIndex, item);
                      });
                      postReorder(items.map((p) => p.id).toList());
                    },
                  ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final catalog = context.watch<CatalogProvider>();
    if (consoleEditNotifier.value) return _buildEditor(context, catalog);
    final products = _filtered(catalog);
    return Scaffold(
      backgroundColor: AppColors.white,
      appBar: AppBar(
        title: const RemoteText('app.catalog.title', 'КАТАЛОГ'),
        actions: [
          _FilterButton(
            activeCount: _filters.activeCount,
            onTap: _openFilters,
          ),
          _SortButton(
            current: _sortBy,
            onChanged: (val) => setState(() => _sortBy = val),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: Column(
        children: [
          _ShowcaseFilter(
            selectedTab: _pendingCategory ?? _selectedTab,
            selectedGroup: _selectedGroup,
            onTab: _selectTab,
            onGroup: _selectGroup,
          ),
          const Divider(height: 1),

          // Active filters summary bar
          if (_filters.isActive)
            _ActiveFiltersBar(
              filters: _filters,
              count: products.length,
              onClear: () => setState(() => _filters = const CatalogFilters()),
            ),

          Expanded(
            // Каталог ещё грузится — сетка-заглушка, а не «Ничего не найдено»:
            // человек принимал загрузку за сломанный каталог (аудит 21.11.2026).
            child: products.isEmpty && catalog.isLoading
                ? const _GridSkeleton()
                : products.isEmpty
                ? _EmptyResult(
                    onReset: () =>
                        setState(() => _filters = const CatalogFilters()),
                  )
                : GridView.builder(
                    padding: const EdgeInsets.all(16),
                    gridDelegate: _catalogGrid,
                    itemCount: products.length,
                    itemBuilder: (context, index) {
                      return ProductCard(product: products[index]);
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

// ─── Заглушка сетки на время загрузки ────────────────────────────────────────

class _GridSkeleton extends StatelessWidget {
  const _GridSkeleton();

  @override
  Widget build(BuildContext context) {
    return Shimmer.fromColors(
      baseColor: AppColors.grey100,
      highlightColor: AppColors.white,
      child: GridView.builder(
        physics: const NeverScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        gridDelegate: _catalogGrid,
        itemCount: 6,
        itemBuilder: (_, __) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: Container(color: AppColors.grey100)),
            const SizedBox(height: 10),
            Container(height: 12, width: 110, color: AppColors.grey100),
            const SizedBox(height: 6),
            Container(height: 12, width: 70, color: AppColors.grey100),
          ],
        ),
      ),
    );
  }
}

// ─── Active filters bar ───────────────────────────────────────────────────────

class _ActiveFiltersBar extends StatelessWidget {
  final CatalogFilters filters;
  final int count;
  final VoidCallback onClear;

  const _ActiveFiltersBar({
    required this.filters,
    required this.count,
    required this.onClear,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      color: AppColors.grey100,
      child: Row(
        children: [
          const Icon(Icons.filter_list, size: 16, color: AppColors.black),
          const SizedBox(width: 8),
          Text(
            '$count ${_plural(count)} · ${filters.activeCount} '
            '${_filterPlural(filters.activeCount)}',
            style: const TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: AppColors.black,
            ),
          ),
          const Spacer(),
          GestureDetector(
            onTap: onClear,
            child: const RemoteText(
              'app.catalog.clear',
              'Сбросить',
              style: TextStyle(
                fontSize: 13,
                color: AppColors.red,
                decoration: TextDecoration.underline,
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _plural(int n) {
    if (n % 10 == 1 && n % 100 != 11) return 'товар';
    if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) {
      return 'товара';
    }
    return 'товаров';
  }

  String _filterPlural(int n) {
    if (n % 10 == 1 && n % 100 != 11) return 'фильтр';
    if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) {
      return 'фильтра';
    }
    return 'фильтров';
  }
}

// ─── Empty result ─────────────────────────────────────────────────────────────

class _EmptyResult extends StatelessWidget {
  final VoidCallback onReset;
  const _EmptyResult({required this.onReset});

  @override
  Widget build(BuildContext context) {
    return MataEmpty(
      icon: Icons.search_off,
      iconColor: AppStates.icon,
      titleWidget: const RemoteText(
        'app.catalog.empty.title',
        'Ничего не найдено',
        style: AppStates.title,
      ),
      hintWidget: const RemoteText(
        'app.catalog.empty.subtitle',
        'Попробуйте изменить фильтры',
        style: AppStates.hint,
      ),
      action: GestureDetector(
        onTap: onReset,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
          color: AppColors.black,
          child: const RemoteText(
            'app.catalog.empty.reset',
            'СБРОСИТЬ ФИЛЬТРЫ',
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: AppColors.white,
              letterSpacing: 1.5,
            ),
          ),
        ),
      ),
    );
  }
}

// ─── Filter button (with badge) ───────────────────────────────────────────────

class _FilterButton extends StatelessWidget {
  final int activeCount;
  final VoidCallback onTap;

  const _FilterButton({required this.activeCount, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Stack(
      clipBehavior: Clip.none,
      children: [
        IconButton(
          onPressed: onTap,
          icon: Icon(
            Icons.tune,
            color: activeCount > 0 ? AppColors.black : AppColors.grey600,
          ),
        ),
        if (activeCount > 0)
          Positioned(
            right: 6,
            top: 6,
            child: Container(
              width: 16,
              height: 16,
              decoration: const BoxDecoration(
                color: AppColors.black,
                shape: BoxShape.circle,
              ),
              alignment: Alignment.center,
              child: Text(
                '$activeCount',
                style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                ),
              ),
            ),
          ),
      ],
    );
  }
}

// ─── Filter bottom sheet ──────────────────────────────────────────────────────

class _FilterSheet extends StatefulWidget {
  final CatalogFilters initial;
  final List<String> brands;
  final List<String> sizes;
  final double minPrice;
  final double maxPrice;

  const _FilterSheet({
    required this.initial,
    required this.brands,
    required this.sizes,
    required this.minPrice,
    required this.maxPrice,
  });

  @override
  State<_FilterSheet> createState() => _FilterSheetState();
}

class _FilterSheetState extends State<_FilterSheet> {
  late RangeValues _priceRange;
  late Set<String> _brands;
  late Set<String> _sizes;
  late bool _onlySale;
  late bool _onlyNew;

  late final double _minPrice;
  late final double _maxPrice;

  @override
  void initState() {
    super.initState();
    _minPrice = widget.minPrice;
    _maxPrice = widget.maxPrice;
    _priceRange = widget.initial.priceRange ??
        RangeValues(_minPrice, _maxPrice);
    _brands = {...widget.initial.brands};
    _sizes = {...widget.initial.sizes};
    _onlySale = widget.initial.onlySale;
    _onlyNew = widget.initial.onlyNew;
  }

  bool get _priceChanged =>
      _priceRange.start > _minPrice || _priceRange.end < _maxPrice;

  void _reset() {
    setState(() {
      _priceRange = RangeValues(_minPrice, _maxPrice);
      _brands.clear();
      _sizes.clear();
      _onlySale = false;
      _onlyNew = false;
    });
  }

  void _apply() {
    Navigator.pop(
      context,
      CatalogFilters(
        priceRange: _priceChanged ? _priceRange : null,
        brands: _brands,
        sizes: _sizes,
        onlySale: _onlySale,
        onlyNew: _onlyNew,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.78,
      minChildSize: 0.5,
      maxChildSize: 0.95,
      expand: false,
      builder: (context, scrollController) {
        return Column(
          children: [
            // Handle + title
            Container(
              padding: const EdgeInsets.fromLTRB(20, 12, 12, 12),
              decoration: const BoxDecoration(
                border: Border(
                  bottom: BorderSide(color: AppColors.grey200),
                ),
              ),
              child: Row(
                children: [
                  RemoteText(
                    'app.catalog.filters',
                    'ФИЛЬТРЫ',
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 2,
                      color: AppColors.black,
                    ),
                  ),
                  const Spacer(),
                  TextButton(
                    onPressed: _reset,
                    child: const RemoteText(
                      'app.catalog.reset',
                      'Сбросить',
                      style: TextStyle(
                        color: AppColors.grey600,
                        fontSize: 14,
                      ),
                    ),
                  ),
                  GestureDetector(
                    onTap: () => Navigator.pop(context),
                    child: const Padding(
                      padding: EdgeInsets.all(6),
                      child: Icon(Icons.close, size: 22),
                    ),
                  ),
                ],
              ),
            ),

            Expanded(
              child: ListView(
                controller: scrollController,
                padding: const EdgeInsets.fromLTRB(20, 20, 20, 20),
                children: [
                  // Price
                  _SectionTitle('app.catalog.filterPrice', 'Цена, ₽'),
                  const SizedBox(height: 4),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      _PriceChip('${_priceRange.start.toInt()} ₽'),
                      Container(
                        width: 20,
                        height: 1,
                        color: AppColors.grey200,
                      ),
                      _PriceChip('${_priceRange.end.toInt()} ₽'),
                    ],
                  ),
                  RangeSlider(
                    values: _priceRange,
                    min: _minPrice,
                    max: _maxPrice,
                    divisions: 24,
                    activeColor: AppColors.black,
                    inactiveColor: AppColors.grey200,
                    labels: RangeLabels(
                      '${_priceRange.start.toInt()}',
                      '${_priceRange.end.toInt()}',
                    ),
                    onChanged: (v) => setState(() => _priceRange = v),
                  ),

                  const SizedBox(height: 16),

                  // Brand
                  _SectionTitle('app.catalog.filterBrand', 'Бренд'),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: widget.brands.map((brand) {
                      final selected = _brands.contains(brand);
                      return _FilterChip(
                        label: brand,
                        selected: selected,
                        onTap: () => setState(() {
                          if (selected) {
                            _brands.remove(brand);
                          } else {
                            _brands.add(brand);
                          }
                        }),
                      );
                    }).toList(),
                  ),

                  const SizedBox(height: 24),

                  // Size
                  _SectionTitle('app.catalog.filterSize', 'Размер'),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: widget.sizes.map((size) {
                      final selected = _sizes.contains(size);
                      return _FilterChip(
                        label: size,
                        selected: selected,
                        compact: true,
                        onTap: () => setState(() {
                          if (selected) {
                            _sizes.remove(size);
                          } else {
                            _sizes.add(size);
                          }
                        }),
                      );
                    }).toList(),
                  ),

                  const SizedBox(height: 24),

                  // Toggles
                  _SectionTitle('app.catalog.filterExtra', 'Дополнительно'),
                  const SizedBox(height: 8),
                  _ToggleRow(
                    contentKey: 'app.catalog.onlySale',
                    label: 'Только со скидкой',
                    value: _onlySale,
                    onChanged: (v) => setState(() => _onlySale = v),
                  ),
                  _ToggleRow(
                    contentKey: 'app.catalog.onlyNew',
                    label: 'Только новинки',
                    value: _onlyNew,
                    onChanged: (v) => setState(() => _onlyNew = v),
                  ),

                  const SizedBox(height: 16),
                ],
              ),
            ),

            // Apply button
            Container(
              padding: EdgeInsets.fromLTRB(
                20,
                12,
                20,
                12 + MediaQuery.of(context).padding.bottom,
              ),
              decoration: const BoxDecoration(
                border: Border(top: BorderSide(color: AppColors.grey200)),
              ),
              child: GestureDetector(
                onTap: _apply,
                child: Container(
                  height: 52,
                  color: AppColors.black,
                  alignment: Alignment.center,
                  child: RemoteText(
                    'app.catalog.showProducts',
                    'ПОКАЗАТЬ ТОВАРЫ',
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: AppColors.white,
                      letterSpacing: 2,
                    ),
                  ),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String contentKey;
  final String text;
  const _SectionTitle(this.contentKey, this.text);

  @override
  Widget build(BuildContext context) {
    return RemoteText(
      contentKey,
      text,
      upper: true,
      style: const TextStyle(
        fontSize: 12,
        fontWeight: FontWeight.w700,
        letterSpacing: 1,
        color: AppColors.black,
      ),
    );
  }
}

class _PriceChip extends StatelessWidget {
  final String text;
  const _PriceChip(this.text);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      decoration: BoxDecoration(
        border: Border.all(color: AppColors.grey200),
      ),
      child: Text(
        text,
        style: const TextStyle(
          fontSize: 14,
          fontWeight: FontWeight.w700,
          color: AppColors.black,
        ),
      ),
    );
  }
}

class _FilterChip extends StatelessWidget {
  final String label;
  final bool selected;
  final bool compact;
  final VoidCallback onTap;

  const _FilterChip({
    required this.label,
    required this.selected,
    required this.onTap,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        padding: EdgeInsets.symmetric(
          horizontal: compact ? 16 : 18,
          vertical: 10,
        ),
        decoration: BoxDecoration(
          color: selected ? AppColors.black : AppColors.white,
          border: Border.all(
            color: selected ? AppColors.black : AppColors.grey400,
            width: selected ? 1.5 : 1,
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 13,
            fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
            color: selected ? AppColors.white : AppColors.black,
          ),
        ),
      ),
    );
  }
}

class _ToggleRow extends StatelessWidget {
  final String contentKey;
  final String label;
  final bool value;
  final ValueChanged<bool> onChanged;

  const _ToggleRow({
    required this.contentKey,
    required this.label,
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => onChanged(!value),
      behavior: HitTestBehavior.opaque,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Row(
          children: [
            RemoteText(
              contentKey,
              label,
              style: const TextStyle(fontSize: 14, color: AppColors.black),
            ),
            const Spacer(),
            // Custom mono switch
            AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              width: 44,
              height: 26,
              padding: const EdgeInsets.all(3),
              decoration: BoxDecoration(
                color: value ? AppColors.black : AppColors.grey200,
                borderRadius: BorderRadius.circular(13),
              ),
              alignment:
                  value ? Alignment.centerRight : Alignment.centerLeft,
              child: Container(
                width: 20,
                height: 20,
                decoration: const BoxDecoration(
                  color: Colors.white,
                  shape: BoxShape.circle,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ─── Category filter (unchanged) ──────────────────────────────────────────────

/// Ряд вкладок («Все · Обувь · Одежда…») и под ним — группы выбранной вкладки
/// («Кроссовки · Ботинки»). Без вкладок от бэкенда — прежний ряд категорий 1С.
class _ShowcaseFilter extends StatelessWidget {
  final String selectedTab;
  final String? selectedGroup;
  final ValueChanged<String> onTab;
  final ValueChanged<String> onGroup;

  const _ShowcaseFilter({
    required this.selectedTab,
    required this.selectedGroup,
    required this.onTab,
    required this.onGroup,
  });

  @override
  Widget build(BuildContext context) {
    final catalog = context.watch<CatalogProvider>();
    final tabs = catalog.showcase;
    final List<(String, String)> row;
    if (tabs.isEmpty) {
      row = [for (final c in catalog.categories) (c.id, c.name)];
    } else {
      final all = catalog.categoryById('all');
      row = [
        ('all', all?.name ?? 'Все'),
        for (final t in tabs) (t.id, t.name),
      ];
    }
    final tab = catalog.tabById(selectedTab);
    final groups = tab != null && tab.groups.length > 1 ? tab.groups : null;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          height: 52,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            itemCount: row.length,
            separatorBuilder: (_, __) => const SizedBox(width: 8),
            itemBuilder: (context, index) {
              final (id, name) = row[index];
              return _TabChip(
                key: ValueKey('tab-$id'),
                label: name,
                selected: id == selectedTab,
                onTap: () => onTab(id),
              );
            },
          ),
        ),
        if (groups != null)
          SizedBox(
            height: 44,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              itemCount: groups.length,
              separatorBuilder: (_, __) => const SizedBox(width: 8),
              itemBuilder: (context, index) {
                final g = groups[index];
                return _GroupChip(
                  key: ValueKey('group-${g.id}'),
                  label: g.name,
                  count: g.count,
                  selected: g.id == selectedGroup,
                  onTap: () => onGroup(g.id),
                );
              },
            ),
          ),
      ],
    );
  }
}

class _TabChip extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _TabChip({super.key, required this.label, required this.selected, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      selected: selected,
      child: GestureDetector(
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: selected ? AppColors.black : AppColors.grey100,
            borderRadius: BorderRadius.circular(20),
          ),
          child: Text(
            label,
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: selected ? AppColors.white : AppColors.black,
            ),
          ),
        ),
      ),
    );
  }
}

/// Группа — мельче и тише вкладки: обводка вместо заливки, рядом число карточек.
class _GroupChip extends StatelessWidget {
  final String label;
  final int count;
  final bool selected;
  final VoidCallback onTap;

  const _GroupChip({
    super.key,
    required this.label,
    required this.count,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      selected: selected,
      child: GestureDetector(
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          padding: const EdgeInsets.symmetric(horizontal: 12),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: selected ? AppColors.grey100 : AppColors.white,
            borderRadius: BorderRadius.circular(18),
            border: Border.all(
              color: selected ? AppColors.black : AppColors.grey400,
            ),
          ),
          child: Text.rich(
            TextSpan(children: [
              TextSpan(
                text: label,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: selected ? FontWeight.w700 : FontWeight.w600,
                  color: AppColors.black,
                ),
              ),
              TextSpan(
                text: '  $count',
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w500,
                  color: AppColors.grey600,
                ),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

// ─── Sort button (unchanged) ──────────────────────────────────────────────────

class _SortButton extends StatelessWidget {
  final String current;
  final ValueChanged<String> onChanged;

  const _SortButton({required this.current, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return IconButton(
      onPressed: () async {
        final result = await showModalBottomSheet<String>(
          context: context,
          shape: const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
          builder: (_) => _SortSheet(current: current),
        );
        if (result != null) onChanged(result);
      },
      icon: Icon(
        Icons.sort,
        color: current != 'default' ? AppColors.black : AppColors.grey600,
      ),
    );
  }
}

class _SortSheet extends StatelessWidget {
  final String current;

  const _SortSheet({required this.current});

  @override
  Widget build(BuildContext context) {
    final options = [
      ('default', 'По умолчанию'),
      ('price_asc', 'Цена: по возрастанию'),
      ('price_desc', 'Цена: по убыванию'),
      ('new', 'Сначала новинки'),
    ];

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 36,
            height: 4,
            margin: const EdgeInsets.only(bottom: 12),
            decoration: BoxDecoration(
              color: AppColors.grey200,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Align(
              alignment: Alignment.centerLeft,
              child: RemoteText(
                'app.catalog.sort',
                'СОРТИРОВКА',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1,
                  color: AppColors.black,
                ),
              ),
            ),
          ),
          ...options.map(
            (opt) => ListTile(
              title: Text(
                opt.$2,
                style: TextStyle(
                  fontWeight: opt.$1 == current
                      ? FontWeight.w700
                      : FontWeight.w400,
                ),
              ),
              trailing: opt.$1 == current
                  ? const Icon(Icons.check, size: 18)
                  : null,
              onTap: () => Navigator.pop(context, opt.$1),
            ),
          ),
          const SizedBox(height: 8),
        ],
      ),
    );
  }
}
