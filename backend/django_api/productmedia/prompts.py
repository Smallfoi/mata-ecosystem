"""Универсальные промты «стиль МАТА» для фотопайплайна (v2).

УНИВЕРСАЛЬНЫЕ: конкретный принт/цвет/текст НЕ зашиваем — модель берёт их из
приложенного референса. Стиль (свет/фон/кадр) фиксированный — это и есть единый вид
каталога.

Почему v2 на английском и по пунктам: на живых прогонах 27.09 обе модели (gpt-image-1 и
gpt-image-2.5-flare) при русском промте «сохрани надписи как есть» выдумывали слова
(«Staw Running Member» → «Stow Runbing Member» / «Slaw Running Machine») и меняли ткань.
Жёсткие пункты на английском модели держат надёжнее, а буквальный текст принта (если
известен) передаётся отдельно — with_text(); так буквы рисуются куда точнее, чем
«срисуй с фото». Текст не зашит в промт, поэтому промт остаётся универсальным.
"""

# Правила точности — общие для обоих треков.
_FIDELITY = (
    "PRODUCT FIDELITY (highest priority, never violate):\n"
    "- Use exactly ONE garment: the most prominent one in the reference image. "
    "Ignore everything else in the reference.\n"
    "- Keep the garment identical to the reference: same colour and shade, same "
    "fabric and surface texture (knit stays knit, woven stays woven, mesh stays mesh), "
    "same cut, length, proportions, neckline, seams, panels and trims.\n"
    "- Text, logos and graphics: reproduce them exactly as in the reference - the same "
    "letters and spelling, font style, size and position. Never invent, rephrase, "
    "translate or 'correct' any text. Do not add text or logos that are not in the "
    "reference. If the garment has no print, keep it plain.\n"
    "- Keep the SAME SIDE of the garment as in the reference: if the reference shows "
    "the back, show the back (back neckline, back panel); if it shows the front, show "
    "the front. Never move prints, text or graphics to another side of the garment, "
    "and do not invent what is on the side that is not visible.\n"
)

# Трек 1 — каталог: товар без человека, точность важна.
CATALOG = (
    "Create a professional e-commerce catalog photo of the garment from the reference "
    "image.\n"
    + _FIDELITY
    + "- Remove any person, mannequin, hanger and the original background.\n"
    "STYLE:\n"
    "- Ghost-mannequin (invisible mannequin), viewed straight on from the same side "
    "as in the reference: the garment keeps a natural "
    "worn shape, neatly smoothed, centred with even margins.\n"
    "- Pure white seamless background, soft natural contact shadow under the garment.\n"
    "- Large softbox key light plus fill, high-key, even exposure, crisp detail edge to "
    "edge, true-to-life colour, commercial catalog quality."
)

# Трек 2 — маркетинг: товар на модели (реклама, не карточка).
MODEL = (
    "Create a professional studio advertising photo of an athletic model wearing the "
    "garment from the reference image.\n"
    + _FIDELITY
    + "STYLE:\n"
    "- Model: athletic build, neutral expression, standing straight, arms relaxed along "
    "the body, no cap and no glasses; turned to the camera with the same side of the "
    "garment as in the reference (back to the camera if the reference shows the back). "
    "Framing from the thighs up.\n"
    "- Light-grey seamless studio background with a subtle gradient, large softbox key "
    "light and soft rim light, natural skin, sharp focus on the garment, commercial "
    "quality."
)


def with_text(prompt: str, text: str = "") -> str:
    """Добавить к промту буквальный текст принта, если он известен.

    Модели рисуют надпись точнее, когда строку им дают словами, а не просят срисовать
    с фото. Пустой текст — промт без изменений.
    """
    text = (text or "").strip()
    if not text:
        return prompt
    return (
        prompt
        + "\nPRINTED TEXT: the print on the garment reads exactly \"%s\". Render exactly "
        "these characters, letter for letter, in the same place and style as in the "
        "reference, and no other text." % text
    )


def with_note(prompt: str, note: str = "") -> str:
    """Добавить замечание проверяющего к промту повторной попытки («Переделать»).

    Замечание пишет человек на экране проверки («принт перенесён на перед», «не та
    ткань»); модель получает его как обязательную правку. Пустое — промт без изменений.
    """
    note = (note or "").strip()
    if not note:
        return prompt
    return (
        prompt
        + "\nREVIEWER FEEDBACK on the previous attempt - it was rejected for this reason, "
        "fix it now (the note may be in Russian): %s" % note
    )
