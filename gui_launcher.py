import sys
import logging
import threading
from typing import Optional
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QTextEdit, QLabel, QHBoxLayout
from PySide6.QtCore import Qt, Signal, QObject, QThread
from PySide6.QtGui import QMovie ### NUEVO ###
from selenium_story_notifier import main as selenium_main, RUN_START_HOUR, RUN_END_HOUR

# ... (Las clases GuiLogger y NotifierWorker se quedan igual) ...
class GuiLogger(logging.Handler, QObject):
    log_signal = Signal(str, str)
    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)
    def emit(self, record):
        msg = self.format(record)
        self.log_signal.emit(record.levelname, msg)

class NotifierWorker(QObject):
    finished = Signal()
    update_gui_signal = Signal(dict)
    def __init__(self, stop_flag: threading.Event):
        super().__init__()
        self.stop_flag = stop_flag
    def run_notifier(self):
        try:
            selenium_main(stop_flag=self.stop_flag, update_gui_callback=self.update_gui)
        finally:
            self.finished.emit()
    def update_gui(self, **kwargs):
        self.update_gui_signal.emit(kwargs)


class NotifierGUI(QWidget):
    thread: Optional[QThread] = None
    worker: Optional[NotifierWorker] = None

    def __init__(self):
        super().__init__()

        self.THEMES = {
            "nebula": """
                /* --- TEMA: NEBULOSA PÚRPURA --- */
                QWidget { background-color: #1c1a2e; color: #e0e0ff; font-family: Segoe UI, Calibri, sans-serif; font-size: 14px; }
                #TitleLabel { font-size: 28px; font-weight: bold; color: #9f70e0; padding-bottom: 10px; }
                #IndicatorLabel { font-size: 11px; color: #a0a0c0; text-transform: uppercase; padding-top: 5px; }
                #IndicatorValue { font-size: 16px; font-weight: bold; color: #e0e0ff; background-color: #2a2840; border: 1px solid #3a3858; border-radius: 4px; padding: 8px; }
                QTextEdit { background-color: #121020; border: 1px solid #3a3858; padding: 5px; font-family: Consolas, Courier New, monospace; }
                QPushButton { background-color: #9f70e0; color: #ffffff; border: none; padding: 8px 16px; border-radius: 5px; font-weight: bold; }
                QPushButton:hover { background-color: #b080f0; }
                QPushButton:pressed { background-color: #8a60c8; }
                QPushButton:disabled { background-color: #4a4868; color: #80809c; }
            """,
            "souls": """
                /* --- TEMA: CENIZAS DE LOTHRIC --- */
                QWidget { background-color: #1a1a1a; color: #d1d1d1; font-family: Garamond, Georgia, serif; font-size: 15px; }
                #TitleLabel { font-size: 28px; font-weight: bold; color: #b99767; padding-bottom: 10px; }
                #IndicatorLabel { font-size: 11px; color: #8c8c8c; text-transform: uppercase; padding-top: 5px; }
                #IndicatorValue { font-size: 16px; font-weight: bold; color: #d1d1d1; background-color: #2f2f2f; border: 1px solid #4a4a4a; border-radius: 2px; padding: 8px; }
                QTextEdit { background-color: #0f0f0f; border: 1px solid #4a4a4a; padding: 5px; font-family: Consolas, Courier New, monospace; }
                QPushButton { background-color: #2f2f2f; color: #b99767; border: 1px solid #b99767; padding: 8px 16px; border-radius: 2px; font-weight: bold; }
                QPushButton:hover { background-color: #3f3f3f; color: #d4b27f; border-color: #d4b27f; }
                QPushButton:pressed { background-color: #2a2a2a; }
                QPushButton:disabled { background-color: #3f3f3f; color: #6e6e6e; border: 1px solid #3f3f3f; }
            """
        }

        self.setWindowTitle("Alma Story Notifier")
        self.setMinimumSize(800, 600)

        # Guardamos el nombre del tema por defecto, pero no lo aplicamos aún
        self.current_theme_name = "nebula"

        layout = QVBoxLayout()

        title_label = QLabel("Alma")
        title_label.setObjectName("TitleLabel")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        status_layout = QHBoxLayout()
        self.status_label = QLabel("Esperando en el firmamento...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.animation_label = QLabel()
        self.animation_label.setFixedSize(32, 32)
        self.animation_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        status_layout.addStretch()
        status_layout.addWidget(self.status_label)
        # Eliminamos el addStretch() que estaba aquí
        status_layout.addWidget(self.animation_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)

        # ... (El código de los indicadores se queda igual) ...
        indicators_layout = QHBoxLayout()
        indicators_layout.setSpacing(15)
        horario_container = QVBoxLayout()
        horario_label = QLabel("Horario de Ejecución")
        horario_label.setObjectName("IndicatorLabel")
        self.horario_text = QLabel(f"{RUN_START_HOUR}:00 - {RUN_END_HOUR}:00")
        self.horario_text.setObjectName("IndicatorValue")
        horario_container.addWidget(horario_label)
        horario_container.addWidget(self.horario_text)
        last_check_container = QVBoxLayout()
        last_check_label = QLabel("Última Verificación")
        last_check_label.setObjectName("IndicatorLabel")
        self.last_check_text = QLabel("N/A")
        self.last_check_text.setObjectName("IndicatorValue")
        last_check_container.addWidget(last_check_label)
        last_check_container.addWidget(self.last_check_text)
        total_viewers_container = QVBoxLayout()
        total_viewers_label = QLabel("Total de Espectadores")
        total_viewers_label.setObjectName("IndicatorLabel")
        self.total_viewers_text = QLabel("N/A")
        self.total_viewers_text.setObjectName("IndicatorValue")
        total_viewers_container.addWidget(total_viewers_label)
        total_viewers_container.addWidget(self.total_viewers_text)
        story_age_container = QVBoxLayout()
        story_age_label = QLabel("Antigüedad de Historia")
        story_age_label.setObjectName("IndicatorLabel")
        self.story_age_text = QLabel("N/A")
        self.story_age_text.setObjectName("IndicatorValue")
        story_age_container.addWidget(story_age_label)
        story_age_container.addWidget(self.story_age_text)
        indicators_layout.addLayout(horario_container)
        indicators_layout.addLayout(last_check_container)
        indicators_layout.addLayout(total_viewers_container)
        indicators_layout.addLayout(story_age_container)
        layout.addLayout(indicators_layout)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

        self.start_button = QPushButton("🚀 Iniciar Vigilia")
        self.start_button.clicked.connect(self.start_notifier)
        layout.addWidget(self.start_button)

        self.stop_button = QPushButton("⏹️ Detener Vigilia")
        self.stop_button.clicked.connect(self.stop_notifier)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)

        separator = QLabel()
        layout.addWidget(separator)
        theme_layout = QHBoxLayout()
        theme_layout.addStretch()
        theme_label = QLabel("Temas:")
        nebula_button = QPushButton("Nebulosa")
        nebula_button.clicked.connect(lambda: self.change_theme("nebula"))
        souls_button = QPushButton("Lothric")
        souls_button.clicked.connect(lambda: self.change_theme("souls"))
        theme_layout.addWidget(theme_label)
        theme_layout.addWidget(nebula_button)
        theme_layout.addWidget(souls_button)
        layout.addLayout(theme_layout)

        self.setLayout(layout)

        self.gui_logger = GuiLogger()
        self.gui_logger.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(self.gui_logger)
        logging.getLogger().setLevel(logging.INFO)
        self.gui_logger.log_signal.connect(self.append_log)

        self.stop_flag = threading.Event()

        # Se crean los objetos QMovie
# --- DESPUÉS ---
        self.movie_star = QMovie("assets/star.gif")
        self.movie_star.setScaledSize(self.animation_label.size()) # Escala al tamaño del label

        self.movie_bonfire = QMovie("assets/bonfire.gif")
        self.movie_bonfire.setScaledSize(self.animation_label.size()) # Escala al tamaño del label

        # Ahora que TODO está creado, aplicamos el tema inicial.
        self.change_theme(self.current_theme_name)

    ### NUEVO: Método para cambiar la animación activa ###
    def update_active_animation(self):
        if self.current_theme_name == "souls":
            self.animation_label.setMovie(self.movie_bonfire)
        else: # Default a nebula
            self.animation_label.setMovie(self.movie_star)

    def change_theme(self, theme_name):
        if theme_name in self.THEMES:
            self.setStyleSheet(self.THEMES[theme_name])
            self.current_theme_name = theme_name ### MODIFICADO ###
            self.update_active_animation() ### MODIFICADO ###
            logging.info(f"Tema cambiado a: {theme_name}")

    def append_log(self, level, msg):
        color = {"INFO": "#aaffaa", "WARNING": "#ffff66", "ERROR": "#ff6666"}.get(level, "#e0e0ff")
        self.log_area.append(f'<span style="color:{color}">{msg}</span>')
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())

    def update_indicators(self, data):
        self.last_check_text.setText(data.get("last_check_time", "N/A"))
        self.total_viewers_text.setText(str(data.get("total_viewers", "N/A")))
        self.story_age_text.setText(data.get("story_age", "N/A"))

    def start_notifier(self):
        logging.info("Iniciando vigilia cósmica...")
        self.status_label.setText("Observando el universo de historias...")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.animation_label.movie().start() ### MODIFICADO ###

        self.stop_flag.clear()
        self.thread = QThread()
        self.worker = NotifierWorker(self.stop_flag)
        self.worker.update_gui_signal.connect(self.update_indicators)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run_notifier)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.on_notifier_stopped)
        self.thread.start()

    def stop_notifier(self):
        logging.info("Enviando señal para detener la vigilia...")
        self.status_label.setText("Retornando de la órbita...")
        self.animation_label.movie().stop() ### MODIFICADO ###
        self.stop_flag.set()

    def on_notifier_stopped(self):
        self.status_label.setText("Esperando en el firmamento...")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.animation_label.movie().stop() ### MODIFICADO ###
        self.animation_label.clear() ### MODIFICADO ###

        self.last_check_text.setText("N/A")
        self.total_viewers_text.setText("N/A")
        self.story_age_text.setText("N/A")
        logging.info("La vigilia ha concluido.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = NotifierGUI()
    gui.show()
    sys.exit(app.exec())