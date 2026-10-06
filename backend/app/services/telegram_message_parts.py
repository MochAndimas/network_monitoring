"""Deterministic plaintext Telegram transport segmentation."""


def telegram_message_parts(message: str, *, units: int = 4096) -> tuple[str, ...]:
    """Split plaintext without truncation or splitting Unicode code points."""
    if units < 2 or units > 4096:
        raise ValueError("Invalid Telegram part size")
    parts: list[str] = []
    start = size = 0
    for index, character in enumerate(message):
        width = 2 if ord(character) > 0xFFFF else 1
        if size + width > units:
            parts.append(message[start:index])
            start, size = index, 0
        size += width
    if start < len(message):
        parts.append(message[start:])
    return tuple(parts)
