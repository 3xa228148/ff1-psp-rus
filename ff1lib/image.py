"""Образы дисков: ISO, CSO (v1, v2), ZSO и файловая система ISO9660."""
import struct
import zlib

SECTOR = 2048


class ImageError(Exception):
    pass


def lz4_block(src, limit):
    """Распаковка одного блока LZ4 (формат block, без кадра)."""
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += src[i:i + lit]
        i += lit
        if i >= n or len(out) >= limit:
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        ml = token & 15
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(out) - off
        if off >= ml:
            out += out[start:start + ml]
        else:
            for k in range(ml):
                out.append(out[start + k])
    return bytes(out)


def read_image(path):
    """Прочитать образ (ISO, CSO v1/v2 или ZSO) -> bytearray с обычным ISO."""
    with open(path, 'rb') as f:
        data = f.read()
    magic = data[:4]
    if magic not in (b'CISO', b'ZISO'):
        return bytearray(data)
    hsize, total, bsize, ver, align = struct.unpack('<IQIBB', data[4:22])
    if hsize < 24:
        hsize = 24
    n = (total + bsize - 1) // bsize
    idx = struct.unpack('<%dI' % (n + 1), data[hsize:hsize + 4 * (n + 1)])
    out = bytearray()
    for i in range(n):
        a = (idx[i] & 0x7FFFFFFF) << align
        b = (idx[i + 1] & 0x7FFFFFFF) << align
        flag = idx[i] & 0x80000000
        blk = data[a:b]
        if magic == b'ZISO':
            out += blk[:bsize] if flag else lz4_block(blk, bsize)[:bsize]
        elif ver >= 2:
            if len(blk) >= bsize:
                out += blk[:bsize]
            elif flag:
                out += lz4_block(blk, bsize)[:bsize]
            else:
                out += zlib.decompressobj(-15).decompress(blk)[:bsize]
        else:
            out += blk[:bsize] if flag else zlib.decompressobj(-15).decompress(blk)[:bsize]
    return out[:total]


def write_image(path, iso, progress=None):
    """Записать образ: .cso -> CSO v1 (совместим со всеми прошивками), иначе ISO."""
    if not path.lower().endswith('.cso'):
        with open(path, 'wb') as f:
            f.write(iso)
        return
    total = len(iso)
    n = (total + SECTOR - 1) // SECTOR
    hdr = b'CISO' + struct.pack('<IQIBB2x', 24, total, SECTOR, 1, 0)
    pos = 24 + 4 * (n + 1)
    idx, blocks = [], []
    for i in range(n):
        blk = bytes(iso[i * SECTOR:(i + 1) * SECTOR]).ljust(SECTOR, b'\0')
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        z = c.compress(blk) + c.flush()
        if len(z) >= SECTOR:
            idx.append(pos | 0x80000000)
            blocks.append(blk)
            pos += SECTOR
        else:
            idx.append(pos)
            blocks.append(z)
            pos += len(z)
        if progress and i % 8192 == 0:
            progress(i, n)
    idx.append(pos)
    with open(path, 'wb') as f:
        f.write(hdr)
        f.write(struct.pack('<%dI' % len(idx), *idx))
        for b in blocks:
            f.write(b)


def is_iso9660(iso):
    return len(iso) > 17 * SECTOR and iso[16 * SECTOR + 1:16 * SECTOR + 6] == b'CD001'


def find_file(iso, path):
    """Найти файл в ISO9660 -> (lba, size). LookupError, если файла нет."""
    root = iso[16 * SECTOR + 156:16 * SECTOR + 190]
    lba, size = struct.unpack('<I', root[2:6])[0], struct.unpack('<I', root[10:14])[0]
    for want in path.strip('/').split('/'):
        data = iso[lba * SECTOR:lba * SECTOR + size]
        i, found = 0, None
        while i < len(data):
            ln = data[i]
            if ln == 0:
                i = (i // SECTOR + 1) * SECTOR
                continue
            rec = data[i:i + ln]
            name = rec[33:33 + rec[32]].decode('latin1').split(';')[0]
            if name.upper() == want.upper():
                found = (struct.unpack('<I', rec[2:6])[0], struct.unpack('<I', rec[10:14])[0])
                break
            i += ln
        if not found:
            raise LookupError(path)
        lba, size = found
    return lba, size


def read_file(iso, path):
    lba, size = find_file(iso, path)
    return bytes(iso[lba * SECTOR:lba * SECTOR + size])


def write_file(iso, path, data):
    """Заменить содержимое файла того же размера (на месте)."""
    lba, size = find_file(iso, path)
    if len(data) != size:
        raise ImageError('размер %s изменился (%d -> %d)' % (path, size, len(data)))
    iso[lba * SECTOR:lba * SECTOR + size] = data
