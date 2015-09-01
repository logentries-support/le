import threading
import sys


class StoppableAsyncTask(threading.Thread):
    def __init__(self, fn=None, *args):
        threading.Thread.__init__(self)
        self.daemon = True
        self.stop_event = threading.Event()

        if sys.version_info < (2, 6):
            self.need_to_stop_signal = self.stop_event.isSet
        else:
            self.need_to_stop_signal = self.stop_event.is_set

        self.fn = fn
        self.args = args

    def run(self):
        while not self.need_to_stop_signal():
            self.fn(*self.args)

    def stop(self):
        self.stop_event.set()

    def join(self, timeout=None):
        self.stop_event.set()
        threading.Thread.join(self, timeout)

    def is_stopped(self):
        return self.need_to_stop_signal()
