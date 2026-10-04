"""Сборка файлов игры из папки translation/ по описанию translation/manifest.json.

Операции manifest.json для файла архива:
  {"op": "copy", "file": F, "sha1": ..., "want": ...}   - копия файла F из образа
  {"op": "pck", "subs": {...}, "order": [...], "size": N} - контейнер PCK, в котором
      заменяются вложенные файлы; остальные берутся из образа
Операции для вложенных файлов:
  copy  - взять файл из образа (file, sub), при необходимости дописать байты append
  text  - собрать MSG из текстового файла path шрифтом font
  dat   - системное сообщение из файла path по ключу key
  bin   - файл из папки перевода как есть (шрифты)
  blit  - картинка: base + участки пикселей из файлов grids
"sha1" - контрольная сумма оригинального файла-источника, "want" - результата.
"""
import hashlib
import json
import os

from . import font as fontmod
from . import gim as gimmod
from . import msgtext
from . import pck


def sha1(b):
    return hashlib.sha1(b).hexdigest()


class ProjectError(Exception):
    pass


def read_grid(path):
    """Файл участка картинки: '@at X Y' и строки номеров цветов (hex по 2 цифры)."""
    x = y = None
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('@at'):
                x, y = (int(v) for v in line.split()[1:3])
                continue
            rows.append([int(line[i:i + 2], 16) for i in range(0, len(line), 2)])
    if x is None:
        raise ValueError('нет строки @at X Y')
    return x, y, rows


class Project:
    def __init__(self, root):
        self.root = root
        with open(os.path.join(root, 'manifest.json'), encoding='utf-8') as f:
            self.manifest = json.load(f)
        self._texts = {}
        self._keyed = {}
        self._codecs = {}

    def path(self, rel):
        return os.path.join(self.root, *rel.split('/'))

    def read_bin(self, rel):
        with open(self.path(rel), 'rb') as f:
            return f.read()

    def text(self, rel):
        if rel not in self._texts:
            self._texts[rel] = msgtext.read_text_file(self.path(rel))
        return self._texts[rel]

    def keyed(self, rel):
        if rel not in self._keyed:
            self._keyed[rel] = msgtext.read_keyed_file(self.path(rel))
        return self._keyed[rel]

    def codec(self, font_rel):
        if font_rel not in self._codecs:
            fif = fontmod.Fif(self.read_bin(font_rel + '.FIF'))
            chars = fontmod.load_charmap(self.path(font_rel + '.charmap.txt'), fif.count)
            self._codecs[font_rel] = msgtext.Codec(fif, chars, font_rel)
        return self._codecs[font_rel]

    def grid(self, rel):
        try:
            return read_grid(self.path(rel))
        except ValueError as e:
            raise ProjectError('%s: %s' % (rel, e))

    def code_patch(self):
        out = []
        rel = self.manifest.get('code_patch')
        if not rel:
            return out
        with open(self.path(rel), encoding='utf-8') as f:
            for line in f:
                line = line.split('#', 1)[0].strip()
                if line:
                    off, old, new = line.split()
                    out.append((int(off, 0), bytes.fromhex(old), bytes.fromhex(new)))
        return out


class Builder:
    """Собирает изменённые файлы архива из папки перевода и файлов исходного образа."""

    def __init__(self, project, archive, warn):
        self.p = project
        self.archive = archive
        self.warn = warn
        self.ents = {e[0]: e for e in pck.parse(archive)}
        self.cache = {}
        self.official = project.manifest['result']['files']

    def src(self, name):
        if name not in self.ents:
            return None
        if name not in self.cache:
            self.cache[name] = pck.content(self.archive, self.ents[name])
        return self.cache[name]

    def src_sub(self, name, sub):
        data = self.src(name)
        if data is None or not pck.is_pck(data):
            return None
        return pck.files(data).get(sub)

    def _copy(self, op, current, where):
        if current is not None and sha1(current) == op['want']:
            return current                      # в образе уже нужное содержимое
        data = self.src_sub(op['file'], op['sub']) if op.get('sub') else self.src(op['file'])
        if data is not None and sha1(data) == op['sha1']:
            return data + bytes.fromhex(op.get('append', ''))
        if data is None:
            self.warn('%s: в образе нет %s, оставлен как есть' % (where, op['file'] + ('/' + op['sub'] if op.get('sub') else '')))
            return None
        self.warn('%s: исходный %s отличается от оригинального, взят как есть'
                  % (where, op['file'] + ('/' + op['sub'] if op.get('sub') else '')))
        return data + bytes.fromhex(op.get('append', ''))

    def _sub(self, target, sub, op, current):
        where = '%s/%s' % (target, sub)
        kind = op['op']
        if kind == 'copy':
            return self._copy(op, current, where)
        if kind == 'bin':
            return self.p.read_bin(op['path'])
        if kind == 'text':
            mode, texts = self.p.text(op['path'])
            codec = self.p.codec(op['font'])
            entries = []
            for i, t in enumerate(texts):
                try:
                    entries.append(codec.encode(t))
                except msgtext.EncodeError as e:
                    raise ProjectError('%s, запись "=== %d ===": %s' % (op['path'], i, e))
            return msgtext.build_msg(mode, entries)
        if kind == 'dat':
            texts = self.p.keyed(op['path'])
            if op['key'] not in texts:
                raise ProjectError('%s: нет сообщения %s' % (op['path'], op['key']))
            return texts[op['key']].replace('\n', '\r\n').encode('utf-8') + b'\0'
        if kind == 'blit':
            if current is not None and sha1(current) == op['want']:
                return current                  # картинка уже исправлена
            base = self._copy(op['base'], None, where)
            if base is None:
                return None
            img = gimmod.Gim(base)
            for rel in op['grids']:
                x, y, rows = self.p.grid(rel)
                img.blit(x, y, rows)
            return img.save()
        raise ProjectError('неизвестная операция %s' % kind)

    def build(self):
        out = {}
        for name, op in self.p.manifest['files'].items():
            current = self.src(name)
            if current is None:
                self.warn('в архиве образа нет файла %s, пропущен' % name)
                continue
            if op['op'] == 'copy':
                data = self._copy(op, current, name)
                if data is not None:
                    out[name] = data
                continue
            if not pck.is_pck(current):
                self.warn('%s в образе повреждён или не является контейнером, пропущен' % name)
                continue
            cur_files = pck.files(current)
            missing = [s for s in op['subs'] if s not in cur_files]
            if missing:
                self.warn('%s: в образе нет вложенных файлов %s, пропущен' % (name, ', '.join(missing)))
                continue
            repl = {}
            for sub, sop in op['subs'].items():
                data = self._sub(name, sub, sop, cur_files[sub])
                if data is not None:
                    repl[sub] = data
            data = pck.build(current, repl, op.get('order'))
            if 'size' in op and len(data) < op['size']:
                data = data.ljust(op['size'], b'\0')
            out[name] = data
        return out

    def compare_official(self, built):
        """Сколько собранных файлов отличается от эталонной сборки."""
        return [n for n, d in built.items() if self.official.get(n) != sha1(d)]
