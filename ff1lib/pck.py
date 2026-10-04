"""Контейнеры PCK и архив ff1psp.dpk (тот же формат на верхнем уровне).

Заголовок: u32 число файлов, u32 размер, 8 нулевых байт; затем записи по 36 байт:
имя (22 байта), u16 ключ (хэш имени для поиска), u32 смещение, u32 размер,
u32 размер после распаковки. Данные файлов выровнены на 16 байт.
"""
import struct

from . import wp16


def align(x, a):
    return (x + a - 1) // a * a


def parse(b):
    cnt = struct.unpack('<I', b[:4])[0]
    ents = []
    for i in range(cnt):
        e = b[16 + i * 36:52 + i * 36]
        name = e[:22].split(b'\0')[0].decode('latin1')
        key, off, sz, sz2 = struct.unpack('<HIII', e[22:36])
        ents.append([name, key, off, sz, sz2, e[:22]])
    return ents


def files(b):
    return {e[0]: b[e[2]:e[2] + e[3]] for e in parse(b)}


def is_pck(b):
    if len(b) < 16:
        return False
    cnt = struct.unpack('<I', b[:4])[0]
    if not 0 < cnt < 4096 or len(b) < 16 + 36 * cnt:
        return False
    try:
        return all(e[2] + e[3] <= len(b) for e in parse(b))
    except struct.error:
        return False


def build(orig, replace, data_order=None):
    """Пересобрать PCK: порядок записей и ключи - как в orig,
    replace = {имя: новые данные}, data_order - порядок размещения данных."""
    ents = parse(orig)
    cnt = len(ents)
    datas = [replace.get(e[0], orig[e[2]:e[2] + e[3]]) for e in ents]
    if data_order:
        pos_of = {n: i for i, n in enumerate(data_order)}
        order = sorted(range(cnt), key=lambda i: pos_of.get(ents[i][0], cnt + i))
    else:
        order = sorted(range(cnt), key=lambda i: ents[i][2])
    pos = align(16 + 36 * cnt, 16)
    offs, body = [0] * cnt, bytearray()
    for i in order:
        offs[i] = pos + len(body)
        body += datas[i]
        body += b'\0' * (-len(body) % 16)
    total = offs[order[-1]] + len(datas[order[-1]])
    hdr = bytearray(struct.pack('<4I', cnt, total, 0, 0))
    for i, e in enumerate(ents):
        sz2 = len(datas[i]) if e[0] in replace else e[4]
        hdr += e[5] + struct.pack('<HIII', e[1], offs[i], len(datas[i]), sz2)
    hdr += b'\0' * (pos - len(hdr))
    return (bytes(hdr) + bytes(body))[:total]


def content(archive, ent):
    """Распакованное содержимое файла архива."""
    x = archive[ent[2]:ent[2] + ent[3]]
    return wp16.decompress(x) if x[:4] == b'Wp16' else x


def _pad16(raw):
    """Дополнить файл до кратности 16; в контейнере PCK размер в заголовке
    тоже указывается с учётом дополнения (как во всех файлах оригинала)."""
    raw = raw + b'\0' * (-len(raw) % 16)
    if is_pck(raw) and struct.unpack('<I', raw[4:8])[0] < len(raw):
        raw = raw[:4] + struct.pack('<I', len(raw)) + raw[8:]
    return raw


def build_archive(orig, replace_raw, progress=None):
    """Пересобрать ff1psp.dpk. Новые файлы сжимаются заново.

    Соблюдаются правила, по которым упакован оригинальный архив:
    распакованный размер каждого файла кратен 16 (данные дополняются нулями,
    размер в заголовке PCK - вместе с ними), сжатый поток Wp16 кратен 4,
    данные в архиве выровнены на 16.
    Игра читает сжатые данные 32-битными инструкциями и раскладывает
    распакованные файлы в памяти подряд, поэтому при нарушении выравнивания
    настоящая PSP зависает или выключается (эмуляторы это прощают)."""
    cnt, tot = struct.unpack('<II', orig[:8])
    ents = parse(orig)
    datas = {}
    done = 0
    for name, key, off, sz, sz2, _ in ents:
        x = orig[off:off + sz]
        packed = x[:4] == b'Wp16'
        if name in replace_raw:
            raw = _pad16(replace_raw[name])
            x = wp16.compress(raw) if packed else raw
            done += 1
            if progress:
                progress(done, len(replace_raw))
        elif packed:
            hs = struct.unpack('<I', x[4:8])[0]
            if hs % 16 or hs != sz2:
                x = wp16.compress(_pad16(wp16.decompress(x)))
        elif sz % 16 or sz != sz2:
            x = _pad16(x)
        datas[name] = x
    order = sorted(ents, key=lambda e: e[2])
    start = order[0][2]
    offs, body = {}, bytearray()
    for e in order:
        offs[e[0]] = start + len(body)
        body += datas[e[0]]
        body += b'\0' * (-len(body) % 16)
    if start + len(body) > tot:
        raise OverflowError('архив не помещается в исходный размер (%d > %d байт)'
                            % (start + len(body), tot))
    hdr = bytearray(struct.pack('<4I', cnt, tot, 0, 0))
    for name, key, off, sz, sz2, raw22 in ents:
        x = datas[name]
        s2 = struct.unpack('<I', x[4:8])[0] if x[:4] == b'Wp16' else len(x)
        hdr += raw22 + struct.pack('<HIII', key, offs[name], len(x), s2)
    hdr += orig[len(hdr):start]
    out = bytes(hdr) + bytes(body)
    return out + b'\0' * (tot - len(out))
