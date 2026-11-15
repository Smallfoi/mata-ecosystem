from celery import shared_task


@shared_task(name="attestation.verify_integrity", ignore_result=True)
def verify_integrity(check_pk):
    from .service import verify

    verify(check_pk)
