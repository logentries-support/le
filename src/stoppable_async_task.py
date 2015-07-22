import threading


class StoppableAsyncTask(threading.Thread):
    def __init__(self, fn=None, *args):
        threading.Thread.__init__(self)
        self.daemon = True
        self.stop_event = threading.Event()
        self.fn = fn
        self.args = args

    def run(self):
        while not self.stop_event.is_set():
            self.fn(*self.args)

    def stop(self):
        self.stop_event.set()

    def join(self, timeout=None):
        self.stop_event.set()
        threading.Thread.join(self, timeout)

    def is_stopped(self):
        return self.stop_event.is_set()
