#!/usr/bin/env python3
"""
Русификатор Final Fantasy (Anniversary Edition) для PSP.

    python3 ff1_rus.py ОБРАЗ [РЕЗУЛЬТАТ]

ОБРАЗ - американская версия игры (ULUS-10251): ISO, CSO или ZSO.
РЕЗУЛЬТАТ - имя нового файла (.iso или .cso). Если не указан, рядом
с исходным образом создаётся "<имя> [RUS]" в том же формате.
Без аргументов скрипт ищет образ в своей папке.

Перевод собирается из папки translation/ (тексты, шрифты, картинки),
файлы игры берутся из вашего образа. Исходный образ не изменяется.
"""
import hashlib
import os
import sys

if sys.version_info < (3, 8):
    sys.exit('Нужен Python 3.8 или новее (сейчас %d.%d).' % sys.version_info[:2])

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ff1lib import image, pck              # noqa: E402
from ff1lib.project import Builder, Project, ProjectError  # noqa: E402

DPK = '/PSP_GAME/USRDIR/data/ff1psp.dpk'
BOOT = '/PSP_GAME/SYSDIR/BOOT.BIN'
EBOOT = '/PSP_GAME/SYSDIR/EBOOT.BIN'
IMAGE_EXT = ('.iso', '.cso', '.zso')
ISSUES_URL = 'https://github.com/3xa228148/ff1-psp-rus/issues/new/choose'


def sha1(b):
    return hashlib.sha1(b).hexdigest()


class Log:
    def __init__(self):
        self.warnings = []

    def info(self, msg):
        print(msg, flush=True)

    def warn(self, msg):
        self.warnings.append(msg)
        print('  ВНИМАНИЕ: ' + msg, flush=True)


def fail(msg):
    print('\nОШИБКА: ' + msg, flush=True)
    print('Если не получается разобраться, сообщите о проблеме: ' + ISSUES_URL, flush=True)
    sys.exit(1)


def default_output(src):
    root, ext = os.path.splitext(src)
    ext = '.cso' if ext.lower() in ('.cso', '.zso') else '.iso'
    return root + ' [RUS]' + ext


def find_image():
    """Поиск образа рядом со скриптом и в текущей папке."""
    found = []
    for d in dict.fromkeys([HERE, os.getcwd()]):
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith(IMAGE_EXT) and '[RUS]' not in fn:
                found.append(os.path.join(d, fn))
    if not found:
        print(__doc__)
        print('Образ не найден. Положите образ игры (.iso или .cso) в папку\n%s\n'
              'или перетащите его на rusify.bat / укажите путь в командной строке.' % HERE)
        sys.exit(1)
    if len(found) == 1:
        return found[0]
    print('Найдено несколько образов:')
    for i, f in enumerate(found, 1):
        print('  %d. %s' % (i, os.path.basename(f)))
    while True:
        try:
            ans = input('Номер образа для русификации: ').strip()
        except EOFError:
            sys.exit(1)
        if ans.isdigit() and 1 <= int(ans) <= len(found):
            return found[int(ans) - 1]


def patch_code(boot, eboot_size, code, log):
    """Правка меню выбора языка. Возвращает (BOOT.BIN, EBOOT.BIN) или (None, None)."""
    if boot[:4] != b'\x7fELF':
        log.warn('BOOT.BIN не является программой ELF - правка кода пропущена '
                 '(в меню выбора языка будет лишний пункт)')
        return None, None
    new = bytearray(boot)
    for off, old, rep in code:
        cur = bytes(new[off:off + len(old)])
        if cur == old:
            new[off:off + len(rep)] = rep
        elif cur != rep:
            log.warn('BOOT.BIN отличается от ожидаемого - правка кода пропущена '
                     '(в меню выбора языка будет лишний пункт)')
            return None, None
    new = bytes(new)
    if eboot_size < len(new):
        log.warn('EBOOT.BIN меньше BOOT.BIN - правка кода пропущена')
        return None, None
    return new, new + b'\0' * (eboot_size - len(new))


def run(src, dst):
    log = Log()
    project = Project(os.path.join(HERE, 'translation'))
    m = project.manifest

    log.info('Исходный образ: %s' % src)
    try:
        iso = image.read_image(src)
    except (OSError, ValueError) as e:
        fail('не удалось прочитать образ: %s' % e)
    if not image.is_iso9660(iso):
        fail('файл не похож на образ диска PSP (ISO, CSO или ZSO).')
    try:
        umd = image.read_file(iso, '/UMD_DATA.BIN').split(b'|')[0].decode('latin1')
    except LookupError:
        umd = '?'
    if umd != m['game']:
        log.warn('код диска %s, а перевод сделан для %s. Продолжаю, но результат '
                 'не гарантирован.' % (umd, m['game']))
    try:
        dpk = image.read_file(iso, DPK)
        boot = image.read_file(iso, BOOT)
        eboot_size = image.find_file(iso, EBOOT)[1]
    except LookupError as e:
        fail('в образе нет файла %s - это не Final Fantasy для PSP, русифицировать нечего.' % e)

    h = sha1(dpk)
    if h == m['source']['dpk_sha1']:
        log.info('Образ оригинальный, проверка пройдена.')
    elif h == m['result']['dpk_sha1']:
        log.info('Образ уже русифицирован этой версией перевода - будет пересобран.')
    else:
        log.warn('образ отличается от оригинального (другой дамп, изменённый '
                 'или уже переведённый образ). Продолжаю: перевод будет '
                 'наложен везде, где это возможно.')

    log.info('Сборка перевода из папки translation ...')
    try:
        built = Builder(project, dpk, log.warn).build()
    except ProjectError as e:
        fail('ошибка в файлах перевода: %s' % e)
    changed = [n for n, d in built.items() if m['result']['files'].get(n) != sha1(d)]

    log.info('Упаковка архива игры (%d файлов) ...' % len(built))

    def progress(done, total):
        if done % 100 == 0 or done == total:
            log.info('  %d/%d' % (done, total))
    try:
        new_dpk = pck.build_archive(dpk, built, progress)
    except OverflowError as e:
        fail('%s. Перевод не помещается в архив этого образа.' % e)

    new_boot, new_eboot = patch_code(boot, eboot_size, project.code_patch(), log)

    image.write_file(iso, DPK, new_dpk)
    if new_boot is not None:
        image.write_file(iso, BOOT, new_boot)
        image.write_file(iso, EBOOT, new_eboot)

    log.info('Запись: %s' % dst)
    try:
        image.write_image(dst, iso)
    except OSError as e:
        fail('не удалось записать результат: %s' % e)

    exact = (sha1(new_dpk) == m['result']['dpk_sha1'] and new_boot is not None
             and sha1(new_eboot) == m['result']['eboot_sha1'])
    print()
    if exact:
        log.info('Готово. Результат совпадает с эталонной сборкой перевода.')
    elif not changed and len(built) == len(m['result']['files']) and new_boot is not None:
        log.info('Готово. Все переведённые файлы совпадают с эталонной сборкой.')
    else:
        log.info('Готово.')
        if changed:
            log.info('Файлов, отличающихся от эталонной сборки: %d '
                     '(изменён перевод или исходный образ нестандартный).' % len(changed))
    if log.warnings:
        log.info('Предупреждений: %d (см. выше). Проверьте игру перед тем, как делиться образом.'
                 % len(log.warnings))
        log.info('Если с игрой что-то не так, сообщите: ' + ISSUES_URL)


def main(argv):
    args = [a for a in argv[1:] if a]
    if args and args[0] in ('-h', '--help', '/?'):
        print(__doc__)
        return 0
    src = args[0] if args else find_image()
    dst = args[1] if len(args) > 1 else default_output(src)
    if not os.path.isfile(src):
        fail('файл не найден: %s' % src)
    if os.path.abspath(src) == os.path.abspath(dst):
        fail('результат нужно сохранить в другой файл - исходный образ не перезаписывается.')
    if not dst.lower().endswith(('.iso', '.cso')):
        fail('имя результата должно оканчиваться на .iso или .cso')
    run(src, dst)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        sys.exit('\nПрервано.')
