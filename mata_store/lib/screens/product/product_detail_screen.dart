import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';
import '../../data/api/api_config.dart';
import '../../models/product.dart';
import '../../models/review.dart';
import '../../providers/cart_provider.dart';
import '../../providers/catalog_provider.dart';
import '../../providers/wishlist_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/price_text.dart';
import '../../widgets/product_image.dart';
import '../../widgets/remote_text.dart';

class ProductDetailScreen extends StatefulWidget {
  final String productId;
  final String? heroTag;

  const ProductDetailScreen({
    super.key,
    required this.productId,
    this.heroTag,
  });

  @override
  State<ProductDetailScreen> createState() => _ProductDetailScreenState();
}

class _ProductDetailScreenState extends State<ProductDetailScreen> {
  final _pageController = PageController();
  int _currentImage = 0;
  String? _selectedSize;
  String? _selectedColor;
  bool _prefetched = false;

  /// Показать снимок из ленты миниатюр.
  void _showPhoto(int index) {
    setState(() => _currentImage = index);
    if (_pageController.hasClients) {
      _pageController.animateToPage(index,
          duration: const Duration(milliseconds: 220), curve: Curves.easeOut);
    }
  }

  /// Первый снимок каждого цвета — в кэш заранее: переключение цвета должно быть
  /// мгновенным, а не «подождите, грузится» (D-99).
  void _prefetchColors(Product product) {
    if (_prefetched) return;
    _prefetched = true;
    for (final url in product.colorCovers) {
      if (url.isEmpty) continue;
      precacheImage(CachedNetworkImageProvider(url), context);
    }
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  void _addToCart(Product product) {
    // Выбор требуем только там, где есть из чего выбирать: у геля нет размера,
    // у половины каталога 1С ещё не заполнила цвет. Иначе такой товар вообще
    // нельзя положить в корзину — «Выберите размер» при пустом списке.
    if (product.sizes.isNotEmpty && _selectedSize == null) {
      _showErrorSnack('Выберите размер');
      return;
    }
    if (product.colors.isNotEmpty && _selectedColor == null) {
      _showErrorSnack('Выберите цвет');
      return;
    }
    final size = _selectedSize ?? '';
    final color = _selectedColor ?? '';

    // Заказ уходит на складскую позицию: карточка модели — это витрина,
    // а на складе живут отдельные карточки по цвету и размеру (D-94).
    final variant = product.variantFor(size, color);
    if (product.variants.isNotEmpty && variant == null) {
      _showErrorSnack('Этого сочетания нет в наличии');
      return;
    }
    final ordered = variant == null
        ? product
        : product.copyWith(id: variant.productId, price: variant.price);
    context.read<CartProvider>().add(ordered, size, color);
    _showAddedToCartSheet(ordered);
  }

  void _showErrorSnack(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: AppColors.red,
        behavior: SnackBarBehavior.floating,
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
        duration: const Duration(seconds: 2),
      ),
    );
  }

  void _showAddedToCartSheet(Product product) {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: false,
      builder: (_) => _AddedToCartSheet(
        product: product,
        size: _selectedSize!,
        color: _selectedColor!,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final product = context.watch<CatalogProvider>().getById(widget.productId);

    if (product == null) {
      return Scaffold(
        appBar: AppBar(),
        body: const Center(
            child: RemoteText('app.product.notFound', 'Товар не найден')),
      );
    }

    // Первый доступный цвет отмечаем сразу — как на сайте, у Nike и STAW:
    // карточка обязана открыться показанной вещью, а не пустой галереей. Размер
    // человек выбирает сам: это настоящее решение, а цвет виден на фото.
    // Присваиваем без setState: значение используется тут же, в этом же кадре.
    if (_selectedColor == null && product.colors.isNotEmpty) {
      for (final c in product.colors) {
        if (product.hasColor(c)) {
          _selectedColor = c;
          break;
        }
      }
    }
    _prefetchColors(product);

    return Scaffold(
      backgroundColor: AppColors.white,
      body: Stack(
        children: [
          CustomScrollView(
            slivers: [
              _ImageGallery(
                product: product,
                photos: product.photosFor(_selectedColor),
                controller: _pageController,
                currentIndex: _currentImage,
                onPageChanged: (i) => setState(() => _currentImage = i),
                onThumbTap: _showPhoto,
                heroTag: widget.heroTag,
              ),
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        product.brand.toUpperCase(),
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: AppColors.grey600,
                          letterSpacing: 1,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        product.name,
                        style: const TextStyle(
                          fontSize: 22,
                          fontWeight: FontWeight.w800,
                          color: AppColors.black,
                          height: 1.2,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          const Icon(Icons.star,
                              size: 16, color: AppColors.black),
                          const SizedBox(width: 4),
                          Text(
                            '${product.rating}',
                            style: const TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          const SizedBox(width: 4),
                          Text(
                            '(${product.reviewCount} отзывов)',
                            style: const TextStyle(
                              fontSize: 13,
                              color: AppColors.grey600,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      PriceText(
                        price: product.price,
                        oldPrice: product.oldPrice,
                        priceStyle: const TextStyle(
                          fontSize: 22,
                          fontWeight: FontWeight.w600,
                          letterSpacing: -0.6,
                          color: AppColors.black,
                        ),
                      ),
                      const SizedBox(height: 16),
                      // Голос бренда — серифная строка с лаймовой чертой (D-34)
                      Container(
                        padding: const EdgeInsets.only(left: 12),
                        decoration: const BoxDecoration(
                          border: Border(
                            left: BorderSide(color: AppColors.lime, width: 2),
                          ),
                        ),
                        child: RemoteText(
                          'app.product.brandLine',
                          'Рядом с тобой в любом состоянии',
                          style: GoogleFonts.robotoSerif(
                            fontSize: 13,
                            fontStyle: FontStyle.italic,
                            fontWeight: FontWeight.w200,
                            color: AppColors.grey600,
                          ),
                        ),
                      ),
                      const SizedBox(height: 24),
                      const Divider(),
                      const SizedBox(height: 20),
                      // Пустой блок «РАЗМЕР» без единой кнопки только путает:
                      // у геля размера нет, и спрашивать его не о чем.
                      if (product.sizes.isNotEmpty) _SizeSelector(
                        sizes: product.sizes,
                        selected: _selectedSize,
                        // Наличие зависит от цвета: чёрных 42-х может не быть,
                        // а белые лежат. Выбрал цвет — видно, что реально есть.
                        isAvailable: (size) =>
                            product.hasSizeInColor(size, _selectedColor),
                        onSelected: (s) => setState(() => _selectedSize = s),
                      ),
                      if (product.sizes.isNotEmpty) const SizedBox(height: 20),
                      if (product.colors.isNotEmpty) _ColorSelector(
                        colors: product.colors,
                        selected: _selectedColor,
                        isAvailable: product.hasColor,
                        coverOf: (c) {
                          final shots = product.photosByColor[c];
                          return (shots == null || shots.isEmpty) ? '' : shots.first.thumb;
                        },
                        onSelected: (c) => setState(() {
                          _selectedColor = c;
                          // Галерея показывает выбранный цвет — начинаем с первого
                          // его снимка, иначе остался бы кадр от прежнего цвета.
                          _currentImage = 0;
                          if (_pageController.hasClients) {
                            _pageController.jumpToPage(0);
                          }
                          // Размер мог быть только у прежнего цвета — снимаем,
                          // чтобы не положить в корзину то, чего нет.
                          if (_selectedSize != null &&
                              !product.hasSizeInColor(_selectedSize!, c)) {
                            _selectedSize = null;
                          }
                        }),
                      ),
                      const SizedBox(height: 24),
                      const Divider(),
                      const SizedBox(height: 20),
                      const RemoteText(
                        'app.product.descLabel',
                        'ОПИСАНИЕ',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 1,
                          color: AppColors.grey600,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        product.description,
                        style: const TextStyle(
                          fontSize: 15,
                          color: AppColors.black,
                          height: 1.6,
                        ),
                      ),
                      const SizedBox(height: 24),
                      const Divider(),
                      const SizedBox(height: 16),
                      _ReviewsSection(productId: product.id),
                      const SizedBox(height: 120),
                    ],
                  ),
                ),
              ),
            ],
          ),
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: _BottomBar(
              product: product,
              onAddToCart: () => _addToCart(product),
            ),
          ),
        ],
      ),
    );
  }
}

class _ImageGallery extends StatelessWidget {
  final Product product;

  /// Снимки ВЫБРАННОГО цвета (D-99): выбрал чёрный — смотришь чёрный.
  final List<ProductPhoto> photos;
  final PageController controller;
  final int currentIndex;
  final ValueChanged<int> onPageChanged;
  final ValueChanged<int> onThumbTap;
  final String? heroTag;

  const _ImageGallery({
    required this.product,
    required this.photos,
    required this.controller,
    required this.currentIndex,
    required this.onPageChanged,
    required this.onThumbTap,
    this.heroTag,
  });

  @override
  Widget build(BuildContext context) {
    return SliverAppBar(
      expandedHeight: photos.length > 1 ? 520 : 440,
      pinned: true,
      backgroundColor: AppColors.white,
      leading: GestureDetector(
        onTap: () => Navigator.of(context).pop(),
        child: Container(
          margin: const EdgeInsets.all(8),
          decoration: const BoxDecoration(
            color: AppColors.white,
            shape: BoxShape.circle,
          ),
          child: const Icon(Icons.arrow_back, color: AppColors.black),
        ),
      ),
      flexibleSpace: FlexibleSpaceBar(
        background: Column(
          children: [
            Expanded(
              child: Stack(
                children: [
                  if (photos.isEmpty)
                    // Снимков у выбранного цвета ещё нет: честная заглушка, а не
                    // фотография другого цвета.
                    const ProductImage(path: ''),
                  PageView.builder(
                    controller: controller,
                    itemCount: photos.length,
                    onPageChanged: onPageChanged,
                    itemBuilder: (context, index) {
                      final image = ProductImage(path: photos[index].url);
                      // Hero только на первом фото — совпадает с ProductCard
                      if (index == 0) {
                        return Hero(
                          tag: heroTag ?? 'product-img-${product.id}',
                          child: image,
                        );
                      }
                      return image;
                    },
                  ),
                  if (photos.length > 1)
                    Positioned(
                      bottom: 16,
                      left: 0,
                      right: 0,
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: List.generate(
                          photos.length,
                          (i) => AnimatedContainer(
                            duration: const Duration(milliseconds: 200),
                            margin: const EdgeInsets.symmetric(horizontal: 3),
                            width: i == currentIndex ? 16 : 6,
                            height: 6,
                            decoration: BoxDecoration(
                              color: i == currentIndex
                                  ? AppColors.black
                                  : AppColors.grey400,
                              borderRadius: BorderRadius.circular(3),
                            ),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
            // Лента миниатюр: видно сразу все снимки цвета, и до нужного один
            // палец вместо нескольких смахиваний.
            if (photos.length > 1)
              SizedBox(
                height: 76,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  itemCount: photos.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (context, i) => GestureDetector(
                    onTap: () => onThumbTap(i),
                    child: Container(
                      width: 48,
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(
                          color: i == currentIndex
                              ? AppColors.black
                              : AppColors.grey200,
                          width: i == currentIndex ? 2 : 1,
                        ),
                      ),
                      clipBehavior: Clip.antiAlias,
                      child: ProductImage(path: photos[i].thumb),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _SizeSelector extends StatelessWidget {
  final List<String> sizes;
  final String? selected;
  final ValueChanged<String> onSelected;

  /// Есть ли размер на складе (остаток по размерам приходит из 1С).
  final bool Function(String size) isAvailable;

  const _SizeSelector({
    required this.sizes,
    required this.selected,
    required this.onSelected,
    required this.isAvailable,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const RemoteText(
              'app.product.sizeLabel',
              'РАЗМЕР',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                letterSpacing: 1,
                color: AppColors.grey600,
              ),
            ),
            if (selected != null) ...[
              const SizedBox(width: 8),
              Text(
                selected!,
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  color: AppColors.black,
                ),
              ),
            ],
          ],
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: sizes.map((size) {
            final isSelected = size == selected;
            // Размера нет на складе: гасим и зачёркиваем, нажать нельзя. Узнать
            // об отсутствии в корзине или после оформления — куда обиднее.
            final available = isAvailable(size);
            return GestureDetector(
              onTap: available ? () => onSelected(size) : null,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 150),
                width: 52,
                height: 42,
                decoration: BoxDecoration(
                  color: !available
                      ? AppColors.grey100
                      : (isSelected ? AppColors.black : AppColors.white),
                  border: Border.all(
                    color: !available
                        ? AppColors.grey200
                        : (isSelected ? AppColors.black : AppColors.grey200),
                    width: 1.5,
                  ),
                  borderRadius: BorderRadius.circular(8),
                ),
                alignment: Alignment.center,
                child: Text(
                  size,
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: !available
                        ? AppColors.grey400
                        : (isSelected ? AppColors.lime : AppColors.black),
                    decoration:
                        available ? TextDecoration.none : TextDecoration.lineThrough,
                    decorationColor: AppColors.grey400,
                  ),
                ),
              ),
            );
          }).toList(),
        ),
      ],
    );
  }
}

class _ColorSelector extends StatelessWidget {
  final List<String> colors;
  final String? selected;
  final bool Function(String color) isAvailable;

  /// Миниатюра вещи в этом цвете — честнее точки: видно, как выглядит, ещё до
  /// нажатия (D-99). Пусто — снимков у цвета нет, показываем одно название.
  final String Function(String color) coverOf;
  final ValueChanged<String> onSelected;

  const _ColorSelector({
    required this.colors,
    required this.selected,
    required this.isAvailable,
    required this.coverOf,
    required this.onSelected,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const RemoteText(
              'app.product.colorLabel',
              'ЦВЕТ',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                letterSpacing: 1,
                color: AppColors.grey600,
              ),
            ),
            if (selected != null) ...[
              const SizedBox(width: 8),
              Text(
                selected!,
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  color: AppColors.black,
                ),
              ),
            ],
          ],
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: colors.map((color) {
            final isSelected = color == selected;
            // Цвета нет ни в одном размере — гасим и не даём выбрать: узнать об
            // этом в корзине куда обиднее.
            final available = isAvailable(color);
            final cover = coverOf(color);
            return GestureDetector(
              onTap: available ? () => onSelected(color) : null,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 150),
                padding: EdgeInsets.only(
                    left: cover.isEmpty ? 16 : 6, right: 16,
                    top: cover.isEmpty ? 10 : 6, bottom: cover.isEmpty ? 10 : 6),
                decoration: BoxDecoration(
                  color: !available
                      ? AppColors.grey100
                      : (isSelected ? AppColors.black : AppColors.white),
                  border: Border.all(
                    color: !available
                        ? AppColors.grey200
                        : (isSelected ? AppColors.black : AppColors.grey200),
                    width: 1.5,
                  ),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (cover.isNotEmpty) ...[
                      ClipOval(
                        child: SizedBox(
                          width: 22,
                          height: 22,
                          child: Opacity(
                            opacity: available ? 1 : .45,
                            child: ProductImage(path: cover),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                    ],
                    Text(
                      color,
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                        decoration: available
                            ? TextDecoration.none
                            : TextDecoration.lineThrough,
                        color: !available
                            ? AppColors.grey400
                            : (isSelected ? AppColors.lime : AppColors.black),
                      ),
                    ),
                  ],
                ),
              ),
            );
          }).toList(),
        ),
      ],
    );
  }
}

class _BottomBar extends StatelessWidget {
  final Product product;
  final VoidCallback onAddToCart;

  const _BottomBar({required this.product, required this.onAddToCart});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.fromLTRB(
        20,
        12,
        20,
        12 + MediaQuery.of(context).padding.bottom,
      ),
      decoration: const BoxDecoration(
        color: AppColors.white,
        border: Border(top: BorderSide(color: AppColors.grey200)),
      ),
      child: Row(
        children: [
          Consumer<WishlistProvider>(
            builder: (context, wishlist, _) {
              final isFav = wishlist.contains(product.id);
              return GestureDetector(
                onTap: () => wishlist.toggle(product),
                child: Container(
                  width: 52,
                  height: 52,
                  decoration: BoxDecoration(
                    border: Border.all(color: AppColors.grey200),
                  ),
                  child: Icon(
                    isFav ? Icons.favorite : Icons.favorite_border,
                    color: isFav ? AppColors.red : AppColors.black,
                    size: 22,
                  ),
                ),
              );
            },
          ),
          const SizedBox(width: 12),
          Expanded(
            child: ElevatedButton(
              onPressed: onAddToCart,
              child: const RemoteText('app.product.addToCart', 'Добавить в корзину'),
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Bottom sheet: товар добавлен в корзину ───────────────────────────────────

class _AddedToCartSheet extends StatelessWidget {
  final Product product;
  final String size;
  final String color;

  const _AddedToCartSheet({
    required this.product,
    required this.size,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.white,
      padding: EdgeInsets.fromLTRB(
        20, 20, 20, 20 + MediaQuery.of(context).padding.bottom,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 36, height: 4,
            decoration: BoxDecoration(
              color: AppColors.grey200,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(height: 20),

          // Заголовок
          Row(
            children: [
              Container(
                width: 28, height: 28,
                decoration: const BoxDecoration(
                  color: AppColors.black,
                  shape: BoxShape.circle,
                ),
                child: const Icon(Icons.check, color: Colors.white, size: 16),
              )
                  .animate()
                  .scale(
                    begin: const Offset(0, 0),
                    duration: 400.ms,
                    curve: Curves.elasticOut,
                  ),
              const SizedBox(width: 12),
              RemoteText(
                'app.product.addedToCart',
                'Добавлено в корзину',
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w600,
                  color: AppColors.black,
                  letterSpacing: -0.3,
                ),
              ).animate(delay: 150.ms).fadeIn(duration: 300.ms),
            ],
          ),

          const SizedBox(height: 16),
          const Divider(height: 1),
          const SizedBox(height: 16),

          // Превью
          Row(
            children: [
              SizedBox(
                width: 72, height: 88,
                child: ProductImage(path: product.firstImage),
              ).animate(delay: 100.ms).fadeIn(duration: 300.ms).slideX(begin: -0.1),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      product.brand.toUpperCase(),
                      style: const TextStyle(
                        fontSize: 10, fontWeight: FontWeight.w600,
                        color: AppColors.grey600, letterSpacing: 1,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      product.name,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 14, fontWeight: FontWeight.w600,
                        color: AppColors.black, height: 1.3,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '$size  ·  $color',
                      style: const TextStyle(fontSize: 12, color: AppColors.grey400),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      '${product.price.toInt()} ₽',
                      style: const TextStyle(
                        fontSize: 16, fontWeight: FontWeight.w800,
                        color: AppColors.black,
                      ),
                    ),
                  ],
                ),
              ).animate(delay: 150.ms).fadeIn(duration: 300.ms).slideX(begin: 0.1),
            ],
          ),

          const SizedBox(height: 20),

          // Перейти в корзину
          GestureDetector(
            onTap: () {
              Navigator.of(context).pop();
              context.go('/cart');
            },
            child: Container(
              height: 52,
              decoration: BoxDecoration(
                color: AppColors.black,
                borderRadius: BorderRadius.circular(12),
              ),
              alignment: Alignment.center,
              child: const RemoteText(
                'app.product.toCart',
                'Перейти в корзину',
                style: TextStyle(
                  fontSize: 14.5, fontWeight: FontWeight.w600,
                  color: AppColors.lime, letterSpacing: 0.2,
                ),
              ),
            ),
          ).animate(delay: 200.ms).fadeIn(duration: 300.ms).slideY(begin: 0.1),

          const SizedBox(height: 12),

          GestureDetector(
            onTap: () => Navigator.of(context).pop(),
            child: const RemoteText(
              'app.product.continueShopping',
              'Продолжить покупки',
              style: TextStyle(
                fontSize: 14, color: AppColors.grey600,
                decoration: TextDecoration.underline,
              ),
            ),
          ).animate(delay: 260.ms).fadeIn(duration: 300.ms),
        ],
      ),
    );
  }
}

// ─── Отзывы на товар ──────────────────────────────────────────────────────────

class _Stars extends StatelessWidget {
  final int rating;
  final double size;
  const _Stars({required this.rating, this.size = 16});

  @override
  Widget build(BuildContext context) => Row(
        mainAxisSize: MainAxisSize.min,
        children: List.generate(
          5,
          (i) => Icon(
            i < rating ? Icons.star : Icons.star_border,
            size: size,
            color: AppColors.black,
          ),
        ),
      );
}

class _ReviewTile extends StatelessWidget {
  final Review review;
  const _ReviewTile({required this.review});

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: AppColors.grey100,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    review.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
                _Stars(rating: review.rating, size: 14),
              ],
            ),
            if (review.text.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                review.text,
                style: const TextStyle(
                  fontSize: 14,
                  height: 1.4,
                  color: AppColors.black,
                ),
              ),
            ],
            if (review.photos.isNotEmpty) ...[
              const SizedBox(height: 10),
              SizedBox(
                height: 72,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: review.photos.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (_, i) => ClipRRect(
                    borderRadius: BorderRadius.circular(8),
                    child: Image.network(
                      ApiConfig.resolveMedia(review.photos[i]),
                      width: 72,
                      height: 72,
                      fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => Container(
                        width: 72,
                        height: 72,
                        color: AppColors.grey200,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ],
        ),
      );
}

/// Миниатюра фото в форме отзыва (с кнопкой удаления).
class _ReviewPhotoThumb extends StatelessWidget {
  final String url;
  final VoidCallback onRemove;
  const _ReviewPhotoThumb({required this.url, required this.onRemove});

  @override
  Widget build(BuildContext context) => Stack(
        clipBehavior: Clip.none,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(10),
            child: Image.network(
              ApiConfig.resolveMedia(url),
              width: 64,
              height: 64,
              fit: BoxFit.cover,
              errorBuilder: (_, __, ___) => Container(
                width: 64,
                height: 64,
                color: AppColors.grey200,
              ),
            ),
          ),
          Positioned(
            top: 2,
            right: 2,
            child: GestureDetector(
              onTap: onRemove,
              child: Container(
                decoration: const BoxDecoration(
                  color: Colors.black54,
                  shape: BoxShape.circle,
                ),
                padding: const EdgeInsets.all(2),
                child: const Icon(Icons.close, size: 14, color: Colors.white),
              ),
            ),
          ),
        ],
      );
}

class _ReviewsSection extends StatefulWidget {
  final String productId;
  const _ReviewsSection({required this.productId});

  @override
  State<_ReviewsSection> createState() => _ReviewsSectionState();
}

class _ReviewsSectionState extends State<_ReviewsSection> {
  ProductReviews? _data;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (mounted) setState(() => _loading = true);
    try {
      final d =
          await context.read<CatalogProvider>().getReviews(widget.productId);
      if (mounted) {
        setState(() {
          _data = d;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _writeReview() async {
    Review? mine;
    for (final r in (_data?.reviews ?? const <Review>[])) {
      if (r.mine) {
        mine = r;
        break;
      }
    }
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      backgroundColor: AppColors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (_) => _ReviewForm(
        productId: widget.productId,
        initialRating: mine?.rating ?? 5,
        initialText: mine?.text ?? '',
      ),
    );
    if (ok == true) _load();
  }

  @override
  Widget build(BuildContext context) {
    final d = _data;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const RemoteText(
              'app.product.reviewsLabel',
              'ОТЗЫВЫ',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                letterSpacing: 1,
                color: AppColors.grey600,
              ),
            ),
            if (d != null && d.canReview)
              TextButton(
                onPressed: _writeReview,
                child: RemoteText(
                  d.hasMine ? 'app.product.editReview' : 'app.product.leaveReview',
                  d.hasMine ? 'Изменить' : 'Оставить отзыв',
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    color: AppColors.black,
                  ),
                ),
              ),
          ],
        ),
        const SizedBox(height: 8),
        if (_loading)
          const Padding(
            padding: EdgeInsets.all(16),
            child: Center(child: CircularProgressIndicator()),
          )
        else if (d == null || d.reviews.isEmpty)
          RemoteText(
            d?.canReview == true
                ? 'app.product.reviewsEmptyCanReview'
                : 'app.product.reviewsEmpty',
            d?.canReview == true
                ? 'Отзывов пока нет. Будьте первым!'
                : 'Отзывов пока нет.',
            style: const TextStyle(color: AppColors.grey600, fontSize: 14),
          )
        else ...[
          Row(
            children: [
              _Stars(rating: d.rating.round()),
              const SizedBox(width: 8),
              Text(
                d.rating.toStringAsFixed(1),
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
              const SizedBox(width: 6),
              Text(
                '· ${d.reviewCount}',
                style: const TextStyle(color: AppColors.grey600),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ...d.reviews.map((r) => _ReviewTile(review: r)),
        ],
      ],
    );
  }
}

class _ReviewForm extends StatefulWidget {
  final String productId;
  final int initialRating;
  final String initialText;
  const _ReviewForm({
    required this.productId,
    required this.initialRating,
    required this.initialText,
  });

  @override
  State<_ReviewForm> createState() => _ReviewFormState();
}

class _ReviewFormState extends State<_ReviewForm> {
  late int _rating = widget.initialRating;
  late final TextEditingController _ctrl =
      TextEditingController(text: widget.initialText);
  bool _saving = false;
  String? _error;
  final List<String> _photos = [];
  bool _uploading = false;

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  Future<void> _pickPhoto() async {
    if (_photos.length >= 5) return;
    final catalog = context.read<CatalogProvider>();
    final x = await ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: 1600,
      imageQuality: 85,
    );
    if (x == null) return;
    setState(() {
      _uploading = true;
      _error = null;
    });
    try {
      final url = await catalog.uploadReviewPhoto(x.path);
      if (mounted && url.isNotEmpty) setState(() => _photos.add(url));
    } catch (_) {
      if (mounted) setState(() => _error = 'Не удалось загрузить фото');
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  Future<void> _submit() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await context.read<CatalogProvider>().submitReview(
            widget.productId,
            rating: _rating,
            text: _ctrl.text.trim(),
            photos: _photos,
          );
      if (mounted) Navigator.pop(context, true);
    } catch (_) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = 'Не удалось отправить отзыв';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).viewInsets.bottom;
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 20, 20, bottom + 20),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const RemoteText(
            'app.product.yourReview',
            'Ваш отзыв',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 16),
          Row(
            children: List.generate(
              5,
              (i) => GestureDetector(
                onTap: () => setState(() => _rating = i + 1),
                child: Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: Icon(
                    i < _rating ? Icons.star : Icons.star_border,
                    size: 38,
                    color: AppColors.black,
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _ctrl,
            maxLines: 4,
            decoration: const InputDecoration(
              hintText: 'Расскажите о товаре…',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 14),
          const RemoteText(
            'app.product.photoOptional',
            'Фото (по желанию)',
            style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              ..._photos.map(
                (url) => _ReviewPhotoThumb(
                  url: url,
                  onRemove: () => setState(() => _photos.remove(url)),
                ),
              ),
              if (_photos.length < 5)
                GestureDetector(
                  onTap: _uploading ? null : _pickPhoto,
                  child: Container(
                    width: 64,
                    height: 64,
                    decoration: BoxDecoration(
                      color: AppColors.grey100,
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: AppColors.grey200),
                    ),
                    child: _uploading
                        ? const Center(
                            child: SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            ),
                          )
                        : const Icon(
                            Icons.add_a_photo_outlined,
                            color: AppColors.grey600,
                          ),
                  ),
                ),
            ],
          ),
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text(_error!, style: const TextStyle(color: AppColors.red)),
          ],
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            height: 52,
            child: ElevatedButton(
              onPressed: _saving ? null : _submit,
              child: _saving
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: AppColors.white,
                      ),
                    )
                  : const RemoteText('app.product.submit', 'Отправить'),
            ),
          ),
        ],
      ),
    );
  }
}
