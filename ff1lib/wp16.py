"""Сжатие Wp16 (LZ77 по 16-битным словам), которым игра упаковывает файлы.

Поток: 'Wp16', u32 размер, затем группы по 32 токена: u32 флаги и токены.
Бит флага 1 - литерал (одно 16-битное слово), 0 - ссылка
u16 = (расстояние << 5) | (длина - 2), расстояние и длина в словах.
"""
import struct


def decompress(src):
    if src[:4] != b'Wp16':
        raise ValueError('not Wp16')
    size = struct.unpack('<I', src[4:8])[0]
    n = (size + 1) // 2
    out = []
    p, bits, flags = 8, 0, 0
    while len(out) < n:
        if bits == 0:
            flags = struct.unpack('<I', src[p:p + 4])[0]
            p += 4
            bits = 32
        if flags & 1:
            out.append(struct.unpack('<H', src[p:p + 2])[0])
            p += 2
        else:
            v = struct.unpack('<H', src[p:p + 2])[0]
            p += 2
            dist, ln = v >> 5, min((v & 31) + 2, n - len(out))
            s = len(out) - dist
            for k in range(ln):
                out.append(out[s + k] if s + k >= 0 else 0)
        flags >>= 1
        bits -= 1
    return struct.pack('<%dH' % len(out), *out)[:size]


def compress(data):
    """Сжать данные. Результат дополняется до кратности 4 байтам:
    игра читает сжатые данные 32-битными инструкциями, и на настоящей PSP
    невыровненный адрес приводит к зависанию (эмуляторы это прощают)."""
    size = len(data)
    if size & 1:
        data += b'\0'
    w = struct.unpack('<%dH' % (len(data) // 2), data)
    n = len(w)
    head, prev = {}, [-1] * n
    tokens = []

    def insert(q):
        if q + 1 < n:
            key = (w[q], w[q + 1])
            prev[q] = head.get(key, -1)
            head[key] = q

    i = 0
    while i < n:
        best_len = best_d = 0
        if i + 1 < n:
            q, tries = head.get((w[i], w[i + 1]), -1), 0
            while q >= 0 and i - q <= 2047 and tries < 256:
                mx = min(33, n - i)
                ln = 2
                while ln < mx and w[q + ln] == w[i + ln]:
                    ln += 1
                if ln > best_len:
                    best_len, best_d = ln, i - q
                if ln == mx:
                    break
                q, tries = prev[q], tries + 1
        if best_len >= 2:
            tokens.append((0, (best_d << 5) | (best_len - 2)))
            for q in range(i, i + best_len):
                insert(q)
            i += best_len
        else:
            tokens.append((1, w[i]))
            insert(i)
            i += 1
    out = bytearray(b'Wp16' + struct.pack('<I', size))
    for g in range(0, len(tokens), 32):
        grp = tokens[g:g + 32]
        out += struct.pack('<I', sum(1 << b for b, t in enumerate(grp) if t[0]))
        for _, v in grp:
            out += struct.pack('<H', v)
    while len(out) % 4:
        out += b'\0'
    if decompress(bytes(out)) != data[:size]:
        raise RuntimeError('Wp16 self-check failed')
    return bytes(out)
