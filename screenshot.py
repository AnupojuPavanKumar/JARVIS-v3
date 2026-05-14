import sys
print('Loading...', flush=True)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

app = QApplication(sys.argv)
try:
    from ui.main_ui import JarvisUI
    ui = JarvisUI()
    ui.show()
    print('UI shown OK', flush=True)

    def capture():
        px = ui.grab()
        px.save('ui_final.png')
        print('Saved ui_final.png', flush=True)
        app.quit()

    QTimer.singleShot(2500, capture)
    app.exec()
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
