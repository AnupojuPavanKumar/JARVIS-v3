import sys
import asyncio
import os
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer
import time

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

# Simulation of a "Call Window"
class MockCallWindow(QWidget):
    def __init__(self, title="Thomas - WhatsApp Call"):
        super().__init__()
        self.setWindowTitle(title)
        self.setFixedSize(400, 200)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        
        layout = QVBoxLayout()
        label = QLabel(f"SIMULATED INCOMING CALL\n\nTitle: {title}\n\nJARVIS is watching...")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("font-size: 16px; font-weight: bold; color: green;")
        layout.addWidget(label)
        self.setLayout(layout)

async def run_logic(mock):
    print("\n[Sim] Created fake Phone Link call window.")
    
    from skills.secretary_skill import _get_incoming_call_window
    
    print("[Sim] JARVIS is checking for call windows...")
    found = False
    for i in range(10):
        win, provider = _get_incoming_call_window()
        if win:
            print(f"[SUCCESS] JARVIS Detected {provider} call!")
            found = True
            break
        time.sleep(1)
    
    if not found:
        print("[FAIL] JARVIS did not see the fake window.")
    
    if found:
        print("[Sim] Testing 'Answer' logic (Clicking green button area)...")
        from skills.secretary_skill import _answer_call
        result = _answer_call()
        print(f"[JARVIS]: {result}")

    print("[Sim] Closing simulation...")
    time.sleep(2)
    mock.close()
    QApplication.quit()

if __name__ == "__main__":
    print("=== JARVIS SECRETARY SIMULATION ===")
    app = QApplication(sys.argv)
    
    mock = MockCallWindow("Incoming Phone Link Call")
    mock.show()
    
    QTimer.singleShot(1000, lambda: asyncio.run(run_logic(mock)))
    sys.exit(app.exec())
