class ContextEngine:

    def __init__(self):

        self.current_task = None
        self.last_apps = []
        self.last_search = None
        self.session_start = None

    def set_task(self, task):

        self.current_task = task

    def add_app(self, app):
        if app not in self.last_apps:
            self.last_apps.append(app)
            if len(self.last_apps) > 20:   # cap to prevent unbounded growth
                self.last_apps = self.last_apps[-20:]

    def set_search(self, query):

        self.last_search = query

    def get_context(self):

        return {
            "task": self.current_task,
            "apps": self.last_apps,
            "search": self.last_search
        }