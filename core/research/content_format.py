from __future__ import annotations

from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse
import re


ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "ul",
    "ol",
    "li",
    "blockquote",
    "code",
    "pre",
    "a",
    "img",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
}
VOID_TAGS = {"br", "img", "hr"}
DATA_IMAGE_RE = re.compile(
    r"^data:image/(?:png|jpe?g|gif|webp);base64,[a-z0-9+/=\s]+$",
    re.IGNORECASE,
)
HTML_TAG_RE = re.compile(
    r"</?(?:p|br|strong|b|em|i|u|ul|ol|li|blockquote|code|pre|a|img|h[1-6]|hr)\b[^>]*>",
    re.IGNORECASE,
)
MAX_DATA_URI_LEN = 5_000_000


def _is_safe_httpish_url(raw: str) -> bool:
    parsed = urlparse(raw)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_safe_data_image(raw: str) -> bool:
    if len(raw) > MAX_DATA_URI_LEN:
        return False
    return bool(DATA_IMAGE_RE.match(raw))


def _normalize_space(raw: str) -> str:
    return " ".join((raw or "").split())


def looks_like_html(value: str | None) -> bool:
    text = str(value or "")
    return bool(HTML_TAG_RE.search(text))


class _SnippetHTMLSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._stack: list[str] = []
        self._drop_content_depth = 0

    def _append_start(self, tag: str, attrs: list[tuple[str, str]]) -> None:
        if attrs:
            attrs_str = " ".join(f'{k}="{escape(v, quote=True)}"' for k, v in attrs)
            self._out.append(f"<{tag} {attrs_str}>")
        else:
            self._out.append(f"<{tag}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = (tag or "").lower()
        if tag not in ALLOWED_TAGS:
            if tag in {"script", "style"}:
                self._drop_content_depth += 1
            return

        cleaned: list[tuple[str, str]] = []
        attr_map = {str(k).lower(): ("" if v is None else str(v)) for k, v in attrs}

        if tag == "a":
            href = attr_map.get("href", "").strip()
            if href and _is_safe_httpish_url(href):
                cleaned.append(("href", href))
                cleaned.append(("target", "_blank"))
                cleaned.append(("rel", "noopener noreferrer nofollow"))
            title = _normalize_space(attr_map.get("title", ""))
            if title:
                cleaned.append(("title", title[:500]))
        elif tag == "img":
            src = attr_map.get("src", "").strip()
            if src and (_is_safe_httpish_url(src) or _is_safe_data_image(src)):
                cleaned.append(("src", src))
                alt = _normalize_space(attr_map.get("alt", ""))
                if alt:
                    cleaned.append(("alt", alt[:500]))
                title = _normalize_space(attr_map.get("title", ""))
                if title:
                    cleaned.append(("title", title[:500]))
                cleaned.append(("loading", "lazy"))
                cleaned.append(("decoding", "async"))
            else:
                return

        self._append_start(tag, cleaned)
        if tag not in VOID_TAGS:
            self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = (tag or "").lower()
        if tag in {"script", "style"} and self._drop_content_depth > 0:
            self._drop_content_depth -= 1
            return
        if tag not in ALLOWED_TAGS or tag in VOID_TAGS or tag not in self._stack:
            return

        while self._stack:
            top = self._stack.pop()
            self._out.append(f"</{top}>")
            if top == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._drop_content_depth <= 0 and data:
            self._out.append(escape(data))

    def get_html(self) -> str:
        while self._stack:
            self._out.append(f"</{self._stack.pop()}>")
        return "".join(self._out).strip()


def sanitize_html_fragment(value: str | None) -> str:
    parser = _SnippetHTMLSanitizer()
    parser.feed(str(value or ""))
    parser.close()
    return parser.get_html()


def normalize_snippet_content(value: str | None) -> str:
    raw = str(value or "")
    if looks_like_html(raw):
        return sanitize_html_fragment(raw)
    return raw


def render_snippet_content(value: str | None) -> str:
    raw = str(value or "")
    if not raw.strip():
        return ""
    if looks_like_html(raw):
        return sanitize_html_fragment(raw)
    return escape(raw).replace("\n", "<br>")
