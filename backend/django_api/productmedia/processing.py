"""Обработка исходника в «стиль МАТА» по треку → мастер (высокое разрешение).

Трек 1 «catalog» — товар без человека, точность важна (беречь принт/цвет/крой).
Трек 2 «model»   — товар на модели, генерация свободнее (это реклама, не карточка).
Готовый мастер дальше превращаем в webp (images.make_webp) и раскладываем по карточкам.
"""
from productmedia import prompts, providers

# трек → (промт, размер, беречь товар точнее)
TRACKS = {
    "catalog": (prompts.CATALOG, "1024x1536", True),
    "model": (prompts.MODEL, "1024x1536", False),
}


def process(source_bytes: bytes, track: str = "catalog", text: str = "") -> bytes:
    """Исходник → мастер по выбранному треку. Кидает ImageProviderError при сбое/без ключа.

    text — буквальный текст принта, если известен (см. prompts.with_text).
    """
    if track not in TRACKS:
        raise providers.ImageProviderError("неизвестный трек: %s" % track)
    prompt, size, high_fidelity = TRACKS[track]
    prompt = prompts.with_text(prompt, text)
    return providers.edit_image(source_bytes, prompt, size=size, high_fidelity=high_fidelity)
