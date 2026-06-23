import html
import re
from html.parser import HTMLParser


TELEGRAM_MESSAGE_LIMIT = 4096


class _HtmlToTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        normalized = tag.lower()
        if normalized in {"script", "style", "head", "title", "meta"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if normalized in {"br", "p", "div", "li", "tr", "table", "section"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        normalized = tag.lower()
        if normalized in {"script", "style", "head", "title", "meta"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if normalized in {"p", "div", "li", "tr", "table", "section"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth or not data:
            return
        self.parts.append(data)

    def get_text(self) -> str:
        return "".join(self.parts)


def html_to_text(value: str) -> str:
    parser = _HtmlToTextParser()
    parser.feed(value or "")
    parser.close()
    return html.unescape(parser.get_text())


def sanitize_mail_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"https?://\S*(?:utm_[^=\s]+|trk|tracking)\S*", "", text, flags=re.IGNORECASE)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_telegram_text(value: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks
