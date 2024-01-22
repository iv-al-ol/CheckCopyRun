from PyQt5.QtWidgets import QWidget, QGridLayout,\
                            QLabel, QLineEdit, QPushButton,\
                            QProgressBar, QCheckBox,\
                            QStatusBar, QMainWindow, QTableWidget
from PyQt5.QtCore import pyqtSignal


class DirectoryView(QMainWindow):
    """Класс окна отображения."""
    closed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.init_ui()
        self.setWindowTitle("Check, Copy & Run")
        self.resize(480, 200)
        
    def init_ui(self):
        """Инициализирует окно."""
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.layout = QGridLayout(self.central_widget)
        
        labels = ["Копировать из:", 
                  "Копировать в:", 
                  "Запустить приложение после проверки:"]
        self.directory_inputs = []
        self.browse_buttons = []

        self.statusBar().showMessage("Выберите директории и нажмите \"Копировать\".")

        for i, label_text in enumerate(labels):
            label = QLabel(label_text)
            self.layout.addWidget(label, i * 2, 0, 1, 4)
            
            directory_input = QLineEdit()
            directory_input.setEnabled(False)
            self.layout.addWidget(directory_input, i * 2 + 1, 0, 1, 3)
            self.directory_inputs.append(directory_input)

            if i < 2:
                browse_button = QPushButton("Выбрать директорию")
            else:
                browse_button = QPushButton("Выбрать файл")
            self.layout.addWidget(browse_button, i * 2 + 1, 3)
            self.browse_buttons.append(browse_button)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.layout.addWidget(self.progress_bar, 6, 0, 1, 4)

        self.auto_check = QCheckBox("Автоматически копировать при включении")
        self.layout.addWidget(self.auto_check, 7, 0, 1, 2)

        self.auto_start = QCheckBox("Запустить приложение после копирования")
        self.layout.addWidget(self.auto_start, 7, 2, 1, 2)
        
        self.clear_button = QPushButton("Сбросить")
        self.layout.addWidget(self.clear_button, 8, 0, 1, 1)

        self.check_button = QPushButton("Копировать")
        self.layout.addWidget(self.check_button, 8, 2, 1, 1)

        self.start_button = QPushButton("Запустить приложение")
        self.start_button.setEnabled(False)
        self.layout.addWidget(self.start_button, 8, 3, 1, 1)

        self.setLayout(self.layout)
    
    def closeEvent(self, event):
        """Выдает сигнал при закрытии окна."""
        super().closeEvent(event)
        self.closed.emit()
        event.accept()
        