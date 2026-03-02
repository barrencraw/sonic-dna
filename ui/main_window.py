print("main_window.py loaded")

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QFrame, QStackedWidget
)
from PySide6.QtCore import Qt
from ui.music_panel import MusicPanel


class MainWindow(QMainWindow):
    def __init__(self, rng=None):
        super().__init__()
        self.rng = rng
        self.setWindowTitle("ToonGloom Studio – Phase 0")
        self.resize(900, 600)

        # --- Central widget & root layout ---
        central = QWidget(self)
        root_layout = QHBoxLayout(central)
        central.setLayout(root_layout)

        # --- Sidebar ---
        sidebar = QVBoxLayout()
        sidebar.setSpacing(15)

        self.music_btn = QPushButton("Music/SFX")
        self.music_btn.setMinimumHeight(40)
        self.music_btn.setMaximumWidth(140)

        sidebar.addWidget(self.music_btn)
        sidebar.addStretch()

        # Divider line between sidebar & main area
        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setFrameShadow(QFrame.Sunken)

        root_layout.addLayout(sidebar)
        root_layout.addWidget(divider)

        # --- Main area with stacked widget ---
        self.stacked = QStackedWidget()

        # Welcome page
        welcome_page = QWidget()
        welcome_layout = QVBoxLayout(welcome_page)
        welcome_label = QLabel("Click 'Music/SFX' to begin")
        welcome_label.setStyleSheet("font-size: 22px; color: #888;")
        welcome_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)

        welcome_layout.addStretch(2)
        welcome_layout.addWidget(welcome_label)
        welcome_layout.addStretch(3)

        self.stacked.addWidget(welcome_page)

        # MusicPanel page (lazy‑loaded later)
        self.music_panel = None

        root_layout.addWidget(self.stacked, 2)
        self.setCentralWidget(central)

        # --- Signals ---
        self.music_btn.clicked.connect(self.show_music_panel)

        print("MainWindow initialized")

    def show_music_panel(self):
        print("Switching to MusicPanel")
        if self.music_panel is None:
            self.music_panel = MusicPanel(rng=self.rng)
            self.stacked.addWidget(self.music_panel)
        self.stacked.setCurrentWidget(self.music_panel)
