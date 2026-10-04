from __future__ import annotations
from dataclasses import dataclass
import re
from .toc_parser import normalize_text, _roman_to_int, _word_to_int, SMALL_NUMBER_WORDS

@dataclass
class Heading:
    label: tuple[int, ...]
    kind: str
    display: str
    title: str
CHINESE = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '兩': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}

def chinese_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    total = current = 0
    for char in value:
        if char in CHINESE:
            current = CHINESE[char]
        elif char in '十百千':
            total += (current or 1) * {'十': 10, '百': 100, '千': 1000}[char]
            current = 0
        else:
            raise ValueError('Unsupported Chinese numeral')
    return total + current

def parse_heading(value: str) -> Heading | None:
    value = normalize_text(value).strip(' .')
    chinese = re.match('^第([零〇一二两兩三四五六七八九十百千\\d]+)([章篇部节節])\\s*[、.：: -]*(.*)$', value)
    if chinese:
        number, unit, title = chinese.groups()
        return Heading((chinese_number(number),), 'part' if unit in '篇部' else 'section' if unit in '节節' else 'chapter', f'第{number}{unit}', title.strip())
    appendix = re.match('^(?:appendix|appendices|附录|附錄)\\s*([A-Za-z]|\\d+)((?:\\.\\d+)*)\\s*[.：: -]*(.*)$', value, re.I)
    if appendix:
        token, tail, title = appendix.groups()
        label = (int(token) if token.isdigit() else ord(token.upper()) - 64,) + tuple((int(n) for n in tail.split('.') if n))
        return Heading(label, 'chapter' if len(label) == 1 else 'section', token + tail, title.strip())
    generic = re.match('^(chapter|part|book|unit|lesson|lecture|module|section)\\s+(.+)$', value, re.I)
    if generic:
        prefix, rest = generic.groups()
        kind = 'part' if prefix.lower() in {'part', 'book'} else 'section' if prefix.lower() == 'section' else 'chapter'
        word = re.match('^([A-Za-z]+(?:[ -][A-Za-z]+)*)', rest)
        tokens = word.group(1).replace('-', ' ').split() if word else []
        numeric_words = []
        for token in tokens:
            if token.lower() not in SMALL_NUMBER_WORDS:
                break
            numeric_words.append(token)
        if numeric_words:
            original = re.match('^(?:' + '[ -]'.join((re.escape(t) for t in numeric_words)) + ')', rest, re.I).group(0)
            return Heading((_word_to_int(' '.join(numeric_words)),), kind, original, rest[len(original):].strip(' .:-'))
        match = re.match('^([A-Za-z0-9]+(?:[.\\-]\\d+)*\\.?)\\s*[: -]*(.*)$', rest)
        if not match:
            return None
        token, title = match.groups()
        token = token.rstrip('.')
        if re.fullmatch('\\d+(?:[.\\-]\\d+)*', token):
            label = tuple((int(n) for n in re.split('[.\\-]', token)))
        elif re.fullmatch('[IVXLCDM]+', token, re.I):
            label = (_roman_to_int(token),)
        else:
            compound = re.fullmatch('(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(one|two|three|four|five|six|seven|eight|nine)', token, re.I)
            if not compound:
                return None
            label = (_word_to_int(' '.join(compound.groups())),)
        return Heading(label, 'section' if len(label) > 1 else kind, token, title.strip())
    match = re.match('^(\\d+(?:[.\\-]\\d+)*\\.?|[A-Za-z]\\.\\d+(?:\\.\\d+)*)\\s+(.+)$', value)
    if match:
        token, title = match.groups()
        token = token.rstrip('.')
        if re.match('[A-Za-z]', token):
            label = (ord(token[0].upper()) - 64,) + tuple((int(n) for n in token[2:].split('.')))
        else:
            label = tuple((int(n) for n in re.split('[.\\-]', token)))
        return Heading(label, 'chapter' if len(label) == 1 else 'section', token, title.strip())
    return None
