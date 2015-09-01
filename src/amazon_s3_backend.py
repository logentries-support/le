from utils import *
from s3_archiving_backend import *
from s3_comm_wrapper import *

LOG_LE_AGENT = 'logentries.com'
log = logging.getLogger(LOG_LE_AGENT)

class AmazonS3Backend:

    def __init__(self, local_config, general_config):

        self.local_config = local_config
        self.general_config = general_config

        self.enabled = self.general_config.use_config_log_paths
        self.no_s3_sending_avail = False

        self.s3_comm = None
        self.s3_archiving_backend = None

        if self.enabled:
            self.s3_comm = AmazonS3ConnectionWrapper(self.local_config, self.general_config)
            self.no_s3_sending_avail = not self.s3_comm.is_enabled
            if self.no_s3_sending_avail:
                log.info('Archives sending to S3 is not available.')

            self.s3_archiving_backend = AmazonS3ArchivingBackend()
            self.s3_archiving_backend.s3_sending_callback = self.add_to_s3_sending_queue

