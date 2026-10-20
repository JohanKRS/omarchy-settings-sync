from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
from message_markup import html_markup, inline_markup, parse_markdown, safe_href


def inline(text):
    return inline_markup(parse_markdown(text)[0]['children'])


class MessageMarkupTests(unittest.TestCase):
    def test_table_with_inline_formatting_and_alignment(self):
        table = parse_markdown('| Option | Result |\n| :--- | ---: |\n'
                               '| **Use** `~/Desktop` | [Source](https://example.com) |')[0]
        self.assertEqual(table['type'], 'table')
        self.assertEqual(table['children'][0]['children'][1]['attrs']['align'], 'right')
        row = table['children'][1]['children'][0]['children']
        self.assertEqual(inline_markup(row[0]['children']), '<b>Use</b> <tt>~/Desktop</tt>')
        self.assertEqual(inline_markup(row[1]['children']), '<a href="https://example.com">Source</a>')

    def test_combined_inline_and_entities(self):
        self.assertEqual(inline('**Bold *nested*** ~~old~~ `x < y` &amp; &lt;tag&gt;'),
                         '<b>Bold <i>nested</i></b> <s>old</s> <tt>x &lt; y</tt> &amp; &lt;tag&gt;')
        self.assertEqual(inline('`&amp; **literal**`'), '<tt>&amp;amp; **literal**</tt>')

    def test_links_and_autolinks(self):
        for source in ('[Example](https://example.com?a=1&b=2)', '<https://example.com?a=1&b=2>',
                       'https://example.com?a=1&b=2'):
            root = ElementTree.fromstring('<root>' + inline(source) + '</root>')
            self.assertEqual(root.find('a').attrib['href'], 'https://example.com?a=1&b=2')
        self.assertEqual(safe_href('/tmp/report.md'), 'file:///tmp/report.md')
        self.assertEqual(safe_href('mailto:person@example.com'), 'mailto:person@example.com')

    def test_html_inline_allowlist(self):
        self.assertEqual(html_markup('<strong>A</strong><br/><em>B</em> <kbd>Enter</kbd> H<sub>2</sub>'),
                         '<b>A</b>\n<i>B</i> <tt>Enter</tt> H<sub>2</sub>')
        self.assertEqual(html_markup('<b onclick="alert(1)">Hello</b>'), '<b>Hello</b>')
        self.assertEqual(html_markup('<script>alert(1)</script>'), '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertEqual(html_markup('<span foreground="red">Text</span>'),
                         '&lt;span foreground=&quot;red&quot;&gt;Text&lt;/span&gt;')

    def test_unsafe_links_cannot_be_activated(self):
        for url in ('javascript:alert(1)', 'data:text/html,hi', 'vscode:open', '//example.com',
                    'file://remote/share', 'https://', 'https://example.com\n', 'http://[broken'):
            self.assertIsNone(safe_href(url), url)
        self.assertEqual(html_markup('<a href="jav&#x61;script:alert(1)">Click</a>'), 'Click')
        self.assertNotIn('<a ', inline('[Click](javascript:evil)'))

    def test_streaming_fragments_always_produce_balanced_markup(self):
        text = '**Bold** <b>mixed <i>HTML</b></i> &amp; `x < 3` [Link](https://example.com)'
        for end in range(1, len(text) + 1):
            markup = inline(text[:end])
            ElementTree.fromstring('<root>' + markup + '</root>')

    def test_nested_lists_and_code_are_preserved(self):
        tokens = parse_markdown('3. First\n   - Nested\n4. Second\n\n```html\n<b>literal</b>\n```')
        self.assertEqual(tokens[0]['attrs']['start'], 3)
        self.assertEqual(tokens[0]['children'][0]['children'][1]['type'], 'list')
        self.assertEqual(tokens[-1]['type'], 'block_code')
        self.assertEqual(tokens[-1]['raw'], '<b>literal</b>\n')


if __name__ == '__main__':
    unittest.main()
