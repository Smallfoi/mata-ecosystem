"""Обработка исходника в «стиль МАТА» по треку → мастер (высокое разрешение).

Трек 1 «catalog» — товар без человека, точность важна (беречь принт/цвет/крой).
Трек 2 «model»   — товар на модели, генерация свободнее (это реклама, не карточка).
Готовый мастер дальше превращаем в webp (images.make_webp) и раскладываем по карточкам.
"""
from productmedia import prompts, providers

# трек → (встроенный промт, размер, беречь товар точнее)
TRACKS = {
    "catalog": (prompts.CATALOG, "1024x1536", True),
    "model": (prompts.MODEL, "1024x1536", False),
}


def process(source_bytes: bytes, track: str = "catalog", text: str = "",
            note: str = "", details=None, base: str = "") -> bytes:
    """Исходник → мастер по выбранному треку. Кидает ImageProviderError при сбое/без ключа.

    text    — буквальный текст принта, если известен (prompts.with_text);
    note    — замечание проверяющего к повторной попытке (prompts.with_note);
    details — байты крупных планов принта, уходят в запрос следующими картинками;
    base    — текст промта из админки (версия PhotoPrompt); пусто — встроенный.
    """
    if track not in TRACKS:
        raise providers.ImageProviderError("неизвестный трек: %s" % track)
    builtin, size, high_fidelity = TRACKS[track]
    details = [d for d in (details or []) if d]
    prompt = (base or "").strip() or builtin
    prompt = prompts.with_details(prompt, len(details))
    prompt = prompts.with_note(prompts.with_text(prompt, text), note)
    return providers.edit_image(source_bytes, prompt, size=size, high_fidelity=high_fidelity,
                                extra_images=details)
