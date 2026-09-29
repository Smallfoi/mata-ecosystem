"""Зеркало старого реестра в лоты v1 (см. loyalty/v1.py, «Как совмещены два реестра»)."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import LoyaltyTransaction


@receiver(post_save, sender=LoyaltyTransaction)
def _mirror_to_lots(sender, instance, created, **kwargs):
    if created and instance.amount:
        from .v1 import mirror_legacy

        mirror_legacy(instance)
