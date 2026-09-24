import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../models/product.dart';
import '../providers/wishlist_provider.dart';
import '../theme/app_theme.dart';
import 'price_text.dart';
import 'product_image.dart';

class ProductCard extends StatefulWidget {
  final Product product;
  final double? width;
  final String? heroTag;

  const ProductCard({
    super.key,
    required this.product,
    this.width,
    this.heroTag,
  });

  @override
  State<ProductCard> createState() => _ProductCardState();
}

class _ProductCardState extends State<ProductCard> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    final p = widget.product;
    final heroTag = widget.heroTag ?? 'product-img-${p.id}';

    return GestureDetector(
      onTap: () => context.push('/product/${p.id}', extra: heroTag),
      onTapDown: (_) => setState(() => _pressed = true),
      onTapUp: (_) { if (mounted) setState(() => _pressed = false); },
      onTapCancel: () { if (mounted) setState(() => _pressed = false); },
      child: AnimatedScale(
        scale: _pressed ? 0.97 : 1.0,
        duration: const Duration(milliseconds: 120),
        curve: Curves.easeOut,
        child: SizedBox(
          width: widget.width,
          // ── Рамка объединяет фото и текст в единый блок ───────────────
          child: Container(
            clipBehavior: Clip.antiAlias,
            decoration: BoxDecoration(
              border: Border.all(color: AppColors.grey200, width: 1),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [

                // ── Фото (Expanded — всё доступное место) ──────────────
                Expanded(
                  child: Stack(
                    children: [
                      Positioned.fill(
                        child: Hero(
                          tag: heroTag,
                          child: ProductImage(path: p.coverThumb),
                        ),
                      ),

                      // Бейдж НОВИНКА
                      if (p.isNew)
                        Positioned(
                          top: 8,
                          left: 8,
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 7, vertical: 3),
                            decoration: BoxDecoration(
                              color: AppColors.black,
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: const Text(
                              'НОВИНКА',
                              style: TextStyle(
                                fontSize: 9,
                                fontWeight: FontWeight.w600,
                                color: AppColors.lime,
                                letterSpacing: 0.5,
                              ),
                            ),
                          ),
                        ),

                      // Бейдж скидки — лайм (брендбук), не красный
                      if (p.isOnSale)
                        Positioned(
                          top: p.isNew ? 32 : 8,
                          left: 8,
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 7, vertical: 3),
                            decoration: BoxDecoration(
                              color: AppColors.lime,
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: Text(
                              '−${p.discountPercent}%',
                              style: const TextStyle(
                                fontSize: 9,
                                fontWeight: FontWeight.w600,
                                color: AppColors.black,
                              ),
                            ),
                          ),
                        ),

                      // Кнопка избранного
                      Positioned(
                        top: 2,
                        right: 2,
                        child: Consumer<WishlistProvider>(
                          builder: (context, wishlist, _) {
                            final isFav = wishlist.contains(p.id);
                            return GestureDetector(
                              onTap: () => wishlist.toggle(p),
                              child: Container(
                                width: 34,
                                height: 34,
                                color: Colors.transparent,
                                alignment: Alignment.center,
                                child: Icon(
                                  isFav ? Icons.favorite : Icons.favorite_border,
                                  color: AppColors.black,
                                  size: 19,
                                )
                                    .animate(key: ValueKey(isFav))
                                    .scale(
                                      begin: isFav
                                          ? const Offset(1.5, 1.5)
                                          : const Offset(1.0, 1.0),
                                      end: const Offset(1.0, 1.0),
                                      duration: 350.ms,
                                      curve: Curves.elasticOut,
                                    ),
                              ),
                            );
                          },
                        ),
                      ),
                    ],
                  ),
                ),

                // ── Текст — внутри рамки, отделён от фото ──────────────
                Container(
                  width: double.infinity,
                  color: AppColors.white,
                  padding: const EdgeInsets.fromLTRB(8, 8, 8, 10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        p.name,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: AppColors.black,
                          height: 1.3,
                        ),
                      ),
                      const SizedBox(height: 5),
                      PriceText(price: p.price, oldPrice: p.oldPrice),
                    ],
                  ),
                ),

              ],
            ),
          ),
        ),
      ),
    );
  }
}
