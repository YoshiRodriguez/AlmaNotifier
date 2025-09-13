import sys
import logging
import threading
from typing import Optional
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QTextEdit, QLabel, QLineEdit, QHBoxLayout
from PySide6.QtCore import Qt, Signal, QObject, QThread
from selenium_story_notifier import main as selenium_main, RUN_START_HOUR, RUN_END_HOUR

# --- Log handler for GUI ---
class GuiLogger(logging.Handler, QObject):
    """
    Custom log handler that emits a signal for each log record.
    This allows us to update the GUI's log viewer from a separate thread.
    """
    log_signal = Signal(str, str)  # levelname, message

    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)

    def emit(self, record):
        msg = self.format(record)
        self.log_signal.emit(record.levelname, msg)

# --- Worker for running the Selenium script in a new thread ---
class NotifierWorker(QObject):
    """
    Worker object to run the main Selenium function.
    This allows the GUI to remain responsive while the script runs.
    """
    finished = Signal()
    update_gui_signal = Signal(dict)

    def __init__(self, stop_flag: threading.Event):
        super().__init__()
        self.stop_flag = stop_flag
        
    def run_notifier(self):
        try:
            # Pass the stop flag and the signal to the main function
            selenium_main(stop_flag=self.stop_flag, update_gui_callback=self.update_gui)
        finally:
            self.finished.emit()

    def update_gui(self, **kwargs):
        """
        New implementation of update_gui that accepts keyword arguments and
        emits a dictionary.
        """
        self.update_gui_signal.emit(kwargs)

# --- Main GUI ---
class NotifierGUI(QWidget):
    # Fix: Explicitly declare the types to resolve Pylance errors
    thread: Optional[QThread] = None
    worker: Optional[NotifierWorker] = None

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Instagram Story Notifier")
        self.setMinimumSize(800, 600)
        self.setStyleSheet("""
            QWidget { background-color: #2e2e2e; color: #ddd; font-size: 14px; }
            QPushButton { background-color: #444; color: #ddd; border: none; padding: 10px; border-radius: 5px; }
            QPushButton:hover { background-color: #555; }
            QPushButton:pressed { background-color: #333; }
            QPushButton:disabled { background-color: #222; color: #888; }
            QTextEdit { background-color: #1e1e1e; color: #ddd; border: 1px solid #555; padding: 5px; }
            QLabel { font-weight: bold; }
        """)

        layout = QVBoxLayout()
        
        self.status_label = QLabel("Whenever you're ready.")
        layout.addWidget(self.status_label)

        # --- New Indicator Boxes ---
        indicators_layout = QHBoxLayout()

        # Horario
        horario_container = QVBoxLayout()
        horario_label = QLabel("Horario de ejecución:")
        self.horario_text = QLineEdit(f"{RUN_START_HOUR}:00 - {RUN_END_HOUR}:00")
        self.horario_text.setReadOnly(True)
        horario_container.addWidget(horario_label)
        horario_container.addWidget(self.horario_text)

        # Última Verificación
        last_check_container = QVBoxLayout()
        last_check_label = QLabel("Última verificación:")
        self.last_check_text = QLineEdit("N/A")
        self.last_check_text.setReadOnly(True)
        last_check_container.addWidget(last_check_label)
        last_check_container.addWidget(self.last_check_text)

        # Total de Espectadores
        total_viewers_container = QVBoxLayout()
        total_viewers_label = QLabel("Total de espectadores:")
        self.total_viewers_text = QLineEdit("N/A")
        self.total_viewers_text.setReadOnly(True)
        total_viewers_container.addWidget(total_viewers_label)
        total_viewers_container.addWidget(self.total_viewers_text)

        # Antigüedad de la historia
        story_age_container = QVBoxLayout()
        story_age_label = QLabel("Antigüedad de la historia:")
        self.story_age_text = QLineEdit("N/A")
        self.story_age_text.setReadOnly(True)
        story_age_container.addWidget(story_age_label)
        story_age_container.addWidget(self.story_age_text)

        indicators_layout.addLayout(horario_container)
        indicators_layout.addLayout(last_check_container)
        indicators_layout.addLayout(total_viewers_container)
        indicators_layout.addLayout(story_age_container)
        
        layout.addLayout(indicators_layout)
        # --- End of New Indicator Boxes ---

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

        self.start_button = QPushButton("🚀 Start Notifier")
        self.start_button.clicked.connect(self.start_notifier)
        layout.addWidget(self.start_button)

        self.stop_button = QPushButton("⏹️ Stop Notifier")
        self.stop_button.clicked.connect(self.stop_notifier)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)

        self.setLayout(layout)

        # Logging setup
        self.gui_logger = GuiLogger()
        self.gui_logger.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(self.gui_logger)
        logging.getLogger().setLevel(logging.INFO)
        self.gui_logger.log_signal.connect(self.append_log)

        # Threading objects
        self.stop_flag = threading.Event()

    def append_log(self, level, msg):
        """Appends a color-coded log message to the QTextEdit."""
        color = {
            "INFO": "#aaffaa",
            "WARNING": "#ffff66",
            "ERROR": "#ff6666"
        }.get(level, "#ddd")
        self.log_area.append(f'<span style="color:{color}">{msg}</span>')
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())

    def update_indicators(self, data):
        """Updates the indicator boxes with the received data."""
        self.last_check_text.setText(data.get("last_check_time", "N/A"))
        self.total_viewers_text.setText(str(data.get("total_viewers", "N/A")))
        self.story_age_text.setText(data.get("story_age", "N/A"))
        
    def start_notifier(self):
        """Starts the notifier script in a new thread."""
        logging.info("Starting notifier...")
        self.status_label.setText("Running...")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        
        self.stop_flag.clear()
        
        self.thread = QThread()
        self.worker = NotifierWorker(self.stop_flag)
        
        # Connect the worker's custom signal to the GUI's update slot
        self.worker.update_gui_signal.connect(self.update_indicators)

        self.worker.moveToThread(self.thread)
        
        # Connect signals and slots
        self.thread.started.connect(self.worker.run_notifier)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.on_notifier_stopped)
        
        self.thread.start()
        
    def stop_notifier(self):
        """Sets the stop flag to signal the worker thread to exit."""
        logging.info("Sending stop signal to notifier...")
        self.stop_flag.set()

    def on_notifier_stopped(self):
        """Cleanup after the worker thread finishes."""
        self.status_label.setText("Ready.")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        
        # Reset dynamic indicators to N/A
        self.last_check_text.setText("N/A")
        self.total_viewers_text.setText("N/A")
        self.story_age_text.setText("N/A")
        
        logging.info("Notifier stopped.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = NotifierGUI()
    gui.show()
    sys.exit(app.exec())