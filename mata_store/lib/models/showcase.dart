/// Вкладки витрины (D-133): «Обувь / Одежда / Аксессуары / Питание» поверх
/// категорий 1С. Бэкенд `GET /v1/showcase` отдаёт только непустые вкладки и
/// группы; карточка попадает в группу, если её categoryId в [categoryIds].
class ShowcaseGroup {
  final String id;
  final String name;
  final int count;
  final List<String> categoryIds;

  const ShowcaseGroup({
    required this.id,
    required this.name,
    required this.count,
    required this.categoryIds,
  });

  factory ShowcaseGroup.fromJson(Map<String, dynamic> j) => ShowcaseGroup(
        id: '${j['id']}',
        name: '${j['name']}',
        count: (j['count'] as num?)?.toInt() ?? 0,
        categoryIds: [for (final c in (j['categoryIds'] as List? ?? const [])) '$c'],
      );
}

class ShowcaseTab {
  final String id;
  final String name;
  final int count;
  final List<ShowcaseGroup> groups;

  const ShowcaseTab({
    required this.id,
    required this.name,
    required this.count,
    required this.groups,
  });

  /// Все категории 1С вкладки — для фильтра «вся вкладка».
  Set<String> get categoryIds => {for (final g in groups) ...g.categoryIds};

  factory ShowcaseTab.fromJson(Map<String, dynamic> j) => ShowcaseTab(
        id: '${j['id']}',
        name: '${j['name']}',
        count: (j['count'] as num?)?.toInt() ?? 0,
        groups: [
          for (final g in (j['groups'] as List? ?? const []))
            ShowcaseGroup.fromJson(g as Map<String, dynamic>)
        ],
      );
}
