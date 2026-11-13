import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../models/category.dart';
import '../../models/product.dart';
import '../../providers/catalog_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/product_card.dart';
import '../../widgets/remote_image.dart';

// ─── Session-level recent searches ───────────────────────────────────────────
final _recentSearches = <String>[];

enum _SearchState { idle, typing, results }

class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key});

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  final _controller = TextEditingController();
  final _focusNode = FocusNode();

  _SearchState _state = _SearchState.idle;
  List<String> _suggestions = [];
  List<Product> _results = [];
  String _activeQuery = '';
  String _selectedCategory = 'all';

  static const _popular = [
    'Беговые кроссовки',
    'Худи',
    'Ветровка',
    'Рюкзак',
    'Компрессия',
    'Зимняя куртка',
    'Термобельё',
    'Перчатки',
  ];

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  void _onChanged(String value) {
    final q = value.trim();
    if (q.isEmpty) {
      setState(() {
        _state = _SearchState.idle;
        _suggestions = [];
      });
      return;
    }

    final catalog = context.read<CatalogProvider>();
    final ql = q.toLowerCase();
    final sugg = <String>{};
    for (final p in catalog.products) {
      if (p.name.toLowerCase().contains(ql)) sugg.add(p.name);
    }
    for (final c in catalog.categories) {
      if (c.id != 'all' && c.name.toLowerCase().contains(ql)) sugg.add(c.name);
    }
    for (final pop in _popular) {
      if (pop.toLowerCase().contains(ql)) sugg.add(pop);
    }
    for (final r in _recentSearches) {
      if (r.toLowerCase().contains(ql)) sugg.add(r);
    }

    setState(() {
      _state = _SearchState.typing;
      _suggestions = sugg.take(8).toList();
    });
  }

  void _submitSearch(String query) {
    final q = query.trim();
    if (q.isEmpty) return;
    _controller.text = q;
    _focusNode.unfocus();

    _recentSearches.remove(q);
    _recentSearches.insert(0, q);
    if (_recentSearches.length > 8) _recentSearches.removeLast();

    setState(() {
      _activeQuery = q;
      _selectedCategory = 'all';
      _results = context.read<CatalogProvider>().search(q);
      _state = _SearchState.results;
    });
  }

  List<Product> get _filteredResults {
    if (_selectedCategory == 'all') return _results;
    return _results.where((p) => p.categoryId == _selectedCategory).toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.white,
      body: SafeArea(
        child: Column(
          children: [
            _SearchBar(
              controller: _controller,
              focusNode: _focusNode,
              onChanged: _onChanged,
              onSubmitted: _submitSearch,
              onCancel: () => Navigator.of(context).pop(),
              onClear: () {
                _controller.clear();
                _onChanged('');
                _focusNode.requestFocus();
              },
            ),
            const Divider(height: 1),
            Expanded(child: _buildBody()),
          ],
        ),
      ),
    );
  }

  Widget _buildBody() {
    switch (_state) {
      case _SearchState.idle:
        return _IdleView(
          popular: _popular,
          onSearch: _submitSearch,
          onRemoveRecent: (q) => setState(() => _recentSearches.remove(q)),
          onClearRecents: () => setState(() => _recentSearches.clear()),
        );
      case _SearchState.typing:
        return _SuggestionsView(
          suggestions: _suggestions,
          query: _controller.text.trim(),
          onTap: _submitSearch,
        );
      case _SearchState.results:
        return _ResultsView(
          query: _activeQuery,
          results: _filteredResults,
          allResults: _results,
          selectedCategory: _selectedCategory,
          onCategoryChanged: (c) => setState(() => _selectedCategory = c),
        );
    }
  }
}

// ─── Search bar ───────────────────────────────────────────────────────────────

class _SearchBar extends StatelessWidget {
  final TextEditingController controller;
  final FocusNode focusNode;
  final ValueChanged<String> onChanged;
  final ValueChanged<String> onSubmitted;
  final VoidCallback onCancel;
  final VoidCallback onClear;

  const _SearchBar({
    required this.controller,
    required this.focusNode,
    required this.onChanged,
    required this.onSubmitted,
    required this.onCancel,
    required this.onClear,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
      child: Row(
        children: [
          Expanded(
            child: Container(
              height: 46,
              decoration: BoxDecoration(
                color: AppColors.grey100,
                borderRadius: BorderRadius.circular(4),
              ),
              child: Row(
                children: [
                  const SizedBox(width: 12),
                  const Icon(Icons.search, size: 20, color: AppColors.grey600),
                  const SizedBox(width: 8),
                  Expanded(
                    child: TextField(
                      controller: controller,
                      focusNode: focusNode,
                      autofocus: true,
                      onChanged: onChanged,
                      onSubmitted: onSubmitted,
                      textInputAction: TextInputAction.search,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w400,
                        color: AppColors.black,
                      ),
                      decoration: const InputDecoration(
                        hintText: 'Поиск товаров',
                        hintStyle: TextStyle(
                          fontSize: 15,
                          color: AppColors.grey500,
                        ),
                        border: InputBorder.none,
                        enabledBorder: InputBorder.none,
                        focusedBorder: InputBorder.none,
                        filled: false,
                        isDense: true,
                        contentPadding: EdgeInsets.zero,
                      ),
                    ),
                  ),
                  ValueListenableBuilder(
                    valueListenable: controller,
                    builder: (_, value, __) {
                      if (value.text.isEmpty) return const SizedBox.shrink();
                      return GestureDetector(
                        onTap: onClear,
                        child: Container(
                          padding: const EdgeInsets.all(8),
                          child: const Icon(
                            Icons.cancel,
                            size: 18,
                            color: AppColors.grey400,
                          ),
                        ),
                      );
                    },
                  ),
                  const SizedBox(width: 4),
                ],
              ),
            ),
          ),
          const SizedBox(width: 12),
          GestureDetector(
            onTap: onCancel,
            child: const Text(
              'Отмена',
              style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w500,
                color: AppColors.black,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Idle view (no input) ─────────────────────────────────────────────────────

class _IdleView extends StatelessWidget {
  final List<String> popular;
  final ValueChanged<String> onSearch;
  final ValueChanged<String> onRemoveRecent;
  final VoidCallback onClearRecents;

  const _IdleView({
    required this.popular,
    required this.onSearch,
    required this.onRemoveRecent,
    required this.onClearRecents,
  });

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: EdgeInsets.zero,
      children: [
        if (_recentSearches.isNotEmpty) ...[
          _SectionLabel(
            title: 'НЕДАВНИЕ',
            action: 'Очистить',
            onAction: onClearRecents,
          ),
          ..._recentSearches.map(
            (q) => _RecentItem(
              query: q,
              onTap: () => onSearch(q),
              onRemove: () => onRemoveRecent(q),
            ),
          ),
          const SizedBox(height: 8),
        ],
        _SectionLabel(title: 'ПОПУЛЯРНЫЕ'),
        const SizedBox(height: 12),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Wrap(
            spacing: 8,
            runSpacing: 8,
            children: popular.map((q) {
              return GestureDetector(
                onTap: () => onSearch(q),
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 9,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.grey100,
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(
                    q,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                      color: AppColors.black,
                    ),
                  ),
                ),
              );
            }).toList(),
          ),
        ),
        const SizedBox(height: 28),
        _SectionLabel(title: 'КАТЕГОРИИ'),
        const SizedBox(height: 12),
        _CategoryCards(),
        const SizedBox(height: 24),
      ],
    );
  }
}

class _SectionLabel extends StatelessWidget {
  final String title;
  final String? action;
  final VoidCallback? onAction;

  const _SectionLabel({required this.title, this.action, this.onAction});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.2,
              color: AppColors.grey600,
            ),
          ),
          if (action != null)
            GestureDetector(
              onTap: onAction,
              child: Text(
                action!,
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w500,
                  color: AppColors.grey600,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _RecentItem extends StatelessWidget {
  final String query;
  final VoidCallback onTap;
  final VoidCallback onRemove;

  const _RecentItem({
    required this.query,
    required this.onTap,
    required this.onRemove,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            const Icon(Icons.history, size: 18, color: AppColors.grey400),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                query,
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w400,
                  color: AppColors.black,
                ),
              ),
            ),
            GestureDetector(
              onTap: onRemove,
              behavior: HitTestBehavior.opaque,
              child: Padding(
                padding: const EdgeInsets.only(left: 8),
                child: const Icon(
                  Icons.close,
                  size: 16,
                  color: AppColors.grey400,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CategoryCards extends StatelessWidget {
  static final _categoryImages = {
    'tshirts': 'assets/images/products/1521572163474-6864f9cf17ab.jpg',
    'hoodies': 'assets/images/products/1620799140408-edc6dcb6d633.jpg',
    'pants': 'assets/images/products/1506629082955-511b1aa562c8.jpg',
    'jackets': 'assets/images/products/1591047139829-d91aecb6caea.jpg',
    'shoes': 'assets/images/products/1542291026-7eec264c27ff.jpg',
    'accessories': 'assets/images/products/1553062407-98eeb64c6a62.jpg',
  };

  @override
  Widget build(BuildContext context) {
    final cats = context
        .watch<CatalogProvider>()
        .categories
        .where((c) => c.id != 'all')
        .toList();

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: GridView.builder(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: 2,
          crossAxisSpacing: 8,
          mainAxisSpacing: 8,
          childAspectRatio: 1.6,
        ),
        itemCount: cats.length,
        itemBuilder: (context, index) {
          final cat = cats[index];
          return _CategoryCard(
            category: cat,
            imageUrl: _categoryImages[cat.id] ?? '',
          );
        },
      ),
    );
  }
}

class _CategoryCard extends StatelessWidget {
  final Category category;
  final String imageUrl;

  const _CategoryCard({required this.category, required this.imageUrl});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () {
        final router = GoRouter.of(context);
        Navigator.of(context).pop();
        router.go('/catalog?category=${category.id}');
      },
      child: Stack(
        fit: StackFit.expand,
        children: [
          RemoteImage('app.search.cat.${category.id}.img', fallbackAsset: imageUrl),
          Container(
            decoration: const BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.centerLeft,
                end: Alignment.centerRight,
                colors: [Color(0xCC000000), Colors.transparent],
              ),
            ),
          ),
          Positioned(
            left: 12,
            bottom: 12,
            child: Text(
              category.name.toUpperCase(),
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w800,
                color: AppColors.white,
                letterSpacing: 0.5,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Suggestions view (while typing) ─────────────────────────────────────────

class _SuggestionsView extends StatelessWidget {
  final List<String> suggestions;
  final String query;
  final ValueChanged<String> onTap;

  const _SuggestionsView({
    required this.suggestions,
    required this.query,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    if (suggestions.isEmpty) {
      return InkWell(
        onTap: () => onTap(query),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
          child: Row(
            children: [
              const Icon(Icons.search, size: 18, color: AppColors.grey400),
              const SizedBox(width: 12),
              Expanded(
                child: RichText(
                  text: TextSpan(
                    style: const TextStyle(
                      fontSize: 15,
                      color: AppColors.black,
                    ),
                    children: [
                      const TextSpan(text: 'Найти «'),
                      TextSpan(
                        text: query,
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                      const TextSpan(text: '»'),
                    ],
                  ),
                ),
              ),
              const Icon(
                Icons.north_west,
                size: 16,
                color: AppColors.grey400,
              ),
            ],
          ),
        ),
      );
    }

    return ListView(
      padding: EdgeInsets.zero,
      children: [
        InkWell(
          onTap: () => onTap(query),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            child: Row(
              children: [
                const Icon(Icons.search, size: 18, color: AppColors.black),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    query,
                    style: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: AppColors.black,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
        const Divider(height: 1),
        ...suggestions.map(
          (s) => _SuggestionItem(
            text: s,
            query: query,
            onTap: () => onTap(s),
          ),
        ),
      ],
    );
  }
}

class _SuggestionItem extends StatelessWidget {
  final String text;
  final String query;
  final VoidCallback onTap;

  const _SuggestionItem({
    required this.text,
    required this.query,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final ql = query.toLowerCase();
    final tl = text.toLowerCase();
    final idx = tl.indexOf(ql);

    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
        child: Row(
          children: [
            const Icon(Icons.search, size: 18, color: AppColors.grey400),
            const SizedBox(width: 12),
            Expanded(
              child: idx < 0
                  ? Text(
                      text,
                      style: const TextStyle(
                        fontSize: 15,
                        color: AppColors.black,
                      ),
                    )
                  : RichText(
                      text: TextSpan(
                        style: const TextStyle(
                          fontSize: 15,
                          color: AppColors.black,
                        ),
                        children: [
                          if (idx > 0)
                            TextSpan(
                              text: text.substring(0, idx),
                              style: const TextStyle(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          TextSpan(
                            text: text.substring(idx, idx + query.length),
                            style: const TextStyle(
                              color: AppColors.grey600,
                              fontWeight: FontWeight.w400,
                            ),
                          ),
                          if (idx + query.length < text.length)
                            TextSpan(
                              text: text.substring(idx + query.length),
                              style: const TextStyle(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                        ],
                      ),
                    ),
            ),
            const Icon(Icons.north_west, size: 15, color: AppColors.grey400),
          ],
        ),
      ),
    );
  }
}

// ─── Results view ─────────────────────────────────────────────────────────────

class _ResultsView extends StatelessWidget {
  final String query;
  final List<Product> results;
  final List<Product> allResults;
  final String selectedCategory;
  final ValueChanged<String> onCategoryChanged;

  const _ResultsView({
    required this.query,
    required this.results,
    required this.allResults,
    required this.selectedCategory,
    required this.onCategoryChanged,
  });

  List<String> _availableCategories() {
    final ids = allResults.map((p) => p.categoryId).toSet();
    return ['all', ...ids];
  }

  String _categoryName(BuildContext context, String id) {
    if (id == 'all') return 'Все';
    try {
      return context
          .read<CatalogProvider>()
          .categories
          .firstWhere((c) => c.id == id)
          .name;
    } catch (_) {
      return id;
    }
  }

  @override
  Widget build(BuildContext context) {
    final cats = _availableCategories();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
          child: Text(
            '${allResults.length} ${_plural(allResults.length)} по запросу «$query»',
            style: const TextStyle(
              fontSize: 13,
              color: AppColors.grey600,
            ),
          ),
        ),
        if (cats.length > 2)
          SizedBox(
            height: 48,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
              itemCount: cats.length,
              separatorBuilder: (_, __) => const SizedBox(width: 8),
              itemBuilder: (context, index) {
                final id = cats[index];
                final isSelected = id == selectedCategory;
                return GestureDetector(
                  onTap: () => onCategoryChanged(id),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 150),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 6,
                    ),
                    decoration: BoxDecoration(
                      color: isSelected ? AppColors.black : AppColors.white,
                      border: Border.all(
                        color: isSelected
                            ? AppColors.black
                            : AppColors.grey200,
                      ),
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Text(
                      _categoryName(context, id),
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color:
                            isSelected ? AppColors.white : AppColors.black,
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        const Divider(height: 1),
        if (results.isEmpty)
          Expanded(child: _NoResults(query: query))
        else
          Expanded(
            child: GridView.builder(
              padding: const EdgeInsets.all(16),
              gridDelegate:
                  const SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: 2,
                crossAxisSpacing: 12,
                mainAxisSpacing: 16,
                childAspectRatio: 0.58,
              ),
              itemCount: results.length,
              itemBuilder: (context, index) {
                return ProductCard(product: results[index]);
              },
            ),
          ),
      ],
    );
  }

  String _plural(int n) {
    if (n % 10 == 1 && n % 100 != 11) return 'товар';
    if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) {
      return 'товара';
    }
    return 'товаров';
  }
}

class _NoResults extends StatelessWidget {
  final String query;

  const _NoResults({required this.query});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(40),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(
              Icons.search_off_rounded,
              size: 64,
              color: AppColors.grey200,
            ),
            const SizedBox(height: 16),
            Text(
              'По запросу «$query»\nничего не найдено',
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 17,
                fontWeight: FontWeight.w700,
                color: AppColors.black,
                height: 1.4,
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              'Проверьте написание или\nпопробуйте другой запрос',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 14,
                color: AppColors.grey600,
                height: 1.5,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
