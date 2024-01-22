import os
import shelve


class DirectoryModel:
    """Класс модели."""
    def __init__(self):
        self.directory_paths = ["", "", ""]
        self.run_directory = ""
        self.checkbox_state = [False, False]
        self.load_all_params()

    def set_directory(self, directory: str, index: int):
        self.directory_paths[index] = directory

    def set_run_directory(self):      
        self.run_directory = os.path.join(self.directory_paths[1], 
                                          self.directory_paths[2])

    def set_checkbox_state(self, state: bool, index: int):
        self.checkbox_state[index] = state
    
    def get_directory(self, index: int):
        return self.directory_paths[index]
    
    def get_run_directory(self):
        return self.run_directory

    def get_checkbox_state(self, index: int):
        return self.checkbox_state[index]

    def save_all_params(self):
        """Сохраняет состояние и директорию при выходе из программы."""
        shel_file = shelve.open("dataFile")
        shel_file["directory_paths"] = self.directory_paths
        shel_file["run_directory"] = self.run_directory
        shel_file["checkbox_state"] = self.checkbox_state
        shel_file.close()
    
    def load_all_params(self):
        """Загружает сосотояние и директорию при включении программы."""
        try:
            shel_file = shelve.open("dataFile")
            self.directory_paths = shel_file["directory_paths"]
            self.run_directory = shel_file["run_directory"]
            self.checkbox_state = shel_file["checkbox_state"]
            shel_file.close()
        except Exception as e:
            self.progress_text = "Файлы сохранения отсутствуют..."   
