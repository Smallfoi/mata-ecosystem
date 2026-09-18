"""Юридические документы экосистемы и аудит согласий пользователей (§3, §13
docs/LAUNCH_READINESS.md). Документы версионируются (тип + версия) и публикуются
(published_at). UserConsent фиксирует, кто/когда/какую версию принял, из какого
продукта и факт отзыва — этого требует launch-gate. Текст документов заполняет
юрист позже; здесь — инфраструктура хранения и аудита."""
from django.db import models
from django.utils import timezone

from accounts.models import Account


class LegalDocument(models.Model):
    TERMS = "terms"            # Пользовательское соглашение
    PRIVACY = "privacy"        # Политика конфиденциальности
    PD_CONSENT = "pd_consent"  # Согласие на обработку персональных данных
    MARKETING = "marketing"    # Согласие на рекламные коммуникации
    OFFER = "offer"            # Публичная оферта (Store)
    LOYALTY = "loyalty"        # Правила программы лояльности
    CLUB = "club"              # Правила сообщества/клубов
    DELIVERY = "delivery"      # Доставка и получение заказа
    RETURNS = "returns"        # Возврат и обмен
    DISTRIBUTION = "distribution"  # Согласие на распространение ПДн (ст. 10.1 152-ФЗ)
    COMPETITION = "competition"    # Правила соревнований и наград (публичный конкурс, гл. 57 ГК)
    CONTACTS = "contacts"          # Контакты продавца (реквизиты, связь, соцсети, лояльность)
    TYPE_CHOICES = [
        (TERMS, "Пользовательское соглашение"),
        (PRIVACY, "Политика конфиденциальности"),
        (PD_CONSENT, "Согласие на обработку ПД"),
        (MARKETING, "Рекламные коммуникации"),
        (OFFER, "Оферта (Store)"),
        (LOYALTY, "Правила лояльности"),
        (CLUB, "Правила сообщества"),
        # Требуются платёжными сервисами: покупатель обязан видеть до оплаты,
        # как он получит товар и как вернёт деньги (ЮKassa проверяет это на модерации).
        (DELIVERY, "Доставка и получение"),
        (RETURNS, "Возврат и обмен"),
        # Отдельное согласие на РАСПРОСТРАНЕНИЕ ПДн (публичный профиль/лидерборд/клуб) —
        # строгая форма по ст. 10.1 152-ФЗ (с 01.03.2021).
        (DISTRIBUTION, "Распространение ПДн (ст. 10.1)"),
        # Правила соревнований/челленджей (публичный конкурс, гл. 57 ГК) — показываются
        # как правила, отдельным обязательным согласием по умолчанию не гейтятся.
        (COMPETITION, "Правила соревнований"),
        # Контакты продавца — редактируются в админке, показываются на сайте и в
        # приложениях (одно место → везде).
        (CONTACTS, "Контакты"),
    ]

    doc_type = models.CharField(max_length=20, choices=TYPE_CHOICES, db_index=True, verbose_name="Тип документа")
    version = models.CharField(max_length=20, verbose_name="Версия")  # напр. "1.0"
    title = models.CharField(max_length=200, verbose_name="Заголовок")
    body = models.TextField(blank=True, default="", verbose_name="Текст")  # текст документа (заполняет юрист)
    is_required = models.BooleanField(default=False, verbose_name="Обязателен к принятию")
    published_at = models.DateTimeField(null=True, blank=True, verbose_name="Опубликован")  # null = черновик
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Создан")

    class Meta:
        db_table = "legal_documents"
        unique_together = [("doc_type", "version")]
        ordering = ["doc_type", "-created_at"]
        verbose_name = "Юридический документ"
        verbose_name_plural = "Юридические документы"

    def __str__(self) -> str:
        return f"{self.get_doc_type_display()} v{self.version}"

    @property
    def is_published(self) -> bool:
        return self.published_at is not None

    def to_json(self, accepted=None) -> dict:
        data = {
            "id": str(self.pk),
            "type": self.doc_type,
            "version": self.version,
            "title": self.title,
            "body": self.body,
            "required": self.is_required,
            "publishedAt": self.published_at.isoformat() if self.published_at else None,
        }
        if accepted is not None:
            data["accepted"] = accepted
        return data

    @classmethod
    def current(cls):
        """Последняя опубликованная версия каждого типа документа."""
        latest = {}
        for d in cls.objects.filter(published_at__isnull=False).order_by(
            "doc_type", "-published_at"
        ):
            latest.setdefault(d.doc_type, d)  # первая на тип = самая свежая
        return list(latest.values())


class UserConsent(models.Model):
    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    document = models.ForeignKey(
        LegalDocument, on_delete=models.PROTECT, related_name="consents", verbose_name="Документ"
    )
    accepted_at = models.DateTimeField(default=timezone.now, verbose_name="Принято")
    source = models.CharField(max_length=30, blank=True, default="", verbose_name="Источник")  # kvartal|mata_store|site
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name="Отозвано")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Создано")

    class Meta:
        db_table = "user_consents"
        ordering = ["-accepted_at"]
        verbose_name = "Согласие пользователя"
        verbose_name_plural = "Согласия пользователей"

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    def to_json(self) -> dict:
        return {
            "id": str(self.pk),
            "type": self.document.doc_type,
            "version": self.document.version,
            "acceptedAt": self.accepted_at.isoformat(),
            "source": self.source,
            "revokedAt": self.revoked_at.isoformat() if self.revoked_at else None,
            "active": self.active,
        }


def record_consent(user_id, document, source=""):
    """Зафиксировать согласие (идемпотентно: повторное принятие той же версии не дублируется)."""
    if not user_id or document is None:
        return None
    consent, _ = UserConsent.objects.get_or_create(
        user_id=user_id,
        document=document,
        revoked_at=None,
        defaults={"source": source},
    )
    return consent


class ConsentClient(Account):
    """Клиент глазами юриста: один раз в списке, согласия — внутри (админка «Согласия»).

    Отдельной таблицы нет — это тот же аккаунт. Прокси нужен, чтобы у списка клиентов
    с согласиями был свой раздел и свои права во вкладке «Документы и согласия».
    """

    class Meta:
        proxy = True
        verbose_name = "Согласия клиента"
        verbose_name_plural = "Согласия клиентов"
