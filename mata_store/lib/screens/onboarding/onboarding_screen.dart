import 'package:flutter/material.dart';
import '../../theme/app_theme.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:smooth_page_indicator/smooth_page_indicator.dart';

import '../../widgets/remote_background.dart';
import '../../widgets/remote_text.dart';

class OnboardingScreen extends StatefulWidget {
  final VoidCallback onComplete;
  const OnboardingScreen({super.key, required this.onComplete});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final _pageCtrl = PageController();
  int _page = 0;

  static const _slides = [
    _SlideData(
      keyBase: 'app.onb.s1',
      icon: Icons.bolt,
      title: 'ЭКИПИРОВКА\nДЛЯ ПОБЕД',
      subtitle:
          'Беговая одежда, кроссовки и аксессуары топовых брендов в одном месте',
    ),
    _SlideData(
      keyBase: 'app.onb.s2',
      icon: Icons.local_shipping_outlined,
      title: 'БЫСТРАЯ\nДОСТАВКА',
      subtitle:
          'Привезём сами или заберёте сами — договоримся, как вам удобно',
    ),
    _SlideData(
      keyBase: 'app.onb.s3',
      icon: Icons.percent,
      title: 'ПЕРСОНАЛЬНЫЕ\nСКИДКИ',
      subtitle:
          'Регистрируйтесь и получайте скидку 10% на первый заказ и доступ к акциям',
    ),
    _SlideData(
      keyBase: 'app.onb.s4',
      icon: Icons.favorite_border,
      title: 'ВСЁ ПОД\nРУКОЙ',
      subtitle:
          'Избранное, история заказов и корзина всегда сохраняются между запусками',
    ),
  ];

  bool get _isLast => _page == _slides.length - 1;

  @override
  void dispose() {
    _pageCtrl.dispose();
    super.dispose();
  }

  void _next() {
    if (_isLast) {
      widget.onComplete();
    } else {
      _pageCtrl.nextPage(
        duration: const Duration(milliseconds: 350),
        curve: Curves.easeInOutCubic,
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.black,
      body: RemoteBackground(
        'app.onb.bg',
        fallbackColor: AppColors.black,
        child: SafeArea(
        child: Column(
          children: [
            // Skip
            Align(
              alignment: Alignment.centerRight,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(0, 8, 12, 0),
                child: AnimatedOpacity(
                  duration: const Duration(milliseconds: 200),
                  opacity: _isLast ? 0 : 1,
                  child: TextButton(
                    onPressed: _isLast ? null : widget.onComplete,
                    child: const RemoteText(
                      'app.onb.skip',
                      'Пропустить',
                      style: TextStyle(
                        color: Color(0xFF888888),
                        fontSize: 14,
                      ),
                    ),
                  ),
                ),
              ),
            ),

            // Slides
            Expanded(
              child: PageView.builder(
                controller: _pageCtrl,
                onPageChanged: (i) => setState(() => _page = i),
                itemCount: _slides.length,
                itemBuilder: (context, i) => _Slide(data: _slides[i]),
              ),
            ),

            // Indicator
            SmoothPageIndicator(
              controller: _pageCtrl,
              count: _slides.length,
              effect: const ExpandingDotsEffect(
                dotHeight: 6,
                dotWidth: 6,
                expansionFactor: 4,
                spacing: 6,
                activeDotColor: Colors.white,
                dotColor: Color(0xFF333333),
              ),
            ),

            const SizedBox(height: 32),

            // Button
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
              child: GestureDetector(
                onTap: _next,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  height: 54,
                  color: Colors.white,
                  alignment: Alignment.center,
                  child: AnimatedSwitcher(
                    duration: const Duration(milliseconds: 250),
                    child: RemoteText(
                      _isLast ? 'app.onb.start' : 'app.onb.next',
                      _isLast ? 'НАЧАТЬ' : 'ДАЛЕЕ',
                      key: ValueKey(_isLast),
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: AppColors.black,
                        letterSpacing: 2,
                      ),
                    ),
                  ),
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

class _SlideData {
  final String keyBase;
  final IconData icon;
  final String title;
  final String subtitle;
  const _SlideData({
    required this.keyBase,
    required this.icon,
    required this.title,
    required this.subtitle,
  });
}

class _Slide extends StatelessWidget {
  final _SlideData data;
  const _Slide({required this.data});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Icon box
          Container(
            width: 96,
            height: 96,
            decoration: BoxDecoration(
              border: Border.all(color: Colors.white24, width: 1.5),
            ),
            child: Icon(data.icon, size: 44, color: Colors.white),
          )
              .animate(key: ValueKey(data.title))
              .scale(duration: 450.ms, curve: Curves.easeOutBack)
              .fadeIn(duration: 300.ms),

          const SizedBox(height: 40),

          RemoteText(
            '${data.keyBase}.title',
            data.title,
            style: TextStyle(
              fontSize: 40,
              fontWeight: FontWeight.w700,
              color: Colors.white,
              letterSpacing: 1,
              height: 1.05,
            ),
          )
              .animate(key: ValueKey('${data.title}_t'))
              .fadeIn(duration: 400.ms, delay: 100.ms)
              .slideX(begin: -0.08, curve: Curves.easeOut),

          const SizedBox(height: 16),

          RemoteText(
            '${data.keyBase}.subtitle',
            data.subtitle,
            style: const TextStyle(
              fontSize: 15,
              color: Color(0xFF999999),
              height: 1.6,
            ),
          )
              .animate(key: ValueKey('${data.title}_s'))
              .fadeIn(duration: 400.ms, delay: 200.ms)
              .slideX(begin: -0.05, curve: Curves.easeOut),
        ],
      ),
    );
  }
}
