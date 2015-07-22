import gzip
import re
import threading
import os
import logging
from stoppable_async_task import StoppableAsyncTask

LOG_LE_AGENT = 'logentries.com'
log = logging.getLogger(LOG_LE_AGENT)

ARCH_FILE_EXTENSION = '.gz'
LOCAL_ROTATED_LOG_REGEXP = re.compile('[0-9_]+\.log', re.IGNORECASE)
LOCAL_ARCHIVED_LOG_REGEXP = re.compile('[0-9_]+\.log' + ARCH_FILE_EXTENSION, re.IGNORECASE)

DEFAULT_TOKEN_IF_UNKNOWN = 'UNKNOWN_TOKEN'


class LogArchivingTask:
    def __init__(self, file_path, callback_fn):
        self.file_path = file_path
        self.callback_fn = callback_fn


class LogsArchiver(StoppableAsyncTask):
    """
    This class is responsive for log files compressing (GZip).
    """
    LOGS_CHECK_WAIT_PERIOD = 300  # 300 sec if not waked up earlier by rotate_log()

    def __init__(self):
        StoppableAsyncTask.__init__(self, self._thread_func)
        self.work_event = threading.Event()
        self.logs_to_compress = []

    @staticmethod
    def compress(file_path):
        """
        The method opens given file and compresses it. The filename is extended with '.gz' extension.
        :param file_path - str - the full path to the file to be compressed, e.g. /var/log/1234567890.log:
        :return file path to archive
        """
        src = None
        dst = None
        try:
            src = open(file_path, 'rb')
            dst = gzip.open(file_path + ARCH_FILE_EXTENSION, 'wb')
            dst.writelines(src)
            return file_path + ARCH_FILE_EXTENSION
        except Exception as e:
            log.error(e.message)
            log.error(e.message)
            raise
        finally:
            src.close()
            dst.close()

    def compress_async(self, file_path, callback_fn=None):
        """
        Compresses files asynchronously

        :param file_path: str - path to file
        :param callback_fn: function - callback function with following signature
               callback(filepath, compressed_file_path)
        :return: None
        """
        task = LogArchivingTask(file_path, callback_fn)
        self.logs_to_compress.append(task)
        self.work_event.set()
        return

    def _thread_func(self):
        try:
            self.work_event.wait(LogsArchiver.LOGS_CHECK_WAIT_PERIOD)
            self.work_event.clear()

            failed_logs = []
            while self.logs_to_compress and not self.is_stopped():

                log_item = self.logs_to_compress.pop()
                filename = log_item.file_path
                archive = filename + ARCH_FILE_EXTENSION if not filename.endswith(ARCH_FILE_EXTENSION) else filename

                try:
                    log.info('Compressing %s...' % filename)

                    compressed_file_path = ""

                    if not filename.endswith(ARCH_FILE_EXTENSION):
                        compressed_file_path = LogsArchiver.compress(filename)

                    if log_item.callback_fn is not None:
                        log_item.callback_fn(filename, compressed_file_path)

                except Exception as e:
                    msg = e.message if e.message != '' else e.strerror
                    log.error('Failed to compress %s. Error: %s' % (filename, msg))
                    if log_item not in failed_logs:
                        failed_logs.append(log_item)
                    try:
                        if os.path.exists(archive):
                            os.remove(archive)
                    except Exception as ex:
                        log.error(ex.message)

            self.logs_to_compress.extend(failed_logs)

        except Exception as e:
            message = e.message if e.message != '' else e.strerror
            log.error('General logs compressing thread error: %s' % message)

    def stop(self):
        StoppableAsyncTask.stop(self)
        self.work_event.set()