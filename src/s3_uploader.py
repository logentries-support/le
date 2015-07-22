import threading
import logging
from stoppable_async_task import StoppableAsyncTask

LOG_LE_AGENT = 'logentries.com'
log = logging.getLogger(LOG_LE_AGENT)

class UploadItem:
    def __init__(self, file_path, destination_path, callback_fn=None):
        self.file_path = file_path
        self.destination_path = destination_path
        self.callback_fn = callback_fn

class AmazonS3Uploader(StoppableAsyncTask):
    """
    This class is responsive for archives uploading. Uploading may be invoked by the compression thread
    or by timeout of need_to_upload event, which is 10 seconds by default. Once the log is uploaded the original
    *.log.gz file is deleted.
    """
    CHECK_PERIOD = 300  # 10 sec if not waked up earlier by the compression thread

    def __init__(self, s3_comm):
        StoppableAsyncTask.__init__(self, self._thread_func)
        self.s3_comm = s3_comm
        self.work_event = threading.Event()
        self.logs_to_send = []

    def upload_async(self, file_path, destination_path, callback_fn=None):
        upload_item = UploadItem(file_path, destination_path, callback_fn)
        self.logs_to_send.append(upload_item)
        self.work_event.set()

    def _thread_func(self):
        try:
            self.work_event.wait(AmazonS3Uploader.CHECK_PERIOD)
            self.work_event.clear()

            failed_logs = []
            while self.logs_to_send and not self.is_stopped():

                log_item = self.logs_to_send.pop()
                try:
                    destination_path = log_item.destination_path
                    file_path = log_item.file_path

                    log.info('Uploading %s...' % file_path)
                    if not self.s3_comm.upload_log_to(file_path, destination_path):
                        raise Exception('Cannot upload ' + file_path)

                    if log_item.callback_fn is not None:
                        log_item.callback_fn(file_path, destination_path)

                except Exception as e:
                    log.error(e.message)
                    if log_item not in failed_logs:
                        failed_logs.append(log_item)

            self.logs_to_send.extend(failed_logs)

        except Exception as e:
            message = e.message if e.message != '' else e.strerror
            log.error('General logs sending thread error: %s' % message)

    def stop(self):
        StoppableAsyncTask.stop(self)
        self.work_event.set()