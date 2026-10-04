"""Шрифты FIF и таблицы символов (charmap).

FIF: u16 высота, u16 число глифов, таблица кодов (код -> номер глифа, 0xFFFF -
нет), затем на каждый глиф: u16 x, u16 y, u16 ширина в атласе GIM.
Игровые тексты хранят номера глифов, поэтому для каждого шрифта нужна таблица
"номер глифа -> символ" (charmap.txt), чтобы тексты можно было читать.
"""
import struct

SPACE_TAG = '<пробел>'
END_TAG = '<конец>'


class Fif:
    def __init__(self, data):
        self.data = data
        self.height, self.count = struct.unpack('<HH', data[:4])
        nmap = (len(data) - 4 - self.count * 6) // 2
        self.codes = list(struct.unpack('<%dH' % nmap, data[4:4 + nmap * 2]))
        base = 4 + nmap * 2
        self.glyphs = [struct.unpack('<HHH', data[base + i * 6:base + i * 6 + 6]) for i in range(self.count)]
        self.end = self.codes[0]          # глиф-терминатор строки (код 0)
        self.space = self.codes[0x20] if len(self.codes) > 0x20 else 0xFFFF


def glyph_bitmap(gim, fif, i):
    """Пиксели глифа i (верхняя половина атласа) как bytes - для сравнения шрифтов."""
    x, y, w = fif.glyphs[i]
    return bytes(gim.get(x + c, y + r) for r in range(fif.height) for c in range(w))


def charmap_from_codes(fif):
    """Таблица для оригинальных шрифтов игры: по таблице кодов ASCII."""
    chars = [''] * fif.count
    for code, g in enumerate(fif.codes):
        if g < fif.count and 0x20 < code < 0x7F and not chars[g]:
            chars[g] = chr(code)
    if fif.space < fif.count:
        chars[fif.space] = ' '
    return chars


def load_charmap(path, count):
    chars = [''] * count
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line or line.startswith('#'):
                continue
            num, _, ch = line.partition('\t')
            i = int(num)
            if ch == SPACE_TAG:
                ch = ' '
            elif ch == END_TAG:
                ch = ''
            if i < count:
                chars[i] = ch
    return chars


def save_charmap(path, chars, fif, title):
    lines = ['# Таблица символов шрифта %s' % title,
             '# Формат: номер глифа <TAB> символ.',
             '# %s - пробел, %s - конец строки, пустое значение - служебный или' % (SPACE_TAG, END_TAG),
             '# нераспознанный глиф (в текстах такой глиф записывается как {gНОМЕР}).',
             '# В тексты этого шрифта можно писать только символы из этой таблицы.',
             '']
    for i in range(fif.count):
        if i == fif.space:
            ch = SPACE_TAG
        elif i == fif.end:
            ch = END_TAG
        else:
            ch = chars[i]
        lines.append('%d\t%s' % (i, ch))
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
