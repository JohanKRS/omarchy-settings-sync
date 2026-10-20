"""Recognize explicit choice questions in prose, without treating every list as input."""
from __future__ import annotations

from dataclasses import dataclass
import re
from xml.etree import ElementTree

from message_markup import inline_markup


@dataclass
class Choice:
    marker: str
    text: str
    tokens: list


@dataclass
class ChoiceGroup:
    question: str
    choices: list[Choice]
    intro: list


def plain_text(tokens):
    return ''.join(ElementTree.fromstring('<root>' + inline_markup(tokens) + '</root>').itertext()).strip()


def choice_question(token):
    if token.get('type') not in {'paragraph', 'heading'}:
        return ''
    text = plain_text(token.get('children', []))
    # Restrict this convenience to explicit selection language in the UI's
    # supported languages. Ordinary instructions, checklists and code stay text.
    selection = re.search(
        r'\b(which|prefer|choose|select|would you like|do you want|'
        r'qual|quais|prefere|quer|deseja|escolha|escolher|selecione|'
        r'cuál|cuáles|prefieres|quieres|deseas|elige|elegir|selecciona)\b', text, re.I)
    if selection and ('?' in text or text.rstrip().endswith(':')):
        return text
    return ''


def list_choices(token):
    if token.get('type') != 'list':
        return []
    choices = []
    attrs = token.get('attrs', {})
    for index, item in enumerate(token['children'], attrs.get('start', 1)):
        blocks = item.get('children', [])
        if item['type'] != 'list_item' or any(b['type'] not in {'paragraph', 'block_text'} for b in blocks):
            return []
        children = []
        for block in blocks:
            if children:
                children.append({'type': 'linebreak'})
            children.extend(block.get('children', []))
        text = plain_text(children)
        if not text:
            return []
        choices.append(Choice(f'{index}.' if attrs.get('ordered') else '•', text, children))
    return choices if 2 <= len(choices) <= 8 else []


def letter_choices(token):
    """Markdown leaves A)/B) options as a paragraph; preserve their formatting."""
    if token.get('type') != 'paragraph':
        return [], []
    lines = [[]]
    for child in token.get('children', []):
        if child['type'] in {'softbreak', 'linebreak'}:
            lines.append([])
        else:
            lines[-1].append(child)
    choices, intro = [], []
    for line in lines:
        first = line[0] if line else {}
        match = re.match(r'^([A-Ha-h])[.)]\s+', first.get('raw', '')) if first.get('type') == 'text' else None
        if not match:
            if choices:
                return [], []
            if intro:
                intro.append({'type': 'softbreak'})
            intro.extend(line)
            continue
        if match[1].lower() != chr(ord('a') + len(choices)):
            return [], []
        children = [{**first, 'raw': first['raw'][match.end():]}, *line[1:]]
        text = plain_text(children)
        if not text:
            return [], []
        choices.append(Choice(match[0].strip(), text, children))
    return (choices, intro) if 2 <= len(choices) <= 8 else ([], [])


def choice_groups(tokens):
    groups = {}
    visible = [i for i, token in enumerate(tokens) if token['type'] != 'blank_line']
    for position, index in enumerate(visible):
        choices, intro = list_choices(tokens[index]), []
        if not choices:
            choices, intro = letter_choices(tokens[index])
        if not choices:
            continue
        question = choice_question({'type': 'paragraph', 'children': intro}) if intro else ''
        for neighbor in (position - 1, position + 1):
            if not question and 0 <= neighbor < len(visible):
                question = choice_question(tokens[visible[neighbor]])
        if question:
            groups[index] = ChoiceGroup(question, choices, intro)
    return groups
