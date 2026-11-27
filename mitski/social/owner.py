from mitski.core.storage import JsonFile


class Owner:
    def __init__(self, cfg):
        self.id = int(cfg.OWNER_ID or 0)
        self.file = JsonFile(cfg.paths.data_file("owner.json"))
        self.data = {"quiet_until": 0}

    @property
    def active(self):
        return self.id != 0

    def is_owner(self, user_or_id):
        uid = getattr(user_or_id, "id", user_or_id)
        return self.active and uid == self.id

    def load(self):
        self.data.update(self.file.load())

    def save(self):
        self.file.save(self.data)
