import json
import os
import re
import sys
import shutil
import hashlib
import subprocess
import unicodedata
from datetime import date, datetime

from PyQt6.QtCore import QDate, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateEdit, QFileDialog,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

DATA_FILE = './data.json'
IMG_PATH = './img/'
REPO_DIR = '.'

SECTIONS = ['altalanos', 'copilot']
CARD_TYPES = ['largeCards', 'smallCards']
LEVELS = ['kezdo', 'halado']
KISOKOS = 'kisokos'      # a felső narancs sáv csempéi — sima lista, nincs típusa/szintje
KISOKOS_MAX = 4          # az index.html MAX_TILES értéke: ennyi jelenik meg az oldalon

ALLOWED_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'}
MAX_IMG_BYTES = 5 * 1024 * 1024  # 5 MB — csak figyelmeztetés, nem tiltás
PUSH_DELAY_MS = 4000  # ennyi nyugalom után indul az automatikus feltöltés
NEW_DAYS = 30  # ennyi napig 'ÚJ' egy kártya — az index.html-ben is ugyanennyi legyen
NO_DATE = QDate(2000, 1, 1)  # a dátummező 'nincs dátum' állása

# Mi történjen, ha a data.json a gépen ÉS a GitHubon is változott?
#   'newer'  -> amelyik frissebb (helyi fájl módosítási ideje vs. GitHub commit ideje)
#   'local'  -> mindig a gépen lévő marad
#   'remote' -> mindig a GitHubos marad
CONFLICT_POLICY = 'remote'
# Ütközésnél a VESZTES oldal mindig ide mentődik, így semmi nem vész el.
# (Nem kerül fel GitHubra, mert a szinkron csak a data.json-t és az img-t tölti fel.)
BACKUP_DIR = './backup/'

# Világos és sötét témán is olvasható színek. A None a téma alap szövegszínét jelenti.
STATUS_NEUTRAL = None
STATUS_PENDING = '#c9911a'
STATUS_OK = '#3aa14b'
STATUS_ERROR = '#e5534b'

ROLE = Qt.ItemDataRole.UserRole


# --- Segédfüggvények -------------------------------------------------------

def sanitize_filename(name):
    """'Képernyőkép 2026-08-30.PNG' -> 'kepernyokep-2026-08-30.png'"""
    base, ext = os.path.splitext(name)

    ext = ext.lower()
    if ext == '.jpeg':
        ext = '.jpg'

    # ékezetek leszedése: NFKD szétbontja az ő-t o + jelre, az ascii ignore eldobja a jelet
    base = unicodedata.normalize('NFKD', base)
    base = base.encode('ascii', 'ignore').decode('ascii')
    base = base.lower()
    base = re.sub(r'\s+', '-', base)
    base = re.sub(r'[^a-z0-9._-]', '', base)
    base = re.sub(r'-{2,}', '-', base).strip('-_.')

    if not base:
        base = 'kep'

    return base + ext


def parse_date(text):
    try:
        return datetime.strptime(text, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def days_left(card):
    """Hány napig számít még újnak a kártya. None, ha már nem új (vagy nincs dátuma)."""
    d = parse_date(card.get('date'))
    if d is None:
        return None
    left = NEW_DAYS - (date.today() - d).days
    return left if left >= 0 else None


def migrate_cards(data):
    """A régi isNew mezőt dátumra cseréli. True, ha bármi változott.

    isNew: true  -> date = ma (innentől NEW_DAYS napig új)
    isNew: false -> a mező egyszerűen eltűnik
    """
    today = date.today().isoformat()
    changed = False

    lists = []
    for section in data.values():
        if isinstance(section, dict):
            lists.extend(v for v in section.values() if isinstance(v, list))
        elif isinstance(section, list):
            lists.append(section)  # pl. a 'kisokos' tömb

    for cards in lists:
        for card in cards:
            if not isinstance(card, dict) or 'isNew' not in card:
                continue
            if card.pop('isNew') and not card.get('date'):
                card['date'] = today
            changed = True

    return changed


def file_hash(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def same_content(path_a, path_b):
    try:
        if os.path.getsize(path_a) != os.path.getsize(path_b):
            return False
        return file_hash(path_a) == file_hash(path_b)
    except OSError:
        return False


def run_git(args):
    """Git parancs futtatása. Sosem kérdez interaktívan, sosem nyit konzolablakot."""
    env = dict(os.environ)
    env['GIT_TERMINAL_PROMPT'] = '0'

    kwargs = {}
    if sys.platform == 'win32':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

    return subprocess.run(
        ['git', '-C', REPO_DIR] + args,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        env=env,
        **kwargs
    )


# --- Fa nézet, csoporton belüli húzással -----------------------------------

class CardTree(QTreeWidget):
    """Kétszintű fa: szekció/típus csoportok, alattuk a kártyák.

    A húzás csak azonos csoporton belül engedélyezett, mert a JSON-ben
    minden csoport külön lista.
    """

    orderChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setColumnCount(5)
        self.setHeaderLabels(['Cím (Keresőhöz)', 'Szint / Alcím', 'Dátum', 'Kép', 'Link'])
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setUniformRowHeights(True)

        self.setColumnWidth(0, 300)
        self.setColumnWidth(1, 140)
        self.setColumnWidth(2, 170)
        self.setColumnWidth(3, 220)

    def dropEvent(self, event):
        dragged = self.currentItem()
        target = self.itemAt(event.position().toPoint())

        # Csak kártyát lehet húzni, csoportot nem
        if dragged is None or dragged.parent() is None:
            event.ignore()
            return

        if target is None:
            event.ignore()
            return

        target_group = target.parent() if target.parent() is not None else target
        if target_group is not dragged.parent():
            event.ignore()
            return

        # Kártyára ejtés helyett mindig sorok közé kerüljön
        position = self.dropIndicatorPosition()
        if (position == QAbstractItemView.DropIndicatorPosition.OnItem
                and target.parent() is not None):
            event.ignore()
            return

        super().dropEvent(event)
        self.orderChanged.emit()


# --- GitHub szinkron háttérszálon ------------------------------------------

def read_bytes(path):
    try:
        with open(path, 'rb') as f:
            return f.read()
    except OSError:
        return None


class GitSyncWorker(QThread):
    """Előbb behúzza a GitHub állapotát, eldönti ki nyer a data.json-nál,
    aztán feltölti, ami helyben új."""

    done = pyqtSignal(str, str, str, bool)  # státusz, szín, hibaüzenet, változott-e a data.json

    def run(self):
        self.start_bytes = read_bytes(DATA_FILE)
        try:
            self.sync()
        except FileNotFoundError:
            self.finish('Nincs git.', STATUS_ERROR,
                        'A git parancs nem található. Telepítsd a Git for Windows csomagot.')
        except Exception as error:  # ne haljon el csendben a szál
            self.finish('Váratlan hiba.', STATUS_ERROR, repr(error))

    def finish(self, status, color, detail=''):
        changed = read_bytes(DATA_FILE) != self.start_bytes
        self.done.emit(status, color or '', detail, changed)

    def git(self, args):
        r = run_git(args)
        return r.returncode, (r.stdout or '').strip(), (r.stderr or r.stdout or '').strip()

    def sync(self):
        rc, _, _ = self.git(['rev-parse', '--is-inside-work-tree'])
        if rc != 0:
            return self.finish('Nem git repo.', STATUS_ERROR,
                               f'A(z) {os.path.abspath(REPO_DIR)} mappa nem git repository.')

        rc, upstream, _ = self.git(['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'])
        if rc != 0:
            return self.finish('Nincs követett ág.', STATUS_ERROR,
                               'Az aktuális ágnak nincs beállítva távoli párja.\n\n'
                               "Futtasd egyszer kézzel a mappában:  git push -u origin main")

        # 1. Távoli állapot letöltése (még nem nyúl a helyi fájlokhoz)
        rc, _, err = self.git(['fetch', '--quiet'])
        if rc != 0:
            return self.finish('Letöltés sikertelen.', STATUS_ERROR,
                               'Nem sikerült elérni a GitHubot:\n\n' + err)

        # A helyi data.json mentése, mielőtt bármi hozzányúlna
        local_bytes = read_bytes(DATA_FILE)
        local_mtime = os.path.getmtime(DATA_FILE) if local_bytes is not None else 0

        # 2. Helyi változások commitolása
        paths = [p for p in ('data.json', 'img') if os.path.exists(p)]
        if paths:
            rc, _, err = self.git(['add', '--'] + paths)
            if rc != 0:
                return self.finish('Add sikertelen.', STATUS_ERROR, err)

        stamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        rc, _, _ = self.git(['diff', '--cached', '--quiet'])
        if rc == 1:
            rc, _, err = self.git(['commit', '-m', f'Kártyák frissítése — {stamp}'])
            if rc != 0:
                return self.finish('Commit sikertelen.', STATUS_ERROR, err)

        # 3. Ki változtatta a data.json-t a közös pont óta?
        rc, base, err = self.git(['merge-base', 'HEAD', upstream])
        if rc != 0:
            return self.finish('Nincs közös előzmény.', STATUS_ERROR,
                               'A helyi és a GitHubos repo előzménye nem kapcsolódik:\n\n' + err)

        local_changed = self.git(['diff', '--quiet', base, 'HEAD', '--', 'data.json'])[0] == 1
        remote_changed = self.git(['diff', '--quiet', base, upstream, '--', 'data.json'])[0] == 1

        conflict = local_changed and remote_changed
        local_wins = True
        if conflict:
            if CONFLICT_POLICY == 'local':
                local_wins = True
            elif CONFLICT_POLICY == 'remote':
                local_wins = False
            else:
                _, ct, _ = self.git(['log', '-1', '--format=%ct', upstream, '--', 'data.json'])
                remote_time = int(ct) if ct.isdigit() else 0
                local_wins = local_mtime >= remote_time

        # 4. Rebase a GitHubos állapotra. Rebase közben az "ours" a távoli,
        #    a "theirs" a helyi commit — ezért fordítva kell megadni.
        behind = self.git(['rev-list', '--count', f'HEAD..{upstream}'])[1]
        if behind not in ('', '0'):
            strategy = 'theirs' if local_wins else 'ours'
            # --autostash: a nem általunk kezelt, módosított fájlokat (pl. index.html)
            # félreteszi a rebase idejére, utána visszarakja
            rc, _, err = self.git(['rebase', '--autostash', '-X', strategy, upstream])
            if rc != 0:
                self.git(['rebase', '--abort'])
                return self.finish('Összefésülés sikertelen.', STATUS_ERROR,
                                   'Nem sikerült összefésülni a GitHubos változásokkal:\n\n' + err)

        # 5. Ütközésnél a nyertes data.json-t egészben érvényesítjük,
        #    hogy ne legyen belőle félig ez, félig az.
        note = ''
        if conflict:
            backup_stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            os.makedirs(BACKUP_DIR, exist_ok=True)
            if local_wins:
                rc_show, remote_text, _ = self.git(['show', f'{upstream}:data.json'])
                if rc_show == 0:
                    with open(os.path.join(BACKUP_DIR, f'data-github-{backup_stamp}.json'),
                              'w', encoding='utf-8') as f:
                        f.write(remote_text + '\n')
            elif local_bytes is not None:
                with open(os.path.join(BACKUP_DIR, f'data-helyi-{backup_stamp}.json'), 'wb') as f:
                    f.write(local_bytes)

            if local_wins and local_bytes is not None:
                with open(DATA_FILE, 'wb') as f:
                    f.write(local_bytes)
                note = ' (ütközés: a gépen lévő maradt, a GitHubos a backup mappában)'
            else:
                self.git(['checkout', upstream, '--', 'data.json'])
                note = ' (ütközés: a GitHubos maradt, a helyi a backup mappában)'

            self.git(['add', '--', 'data.json'])
            if self.git(['diff', '--cached', '--quiet'])[0] == 1:
                rc, _, err = self.git(['commit', '-m', f'data.json ütközés feloldva — {stamp}'])
                if rc != 0:
                    return self.finish('Commit sikertelen.', STATUS_ERROR, err)

        # 6. Push, ha van mit
        ahead = self.git(['rev-list', '--count', f'{upstream}..HEAD'])[1]
        if ahead in ('', '0'):
            return self.finish('Naprakész' + note + '.', STATUS_OK)

        rc, _, err = self.git(['push'])
        if rc != 0:
            return self.finish('Push sikertelen.', STATUS_ERROR,
                               'Nem sikerült feltölteni:\n\n' + err
                               + "\n\nHa hitelesítési hibát látsz, futtass egy 'git push' parancsot "
                                 'kézzel a mappában, és jelentkezz be egyszer.')

        self.finish(f'Feltöltve — {stamp}{note}', STATUS_OK)


# --- Főablak ---------------------------------------------------------------

class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('SharePoint AI Kártya Kezelő')
        self.resize(1100, 800)

        self.data = self.load_data()
        self.disk_snapshot = read_bytes(DATA_FILE)  # amit utoljára láttunk a lemezen
        self.original_image_path = None
        self.push_worker = None

        # Több gyors változtatást (pl. húzogatás) egy commitba fogunk össze
        self.push_timer = QTimer(self)
        self.push_timer.setSingleShot(True)
        self.push_timer.timeout.connect(self.start_push)

        self.build_ui()
        self.refresh_tree()

        # Indításkor először behúzzuk a GitHub állapotát
        QTimer.singleShot(0, self.start_push)

    # --- Adatkezelés -------------------------------------------------------

    def load_data(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                data = None

            if data is not None:
                # isNew -> date átállás CSAK memóriában. A fájlhoz betöltéskor nem
                # nyúlunk, mert az friss módosítási időt adna neki, és szinkronnál
                # tévesen "újabbnak" látszana a GitHubos változatnál.
                # A következő mentéskor a már átállított adat kerül ki.
                migrate_cards(data)
                data.setdefault(KISOKOS, [])
                return data
        return {
            'altalanos': {'largeCards': [], 'smallCards': []},
            'copilot': {'largeCards': [], 'smallCards': []},
            KISOKOS: [],
        }

    def cards_of(self, section, ctype):
        """A kártyák listája egy csoportban. A kisokos sima lista, a többi szekció/típus."""
        if section == KISOKOS:
            return self.data.setdefault(KISOKOS, [])
        return self.data.setdefault(section, {}).setdefault(ctype, [])

    def set_cards(self, section, ctype, cards):
        if section == KISOKOS:
            self.data[KISOKOS] = cards
        else:
            self.data.setdefault(section, {})[ctype] = cards

    def save_data(self):
        """Mentés. Ha a data.json-t közben kívülről (kézzel, másik programmal)
        átírták, nem írjuk felül szó nélkül."""
        on_disk = read_bytes(DATA_FILE)
        if on_disk is not None and on_disk != self.disk_snapshot:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle('A data.json közben megváltozott')
            box.setText('A data.json-t a kezelőn kívül módosították, mióta betöltötted.\n\n'
                        'Betöltés: a lemezen lévő változat jön be, ez az utolsó módosításod elvész.\n'
                        'Felülírás: a kezelőben lévő adat ment ki, a lemezen lévő a backup mappába kerül.')
            reload_btn = box.addButton('Betöltés', QMessageBox.ButtonRole.AcceptRole)
            box.addButton('Felülírás', QMessageBox.ButtonRole.DestructiveRole)
            box.exec()

            if box.clickedButton() is reload_btn:
                self.data = self.load_data()
                self.disk_snapshot = read_bytes(DATA_FILE)
                self.refresh_tree()
                self.clear_form()
                return False

            os.makedirs(BACKUP_DIR, exist_ok=True)
            stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            with open(os.path.join(BACKUP_DIR, f'data-lemezen-{stamp}.json'), 'wb') as f:
                f.write(on_disk)

        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)
        self.disk_snapshot = read_bytes(DATA_FILE)

        self.schedule_push()
        return True

    # --- Felület -----------------------------------------------------------

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Fa
        tree_box = QGroupBox('Meglévő Kártyák — kattints a szerkesztéshez, húzd a sorokat a sorrendezéshez (vagy Alt + ↑/↓)')
        tree_layout = QVBoxLayout(tree_box)

        self.tree = CardTree()
        self.tree.itemSelectionChanged.connect(self.on_select)
        self.tree.orderChanged.connect(self.on_order_changed)
        tree_layout.addWidget(self.tree)
        layout.addWidget(tree_box, stretch=1)
        self.tree_box = tree_box

        # Űrlap
        form_box = QGroupBox('Kártya Szerkesztése / Hozzáadása')
        form_layout = QGridLayout(form_box)

        self.section_combo = QComboBox()
        self.section_combo.addItems(SECTIONS + [KISOKOS])
        self.section_combo.currentTextChanged.connect(self.update_form_mode)
        self.type_combo = QComboBox()
        self.type_combo.addItems(CARD_TYPES)
        self.type_combo.setCurrentText('smallCards')
        self.level_combo = QComboBox()
        self.level_combo.addItems(LEVELS)

        form_layout.addWidget(QLabel('Szekció:'), 0, 0)
        form_layout.addWidget(self.section_combo, 0, 1)
        form_layout.addWidget(QLabel('Kártya típusa:'), 0, 2)
        form_layout.addWidget(self.type_combo, 0, 3)
        form_layout.addWidget(QLabel('Szint:'), 1, 0)
        form_layout.addWidget(self.level_combo, 1, 1)

        # Csak a kisokos csempéknél
        self.sub_edit = QLineEdit()
        self.sub_edit.setPlaceholderText('pl. Új szabályzat — csak kisokosnál')
        form_layout.addWidget(QLabel('Alcím:'), 1, 2)
        form_layout.addWidget(self.sub_edit, 1, 3)

        self.title_edit = QLineEdit()
        form_layout.addWidget(QLabel('Cím (Keresőhöz!):'), 2, 0)
        form_layout.addWidget(self.title_edit, 2, 1, 1, 3)

        self.img_edit = QLineEdit()
        self.img_edit.setReadOnly(True)
        self.img_edit.setPlaceholderText('Nincs kép kiválasztva')
        browse_btn = QPushButton('Tallózás')
        browse_btn.clicked.connect(self.browse_image)
        form_layout.addWidget(QLabel('Kép fájlneve:'), 3, 0)
        form_layout.addWidget(self.img_edit, 3, 1, 1, 2)
        form_layout.addWidget(browse_btn, 3, 3)

        self.link_edit = QLineEdit()
        form_layout.addWidget(QLabel('Link (Cél URL):'), 4, 0)
        form_layout.addWidget(self.link_edit, 4, 1, 1, 3)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat('yyyy.MM.dd')
        self.date_edit.setMinimumDate(NO_DATE)
        self.date_edit.setSpecialValueText('nincs dátum')  # a minimum dátum helyett ez látszik
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.dateChanged.connect(self.update_date_hint)

        today_btn = QPushButton('Ma')
        today_btn.setToolTip('Mai dátum — a kártya újra ' + str(NEW_DAYS) + ' napig ÚJ lesz')
        today_btn.clicked.connect(lambda: self.date_edit.setDate(QDate.currentDate()))

        self.date_hint = QLabel()

        date_row = QHBoxLayout()
        date_row.addWidget(self.date_edit)
        date_row.addWidget(today_btn)
        date_row.addWidget(self.date_hint)
        date_row.addStretch()

        self.mark_cb = QCheckBox('Piros felkiáltójel (kisokos)')
        date_row.addWidget(self.mark_cb)

        form_layout.addWidget(QLabel('Dátum:'), 5, 0)
        form_layout.addLayout(date_row, 5, 1, 1, 3)
        self.update_date_hint()
        self.update_form_mode()

        # Gombsor
        buttons = QHBoxLayout()
        add_btn = QPushButton('Új Hozzáadása')
        add_btn.clicked.connect(self.add_card)
        buttons.addWidget(add_btn)

        self.update_btn = QPushButton('Kiválasztott Módosítása')
        self.update_btn.clicked.connect(self.update_card)
        self.update_btn.setEnabled(False)
        buttons.addWidget(self.update_btn)

        self.delete_btn = QPushButton('Kiválasztott Törlése')
        self.delete_btn.clicked.connect(self.delete_card)
        self.delete_btn.setEnabled(False)
        buttons.addWidget(self.delete_btn)

        clear_btn = QPushButton('Kijelölés Törlése')
        clear_btn.clicked.connect(self.clear_form)
        buttons.addWidget(clear_btn)

        buttons.addSpacing(20)

        self.up_btn = QPushButton('↑ Fel')
        self.up_btn.clicked.connect(lambda: self.nudge_selected(-1))
        self.up_btn.setEnabled(False)
        buttons.addWidget(self.up_btn)

        self.down_btn = QPushButton('↓ Le')
        self.down_btn.clicked.connect(lambda: self.nudge_selected(1))
        self.down_btn.setEnabled(False)
        buttons.addWidget(self.down_btn)

        buttons.addStretch()
        form_layout.addLayout(buttons, 6, 0, 1, 4)
        layout.addWidget(form_box)
        self.form_box = form_box

        # GitHub
        git_box = QGroupBox('GitHub')
        git_layout = QHBoxLayout(git_box)

        self.push_btn = QPushButton('Feltöltés most')
        self.push_btn.setToolTip('Minden mentés automatikusan feltöltődik — '
                                 'ez a gomb csak nem vár a késleltetésre.')
        self.push_btn.clicked.connect(self.push_now)
        git_layout.addWidget(self.push_btn)

        self.git_status = QLabel('Automatikus feltöltés bekapcsolva.')
        git_layout.addWidget(self.git_status)
        git_layout.addStretch()
        layout.addWidget(git_box)

        # Billentyűparancsok
        QShortcut(QKeySequence('Alt+Up'), self, lambda: self.nudge_selected(-1))
        QShortcut(QKeySequence('Alt+Down'), self, lambda: self.nudge_selected(1))

    # --- Fa feltöltése -----------------------------------------------------

    def refresh_tree(self, select=None):
        """select = (section, ctype, index), ha újra ki akarunk jelölni egy kártyát."""
        self.tree.blockSignals(True)
        self.tree.clear()

        groups = [(KISOKOS, None)] + [(sec, ct) for sec in SECTIONS for ct in CARD_TYPES]
        for section, ctype in groups:
                cards = self.cards_of(section, ctype)

                if section == KISOKOS:
                    label = f'AI Kisokos sáv  ›  az első {KISOKOS_MAX} jelenik meg ({len(cards)} db)'
                else:
                    label = f'{section}  ›  {ctype}'
                group = QTreeWidgetItem(self.tree, [label])
                group.setData(0, ROLE, (section, ctype))
                group.setFirstColumnSpanned(True)
                # Nem állítunk fix színt, hogy sötét témában is olvasható maradjon
                group_font = group.font(0)
                group_font.setBold(True)
                group.setFont(0, group_font)
                # A csoport nem húzható, de rá lehet ejteni
                group.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsDropEnabled
                )

                for card in cards:
                    if section == KISOKOS:
                        second = ('❗ ' if card.get('mark') else '') + card.get('sub', '')
                    else:
                        second = card.get('level', '')
                    item = QTreeWidgetItem(group, [
                        card.get('title', ''),
                        second,
                        self.date_label(card),
                        card.get('img', ''),
                        card.get('link', ''),
                    ])
                    item.setData(0, ROLE, card)
                    # A kártya húzható, de nem ejthető rá másik kártya
                    item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsDragEnabled
                    )

        self.tree.expandAll()
        self.tree.blockSignals(False)

        if select:
            self.select_card(*select)

    def select_card(self, section, ctype, index):
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            if group.data(0, ROLE) != (section, ctype):
                continue
            if 0 <= index < group.childCount():
                item = group.child(index)
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
            return

    def selected_path(self):
        """(section, ctype, index) vagy None."""
        item = self.tree.currentItem()
        if item is None or item.parent() is None:
            return None
        group = item.parent()
        section, ctype = group.data(0, ROLE)
        return section, ctype, group.indexOfChild(item)

    # --- Sorrendezés -------------------------------------------------------

    def on_order_changed(self):
        """Húzás után a fa a mérvadó: abból építjük újra a listákat."""
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            section, ctype = group.data(0, ROLE)
            self.set_cards(section, ctype, [
                group.child(j).data(0, ROLE) for j in range(group.childCount())
            ])

        self.save_data()

    def nudge_selected(self, delta):
        path = self.selected_path()
        if not path:
            return

        section, ctype, index = path
        cards = self.cards_of(section, ctype)
        new_index = index + delta

        if not 0 <= new_index < len(cards):
            return

        cards[index], cards[new_index] = cards[new_index], cards[index]
        self.save_data()
        self.refresh_tree(select=(section, ctype, new_index))

    # --- Űrlap <-> adat ----------------------------------------------------

    def on_select(self):
        path = self.selected_path()
        if not path:
            self.update_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            self.up_btn.setEnabled(False)
            self.down_btn.setEnabled(False)
            return

        section, ctype, index = path
        card = self.cards_of(section, ctype)[index]
        self.original_image_path = None

        self.section_combo.setCurrentText(section)
        if ctype:
            self.type_combo.setCurrentText(ctype)
        self.level_combo.setCurrentText(card.get('level', 'kezdo'))
        self.sub_edit.setText(card.get('sub', ''))
        self.mark_cb.setChecked(bool(card.get('mark')))
        self.title_edit.setText(card.get('title', ''))
        self.img_edit.setText(os.path.basename(card.get('img', '')))
        self.link_edit.setText(card.get('link', '#'))
        d = parse_date(card.get('date'))
        self.date_edit.setDate(QDate(d.year, d.month, d.day) if d else NO_DATE)

        self.update_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self.up_btn.setEnabled(True)
        self.down_btn.setEnabled(True)

    def clear_form(self):
        self.tree.clearSelection()
        self.tree.setCurrentItem(None)
        self.original_image_path = None
        self.title_edit.clear()
        self.img_edit.clear()
        self.link_edit.clear()
        self.sub_edit.clear()
        self.mark_cb.setChecked(False)
        self.date_edit.setDate(QDate.currentDate())
        self.update_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.up_btn.setEnabled(False)
        self.down_btn.setEnabled(False)

    # --- Kép ---------------------------------------------------------------

    def browse_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            'Válassz képet',
            '',
            'Képfájlok (*.png *.jpg *.jpeg *.gif *.webp *.svg);;Minden fájl (*)'
        )
        if file_path:
            self.original_image_path = os.path.abspath(file_path)
            self.img_edit.setText(os.path.basename(file_path))

    def resolve_destination(self, filename, source):
        """(végleges fájlnév, cél útvonal, másolás kihagyható-e).

        Ha a név foglalt, de a tartalom ugyanaz, újrahasználjuk a meglévő fájlt.
        Ha foglalt és más a tartalom, -1, -2 ... utótagot kap.
        """
        base, ext = os.path.splitext(filename)
        candidate = filename
        counter = 0

        while True:
            dest = os.path.join(IMG_PATH, candidate)
            if not os.path.exists(dest):
                return candidate, dest, False
            if same_content(source, dest):
                return candidate, dest, True
            counter += 1
            candidate = f'{base}-{counter}{ext}'

    def resolve_image(self):
        """Új kép esetén bemásolja az img/ mappába. Visszaadja a végleges fájlnevet."""
        source = self.original_image_path

        # Nincs új kép kiválasztva -> a kártya meglévő képe marad
        if not source:
            existing = self.img_edit.text().strip()
            if not existing:
                QMessageBox.critical(self, 'Hiba', 'Kép megadása kötelező!')
                return None
            return os.path.basename(existing)

        ext = os.path.splitext(source)[1].lower()
        if ext not in ALLOWED_EXT:
            QMessageBox.critical(
                self, 'Hiba',
                f'Nem támogatott képformátum: {ext or "(nincs kiterjesztés)"}'
            )
            return None

        try:
            size = os.path.getsize(source)
        except OSError as error:
            QMessageBox.critical(self, 'Hiba', str(error))
            return None

        if size > MAX_IMG_BYTES:
            mb = size / (1024 * 1024)
            answer = QMessageBox.question(
                self, 'Nagy fájl',
                f'A kép {mb:.1f} MB. Ez lassíthatja az oldal betöltését. '
                f'Biztosan ezt akarod használni?'
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None

        filename = sanitize_filename(os.path.basename(source))

        try:
            os.makedirs(IMG_PATH, exist_ok=True)
            filename, destination, already_there = self.resolve_destination(filename, source)
            if not already_there:
                shutil.copy2(source, destination)
        except OSError as error:
            QMessageBox.critical(self, 'Hiba', str(error))
            return None

        return filename

    def get_form_data(self):
        title = self.title_edit.text().strip()
        link = self.link_edit.text().strip()

        if not title:
            QMessageBox.critical(
                self, 'Hiba',
                'A cím megadása kötelező, különben nem fog működni a kereső!'
            )
            return None

        img_name = self.resolve_image()
        if not img_name:
            return None

        if not link:
            link = '#'
        elif link != '#' and not link.startswith('http') and not link.startswith('/'):
            link = f'https://{link}'

        if self.section_combo.currentText() == KISOKOS:
            card = {
                'img': f'img/{img_name}',
                'title': title,
                'sub': self.sub_edit.text().strip(),
                'link': link,
                'mark': self.mark_cb.isChecked(),
            }
        else:
            card = {
                'title': title,
                'link': link,
                'img': f'img/{img_name}',
                'level': self.level_combo.currentText(),
            }
        if self.date_edit.date() != NO_DATE:
            card['date'] = self.date_edit.date().toString('yyyy-MM-dd')
        return card

    # --- Dátum megjelenítés ------------------------------------------------

    def target_group(self):
        """Az űrlap szerinti cél csoport: (section, ctype)."""
        section = self.section_combo.currentText()
        return (section, None) if section == KISOKOS else (section, self.type_combo.currentText())

    def update_form_mode(self, *_):
        """Kisokosnál nincs típus és szint, viszont van alcím és felkiáltójel."""
        is_k = self.section_combo.currentText() == KISOKOS
        self.type_combo.setEnabled(not is_k)
        self.level_combo.setEnabled(not is_k)
        self.sub_edit.setEnabled(is_k)
        self.mark_cb.setEnabled(is_k)

    @staticmethod
    def date_label(card):
        d = parse_date(card.get('date'))
        if d is None:
            return '—'
        left = days_left(card)
        text = d.strftime('%Y.%m.%d')
        return f'{text}  · ÚJ még {left} napig' if left is not None else text

    def update_date_hint(self):
        qd = self.date_edit.date()
        if qd == NO_DATE:
            self.date_hint.setText('nem kap ÚJ jelölést')
            return
        left = days_left({'date': qd.toString('yyyy-MM-dd')})
        if left is None:
            self.date_hint.setText('már nem ÚJ')
        else:
            self.date_hint.setText(f'ÚJ jelölés még {left} napig')

    # --- CRUD --------------------------------------------------------------

    def add_card(self):
        new_card = self.get_form_data()
        if not new_card:
            return

        section, ctype = self.target_group()
        cards = self.cards_of(section, ctype)
        cards.append(new_card)

        if not self.save_data():
            return
        self.refresh_tree()
        self.clear_form()

        if section == KISOKOS and len(cards) > KISOKOS_MAX:
            QMessageBox.information(
                self, 'Siker',
                f'Kártya hozzáadva — de a sávban csak az első {KISOKOS_MAX} látszik. '
                f'Húzd feljebb, ha ennek is meg kell jelennie.')
        else:
            QMessageBox.information(self, 'Siker', 'Kártya hozzáadva!')

    def update_card(self):
        path = self.selected_path()
        if not path:
            return

        updated_card = self.get_form_data()
        if not updated_card:
            return

        old_section, old_ctype, index = path
        new_section, new_ctype = self.target_group()

        if (old_section, old_ctype) == (new_section, new_ctype):
            # Helyben cseréljük, hogy ne kerüljön a lista végére
            self.cards_of(old_section, old_ctype)[index] = updated_card
            target = (old_section, old_ctype, index)
        else:
            self.cards_of(old_section, old_ctype).pop(index)
            dest = self.cards_of(new_section, new_ctype)
            dest.append(updated_card)
            target = (new_section, new_ctype, len(dest) - 1)

        if not self.save_data():
            return
        self.refresh_tree(select=target)
        QMessageBox.information(self, 'Siker', 'Kártya módosítva!')

    def delete_card(self):
        path = self.selected_path()
        if not path:
            return

        answer = QMessageBox.question(
            self, 'Megerősítés', 'Biztosan törölni szeretnéd ezt a kártyát?'
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        section, ctype, index = path
        self.cards_of(section, ctype).pop(index)
        if not self.save_data():
            return
        self.refresh_tree()
        self.clear_form()

    # --- GitHub ------------------------------------------------------------

    def set_git_status(self, text, color=STATUS_NEUTRAL):
        """color=None esetén a téma alap szövegszíne marad, így sötét témán is látszik."""
        self.git_status.setText(text)
        self.git_status.setStyleSheet(f'color: {color};' if color else '')

    def schedule_push(self):
        """Minden mentés után hívódik. Nem indít azonnal feltöltést: vár egy kicsit,
        hogy a gyors egymás utáni változtatások egy commitba kerüljenek."""
        self.set_git_status('Változás mentve — feltöltés hamarosan...', STATUS_PENDING)
        self.push_timer.start(PUSH_DELAY_MS)

    def push_now(self):
        self.push_timer.stop()
        self.start_push()

    def start_push(self):
        # Ha még fut az előző feltöltés, kicsit később próbáljuk újra
        if self.push_worker is not None and self.push_worker.isRunning():
            self.push_timer.start(PUSH_DELAY_MS)
            return

        self.push_btn.setEnabled(False)
        # Szinkron alatt nem lehet szerkeszteni, különben a git felülírhatná a friss mentést
        self.tree_box.setEnabled(False)
        self.form_box.setEnabled(False)
        self.set_git_status('Szinkronizálás a GitHubbal...')

        self.push_worker = GitSyncWorker()
        self.push_worker.done.connect(self.on_push_done)
        self.push_worker.start()

    def on_push_done(self, status, color, error_detail, data_changed):
        self.set_git_status(status, color or STATUS_NEUTRAL)
        self.push_btn.setEnabled(True)
        self.tree_box.setEnabled(True)
        self.form_box.setEnabled(True)

        # Ha a GitHubról jött új data.json, töltsük újra a felületet
        if data_changed:
            self.data = self.load_data()
            self.refresh_tree()
            self.clear_form()
        self.disk_snapshot = read_bytes(DATA_FILE)

        if error_detail:
            QMessageBox.critical(self, 'GitHub hiba', error_detail)

    def closeEvent(self, event):
        """Kilépés előtt még feltöltjük, ami a késleltetés miatt bent ragadt."""
        if self.push_timer.isActive():
            self.push_timer.stop()
            if self.push_worker is None or not self.push_worker.isRunning():
                self.push_worker = GitSyncWorker()
                self.push_worker.start()

        if self.push_worker is not None and self.push_worker.isRunning():
            self.set_git_status('Feltöltés befejezése...')
            self.push_worker.wait(30000)

        event.accept()


if __name__ == '__main__':
    # Mindig a script mappájából dolgozzon, akárhonnan indítják
    os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))
    app = QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec())