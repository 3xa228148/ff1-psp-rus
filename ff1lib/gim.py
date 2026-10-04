"""Текстуры GIM: доступ к индексам палитры (4 и 8 бит, со свизлингом PSP)."""
import struct


def _align(x, a):
    return (x + a - 1) // a * a


class Gim:
    def __init__(self, data):
        self.data = data
        img = None
        stack = [(16, len(data))]
        while stack and img is None:
            off, end = stack.pop()
            while off < end:
                bid, _, size, nxt, doff = struct.unpack('<HHIII', data[off:off + 16])
                if bid in (2, 3):
                    stack.append((off + doff, off + size))
                if bid == 4:
                    img = off + doff
                    break
                off += nxt if nxt else size
                if size == 0:
                    break
        if img is None:
            raise ValueError('в GIM нет изображения')
        h = img
        self.fmt, self.order, self.w, self.h = struct.unpack('<HHHH', data[h + 4:h + 12])
        self.pa = struct.unpack('<H', data[h + 14:h + 16])[0]
        ps, pe = struct.unpack('<II', data[h + 0x1C:h + 0x24])
        self.start, self.size = h + ps, pe - ps
        if self.fmt not in (4, 5):
            raise ValueError('поддерживаются только палитровые GIM')
        self.bpp = 4 if self.fmt == 4 else 8
        self.wb = _align(self.w * self.bpp // 8, self.pa)
        self.hh = _align(self.h, 8) if self.order else self.h
        full = self.wb * self.hh
        raw = bytes(data[self.start:self.start + self.size]).ljust(full, b'\0')[:full]
        self.rows = bytearray(self._swizzle(raw, False) if self.order else raw)

    def _swizzle(self, data, forward):
        out = bytearray(len(data))
        i = 0
        for by in range(0, self.hh, 8):
            for bx in range(self.wb // 16):
                for r in range(8):
                    o = (by + r) * self.wb + bx * 16
                    if forward:
                        out[i:i + 16] = data[o:o + 16]
                    else:
                        out[o:o + 16] = data[i:i + 16]
                    i += 16
        return bytes(out)

    def get(self, x, y):
        if self.bpp == 8:
            return self.rows[y * self.wb + x]
        b = self.rows[y * self.wb + x // 2]
        return (b >> 4) if x & 1 else (b & 15)

    def put(self, x, y, v):
        if self.bpp == 8:
            self.rows[y * self.wb + x] = v
            return
        o = y * self.wb + x // 2
        b = self.rows[o]
        self.rows[o] = ((b & 15) | (v << 4)) if x & 1 else ((b & 0xF0) | v)

    def region(self, x0, y0, w, h):
        return [[self.get(x0 + c, y0 + r) for c in range(w)] for r in range(h)]

    def blit(self, x0, y0, rows):
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                self.put(x0 + c, y0 + r, v)

    def save(self):
        raw = self._swizzle(bytes(self.rows), True) if self.order else bytes(self.rows)
        if raw[self.size:].strip(b'\0'):
            raise ValueError('правка выходит за пределы сохранённых пикселей')
        out = bytearray(self.data)
        out[self.start:self.start + self.size] = raw[:self.size]
        return bytes(out)
