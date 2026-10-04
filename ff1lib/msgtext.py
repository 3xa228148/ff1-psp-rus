"""Игровые тексты MSG и текстовый формат перевода.

MSG: 4 нулевых байта, 'TEXT', u8 число языков (1 или 3), u16 число строк на
язык, u8 0, u32 полный размер, таблица смещений строк, строки. Каждая строка -
последовательность номеров глифов шрифта, записанная в UTF-8, в конце - глиф
"конец строки". Номера >= числа глифов - служебные коды (перевод строки и т.п.).

Формат файла перевода (.txt, UTF-8):

    # комментарии (только в начале файла)
    @mode 1
    === 0 ===
    Первая строка игры,
    может быть многострочной.
    === 1 ===
    ...

Теги внутри текста:
    перевод строки   - обычный перенос строки
    {cN}             - служебный код N (оставляйте как есть)
    {gN}             - глиф шрифта номер N без известного символа
    {t}              - символ "конец строки" в середине строки
    {noend}          - строка без завершающего символа (в конце строки)
    {{               - символ "{"
"""
import os
import re
import struct

LAT2CYR = dict(zip('ABCEHKMOPTXaceopxy', 'АВСЕНКМОРТХасеорху'))
CYR2LAT = {v: k for k, v in LAT2CYR.items()}
NEWLINE_CODE = 1          # служебный код "перевод строки" (номер = число глифов + 1)


class EncodeError(Exception):
    pass


def parse_msg(data):
    if data[4:8] != b'TEXT':
        raise ValueError('не MSG')
    mode = data[8]
    total = struct.unpack('<I', data[12:16])[0]
    first = struct.unpack('<I', data[16:20])[0]
    n = (first - 16) // 4
    offs = list(struct.unpack('<%dI' % n, data[16:16 + 4 * n])) + [total]
    return mode, [data[offs[i]:offs[i + 1]] for i in range(n)]


def build_msg(mode, entries):
    first = 16 + 4 * len(entries)
    offs, body = [], bytearray()
    for e in entries:
        offs.append(first + len(body))
        body += e
    count = len(entries) // max(mode, 1)
    hdr = b'\0\0\0\0TEXT' + struct.pack('<BHB', mode, count, 0) + struct.pack('<I', first + len(body))
    return hdr + struct.pack('<%dI' % len(offs), *offs) + bytes(body)


def _is_cyr(ch):
    return 'А' <= ch <= 'я' or ch in 'Ёё'


class Codec:
    """Перевод строк MSG <-> текст по таблице символов шрифта."""

    def __init__(self, fif, chars, name=''):
        self.name = name
        self.count = fif.count
        self.end = fif.end
        self.space = fif.space
        self.chars = list(chars)
        if self.space < self.count:
            self.chars[self.space] = ' '
        if self.end < self.count:
            self.chars[self.end] = ''
        self.index = {}
        for i, ch in enumerate(self.chars):
            if len(ch) == 1 and ch not in self.index and ch != '{':
                self.index[ch] = i
            elif ch == '{' and '{' not in self.index:
                self.index['{'] = i

    # -- decode --
    def decode(self, entry):
        cps = [ord(c) for c in entry.decode('utf-8')]
        noend = not cps or cps[-1] != self.end
        if not noend:
            cps = cps[:-1]
        toks = []
        for c in cps:
            if c == self.end:
                toks.append(('tag', '{t}'))
            elif c >= self.count:
                rel = c - self.count
                toks.append(('nl', '\n') if rel == NEWLINE_CODE else ('tag', '{c%d}' % rel))
            else:
                ch = self.chars[c]
                if len(ch) == 1 and self.index.get(ch) == c:
                    toks.append(('ch', '{{' if ch == '{' else ch))
                else:
                    toks.append(('tag', '{g%d}' % c))
        # латинские двойники кириллицы внутри русских слов показываем кириллицей,
        # если в шрифте нет отдельного кириллического глифа (при сборке вернутся те же глифы)
        out = []
        for k, (kind, v) in enumerate(toks):
            if kind == 'ch' and v in LAT2CYR and LAT2CYR[v] not in self.index:
                if self._cyr_context(toks, k):
                    v = LAT2CYR[v]
            out.append(v)
        text = ''.join(out)
        return text + '{noend}' if noend else text

    @staticmethod
    def _cyr_context(toks, k):
        for step in (-1, 1):
            j = k + step
            while 0 <= j < len(toks) and toks[j][0] == 'ch' and toks[j][1].isalpha():
                v = toks[j][1]
                if _is_cyr(v):
                    return True
                if v not in LAT2CYR:
                    break
                j += step
        return False

    # -- encode --
    _TAG = re.compile(r'\{\{|\{(c|g)(\d+)\}|\{t\}|\{noend\}')

    def encode(self, text):
        noend = text.endswith('{noend}')
        if noend:
            text = text[:-len('{noend}')]
        cps = []
        pos = 0
        for m in self._TAG.finditer(text):
            self._encode_plain(text[pos:m.start()], cps)
            tok = m.group(0)
            if tok == '{{':
                self._encode_plain('{', cps, literal=True)
            elif tok == '{t}':
                cps.append(self.end)
            elif m.group(1) == 'c':
                cps.append(self.count + int(m.group(2)))
            else:
                cps.append(int(m.group(2)))
            pos = m.end()
        self._encode_plain(text[pos:], cps)
        if not noend:
            cps.append(self.end)
        return ''.join(map(chr, cps)).encode('utf-8')

    def _encode_plain(self, s, cps, literal=False):
        for ch in s:
            if ch == '\n':
                cps.append(self.count + NEWLINE_CODE)
                continue
            if ch == '{' and not literal:
                raise EncodeError('непарная "{" (для символа { пишите {{)')
            g = self.index.get(ch)
            if g is None and ch in LAT2CYR:
                g = self.index.get(LAT2CYR[ch])
            if g is None and ch in CYR2LAT:
                g = self.index.get(CYR2LAT[ch])
            if g is None and ch == 'Ё':
                g = self.index.get('Е', self.index.get('E'))
            if g is None:
                raise EncodeError('символа %r нет в шрифте %s' % (ch, self.name))
            cps.append(g)


# ---------------------------------------------------------------- text files
def write_text_file(path, mode, texts, comments):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = ['# ' + c for c in comments]
    lines.append('@mode %d' % mode)
    for i, t in enumerate(texts):
        lines.append('=== %d ===' % i)
        lines.append(t)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')


_ENTRY = re.compile(r'^=== (\d+) ===$', re.M)


def read_text_file(path):
    """-> (mode, [texts])"""
    with open(path, encoding='utf-8-sig') as f:
        data = f.read().replace('\r\n', '\n')
    marks = list(_ENTRY.finditer(data))
    if not marks:
        raise ValueError('%s: нет строк (=== N ===)' % path)
    head = data[:marks[0].start()]
    mode = 1
    for line in head.split('\n'):
        if line.startswith('@mode'):
            mode = int(line.split()[1])
    texts = []
    for k, m in enumerate(marks):
        if int(m.group(1)) != k:
            raise ValueError('%s: строки должны идти по порядку, ожидалась === %d ===' % (path, k))
        start = m.end() + 1
        end = marks[k + 1].start() if k + 1 < len(marks) else len(data)
        body = data[start:end]
        if body.endswith('\n'):
            body = body[:-1]
        texts.append(body)
    return mode, texts


def read_keyed_file(path):
    """Файл вида '=== КЛЮЧ ===' + текст -> {ключ: текст}."""
    with open(path, encoding='utf-8-sig') as f:
        data = f.read().replace('\r\n', '\n')
    marks = list(re.finditer(r'^=== (\S+) ===$', data, re.M))
    out = {}
    for k, m in enumerate(marks):
        end = marks[k + 1].start() if k + 1 < len(marks) else len(data)
        body = data[m.end() + 1:end]
        if body.endswith('\n'):
            body = body[:-1]
        out[m.group(1)] = body
    return out
