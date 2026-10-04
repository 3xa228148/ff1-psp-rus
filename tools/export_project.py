#!/usr/bin/env python3
"""
Экспорт перевода в папку translation/ (для авторов перевода).

Сравнивает оригинальный образ (ULUS-10251) с готовым русским образом и
раскладывает все отличия по файлам: тексты, шрифты, таблицы символов,
картинки, правку кода, а также manifest.json с инструкциями сборки.
Всё, что совпадает с оригинальной игрой, записывается ссылкой, поэтому
папку можно публиковать.

    python3 tools/export_project.py ОРИГИНАЛ.iso РУССКИЙ.iso [translation]

Таблицы символов (charmap.txt) уже существующих шрифтов сохраняются.
Для новых шрифтов символы определяются по совпадению рисунка глифов
с уже известными шрифтами; нераспознанные глифы остаются пустыми.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from ff1lib import font as fontmod      # noqa: E402
from ff1lib import gim as gimmod        # noqa: E402
from ff1lib import image, msgtext, pck  # noqa: E402
from ff1lib.project import Builder, Project, read_grid  # noqa: E402

DPK = '/PSP_GAME/USRDIR/data/ff1psp.dpk'
BOOT = '/PSP_GAME/SYSDIR/BOOT.BIN'
EBOOT = '/PSP_GAME/SYSDIR/EBOOT.BIN'

CATEGORY_TITLES = {
    'dialogs': 'диалоги и сцены',
    'menus': 'меню и экраны',
    'items_magic': 'предметы, оружие, броня, магия и их описания',
    'battle': 'бой',
    'bestiary': 'бестиарий',
    'credits': 'титры',
    'gallery': 'галерея',
    'debug': 'отладочные меню (в обычной игре не видны)',
    'other': 'прочее',
}


def sha1(b):
    return hashlib.sha1(b).hexdigest()


def base(name):
    return name.rsplit('.', 1)[0]


def category(pack_name):
    n = pack_name.upper()
    if n.startswith('USEVM'):
        return 'dialogs'
    if n.startswith('FONT_BATTLE'):
        return 'battle'
    if n.startswith('FM_EXTERN'):
        return 'items_magic'
    if n.startswith('FM_STAFF_ROLL'):
        return 'credits'
    if n.startswith(('FM_MON_BOOK', 'FM_MSBK')):
        return 'bestiary'
    if n.startswith('FM_DBG'):
        return 'debug'
    if n.startswith('FM_GARELLY'):
        return 'gallery'
    if n.startswith('FM_'):
        return 'menus'
    return 'other'


def diff_ranges(a, b):
    out, i = [], 0
    while i < len(a):
        if a[i] != b[i]:
            j = i
            while j < len(a) and a[j] != b[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def changed_boxes(old, new):
    """Прямоугольники изменённых пикселей (соседние объединяются)."""
    pts = [(x, y) for y in range(new.h) for x in range(new.w) if old.get(x, y) != new.get(x, y)]
    boxes = []
    for x, y in pts:
        for b in boxes:
            if b[0] - 4 <= x <= b[2] + 4 and b[1] - 4 <= y <= b[3] + 4:
                b[0], b[1], b[2], b[3] = min(b[0], x), min(b[1], y), max(b[2], x), max(b[3], y)
                break
        else:
            boxes.append([x, y, x, y])
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if a[0] - 4 <= b[2] and b[0] - 4 <= a[2] and a[1] - 4 <= b[3] and b[1] - 4 <= a[3]:
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    return boxes


class GlyphDictionary:
    """Рисунок глифа -> символ, по всем известным таблицам символов."""

    def __init__(self):
        self.map = {}

    def add_font(self, fif_data, gim_data, chars):
        fif = fontmod.Fif(fif_data)
        g = gimmod.Gim(gim_data)
        for i in range(fif.count):
            if chars[i] and i not in (fif.space, fif.end):
                key = (fif.height, fif.glyphs[i][2], fontmod.glyph_bitmap(g, fif, i))
                self.map.setdefault(key, chars[i])

    def guess(self, fif_data, gim_data):
        fif = fontmod.Fif(fif_data)
        g = gimmod.Gim(gim_data)
        chars = [''] * fif.count
        used = set()
        for i in range(fif.count):
            if i in (fif.space, fif.end):
                continue
            ch = self.map.get((fif.height, fif.glyphs[i][2], fontmod.glyph_bitmap(g, fif, i)), '')
            if ch and ch not in used:
                chars[i] = ch
                used.add(ch)
        return chars


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('original')
    ap.add_argument('russian')
    ap.add_argument('out', nargs='?', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'translation'))
    ap.add_argument('--seed', help='JSON {sha1 шрифта: [символы]} для новых шрифтов')
    args = ap.parse_args()
    out = os.path.abspath(args.out)

    oiso, riso = image.read_image(args.original), image.read_image(args.russian)
    odpk, rdpk = image.read_file(oiso, DPK), image.read_file(riso, DPK)
    oboot, rboot = image.read_file(oiso, BOOT), image.read_file(riso, BOOT)
    game = image.read_file(oiso, '/UMD_DATA.BIN').split(b'|')[0].decode()

    oents = {e[0]: e for e in pck.parse(odpk)}
    rents = {e[0]: e for e in pck.parse(rdpk)}
    ocache = {}

    def ofile(n):
        if n not in ocache:
            ocache[n] = pck.content(odpk, oents[n])
        return ocache[n]

    index = {}
    for n in oents:
        index.setdefault(sha1(ofile(n)), {'file': n})
    for n in oents:
        d = ofile(n)
        if n.upper().endswith('.PCK') and pck.is_pck(d):
            for s, x in pck.files(d).items():
                index.setdefault(sha1(x), {'file': n, 'sub': s})

    # существующие таблицы символов: по содержимому шрифта
    old_charmaps = {}
    gdict = GlyphDictionary()
    fonts_dir = os.path.join(out, 'fonts')
    if os.path.isdir(fonts_dir):
        for dp, _, fns in os.walk(fonts_dir):
            for fn in fns:
                if fn.endswith('.charmap.txt'):
                    b = os.path.join(dp, fn[:-len('.charmap.txt')])
                    if os.path.exists(b + '.FIF') and os.path.exists(b + '.GIM'):
                        fd, gd = open(b + '.FIF', 'rb').read(), open(b + '.GIM', 'rb').read()
                        chars = fontmod.load_charmap(b + '.charmap.txt', fontmod.Fif(fd).count)
                        old_charmaps[sha1(fd + gd)] = chars
                        gdict.add_font(fd, gd, chars)
    seed = {}
    if args.seed:
        with open(args.seed, encoding='utf-8') as f:
            seed = json.load(f)

    # чистая перезапись папки
    for sub in ('text', 'fonts', 'graphics', 'code', 'raw'):
        shutil.rmtree(os.path.join(out, sub), ignore_errors=True)
    os.makedirs(out, exist_ok=True)

    def write(rel, data, text=False):
        p = os.path.join(out, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w' if text else 'wb', **({'encoding': 'utf-8', 'newline': '\n'} if text else {})) as f:
            f.write(data)

    files = {}
    fonts = {}          # sha1(fif+gim) -> rel base path
    font_chars = {}     # rel base -> chars
    texts = {}          # rel path -> dict(mode, texts, uses, font)
    text_by_content = {}
    dats = {}           # key -> text
    notes = []

    def font_for(pack_name, nfiles, fif_name):
        gim_name = base(fif_name) + '.GIM'
        fd, gd = nfiles[fif_name], nfiles[gim_name]
        h = sha1(fd + gd)
        if h not in fonts:
            rel = 'fonts/%s/%s' % (base(pack_name), base(fif_name))
            fonts[h] = rel
            write(rel + '.FIF', fd)
            write(rel + '.GIM', gd)
            if h in old_charmaps:
                chars = old_charmaps[h]
            elif h in seed:
                chars = seed[h]
            else:
                chars = gdict.guess(fd, gd)
                unknown = sum(1 for i, c in enumerate(chars) if not c)
                notes.append('новый шрифт %s: нераспознанных глифов %d' % (rel, unknown))
            fontmod.save_charmap(os.path.join(out, *rel.split('/')) + '.charmap.txt', chars,
                                 fontmod.Fif(fd), '%s / %s' % (pack_name, fif_name))
            gdict.add_font(fd, gd, chars)
            font_chars[rel] = chars
        return fonts[h]

    for name in oents:
        new = pck.content(rdpk, rents[name])
        old = ofile(name)
        if new == old:
            continue
        h = sha1(new)
        if h in index and 'sub' not in index[h]:
            files[name] = {'op': 'copy', 'file': index[h]['file'], 'sha1': h, 'want': h}
            continue
        oparts, nparts = pck.parse(old), pck.parse(new)
        if [(e[0], e[1]) for e in oparts] != [(e[0], e[1]) for e in nparts]:
            sys.exit('структура %s отличается от оригинала - не поддерживается' % name)
        ofiles, nfiles = pck.files(old), pck.files(new)
        subs = {}
        for e in nparts:
            s, x = e[0], nfiles[e[0]]
            if ofiles.get(s) == x:
                continue
            hx = sha1(x)
            up = s.upper()
            if hx in index:
                subs[s] = dict(index[hx], op='copy', sha1=hx, want=hx)
                continue
            appended = False
            for k in (1, 2, 4):
                if len(x) > k and sha1(x[:-k]) in index:
                    subs[s] = dict(index[sha1(x[:-k])], op='copy', sha1=sha1(x[:-k]), want=hx, append=x[-k:].hex())
                    appended = True
                    break
            if appended:
                continue
            fifs = [k for k in nfiles if k.upper().endswith('.FIF') and base(k) + '.GIM' in nfiles]
            if up.endswith('.FIF') or (up.endswith('.GIM') and base(s) + '.FIF' in nfiles):
                rel = font_for(name, nfiles, base(s) + '.FIF')
                subs[s] = {'op': 'bin', 'path': rel + s[s.rfind('.'):].upper()}
                continue
            if up.endswith('.MSG') and fifs:
                frel = font_for(name, nfiles, fifs[0])
                fif = fontmod.Fif(nfiles[fifs[0]])
                codec = msgtext.Codec(fif, font_chars[frel], frel)
                mode, entries = msgtext.parse_msg(x)
                dec = [codec.decode(en) for en in entries]
                ok = msgtext.build_msg(mode, [codec.encode(t) for t in dec]) == x
                if ok:
                    key = (mode, tuple(dec))
                    rel = None
                    for cand in text_by_content.get(key, []):
                        rel = cand
                        break
                    if rel is None:
                        rel = 'text/%s/%s/%s.txt' % (category(name), base(name), base(s))
                        texts[rel] = {'mode': mode, 'texts': dec, 'uses': [], 'font': frel}
                        text_by_content.setdefault(key, []).append(rel)
                    texts[rel]['uses'].append('%s / %s' % (name, s))
                    subs[s] = {'op': 'text', 'path': rel, 'font': frel}
                    continue
                notes.append('%s/%s: текст не удалось представить без потерь, сохранён как файл' % (name, s))
            if up.endswith('.DAT'):
                try:
                    t = x.rstrip(b'\0').decode('utf-8').replace('\r\n', '\n')
                    good = t.replace('\n', '\r\n').encode('utf-8') + b'\0' == x
                except UnicodeDecodeError:
                    good = False
                if good:
                    key = s if dats.get(s, t) == t else '%s/%s' % (base(name), s)
                    dats[key] = t
                    subs[s] = {'op': 'dat', 'path': 'text/system/save_messages.txt', 'key': key}
                    continue
            if up.endswith('.GIM') and s in ofiles and len(ofiles[s]) == len(x):
                try:
                    og, ng = gimmod.Gim(ofiles[s]), gimmod.Gim(x)
                    grids = []
                    for k, (x0, y0, x1, y1) in enumerate(changed_boxes(og, ng)):
                        rows = ng.region(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
                        rel = 'graphics/%s/%s_%d.txt' % (base(name), base(s), k + 1)
                        body = ['# Участок картинки %s / %s: номера цветов палитры (hex), по строкам' % (name, s),
                                '@at %d %d' % (x0, y0)] + [''.join('%02x' % v for v in r) for r in rows]
                        write(rel, '\n'.join(body) + '\n', text=True)
                        grids.append(rel)
                    test = gimmod.Gim(ofiles[s])
                    for rel in grids:
                        gx, gy, rows = read_grid(os.path.join(out, *rel.split('/')))
                        test.blit(gx, gy, rows)
                    if test.save() == x:
                        hb = sha1(ofiles[s])
                        subs[s] = {'op': 'blit', 'base': {'op': 'copy', 'file': name, 'sub': s, 'sha1': hb, 'want': hb},
                                   'grids': grids, 'want': hx}
                        continue
                except ValueError:
                    pass
            rel = 'raw/%s/%s' % (base(name), s)
            write(rel, x)
            subs[s] = {'op': 'bin', 'path': rel}
            notes.append('%s/%s сохранён как двоичный файл raw/' % (name, s))
        op = {'op': 'pck', 'subs': subs}
        norder = [e[0] for e in sorted(nparts, key=lambda e: e[2])]
        if norder != [e[0] for e in sorted(oparts, key=lambda e: e[2])]:
            op['order'] = norder
        files[name] = op
        # распакованный файл может быть длиннее на байты выравнивания
        last = max(nparts, key=lambda e: e[2])
        plain_len = last[2] + last[3]
        if len(new) > plain_len and not new[plain_len:].strip(b'\0'):
            op['size'] = len(new)

    # тексты
    for rel, t in texts.items():
        cat = rel.split('/')[1]
        comments = ['Final Fantasy (PSP) - русский перевод. Раздел: %s.' % CATEGORY_TITLES.get(cat, cat),
                    'Игровой файл: ' + t['uses'][0]]
        if len(t['uses']) > 1:
            comments.append('Этот же текст используется в: ' + ', '.join(t['uses'][1:]))
        comments.append('Шрифт: %s.charmap.txt - писать можно только символами этого шрифта.' % t['font'])
        if t['mode'] == 3:
            comments.append('@mode 3: строки идут тройками на каждую фразу: японский 1, японский 2, английский.')
            comments.append('В этом переводе 1-я и 2-я строки тройки - режим English, 3-я - русский.')
        comments.append('Перенос строки - обычный перенос. {cN} - служебные коды игры, не удаляйте их.')
        comments.append('Строки разделяются заголовками "=== номер ===", номера менять нельзя.')
        msgtext.write_text_file(os.path.join(out, *rel.split('/')), t['mode'], t['texts'], comments)

    if dats:
        lines = ['# Системные сообщения PSP при сохранении и загрузке (COMMON.PCK, COMMON2.PCK).',
                 '# Их выводит сама PSP системным шрифтом, поэтому здесь обычный текст.',
                 '# *_US.DAT - русский режим, *_JK.DAT и *_JH.DAT - режим English.',
                 '']
        for k, t in dats.items():
            lines += ['=== %s ===' % k, t]
        write('text/system/save_messages.txt', '\n'.join(lines) + '\n', text=True)

    code = [(a, oboot[a:b], rboot[a:b]) for a, b in diff_ranges(oboot, rboot)]
    if code:
        body = ['# Правка кода игры (BOOT.BIN; EBOOT.BIN собирается из BOOT.BIN):',
                '# меню выбора языка на 2 пункта (English / Русский) вместо 3.',
                '# смещение в BOOT.BIN   было   стало']
        body += ['0x%06x  %s  %s' % (a, o.hex(), n.hex()) for a, o, n in code]
        write('code/boot_patch.txt', '\n'.join(body) + '\n', text=True)

    manifest = {
        'format': 2,
        'game': game,
        'code_patch': 'code/boot_patch.txt' if code else None,
        'source': {'dpk_sha1': sha1(odpk), 'boot_sha1': sha1(oboot)},
        'result': {'files': {}},
        'files': files,
    }
    with open(os.path.join(out, 'manifest.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)

    # проверка: собрать из папки и сравнить с русским образом
    proj = Project(out)
    warns = []
    built = Builder(proj, odpk, warns.append).build()
    bad = [n for n in files if built.get(n) != pck.content(rdpk, rents[n])]
    if bad or warns:
        sys.exit('ОШИБКА: из папки не собирается то же самое: %s %s' % (bad[:5], warns[:5]))
    new_dpk = pck.build_archive(odpk, built)
    new_boot = bytearray(oboot)
    for a, o, n in code:
        new_boot[a:a + len(n)] = n
    eboot_size = image.find_file(oiso, EBOOT)[1]
    new_eboot = bytes(new_boot) + b'\0' * (eboot_size - len(new_boot))
    manifest['result'] = {'files': {n: sha1(d) for n, d in built.items()},
                          'dpk_sha1': sha1(new_dpk), 'boot_sha1': sha1(bytes(new_boot)),
                          'eboot_sha1': sha1(new_eboot)}
    with open(os.path.join(out, 'manifest.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)

    print('Готово: %s' % out)
    print('  изменённых файлов архива: %d, текстов: %d, шрифтов: %d' % (len(files), len(texts), len(fonts)))
    for n in notes:
        print('  примечание: ' + n)


if __name__ == '__main__':
    main()
