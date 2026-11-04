class Component:
    def __init__(self, app):
        self.app = app

    @property
    def cfg(self):
        return self.app.cfg

    @property
    def state(self):
        return self.app.state

    @property
    def messages(self):
        return self.app.messages

    @property
    def memory(self):
        return self.app.memory

    @property
    def llm(self):
        return self.app.llm

    @property
    def me(self):
        return self.app.user
