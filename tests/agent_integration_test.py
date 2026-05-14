import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent.jarvis_brain import JarvisBrain

def main():
    with open("tests/test_output.log", "w", encoding="utf-8") as f:
        f.write("Initializing JarvisBrain...\n")
        f.flush()
        
        class MockUI:
            mode = "idle"
            def set_status(self, text):
                pass
        
        brain = JarvisBrain(identity="owner", ui=MockUI())
        
        # High-complexity autonomous task
        tasks = [
            "Write a Python script in tests/complex_task/data_processor.py that generates a CSV file with 100 random rows of user data (name, email, age), then write a second script that reads this CSV, calculates the average age, runs the script, and outputs the result."
        ]
        
        f.write("\n--- JARVIS INTEGRATION TEST (HIGH COMPLEXITY) ---\n")
        f.flush()
        
        for task in tasks:
            f.write(f"\n[TASK]: {task}\n")
            f.flush()
            try:
                result = brain.process(task)
                f.write(f"[RESULT]:\n{result}\n")
            except Exception as e:
                f.write(f"[ERROR]: {e}\n")
            f.flush()
            
        f.write("\nTest complete.\n")
        f.flush()

    os._exit(0)

if __name__ == "__main__":
    main()
