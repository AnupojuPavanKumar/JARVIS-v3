import os
import json


class AppScanner:

    def __init__(self):
        self.index_file = "memory/app_index.json"
        self.search_paths = self._get_platform_search_paths()
        self.app_index = {}

        os.makedirs("memory", exist_ok=True)

        if os.path.exists(self.index_file):
            self.load_index()
        else:
            self.build_index()

    @staticmethod
    def _get_platform_search_paths() -> list:
        """Return platform-appropriate application search paths."""
        import platform
        system = platform.system().lower()
        if system == "windows":
            pf   = os.environ.get("ProgramFiles",      r"C:\Program Files")
            pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
            return [pf, pf86]
        elif system == "darwin":
            return ["/Applications", "/usr/local/bin", "/opt/homebrew/bin"]
        else:  # Linux / headless
            return ["/usr/bin", "/usr/local/bin", "/opt"]

    @staticmethod
    def _is_executable(filename: str) -> bool:
        """Return True if the filename looks like an executable on the current platform."""
        import platform
        if platform.system().lower() == "windows":
            return filename.endswith(".exe")
        return not "." in filename or os.access(filename, os.X_OK)


    def build_index(self):
        print("Scanning installed applications...")

        for base_path in self.search_paths:
            for root, dirs, files in os.walk(base_path):
                for file in files:
                    if file.endswith(".exe"):
                        name = file.replace(".exe", "").lower()
                        full_path = os.path.join(root, file)

                        if name not in self.app_index:
                            self.app_index[name] = full_path

        self.save_index()
        print("App scan complete.")

    def save_index(self):
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self.app_index, f)

    def load_index(self):
        with open(self.index_file, "r", encoding="utf-8") as f:
            self.app_index = json.load(f)

    def find_app(self, query):
        query = query.lower()

        # Exact match
        if query in self.app_index:
            return self.app_index[query]

        # Partial match
        for name in self.app_index:
            if query in name:
                return self.app_index[name]

        return None