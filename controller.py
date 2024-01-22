from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtCore import QThread, pyqtSignal
from pathlib import Path
import os
import subprocess
import shutil
import filecmp

class DirectoryController:    
    """Класс контроллера."""
    def __init__(self, model, view):
        self.model = model
        self.view = view
        self.setup_view()
        self.check_clicked()
        self.check_auto_start()
        
    def setup_view(self):
        """Настройки параметров окна."""
        for i in range(len(self.model.directory_paths)):
            self.view.directory_inputs[i].setText(self.model.directory_paths[i])
            if (i > 0) and (self.model.directory_paths[i] == ""):
                self.view.browse_buttons[i].setEnabled(False)
            if self.view.browse_buttons[1].isEnabled():
                self.view.browse_buttons[2].setEnabled(True)      
        self.view.auto_check.setChecked(self.model.checkbox_state[0])
        self.view.auto_start.setChecked(self.model.checkbox_state[1])
    
    def check_clicked(self):
        """Контролирует нажатия на элементы окна."""
        for i in range(len(self.model.directory_paths)):
            self.view.browse_buttons[i].clicked.\
                connect(lambda state, index = i: self.setup_directory(index))
                
        self.view.auto_check.clicked.connect(self.pass_checkbox_to_model)
        self.view.auto_start.clicked.connect(self.pass_checkbox_to_model)
        
        self.view.clear_button.clicked.connect(self.clear_all_params)
        self.view.check_button.clicked.connect(lambda : 
            self.start_copy_directories(self.model.directory_paths[0], 
                                        self.model.directory_paths[1]))
        self.view.start_button.clicked.connect(self.start_programm)
        self.view.closed.connect(self.model.save_all_params)

    def check_auto_start(self):
        """Запускает проверку для автоматического копирования."""
        if self.model.checkbox_state[0]:
            self.start_copy_directories(
                        self.model.directory_paths[0], 
                        self.model.directory_paths[1])
            
    def clear_all_params(self):
        """Очищает все параметры."""
        self.model.directory_paths = ["", "", ""]
        self.model.run_directory = ""
        self.model.checkbox_state = [False, False]
        self.view.start_button.setEnabled(False)
        self.view.statusBar().showMessage("Выберите директории и нажмите \"Копировать\"...")
        self.view.progress_bar.setValue(0)
        self.setup_view()
    
    def pass_checkbox_to_model(self):
        """Передает состояние чекбокса в модель."""
        self.model.checkbox_state[0] = self.view.auto_check.isChecked()
        self.model.checkbox_state[1] = self.view.auto_start.isChecked()
    
    def start_copy_directories(self, source_dir, destination_dir):
        """Запускает поток копирования файлов."""
        if (os.path.isdir(self.model.directory_paths[0]) 
            and os.path.isdir(self.model.directory_paths[1])):
            self.copy_thread = CopyThread(source_dir, destination_dir)
            self.copy_thread.update_progress.connect(self.update_progress_bar)
            self.copy_thread.finished.connect(self.copy_directories_finished)
            self.copy_thread.start()
        else:
            if (not os.path.isdir(self.model.directory_paths[0])):
                self.view.directory_inputs[0].\
                    setText("Не выбрана директория для копирования...")
            if (not os.path.isdir(self.model.directory_paths[1])):
                self.view.directory_inputs[1].\
                    setText("Не выбрана директория для копирования...")
    
    def update_progress_bar(self, value):
        """Обновляет програесс бар."""
        self.view.progress_bar.setValue(value)
        self.view.statusBar().showMessage(f"Идет процесс копирования: {value}%")

    def copy_directories_finished(self):
        """Выполняется после завершения копирования."""
        self.view.start_button.setEnabled(True)
        self.view.progress_bar.setValue(100)
        self.view.statusBar().showMessage("Копирование завершено...")
        if (self.model.checkbox_state[1]):
            self.start_programm()

    def start_programm(self):
        """Запускает программу."""
        self.model.save_all_params()
        try:
            subprocess.run(self.model.run_directory)
        except Exception:
            self.view.directory_inputs[2].\
                setText("Не выбрано запускаемое приложение...")
            self.view.statusBar().showMessage("Копирование завершено...")
            
    def is_file_in_directory(self, file_path, directory_path):
        """Проверка соответствия директории файла заданной директории."""
        file_path = Path(file_path).resolve()
        directory_path = Path(directory_path).resolve()
        return file_path.is_relative_to(directory_path)
            
    def activate_directory(self, index):
        """Устанавливает директорию и активирует выбор следующей директории."""
        directory = os.path.abspath(QFileDialog.\
                                    getExistingDirectory(self.view, 
                                                         "Выбери директорию"))
        if directory:
            self.view.directory_inputs[index].setText(directory)
            self.view.browse_buttons[index + 1].setEnabled(True)
            self.model.set_directory(directory, index)
    
    def activate_directory_exe(self, index):
        """Устанавливает запускаемую программу."""
        exe_path = self.model.directory_paths[0]
        
        file_path, _ = QFileDialog.getOpenFileName\
                        (self.view, "Выбери .exe файл для запуска", exe_path,
                            filter="Executable Files (*.exe)")
        file_path = os.path.abspath(file_path)
                    
        if self.is_file_in_directory(file_path, exe_path):
            file_path = os.path.relpath(file_path, exe_path)
            self.view.directory_inputs[index].setText(file_path)
            self.model.set_directory(file_path, index)
            self.model.set_run_directory()
        else:
            self.view.directory_inputs[index].\
                setText("Выберите файл из копируемой директории...")
        
    def setup_directory(self, index):
        """Обновляет модель данных."""
        if index == 0:
            self.activate_directory(index)
                
        elif index == 1:
            self.activate_directory(index)
        
        elif index == 2:
            self.activate_directory_exe(index)
    

class CopyThread(QThread):
    """Класс для копирования директорий в отдельном потоке."""
    update_progress = pyqtSignal(int) # Сигнал для обновления прогресса

    def __init__(self, source_dir, destination_dir):
        super().__init__()
        self.source_dir = source_dir
        self.destination_dir = destination_dir
    
    def run(self):
        folder = Path(self.source_dir)
        total_files = len(list(folder.rglob("*")))
        copied_files = 0
        
        for root, dirs, files in os.walk(self.source_dir):
            for file in files:
                source_path = os.path.join(root, file)
                destination_path = os.path.join(self.destination_dir, 
                                                os.path.relpath(source_path, 
                                                                self.source_dir))
                os.makedirs(os.path.dirname(destination_path), exist_ok = True)
                try:
                    if not filecmp.cmp(source_path, destination_path, shallow = True):
                        shutil.copy2(source_path, destination_path)
                        copied_files += 1
                except FileNotFoundError:
                    shutil.copy2(source_path, destination_path)
                    copied_files += 1
                progress_percentage = int(copied_files / total_files * 100)
                self.update_progress.emit(progress_percentage)
