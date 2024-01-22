import sys
from PyQt5.QtWidgets import QApplication
from model import DirectoryModel
from view import DirectoryView
from controller import DirectoryController


if __name__ == "__main__":
    app = QApplication(sys.argv)

    model = DirectoryModel()
    view = DirectoryView()
    controller = DirectoryController(model, view)

    view.show()
    sys.exit(app.exec_())
