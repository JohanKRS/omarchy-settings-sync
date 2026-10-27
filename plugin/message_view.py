"""Native, selectable Markdown messages; no browser or remote asset loading."""
from __future__ import annotations

from html import escape
import re

from gi.repository import Gtk, Pango

from message_markup import html_markup, inline_markup, parse_markdown
from message_choices import choice_groups
from i18n import tr


class TableView(Gtk.Box):
    """Measure wrapped cells at their allocated width, not the narrow minimum.

    ScrolledWindow with horizontal scrolling requests a constant height. A
    height-for-width parent must supply the grid's actual wrapped height.
    """
    def __init__(self, grid):
        super().__init__(hexpand=True)
        self.set_layout_manager(None)
        self.grid = grid
        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                         vscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroll.set_child(grid)
        self.append(self.scroll)

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            _, natural, _, _ = self.grid.measure(orientation, -1)
            return 0, natural, -1, -1
        width = max(for_size, self.grid.measure(Gtk.Orientation.HORIZONTAL, -1)[0])
        minimum, natural, _, _ = self.grid.measure(orientation, width)
        return minimum, natural, -1, -1

    def do_size_allocate(self, width, height, baseline):
        self.scroll.allocate(width, height, baseline, None)


def markup_label(markup, *, xalign=0):
    label = Gtk.Label(xalign=xalign, yalign=0, wrap=True, selectable=True, hexpand=True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.set_max_width_chars(1)
    label.set_markup(markup)
    return label


class MessageBody(Gtk.Box):
    def __init__(self, text, *, on_choice=None, complete=True, choices_answered=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        self.text = None
        self.on_choice = on_choice
        self.complete = complete
        self.choices_answered = choices_answered
        self.choices_enabled = False
        self.choice_buttons = []
        self.set_text(text)

    def get_text(self):
        # Streaming appends to the original Markdown, never the rendered text.
        return self.text

    def set_text(self, text, *, complete=None):
        complete = self.complete if complete is None else complete
        if text == self.text and complete == self.complete:
            return
        self.text = text
        self.complete = complete
        self.choice_buttons = []
        while self.get_first_child():
            self.remove(self.get_first_child())
        tokens = parse_markdown(text)
        groups = choice_groups(tokens) if self.on_choice and complete else {}
        self.render_blocks(tokens, self, groups)

    def set_choices_enabled(self, enabled):
        self.choices_enabled = enabled and not self.choices_answered
        for button in self.choice_buttons:
            button.set_sensitive(self.choices_enabled)

    def choice_list(self, group):
        listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        if group.intro:
            listing.append(markup_label(inline_markup(group.intro)))
        for choice in group.choices:
            button = Gtk.Button(hexpand=True)
            button.add_css_class('conversation-choice')
            # Links inside an option are displayed as text: activating the row
            # has exactly one meaning, sending the selected answer.
            markup = re.sub(r'</?a(?:\s[^>]*)?>', '', inline_markup(choice.tokens))
            body = markup_label(escape(choice.marker + ' ') + markup)
            body.set_selectable(False)
            button.set_child(body)
            button.set_tooltip_text(tr('Reply now with this option'))
            button.set_sensitive(self.choices_enabled and not self.choices_answered)
            button.connect('clicked', lambda _, q=group.question, a=choice.text:
                           self.on_choice(q, a) if self.choices_enabled and not self.choices_answered else None)
            self.choice_buttons.append(button)
            listing.append(button)
        return listing

    def render_blocks(self, tokens, container, groups=None):
        for index, token in enumerate(tokens):
            if groups and index in groups:
                container.append(self.choice_list(groups[index]))
                continue
            kind = token['type']
            children = token.get('children', [])
            if kind in {'paragraph', 'block_text', 'heading'}:
                content = inline_markup(children)
                if kind == 'heading':
                    content = '<b>' + content + '</b>'
                widget = markup_label(content)
                if kind == 'heading':
                    widget.add_css_class('markdown-heading')
                container.append(widget)
            elif kind == 'table':
                container.append(self.table(token))
            elif kind == 'block_code':
                widget = markup_label('<tt>' + escape(token['raw'].rstrip('\n')) + '</tt>')
                widget.add_css_class('markdown-code')
                container.append(widget)
            elif kind == 'block_quote':
                quote = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                quote.add_css_class('markdown-quote')
                self.render_blocks(children, quote)
                container.append(quote)
            elif kind == 'list':
                listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                attrs = token.get('attrs', {})
                for index, item in enumerate(children, attrs.get('start', 1)):
                    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                    bullet = f'{index}.' if attrs.get('ordered') else '•'
                    if item['type'] == 'task_list_item':
                        bullet = '☑' if item['attrs']['checked'] else '☐'
                    row.append(Gtk.Label(label=bullet, valign=Gtk.Align.START))
                    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
                    self.render_blocks(item['children'], body)
                    row.append(body)
                    listing.append(row)
                container.append(listing)
            elif kind == 'thematic_break':
                container.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            elif kind == 'block_html':
                container.append(markup_label(html_markup(token['raw'])))
            elif children:
                self.render_blocks(children, container)
            elif token.get('raw'):
                container.append(markup_label(escape(token['raw'])))

    @staticmethod
    def table(token):
        grid = Gtk.Grid(column_homogeneous=True, hexpand=True)
        grid.add_css_class('markdown-table')
        rows = [token['children'][0]['children']]
        rows.extend(row['children'] for row in token['children'][1]['children'])
        for y, row in enumerate(rows):
            for x, cell in enumerate(row):
                content = inline_markup(cell['children'])
                if y == 0:
                    content = '<b>' + content + '</b>'
                align = cell.get('attrs', {}).get('align')
                widget = markup_label(content, xalign={'center': .5, 'right': 1}.get(align, 0))
                widget.set_justify({'center': Gtk.Justification.CENTER,
                                    'right': Gtk.Justification.RIGHT}.get(align, Gtk.Justification.LEFT))
                widget.set_width_chars(8)
                widget.set_max_width_chars(8)
                widget.add_css_class('markdown-cell')
                if y == 0:
                    widget.add_css_class('markdown-table-header')
                grid.attach(widget, x, y, 1, 1)
        # Wide tables scroll locally; normal two/three-column tables wrap to fit.
        return TableView(grid)
