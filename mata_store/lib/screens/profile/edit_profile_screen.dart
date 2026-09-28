import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';
import '../../data/api/api_config.dart';
import '../../providers/auth_provider.dart';
import '../../theme/app_theme.dart';
import '../auth/auth_screen.dart';
import '../../widgets/remote_text.dart';

class EditProfileScreen extends StatefulWidget {
  const EditProfileScreen({super.key});

  @override
  State<EditProfileScreen> createState() => _EditProfileScreenState();
}

class _EditProfileScreenState extends State<EditProfileScreen> {
  late final TextEditingController _nameCtrl;
  late final TextEditingController _phoneCtrl;
  late final TextEditingController _profileCityCtrl;
  late final TextEditingController _emailCtrl;

  // Add address inline form
  bool _showAddressForm = false;
  final _labelCtrl = TextEditingController();
  final _addressCityCtrl = TextEditingController();
  final _streetCtrl = TextEditingController();
  final _houseCtrl = TextEditingController();
  final _buildingCtrl = TextEditingController();
  final _aptCtrl = TextEditingController();
  final _postalCtrl = TextEditingController();
  String? _addressError;

  String? _error;
  bool _saved = false;

  @override
  void initState() {
    super.initState();
    final user = context.read<AuthProvider>().user!;
    _nameCtrl = TextEditingController(text: user.name);
    _phoneCtrl = TextEditingController(text: user.phone ?? '');
    _profileCityCtrl = TextEditingController(text: user.city ?? '');
    // Синтетический email телефонных аккаунтов (…@kvartal.local) не показываем —
    // даём поле пустым, чтобы человек ввёл свою настоящую почту.
    final em = user.email;
    _emailCtrl = TextEditingController(
      text: em.endsWith('@kvartal.local') ? '' : em,
    );
  }

  @override
  void dispose() {
    for (final c in [
      _nameCtrl,
      _phoneCtrl,
      _profileCityCtrl,
      _emailCtrl,
      _labelCtrl,
      _addressCityCtrl,
      _streetCtrl,
      _houseCtrl,
      _buildingCtrl,
      _aptCtrl,
      _postalCtrl,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  // ── Avatar picker ────────────────────────────────────────────────────────────

  Future<void> _pickAvatar() async {
    final picker = ImagePicker();
    final result = await picker.pickImage(
      source: ImageSource.gallery,
      imageQuality: 80,
      maxWidth: 600,
    );
    if (result == null || !mounted) return;
    final err = await context.read<AuthProvider>().uploadAvatar(result.path);
    if (err != null && mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(err)));
    }
  }

  Future<void> _removeAvatar() async {
    final err = await context.read<AuthProvider>().removeAvatar();
    if (err != null && mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(err)));
    }
  }

  // ── Address ──────────────────────────────────────────────────────────────────

  void _submitAddress() {
    if (_addressCityCtrl.text.trim().isEmpty) {
      setState(() => _addressError = 'Введите город');
      return;
    }
    if (_streetCtrl.text.trim().isEmpty) {
      setState(() => _addressError = 'Введите улицу');
      return;
    }
    if (_houseCtrl.text.trim().isEmpty) {
      setState(() => _addressError = 'Введите номер дома');
      return;
    }
    context.read<AuthProvider>().addAddress(
      SavedAddress(
        label: _labelCtrl.text.trim(),
        city: _addressCityCtrl.text.trim(),
        street: _streetCtrl.text.trim(),
        house: _houseCtrl.text.trim(),
        building: _buildingCtrl.text.trim().isNotEmpty
            ? _buildingCtrl.text.trim()
            : null,
        apartment: _aptCtrl.text.trim().isNotEmpty
            ? _aptCtrl.text.trim()
            : null,
        postalCode: _postalCtrl.text.trim().isNotEmpty
            ? _postalCtrl.text.trim()
            : null,
      ),
    );
    // clear form
    for (final c in [
      _labelCtrl,
      _addressCityCtrl,
      _streetCtrl,
      _houseCtrl,
      _buildingCtrl,
      _aptCtrl,
      _postalCtrl,
    ]) {
      c.clear();
    }
    setState(() {
      _showAddressForm = false;
      _addressError = null;
    });
  }

  /// Смена пароля = сброс кодом на телефон аккаунта (тот же экран, что
  /// «Забыли пароль?» при входе).
  void _openPasswordReset(String phone) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => AuthScreen(startWithReset: true, initialPhone: phone),
      ),
    );
  }

  // ── Save profile ─────────────────────────────────────────────────────────────

  Future<void> _save() async {
    if (_nameCtrl.text.trim().isEmpty) {
      setState(() => _error = 'Введите имя');
      return;
    }
    final auth = context.read<AuthProvider>();

    final err = await auth.updateProfile(
      name: _nameCtrl.text,
      phone: _phoneCtrl.text,
      city: _profileCityCtrl.text,
      email: _emailCtrl.text,
    );
    if (!mounted) return;
    if (err != null) {
      setState(() => _error = err);
      return;
    }
    setState(() {
      _error = null;
      _saved = true;
    });

    await Future.delayed(const Duration(milliseconds: 800));
    if (mounted) Navigator.of(context).pop();
  }

  // ── Build ────────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final user = auth.user!;
    final isEmail = user.provider == LoginProvider.email;

    return Scaffold(
      backgroundColor: AppColors.white,
      body: Column(
        children: [
          _Header(onClose: () => Navigator.of(context).pop()),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(24, 28, 24, 32),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // ── Avatar ─────────────────────────────────────────────────
                  Center(
                    child: Column(
                      children: [
                        GestureDetector(
                          onTap: _pickAvatar,
                          child: Stack(
                            children: [
                              Container(
                                width: 90,
                                height: 90,
                                decoration: const BoxDecoration(
                                  color: AppColors.black,
                                  shape: BoxShape.circle,
                                ),
                                clipBehavior: Clip.antiAlias,
                                child: user.avatarPath != null
                                    ? Image(
                                        image: ApiConfig.isRemoteAvatar(
                                                user.avatarPath)
                                            ? NetworkImage(ApiConfig.resolveMedia(
                                                user.avatarPath))
                                            : FileImage(File(user.avatarPath!))
                                                as ImageProvider,
                                        fit: BoxFit.cover,
                                        errorBuilder: (_, __, ___) =>
                                            _initialsWidget(user.name),
                                      )
                                    : _initialsWidget(user.name),
                              ),
                              Positioned(
                                bottom: 0,
                                right: 0,
                                child: Container(
                                  width: 28,
                                  height: 28,
                                  decoration: BoxDecoration(
                                    color: Colors.white,
                                    shape: BoxShape.circle,
                                    border: Border.all(
                                      color: AppColors.grey200,
                                    ),
                                  ),
                                  child: const Icon(
                                    Icons.camera_alt,
                                    size: 15,
                                    color: AppColors.black,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: 8),
                        Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            GestureDetector(
                              onTap: _pickAvatar,
                              child: const RemoteText(
                                'app.editprofile.changePhoto',
                                'Изменить фото',
                                style: TextStyle(
                                  fontSize: 13,
                                  color: AppColors.black,
                                  decoration: TextDecoration.underline,
                                ),
                              ),
                            ),
                            if (user.avatarPath != null) ...[
                              const Text(
                                ' · ',
                                style: TextStyle(color: AppColors.grey400),
                              ),
                              GestureDetector(
                                onTap: _removeAvatar,
                                child: const RemoteText(
                                  'app.editprofile.removePhoto',
                                  'Удалить',
                                  style: TextStyle(
                                    fontSize: 13,
                                    color: AppColors.red,
                                    decoration: TextDecoration.underline,
                                  ),
                                ),
                              ),
                            ],
                          ],
                        ),
                      ],
                    ),
                  ).animate().scale(duration: 400.ms, curve: Curves.easeOut),

                  if (!isEmail) ...[
                    const SizedBox(height: 10),
                    Center(
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 5,
                        ),
                        color: AppColors.grey100,
                        child: RemoteText(
                          'app.editprofile.phoneLogin',
                          'Вход по номеру телефона',
                          style: const TextStyle(
                            fontSize: 12,
                            color: AppColors.grey600,
                          ),
                        ),
                      ),
                    ),
                  ],

                  const SizedBox(height: 28),

                  // ── Main fields ────────────────────────────────────────────
                  _Field(
                        ctrl: _nameCtrl,
                        label: 'Имя',
                        hint: 'Иван Иванов',
                        icon: Icons.person_outline,
                        cap: TextCapitalization.words,
                      )
                      .animate()
                      .fadeIn(duration: 350.ms, delay: 80.ms)
                      .slideY(begin: 0.08),
                  const SizedBox(height: 14),
                  _Field(
                        ctrl: _phoneCtrl,
                        label: 'Телефон',
                        hint: '+7 (999) 000-00-00',
                        icon: Icons.phone_outlined,
                        type: TextInputType.phone,
                      )
                      .animate()
                      .fadeIn(duration: 350.ms, delay: 140.ms)
                      .slideY(begin: 0.08),
                  const SizedBox(height: 14),
                  _Field(
                        ctrl: _profileCityCtrl,
                        label: 'Город',
                        hint: 'Якутск',
                        icon: Icons.location_city_outlined,
                        cap: TextCapitalization.words,
                      )
                      .animate()
                      .fadeIn(duration: 350.ms, delay: 170.ms)
                      .slideY(begin: 0.08),
                  const SizedBox(height: 14),
                  _Field(
                        ctrl: _emailCtrl,
                        label: 'Email',
                        hint: 'example@mail.ru',
                        icon: Icons.mail_outline,
                        type: TextInputType.emailAddress,
                      )
                      .animate()
                      .fadeIn(duration: 350.ms, delay: 200.ms)
                      .slideY(begin: 0.08),

                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    _ErrorBanner(_error!),
                  ],

                  // ── Change password ────────────────────────────────────────
                  // Пароль меняется только кодом на телефон (POST /auth/password/reset,
                  // аудит D01): старого маршрута «по текущему паролю» на сервере нет.
                  if ((user.phone ?? '').isNotEmpty) ...[
                    const SizedBox(height: 24),
                    GestureDetector(
                      onTap: () => _openPasswordReset(user.phone!),
                      child: Row(
                        children: [
                          RemoteText(
                            'app.editprofile.changePassword',
                            'СМЕНИТЬ ПАРОЛЬ',
                            style: TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                              letterSpacing: 1.5,
                              color: AppColors.black,
                            ),
                          ),
                          const Spacer(),
                          const Icon(
                            Icons.keyboard_arrow_right,
                            color: AppColors.grey600,
                          ),
                        ],
                      ),
                    ),
                  ],

                  // ── Addresses ──────────────────────────────────────────────
                  const SizedBox(height: 28),
                  Row(
                    children: [
                      RemoteText(
                        'app.editprofile.addresses',
                        'АДРЕСА ДОСТАВКИ',
                        style: TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 1.5,
                          color: AppColors.black,
                        ),
                      ),
                      if (user.addresses.isNotEmpty) ...[
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 7,
                            vertical: 2,
                          ),
                          color: AppColors.black,
                          child: Text(
                            '${user.addresses.length}',
                            style: const TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.w700,
                              color: Colors.white,
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                  const SizedBox(height: 12),

                  if (user.addresses.isEmpty && !_showAddressForm)
                    const RemoteText(
                      'app.editprofile.noAddresses',
                      'Нет сохранённых адресов',
                      style: TextStyle(fontSize: 13, color: AppColors.grey600),
                    ),

                  // Address list
                  ...user.addresses.asMap().entries.map((e) {
                    final i = e.key;
                    final addr = e.value;
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Container(
                        padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
                        decoration: BoxDecoration(
                          border: Border.all(color: AppColors.grey200),
                        ),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Padding(
                              padding: EdgeInsets.only(top: 1),
                              child: Icon(
                                Icons.location_on_outlined,
                                size: 18,
                                color: AppColors.grey600,
                              ),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  if (addr.label.isNotEmpty)
                                    Text(
                                      addr.label,
                                      style: const TextStyle(
                                        fontSize: 12,
                                        fontWeight: FontWeight.w700,
                                        color: AppColors.grey600,
                                        letterSpacing: 0.5,
                                      ),
                                    ),
                                  Text(
                                    addr.displayLine,
                                    style: const TextStyle(
                                      fontSize: 13,
                                      color: AppColors.black,
                                      height: 1.4,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            GestureDetector(
                              onTap: () =>
                                  context.read<AuthProvider>().removeAddress(i),
                              child: const Padding(
                                padding: EdgeInsets.all(6),
                                child: Icon(
                                  Icons.close,
                                  size: 16,
                                  color: AppColors.grey400,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ).animate(delay: (i * 50).ms).fadeIn(duration: 250.ms),
                    );
                  }),

                  // Add address button
                  const SizedBox(height: 8),
                  GestureDetector(
                    onTap: () =>
                        setState(() => _showAddressForm = !_showAddressForm),
                    child: Container(
                      height: 44,
                      decoration: BoxDecoration(
                        border: Border.all(
                          color: _showAddressForm
                              ? AppColors.black
                              : AppColors.grey200,
                          width: _showAddressForm ? 1.5 : 1,
                        ),
                      ),
                      alignment: Alignment.center,
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(
                            _showAddressForm ? Icons.remove : Icons.add,
                            size: 16,
                            color: AppColors.grey600,
                          ),
                          const SizedBox(width: 6),
                          RemoteText(
                            _showAddressForm
                                ? 'app.editprofile.cancel'
                                : 'app.editprofile.addAddress',
                            _showAddressForm ? 'Отмена' : 'Добавить адрес',
                            style: const TextStyle(
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                              color: AppColors.grey600,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),

                  // Inline address form
                  AnimatedCrossFade(
                    duration: const Duration(milliseconds: 300),
                    crossFadeState: _showAddressForm
                        ? CrossFadeState.showFirst
                        : CrossFadeState.showSecond,
                    firstChild: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const SizedBox(height: 16),
                        _Field(
                          ctrl: _labelCtrl,
                          label: 'Название (необязательно)',
                          hint: 'Дом, Работа...',
                          icon: Icons.label_outline,
                        ),
                        const SizedBox(height: 12),
                        _Field(
                          ctrl: _addressCityCtrl,
                          label: 'Город',
                          hint: 'Москва',
                          icon: Icons.location_city_outlined,
                        ),
                        const SizedBox(height: 12),
                        _Field(
                          ctrl: _streetCtrl,
                          label: 'Улица',
                          hint: 'ул. Ленина',
                          icon: Icons.signpost_outlined,
                        ),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            Expanded(
                              flex: 2,
                              child: _Field(
                                ctrl: _houseCtrl,
                                label: 'Дом',
                                hint: '12А',
                                icon: Icons.home_outlined,
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: _Field(
                                ctrl: _buildingCtrl,
                                label: 'Корпус',
                                hint: '1',
                                icon: Icons.apartment_outlined,
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: _Field(
                                ctrl: _aptCtrl,
                                label: 'Кв.',
                                hint: '45',
                                icon: Icons.door_front_door_outlined,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        _Field(
                          ctrl: _postalCtrl,
                          label: 'Индекс (необязательно)',
                          hint: '101000',
                          icon: Icons.markunread_mailbox_outlined,
                          type: TextInputType.number,
                        ),
                        if (_addressError != null) ...[
                          const SizedBox(height: 10),
                          _ErrorBanner(_addressError!),
                        ],
                        const SizedBox(height: 14),
                        GestureDetector(
                          onTap: _submitAddress,
                          child: Container(
                            height: 46,
                            color: AppColors.black,
                            alignment: Alignment.center,
                            child: RemoteText(
                              'app.editprofile.add',
                              'ДОБАВИТЬ',
                              style: TextStyle(
                                fontSize: 14,
                                fontWeight: FontWeight.w600,
                                color: Colors.white,
                                letterSpacing: 2,
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                    secondChild: const SizedBox.shrink(),
                  ),

                  const SizedBox(height: 32),

                  // ── Save button ────────────────────────────────────────────
                  Consumer<AuthProvider>(
                        builder: (context, a, _) => GestureDetector(
                          onTap: a.isLoading || _saved ? null : _save,
                          child: AnimatedContainer(
                            duration: const Duration(milliseconds: 150),
                            height: 52,
                            color: _saved
                                ? const Color(0xFF2E7D32)
                                : a.isLoading
                                ? AppColors.grey800
                                : AppColors.black,
                            alignment: Alignment.center,
                            child: _saved
                                ? const Row(
                                    mainAxisAlignment: MainAxisAlignment.center,
                                    children: [
                                      Icon(
                                        Icons.check,
                                        color: Colors.white,
                                        size: 18,
                                      ),
                                      SizedBox(width: 8),
                                      RemoteText(
                                        'app.editprofile.saved',
                                        'СОХРАНЕНО',
                                        style: TextStyle(
                                          fontSize: 15,
                                          fontWeight: FontWeight.w600,
                                          color: Colors.white,
                                          letterSpacing: 2,
                                        ),
                                      ),
                                    ],
                                  )
                                : a.isLoading
                                ? const SizedBox(
                                    width: 22,
                                    height: 22,
                                    child: CircularProgressIndicator(
                                      color: Colors.white,
                                      strokeWidth: 2,
                                    ),
                                  )
                                : RemoteText(
                                    'app.editprofile.save',
                                    'СОХРАНИТЬ',
                                    style: TextStyle(
                                      fontSize: 15,
                                      fontWeight: FontWeight.w600,
                                      color: Colors.white,
                                      letterSpacing: 2,
                                    ),
                                  ),
                          ),
                        ),
                      )
                      .animate()
                      .fadeIn(duration: 350.ms, delay: 260.ms)
                      .slideY(begin: 0.08),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _initialsWidget(String name) {
    final parts = name.trim().split(' ');
    final initials = parts.length >= 2
        ? '${parts[0][0]}${parts[1][0]}'.toUpperCase()
        : name.isNotEmpty
        ? name[0].toUpperCase()
        : '?';
    return Center(
      child: Text(
        initials,
        style: TextStyle(
          fontSize: 28,
          fontWeight: FontWeight.w700,
          color: Colors.white,
        ),
      ),
    );
  }
}

// ─── Header ───────────────────────────────────────────────────────────────────

class _Header extends StatelessWidget {
  final VoidCallback onClose;
  const _Header({required this.onClose});

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.black,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 8, 24, 20),
          child: Row(
            children: [
              RemoteText(
                'app.editprofile.title',
                'РЕДАКТИРОВАТЬ ПРОФИЛЬ',
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                  letterSpacing: 1.5,
                ),
              ).animate().fadeIn(duration: 400.ms).slideX(begin: -0.1),
              const Spacer(),
              // Крупный хит-эрия + opaque, чтобы крестик уверенно тапался и не
              // жался к самому краю (замечание владельца).
              GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: onClose,
                child: const Padding(
                  padding: EdgeInsets.all(12),
                  child: Icon(Icons.close, color: Colors.white, size: 22),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ─── Locked field ─────────────────────────────────────────────────────────────

// ─── Editable field ───────────────────────────────────────────────────────────

class _Field extends StatefulWidget {
  final TextEditingController ctrl;
  final String label;
  final String hint;
  final IconData icon;
  final TextInputType? type;
  final TextCapitalization cap;

  const _Field({
    required this.ctrl,
    required this.label,
    required this.hint,
    required this.icon,
    this.type,
    this.cap = TextCapitalization.none,
  });

  @override
  State<_Field> createState() => _FieldState();
}

class _FieldState extends State<_Field> {
  bool _focused = false;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          widget.label.toUpperCase(),
          style: const TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.2,
            color: AppColors.grey600,
          ),
        ),
        const SizedBox(height: 6),
        AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          decoration: BoxDecoration(
            border: Border.all(
              color: _focused ? AppColors.black : AppColors.grey200,
              width: _focused ? 1.5 : 1,
            ),
          ),
          child: Focus(
            onFocusChange: (f) => setState(() => _focused = f),
            child: TextField(
              controller: widget.ctrl,
              keyboardType: widget.type,
              textCapitalization: widget.cap,
              style: const TextStyle(fontSize: 15, color: AppColors.black),
              decoration: InputDecoration(
                hintText: widget.hint,
                hintStyle: const TextStyle(
                  color: AppColors.grey400,
                  fontSize: 14,
                ),
                prefixIcon: Icon(
                  widget.icon,
                  size: 18,
                  color: _focused ? AppColors.black : AppColors.grey400,
                ),
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
                contentPadding: const EdgeInsets.symmetric(vertical: 14),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

// ─── Error banner ─────────────────────────────────────────────────────────────

class _ErrorBanner extends StatelessWidget {
  final String message;
  const _ErrorBanner(this.message);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      color: const Color(0xFFFFF0F0),
      child: Row(
        children: [
          const Icon(Icons.error_outline, size: 16, color: AppColors.red),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(fontSize: 13, color: AppColors.red),
            ),
          ),
        ],
      ),
    ).animate().fadeIn(duration: 250.ms).shakeX(hz: 3, amount: 4);
  }
}
