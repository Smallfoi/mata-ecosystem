import 'package:flutter/material.dart';
import '../../widgets/product_image.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:smooth_page_indicator/smooth_page_indicator.dart';
import 'package:mata_ui/mata_ui.dart';
import '../../models/showcase.dart';
import '../../providers/catalog_provider.dart';
import '../../providers/notifications_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/product_card.dart';
import '../../widgets/remote_image.dart';
import '../../widgets/remote_text.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _bannerController = PageController();

  @override
  void dispose() {
    _bannerController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final catalog = context.watch<CatalogProvider>();
    // «Рекомендуем»: отмеченные в админке; не отмечено ничего — товары с фото в
    // порядке витрины (как на сайте), а не пустая полоса на пол-экрана (26.11).
    final featured = catalog.featured.isNotEmpty
        ? catalog.featured
        : catalog.products.where((p) => p.firstImage.isNotEmpty).take(10).toList();
    final newProducts = catalog.newProducts;

    return Scaffold(
      backgroundColor: AppColors.white,
      appBar: AppBar(
        // Фирменный знак вместо текстового заголовка (brand/logo, D-34).
        title: const MataLogo(width: 96, color: AppColors.black),
        titleSpacing: 16,
        actions: [
          IconButton(
            onPressed: () => context.push('/search'),
            icon: const Icon(Icons.search, size: 26),
          ),
          _NotificationBell(),
          const SizedBox(width: 4),
        ],
      ),
      body: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _BannerCarousel(
              controller: _bannerController,
            ).animate().fadeIn(duration: 600.ms),

            _SectionHeader(title: 'КАТЕГОРИИ', contentKey: 'app.home.catTitle')
                .animate(delay: 100.ms)
                .fadeIn(duration: 400.ms)
                .slideX(begin: -0.15, curve: Curves.easeOut),
            const SizedBox(height: 14),
            _CategoryCards()
                .animate(delay: 160.ms)
                .fadeIn(duration: 400.ms)
                .slideY(begin: 0.12, curve: Curves.easeOut),

            const SizedBox(height: 36),

            _SectionHeader(
                  title: 'РЕКОМЕНДУЕМ',
                  contentKey: 'app.home.featTitle',
                  onTap: () => context.go('/catalog'),
                )
                .animate(delay: 220.ms)
                .fadeIn(duration: 400.ms)
                .slideX(begin: -0.15, curve: Curves.easeOut),
            const SizedBox(height: 14),
            _HorizontalProductList(products: featured)
                .animate(delay: 280.ms)
                .fadeIn(duration: 400.ms)
                .slideX(begin: 0.08, curve: Curves.easeOut),

            // Новинок нет — раздела нет (заголовок над пустотой выглядит как поломка).
            if (newProducts.isNotEmpty) ...[
              const SizedBox(height: 36),
              _SectionHeader(
                    title: 'НОВИНКИ',
                    contentKey: 'app.home.newTitle',
                    onTap: () => context.go('/catalog'),
                  )
                  .animate(delay: 340.ms)
                  .fadeIn(duration: 400.ms)
                  .slideX(begin: -0.15, curve: Curves.easeOut),
              const SizedBox(height: 14),
              _NewProductsGrid(products: newProducts),
            ],

            const SizedBox(height: 48),
          ],
        ),
      ),
    );
  }
}

// ─── Notification bell with badge ─────────────────────────────────────────────

class _NotificationBell extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Consumer<NotificationsProvider>(
      builder: (context, notif, _) {
        return Stack(
          clipBehavior: Clip.none,
          children: [
            IconButton(
              onPressed: () => context.push('/notifications'),
              icon: const Icon(Icons.notifications_none, size: 26),
            ),
            if (notif.hasUnread)
              Positioned(
                right: 8,
                top: 8,
                child: Container(
                  constraints: const BoxConstraints(minWidth: 16),
                  height: 16,
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  decoration: const BoxDecoration(
                    color: AppColors.red,
                    borderRadius: BorderRadius.all(Radius.circular(8)),
                  ),
                  alignment: Alignment.center,
                  child: Text(
                    notif.unreadCount > 9 ? '9+' : '${notif.unreadCount}',
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
      },
    );
  }
}

// ─── Banner ───────────────────────────────────────────────────────────────────

class _BannerCarousel extends StatelessWidget {
  final PageController controller;
  const _BannerCarousel({required this.controller});

  @override
  Widget build(BuildContext context) {
    final catalog = context.watch<CatalogProvider>();
    final banners = catalog.banners;
    if (banners.isEmpty) {
      // Пока грузится — место под баннер; загрузилось и баннеров нет (владелец снял
      // демо-баннеры 26.11) — без пустой серой плашки на пол-экрана.
      return catalog.isReady
          ? const SizedBox(height: 16)
          : Container(
              height: 440,
              color: AppColors.grey100,
              margin: const EdgeInsets.only(bottom: 32));
    }
    return Column(
      children: [
        SizedBox(
          height: 440,
          child: PageView.builder(
            controller: controller,
            itemCount: banners.length,
            itemBuilder: (context, i) => _BannerItem(banner: banners[i]),
          ),
        ),
        const SizedBox(height: 16),
        SmoothPageIndicator(
          controller: controller,
          count: banners.length,
          effect: const WormEffect(
            dotHeight: 5,
            dotWidth: 5,
            activeDotColor: AppColors.black,
            dotColor: AppColors.grey200,
          ),
        ),
        const SizedBox(height: 32),
      ],
    );
  }
}

class _BannerItem extends StatelessWidget {
  final Map<String, String> banner;
  const _BannerItem({required this.banner});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(18),
        child: Stack(
      fit: StackFit.expand,
      children: [
        ProductImage(path: banner['imageUrl']!),
        Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [Colors.transparent, Color(0xDD20241F)],
              stops: [0.35, 1.0],
            ),
          ),
        ),
        Positioned(
          left: 20,
          right: 20,
          bottom: 32,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                banner['title']!,
                style: const TextStyle(
                  fontSize: 34,
                  fontWeight: FontWeight.w500,
                  color: AppColors.white,
                  letterSpacing: -1.2,
                  height: 1.05,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                banner['subtitle']!,
                style: GoogleFonts.robotoSerif(
                  fontSize: 13.5,
                  fontStyle: FontStyle.italic,
                  fontWeight: FontWeight.w200,
                  color: const Color(0xFFD8D9DE),
                ),
              ),
              const SizedBox(height: 20),
              _BannerButton(
                label: banner['action']!,
                onTap: () => _openBanner(context, banner),
              ),
            ],
          ),
        ),
      ],
        ),
      ),
    );
  }
}

void _openBanner(BuildContext context, Map<String, String> banner) {
  final title = banner['title'] ?? '';
  final subtitle = banner['subtitle'] ?? '';
  if (title.contains('ЗИМ') || subtitle.toLowerCase().contains('тепло')) {
    context.go('/catalog?category=jackets');
    return;
  }
  if (subtitle.toLowerCase().contains('бег')) {
    context.go('/catalog?category=shoes');
    return;
  }
  context.go('/catalog');
}

class _BannerButton extends StatefulWidget {
  final String label;
  final VoidCallback onTap;
  const _BannerButton({required this.label, required this.onTap});

  @override
  State<_BannerButton> createState() => _BannerButtonState();
}

class _BannerButtonState extends State<_BannerButton> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: widget.onTap,
      onTapDown: (_) => setState(() => _pressed = true),
      onTapUp: (_) => setState(() => _pressed = false),
      onTapCancel: () => setState(() => _pressed = false),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 100),
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
        decoration: BoxDecoration(
          color: _pressed ? const Color(0xFFD8D477) : AppColors.lime,
          borderRadius: BorderRadius.circular(10),
        ),
        child: Text(
          widget.label,
          style: const TextStyle(
            fontSize: 13.5,
            fontWeight: FontWeight.w600,
            color: AppColors.black,
            letterSpacing: 0.2,
          ),
        ),
      ),
    );
  }
}

// ─── Section header ───────────────────────────────────────────────────────────

class _SectionHeader extends StatelessWidget {
  final String title;
  final String contentKey;
  final VoidCallback? onTap;
  const _SectionHeader({
    required this.title,
    required this.contentKey,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          RemoteText(
            contentKey,
            title,
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: AppColors.grey600,
              letterSpacing: 1.5,
            ),
          ),
          if (onTap != null)
            GestureDetector(
              onTap: onTap,
              child: Row(
                children: const [
                  RemoteText(
                    'app.home.seeAll',
                    'ВСЕ',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: AppColors.black,
                      letterSpacing: 1.5,
                    ),
                  ),
                  SizedBox(width: 4),
                  Icon(Icons.arrow_forward, size: 14, color: AppColors.grey600),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

// ─── Category cards ───────────────────────────────────────────────────────────

class _CategoryCards extends StatelessWidget {
  // Разделы витрины (D-133) и ручной выбор лучшего фото НАШЕГО товара на обложку
  // (владелец 26.11: «заменить на наши — самую удачную и хорошего качества»).
  // Раньше тут были стоковые фото (в «Кроссовках» — Nike) и id-заглушки tshirts/
  // hoodies, которых нет в 1С: плитка открывала пустой каталог.
  // Товар пропал/без фото — обложкой станет первый товар раздела с фото; раздел
  // без единого фото не показывается. Поверх всего — фото из Конструктора.
  static const _picks = <String, String>{
    'sneakers': '812625546', // ANTA WALK 3.0
    'tees': '26SADT013', // STAW, футболка
    'longsleeves': '26SACT006', // STAW, лонгслив
    'jackets': '26SAJK007', // STAW, ветровка
    'pants': '26SACK007', // STAW, брюки
    'boots': '812538965C', // ANTA RIDGES 2.0
    'glasses': '14110025007', // Rockbros SHADOW
    'gels': '702456', // SIS GO + Electrolyte
  };

  @override
  Widget build(BuildContext context) {
    final catalog = context.watch<CatalogProvider>();
    final cards = <({String tab, String group, String name, String img})>[];
    void add(String tab, ShowcaseGroup g) {
      final img = catalog.coverFor(g.categoryIds, preferId: _picks[g.id]);
      if (img.isNotEmpty) cards.add((tab: tab, group: g.id, name: g.name, img: img));
    }
    // Сначала выбранные разделы в задуманном порядке, затем остальные непустые.
    for (final id in _picks.keys) {
      for (final t in catalog.showcase) {
        for (final g in t.groups) {
          if (g.id == id) add(t.id, g);
        }
      }
    }
    for (final t in catalog.showcase) {
      for (final g in t.groups) {
        if (!_picks.containsKey(g.id)) add(t.id, g);
      }
    }
    if (cards.isEmpty) return const SizedBox(height: 190);
    return SizedBox(
      height: 190,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        itemCount: cards.length,
        separatorBuilder: (_, __) => const SizedBox(width: 10),
        itemBuilder: (context, i) {
          final cat = cards[i];
          return _CategoryCard(
                tab: cat.tab,
                group: cat.group,
                name: cat.name,
                contentKey: 'app.cat.${cat.group}',
                imageUrl: cat.img,
              )
              .animate(delay: ((i < 6 ? i : 6) * 70).ms)
              .fadeIn(duration: 350.ms)
              .slideX(begin: 0.15, duration: 350.ms, curve: Curves.easeOut);
        },
      ),
    );
  }
}

class _CategoryCard extends StatefulWidget {
  final String tab;
  final String group;
  final String name;
  final String contentKey;
  final String imageUrl;
  const _CategoryCard({
    required this.tab,
    required this.group,
    required this.name,
    required this.contentKey,
    required this.imageUrl,
  });

  @override
  State<_CategoryCard> createState() => _CategoryCardState();
}

class _CategoryCardState extends State<_CategoryCard> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => context.go('/catalog?tab=${widget.tab}&group=${widget.group}'),
      onTapDown: (_) => setState(() => _pressed = true),
      onTapUp: (_) => setState(() => _pressed = false),
      onTapCancel: () => setState(() => _pressed = false),
      child: AnimatedScale(
        scale: _pressed ? 0.95 : 1.0,
        duration: const Duration(milliseconds: 120),
        curve: Curves.easeOut,
        child: SizedBox(
          width: 136,
          height: 190,
          child: Stack(
            fit: StackFit.expand,
            children: [
              RemoteImage(
                '${widget.contentKey}.img',
                fallbackUrl: widget.imageUrl,
                width: 136,
                height: 190,
              ),
              Container(
                decoration: const BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [Colors.transparent, Color(0xBB000000)],
                    stops: [0.4, 1.0],
                  ),
                ),
              ),
              Positioned(
                left: 8,
                right: 8,
                bottom: 10,
                child: RemoteText(
                  widget.contentKey,
                  widget.name,
                  upper: true,
                  // «Футболки и майки», «Куртки и ветровки» — в две строки, не «ФУТБОЛК…».
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600,
                    color: AppColors.white,
                    letterSpacing: 0.3,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ─── Horizontal product list ──────────────────────────────────────────────────

class _HorizontalProductList extends StatelessWidget {
  final List products;
  const _HorizontalProductList({required this.products});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 290,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        itemCount: products.length,
        separatorBuilder: (_, __) => const SizedBox(width: 12),
        itemBuilder: (context, i) {
          return ProductCard(
                product: products[i],
                width: 165,
                heroTag: 'featured-${products[i].id}',
              )
              .animate(delay: ((i < 6 ? i : 6) * 80).ms)
              .fadeIn(duration: 400.ms)
              .slideX(begin: 0.1, duration: 400.ms, curve: Curves.easeOut);
        },
      ),
    );
  }
}

// ─── New products grid ────────────────────────────────────────────────────────

class _NewProductsGrid extends StatelessWidget {
  final List products;
  const _NewProductsGrid({required this.products});

  static const _maxOnHome = 10;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: GridView.builder(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: 2,
          crossAxisSpacing: 12,
          mainAxisSpacing: 16,
          childAspectRatio: 0.6,
        ),
        // Сетка строится целиком (shrinkWrap внутри прокрутки), поэтому на
        // главной — первые 10 новинок; остальные — по «Все» в каталоге.
        // Раньше строились ВСЕ новинки разом, каждая со своей загрузкой фото
        // и анимацией (аудит 21.11.2026).
        itemCount: products.length > _maxOnHome ? _maxOnHome : products.length,
        itemBuilder: (context, i) {
          return ProductCard(
                product: products[i],
                heroTag: 'new-${products[i].id}',
              )
              .animate(delay: ((i < 6 ? i : 6) * 90).ms)
              .fadeIn(duration: 450.ms)
              .slideY(begin: 0.15, duration: 450.ms, curve: Curves.easeOut);
        },
      ),
    );
  }
}
