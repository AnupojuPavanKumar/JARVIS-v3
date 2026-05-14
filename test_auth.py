import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from ui.auth_window import AuthWindow

class FakeID:
    def get_greeting(self): return "Hi"
    def load_profile(self): pass
    def requires_initial_setup(self): return False

w = AuthWindow(FakeID())
w.show()
print("AuthWindow shown")
from PyQt6.QtCore import QTimer
QTimer.singleShot(2000, app.quit)
sys.exit(app.exec())
