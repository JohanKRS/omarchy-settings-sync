"""Parse Markdown and convert only supported inline formatting to GTK markup."""
from __future__ import annotations

from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlsplit

# Ship the pinned parser with the plugin, without requiring a system package.
sys.path.insert(0, str(Path(__file__).with_name('_vendor')))
import mistune

parse_markdown = mistune.create_markdown(
    renderer='ast', plugins=['table', 'strikethrough', 'url', 'task_lists'])


def safe_href(value):
    """Allow explicit web/mail/local-file links; never execute other schemes."""
    if not value or re.search(r'[\x00-\x20\x7f]', value):
        return None
    if value.startswith('/') and not value.startswith('//'):
        return 'file://' + quote(value, safe='/:%')
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    scheme = url.scheme.lower()
    if scheme in {'http', 'https'} and url.hostname:
        return value
    if scheme == 'mailto' and url.path:
        return value
    if scheme == 'file' and url.netloc in {'', 'localhost'} and url.path.startswith('/'):
        return value
    return None


class InlineHTML(HTMLParser):
    """Balance a small formatting whitelist. Other HTML is displayed literally."""
    TAGS = {'b': 'b', 'strong': 'b', 'i': 'i', 'em': 'i', 'u': 'u',
            's': 's', 'del': 's', 'strike': 's', 'code': 'tt', 'tt': 'tt',
            'kbd': 'tt', 'samp': 'tt', 'small': 'small', 'sub': 'sub', 'sup': 'sup'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.parts.append('\n')
        elif tag in self.TAGS:
            target = self.TAGS[tag]
            self.parts.append(f'<{target}>')
            self.tags.append((tag, target))
        elif tag == 'a':
            href = safe_href(dict(attrs).get('href'))
            target = 'a' if href and not any(t == 'a' for _, t in self.tags) else None
            if target:
                self.parts.append(f'<a href="{escape(href, quote=True)}">')
            self.tags.append((tag, target))
        else:
            self.parts.append(escape(self.get_starttag_text()))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != 'br':
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == 'br':
            return
        index = next((i for i in range(len(self.tags) - 1, -1, -1) if self.tags[i][0] == tag), None)
        if index is None:
            self.parts.append(escape(f'</{tag}>'))
            return
        while len(self.tags) > index:
            _, target = self.tags.pop()
            if target:
                self.parts.append(f'</{target}>')

    def handle_data(self, data):
        # Pango uses XML 1.0. Discard controls that XML cannot represent.
        self.parts.append(escape(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', data)))

    def handle_comment(self, data):
        self.parts.append(escape(f'<!--{data}-->'))

    def markup(self):
        self.close()
        while self.tags:
            _, target = self.tags.pop()
            if target:
                self.parts.append(f'</{target}>')
        return ''.join(self.parts)


def html_markup(source):
    parser = InlineHTML()
    parser.feed(source)
    return parser.markup()


def _inline_html(tokens):
    parts = []
    for token in tokens:
        kind = token['type']
        children = token.get('children', [])
        if kind == 'text':
            parts.append(escape(unescape(token['raw'])))
        elif kind == 'codespan':
            parts.append('<code>' + escape(token['raw']) + '</code>')
        elif kind in {'strong', 'emphasis', 'strikethrough'}:
            tag = {'strong': 'b', 'emphasis': 'i', 'strikethrough': 's'}[kind]
            parts.append(f'<{tag}>' + _inline_html(children) + f'</{tag}>')
        elif kind in {'link', 'image'}:
            body = _inline_html(children) or escape(token['attrs']['url'])
            href = safe_href(token['attrs']['url'])
            parts.append(f'<a href="{escape(href, quote=True)}">{body}</a>' if href else body)
        elif kind == 'inline_html':
            parts.append(token['raw'])
        elif kind in {'softbreak', 'linebreak'}:
            parts.append('\n' if kind == 'softbreak' else '<br>')
        elif children:
            parts.append(_inline_html(children))
        else:
            parts.append(escape(token.get('raw', '')))
    return ''.join(parts)


def inline_markup(tokens):
    return html_markup(_inline_html(tokens))
