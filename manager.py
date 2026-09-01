import json
import os
import re
import sys
import shutil
import hashlib
import subprocess
import unicodedata
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
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

ALLOWED_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'}
MAX_IMG_BYTES = 5 * 1024 * 1024  # 5 MB — csak figyelmeztetés, nem tiltás
PUSH_DELAY_MS = 4000  # ennyi nyugalom után indul az automatikus feltöltés

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
        self.setHeaderLabels(['Cím (Keresőhöz)', 'Szint', 'ÚJ', 'Kép', 'Link'])
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setUniformRowHeights(True)

        self.setColumnWidth(0, 300)
        self.setColumnWidth(1, 80)
        self.setColumnWidth(2, 60)
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


# --- GitHub feltöltés háttérszálon -----------------------------------------

class GitPushWorker(QThread):
    done = pyqtSignal(str, str, str)  # státusz szöveg, szín, részletes hibaüzenet

    def run(self):
        try:
            check = run_git(['rev-parse', '--is-inside-work-tree'])
        except FileNotFoundError:
            self.done.emit('Nincs git.', STATUS_ERROR,
                           'A git parancs nem található. Telepítsd a Git for Windows csomagot.')
            return

        if check.returncode != 0:
            self.done.emit('Nem git repo.', STATUS_ERROR,
                           f'A(z) {os.path.abspath(REPO_DIR)} mappa nem git repository.')
            return

        # 1. Távoli változások behúzása
        pull = run_git(['pull', '--rebase', '--autostash'])
        if pull.returncode != 0:
            self.done.emit('Pull sikertelen.', STATUS_ERROR,
                           'Nem sikerült behúzni a távoli változásokat:\n\n'
                           + (pull.stderr or pull.stdout).strip())
            return

        # 2. Változások előkészítése
        add = run_git(['add', '--', 'data.json', 'img'])
        if add.returncode != 0:
            self.done.emit('Add sikertelen.', STATUS_ERROR, (add.stderr or add.stdout).strip())
            return

        # 3. Commit — a "nincs mit commitolni" nem hiba
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        commit = run_git(['commit', '-m', f'Kártyák frissítése — {stamp}'])
        if commit.returncode != 0:
            output = (commit.stdout + commit.stderr).lower()
            if 'nothing to commit' in output or 'nincs mit' in output:
                self.done.emit('Nincs új változás.', STATUS_NEUTRAL or '', '')
                return
            self.done.emit('Commit sikertelen.', STATUS_ERROR, (commit.stderr or commit.stdout).strip())
            return

        # 4. Push
        push = run_git(['push'])
        if push.returncode != 0:
            self.done.emit('Push sikertelen.', STATUS_ERROR,
                           'Nem sikerült feltölteni:\n\n'
                           + (push.stderr or push.stdout).strip()
                           + "\n\nHa hitelesítési hibát látsz, futtass egy 'git push' parancsot "
                             'kézzel a mappában, és jelentkezz be egyszer.')
            return

        self.done.emit(f'Feltöltve — {stamp}', STATUS_OK, '')


# --- Főablak ---------------------------------------------------------------

class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('SharePoint AI Kártya Kezelő')
        self.resize(1100, 800)

        self.data = self.load_data()
        self.original_image_path = None
        self.push_worker = None

        # Több gyors változtatást (pl. húzogatás) egy commitba fogunk össze
        self.push_timer = QTimer(self)
        self.push_timer.setSingleShot(True)
        self.push_timer.timeout.connect(self.start_push)

        self.build_ui()
        self.refresh_tree()

    # --- Adatkezelés -------------------------------------------------------

    def load_data(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
        return {
            'altalanos': {'largeCards': [], 'smallCards': []},
            'copilot': {'largeCards': [], 'smallCards': []},
        }

    def save_data(self):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)

        self.schedule_push()

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

        # Űrlap
        form_box = QGroupBox('Kártya Szerkesztése / Hozzáadása')
        form_layout = QGridLayout(form_box)

        self.section_combo = QComboBox()
        self.section_combo.addItems(SECTIONS)
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

        self.is_new_cb = QCheckBox("Új kártya (megjelenik rajta az 'ÚJ' plecsni)")
        form_layout.addWidget(self.is_new_cb, 5, 1, 1, 3)

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

        for section in SECTIONS:
            for ctype in CARD_TYPES:
                cards = self.data.get(section, {}).get(ctype, [])

                group = QTreeWidgetItem(self.tree, [f'{section}  ›  {ctype}'])
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
                    item = QTreeWidgetItem(group, [
                        card.get('title', ''),
                        card.get('level', ''),
                        'Igen' if card.get('isNew') else 'Nem',
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
            self.data[section][ctype] = [
                group.child(j).data(0, ROLE) for j in range(group.childCount())
            ]

        self.save_data()

    def nudge_selected(self, delta):
        path = self.selected_path()
        if not path:
            return

        section, ctype, index = path
        cards = self.data[section][ctype]
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
        card = self.data[section][ctype][index]
        self.original_image_path = None

        self.section_combo.setCurrentText(section)
        self.type_combo.setCurrentText(ctype)
        self.level_combo.setCurrentText(card.get('level', 'kezdo'))
        self.title_edit.setText(card.get('title', ''))
        self.img_edit.setText(os.path.basename(card.get('img', '')))
        self.link_edit.setText(card.get('link', '#'))
        self.is_new_cb.setChecked(bool(card.get('isNew')))

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
        self.is_new_cb.setChecked(False)
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

        return {
            'title': title,
            'link': link,
            'img': f'img/{img_name}',
            'level': self.level_combo.currentText(),
            'isNew': self.is_new_cb.isChecked(),
        }

    # --- CRUD --------------------------------------------------------------

    def add_card(self):
        new_card = self.get_form_data()
        if not new_card:
            return

        section = self.section_combo.currentText()
        ctype = self.type_combo.currentText()
        self.data[section][ctype].append(new_card)

        self.save_data()
        self.refresh_tree()
        self.clear_form()
        QMessageBox.information(self, 'Siker', 'Kártya hozzáadva!')

    def update_card(self):
        path = self.selected_path()
        if not path:
            return

        updated_card = self.get_form_data()
        if not updated_card:
            return

        old_section, old_ctype, index = path
        new_section = self.section_combo.currentText()
        new_ctype = self.type_combo.currentText()

        if (old_section, old_ctype) == (new_section, new_ctype):
            # Helyben cseréljük, hogy ne kerüljön a lista végére
            self.data[old_section][old_ctype][index] = updated_card
            target = (old_section, old_ctype, index)
        else:
            self.data[old_section][old_ctype].pop(index)
            self.data[new_section][new_ctype].append(updated_card)
            target = (new_section, new_ctype, len(self.data[new_section][new_ctype]) - 1)

        self.save_data()
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
        self.data[section][ctype].pop(index)
        self.save_data()
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
        self.set_git_status('Feltöltés folyamatban...')

        self.push_worker = GitPushWorker()
        self.push_worker.done.connect(self.on_push_done)
        self.push_worker.start()

    def on_push_done(self, status, color, error_detail):
        self.set_git_status(status, color or STATUS_NEUTRAL)
        self.push_btn.setEnabled(True)

        if error_detail:
            QMessageBox.critical(self, 'GitHub hiba', error_detail)

    def closeEvent(self, event):
        """Kilépés előtt még feltöltjük, ami a késleltetés miatt bent ragadt."""
        if self.push_timer.isActive():
            self.push_timer.stop()
            if self.push_worker is None or not self.push_worker.isRunning():
                self.push_worker = GitPushWorker()
                self.push_worker.start()

        if self.push_worker is not None and self.push_worker.isRunning():
            self.set_git_status('Feltöltés befejezése...')
            self.push_worker.wait(30000)

        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec())