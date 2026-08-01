class ImmediateExecutor:
    def __init__(self):
        self.healthy = True
        self.reset_count = 0

    async def run_safe(self, func, *args, timeout=None, **kwargs):
        return func(*args, **kwargs)

    def reset(self):
        self.healthy = True
        self.reset_count += 1


class FakeApplication:
    def __init__(self):
        self.alive = True
        self.busy = False
        self.has_license = True
        self.quit_called = False

    def is_alive(self):
        return self.alive

    def is_busy(self):
        return self.busy

    def licensed(self):
        return self.has_license

    def quit(self):
        self.quit_called = True
        self.alive = False


class FakeLegacyAutomation:
    def __init__(self, app=None):
        self.app = app or FakeApplication()
        self.launch_kwargs = None

    def launch_pscad(self, **kwargs):
        self.launch_kwargs = kwargs
        return self.app


class FakeModernPscad:
    def __init__(self, app=None, versions=None):
        self.app = app or FakeApplication()
        self.installations = versions or [("5.0.2", True)]
        self.launch_kwargs = None

    def versions(self):
        return self.installations

    def connect(self):
        raise ProcessLookupError("no running automation instance")

    def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        return self.app
