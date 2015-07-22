import socket
from collections import deque
import time
from utils import TimeUtils
from logs_archiver import *
from s3_comm_wrapper import *
from s3_uploader import *
import sys
import logging


LOG_LE_AGENT = 'logentries.com'
log = logging.getLogger(LOG_LE_AGENT)

# ------------------------------------ AmazonS3ArchivingBackend constants -------------------------------------
ARCHIVING_BACKEND_BASE_DIRECTORY = '/tmp/Logentries/Agent/S3/'
ARCHIVING_BACKEND_BASE_DIRECTORY_LEN = len(ARCHIVING_BACKEND_BASE_DIRECTORY)
ARCHIVING_BACKEND_LOCAL_LOG_NAME_TEMPLATE = 'amazon_s3_%s_%s_%s'
# Path-related constants area
DEFAULT_LOG_LOCATION = 'Logentries/Agent/%s'  # E.g. Logentries/Agent/Log_Token/some_log.log
ARCHIVING_BACKEND_MAX_DATA_QUEUE_LENGTH = 100000

# Rotation conditions
LOG_FILE_MAX_SIZE = 50 * 1024 * 1024  # 50 Mb
LOG_FILE_MAX_DATES_DISTANCE_HOURS = 3  # 3 hours
MAX_FILE_NAME_INDEX = 10  # Max. index for file rotating name generation.

DATA_QUEUE_CONSUMER_EVT_TIMEOUT = 0.2  # 200 ms

class AmazonS3ArchivingBackend:

    class DataQueueProcessingWorker(threading.Thread):
        """
        The class that is responsive for grabbing data from the data queue and placing it to
        file on local disk. Works as a separate thread trying to get new data from the queue
        once each 200 ms.
        """

        def __init__(self, data_queue, archiving_backend):
            threading.Thread.__init__(self)
            self.need_to_stop = threading.Event()
            self.data_consumer_event = threading.Event()
            self.data_queue = data_queue
            self.archiving_backend = archiving_backend
            self.counter = 0

        def run(self):
            while not self.need_to_stop.is_set():
                try:
                    self.data_consumer_event.wait(DATA_QUEUE_CONSUMER_EVT_TIMEOUT)
                    self.data_consumer_event.clear()
                except:
                    pass

                try:
                    while self.data_queue:
                        item = self.data_queue.pop()
                        try:
                            need_rotate = False
                            rotation_success = False
                            if not self.archiving_backend.no_logs_rotation:
                                log_name = item['log_name']
                                log_object = self.archiving_backend.logs_map.get(log_name)
                                if log_object is not None:
                                    new_data_chunk_size = item['size']
                                    new_timestamp = item['timestamp']

                                    # Check whether the current log object has backend timestamp; it may be None
                                    # if the file had been rotated during previous iteration while the current data
                                    # item resided in data queue. So if the file had been rotated we need to restore
                                    # backend timestamp. The same logic is for the first timestamp in the log (the
                                    # one which is parsed from log messages.
                                    first_log_timestamp = log_object['first_msg_ts']
                                    if first_log_timestamp is None:
                                        log_object['first_msg_ts'] = new_timestamp

                                    need_rotate = AmazonS3ArchivingBackend.check_rotation_needed(log_object,
                                                                                                 new_data_chunk_size,
                                                                                                 new_timestamp)
                                    if need_rotate:
                                        log.info('Rotation for %s; current data size = %d; first timestamp '
                                                 'in the file is %d' %
                                                 (log_name, log_object['size'], log_object['first_msg_ts']))
                                        self.archiving_backend.rotate_log(log_object, log_name)

                            self.archiving_backend.flush_data_to_local_log_file(item['log_name'], item['data'])

                        except Exception as e:
                            log.error('Error: cannot write data to ' +
                                      self.archiving_backend.logs_map[item['log_name']]['local_log_file'] +
                                      '. Error: ' + {True: e.message, False: e.strerror}[e.message != ''])
                except IndexError:
                    pass
                except Exception:
                    pass

        def stop(self):
            self.need_to_stop.set()

    # Local log file open modes: True - the file exists - mode 'ab' (Append Binary); False - the
    # file does not exist - mode 'wb+' (Write-Truncate Binary)
    local_log_file_open_modes = {True: 'ab', False: 'wb+'}

    def __init__(self, no_logs_rotation=False,  # This switch is used by several unit tests in local_backend_test.py
                 no_timestamps=False,  # This switch is used by several unit tests in local_backend_test.py
                 no_logs_compressing=False,  # This switch is used by several unit tests in local_backend_test.py
                 general_config=None,
                 die_on_errors=True):
        self.data_queue = deque(maxlen=ARCHIVING_BACKEND_MAX_DATA_QUEUE_LENGTH)
        self.logs_map = {}

        # Get host's name - will be used as a part of temp. logs names
        self.machine_name = socket.getfqdn().split('.')[0]

        self.local_logs_dir = ''
        self.die_on_errors = die_on_errors
        self.no_logs_rotation = no_logs_rotation
        self.no_timestamps = no_timestamps
        self.no_logs_compressing = no_logs_compressing

        self.s3_comm_wrapper = None
        self.logs_ready_to_send_s3 = []  # Contains dict{'token': TOKEN, 'filepath': FILEPATH}

        self.log_map_lock = threading.RLock()

        try:
            self.local_logs_dir = AmazonS3ArchivingBackend.check_or_create_local_logs_dir()
            if general_config is not None:
                self.s3_comm_wrapper = AmazonS3ConnectionWrapper(general_config)

        except Exception as e:
            if not self.die_on_errors:
                raise
            else:
                log.error(e.message)
                sys.exit(-1)

        self.data_queue_thread = AmazonS3ArchivingBackend.DataQueueProcessingWorker(self.data_queue, self)
        self.data_queue_thread.setDaemon(True)
        self.data_queue_thread.start()

        self.s3_sender = AmazonS3Uploader(self.s3_comm_wrapper)
        self.s3_sender.start()

        self.logs_compressor = LogsArchiver()
        self.logs_compressor.start()

        self._enumerate_existing_archives(ARCHIVING_BACKEND_BASE_DIRECTORY)
        self._enumerate_existing_logs(ARCHIVING_BACKEND_BASE_DIRECTORY, self.compress_callback)

    def shutdown(self):
        self.data_queue_thread.stop()
        self.logs_compressor.stop()
        self.s3_sender.stop()

    @staticmethod
    def generate_s3_log_location(log_path):
        """
        Generates relative path for the given log to be used during file uploading according to
        values of Agent's key, log name and log's token.
        Result will be like this one: Logentries/Agent/LOG_TOKEN_GUID/LOG_NAME.LOG

        :param log_name - str - name of the log file, without path:
        :return the path, relative to bucket's root :
        """
        return DEFAULT_LOG_LOCATION % log_path

    @staticmethod
    def check_or_create_local_logs_dir():
        """
        The method checks existence of local logs directory (where data from incoming messages will be saved). If
        it does not exist - the method tries to create it. If succeeds - returns the path to it; otherwise - raises
        the exception.

        :return path - str - path to local logs directory:
        """
        if os.path.exists(ARCHIVING_BACKEND_BASE_DIRECTORY) and os.path.isdir(ARCHIVING_BACKEND_BASE_DIRECTORY):
            return ARCHIVING_BACKEND_BASE_DIRECTORY
        else:
            if os.path.isfile(ARCHIVING_BACKEND_BASE_DIRECTORY):
                raise Exception('Cannot create the directory for S3 local logs storing.'
                                'there is a file named %s in %s' % (os.path.basename(ARCHIVING_BACKEND_BASE_DIRECTORY,
                                                                    os.path.basedir(ARCHIVING_BACKEND_BASE_DIRECTORY))))
            try:
                os.makedirs(ARCHIVING_BACKEND_BASE_DIRECTORY)
            except Exception as e:
                raise Exception('Cannot create %s. Error is: %s' % (ARCHIVING_BACKEND_BASE_DIRECTORY, e.message))
            return ARCHIVING_BACKEND_BASE_DIRECTORY

    @staticmethod
    def check_local_log_exists(full_log_path):
        """
        The method checks that the given local log file exists on disk. Returns a dictionary
        which contains full path to the given log and and a boolean-type member which indicates
        whether the file exists.

        :param full_log_path - str - full path to the log to be checked:

        :return result - dict - {'path': str - full path, 'exists': boolean - If True - the file exists}:
        """
        return {'path': full_log_path, 'exists': os.path.exists(full_log_path) and os.path.isfile(full_log_path)}

    @staticmethod
    def check_rotation_needed(log_object, data_size, new_timestamp):
        """
        The method checks whether rotation is needed for the given log object (from logs_map) according to given new
        log data chunk size and new message timestamp.

        :param log_object - object - log object from logs_map which holds log-related data, such as total written bytes:
        :param data_size - int - size of new data chunk to be written to the given log object:
        :param new_timestamp - long - timestamp of the new message which is to be saved to the given log object:

        :return need_to_rotate - boolean - if True - the given log object needs to be rotated:
        """
        try:
            if log_object['size'] + data_size > LOG_FILE_MAX_SIZE:
                return True

            prev_timestamp = log_object['first_msg_ts']
            curr_timestamp = new_timestamp

            if not TimeUtils.is_same_day(prev_timestamp, curr_timestamp):  # Use timestamps, not UTC formatted strings
                return True

            days, hours, minutes, seconds = TimeUtils.get_diff(prev_timestamp, curr_timestamp)
            if hours >= LOG_FILE_MAX_DATES_DISTANCE_HOURS:
                return True
            return False
        except Exception as e:
            log.error('Error during rotation conditions checking: %s' % e.message)
            raise

    def upload_callback(self, file_path, destination_path):
        os.remove(file_path)
        parent_path = os.path.dirname(file_path)
        if not os.listdir(parent_path):
            os.rmdir(parent_path)

    def compress_callback(self, file_path, compressed_file_path):
        if file_path:
            os.remove(file_path)

        # Need to get only last part of path - token + file name
        s3_destination = compressed_file_path[ARCHIVING_BACKEND_BASE_DIRECTORY_LEN:]
        s3_destination = self.generate_s3_log_location(s3_destination)
        self.s3_sender.upload_async(compressed_file_path, s3_destination, self.upload_callback)

    def rotate_log(self, log_object, log_name):
        """
        The method performs log rotation which consists of next operations:
        1) The method tries to get the first timestamp for the given log object (which is stored in 'first_msg_ts' field);
        2) If it is None by some reason, the method uses current timestamp with ms. precision to generate the name;
        3) If such log exists - the method tries to generate new name, expanding the old one with '_INDEX' (1,2,3,...)
        4) After new name is generated the method renames given *.log file with new generated name (e.g. 1234567890.log)
        5) After renaming the method adjusts log object's info: 1 - sets total written data size to 0; 2 - sets first
           log's timestamp to None (this is completely new file - it does not contain timestamps yet); 3 - alters last
           message timestamp field with last_data_timestamp value - it is needed by check_rotation_needed() method on
           next iteration of new message processing for this log object.
        6) Pushes new name of the rotated file into LogsArchiver's queue and signalizes that the file needs to be
           compressed.

        :param log_object - dict - log object from logs_map:
        :param log_name - str - the name of currently rotated log (like 'amazon_s3_XXXXX.log'):

        :return rotation_success - boolean - signalizes whether log rotation succeeded:
        """
        old_file_name = log_object['local_log_file']
        rotation_success = False
        new_file_name = ARCHIVING_BACKEND_BASE_DIRECTORY + log_object['token'] + '/'

        if not os.path.exists(new_file_name):
            os.makedirs(new_file_name)

        # Generate new name for the rotated log from it's first backend timestamp or from the
        # current timestamp (current date-time) if it is absent by some reason, like: 212347772784.log
        if log_object['first_msg_ts'] is None:
            numeric_name_part = str(TimeUtils.get_current_time_as_timestamp_as_ms())
            new_file_name += numeric_name_part + '.log'
        else:
            numeric_name_part = str(log_object['first_msg_ts'])
            new_file_name += numeric_name_part + '.log'

        # Check whether we have any files with the name the same as we've just generated. If there are ones -
        # generate new name by adding "_N" prefix to it (N=1,2,3...)
        if os.path.exists(new_file_name):
            generated_name = ''
            for i in range(1, MAX_FILE_NAME_INDEX + 1):
                generated_name = ARCHIVING_BACKEND_BASE_DIRECTORY + log_object['token'] + '/' + numeric_name_part + '_' + str(i) + '.log'
                if not os.path.exists(generated_name):
                    break
                if i == MAX_FILE_NAME_INDEX:
                    raise Exception('Cannot generate new rotation name: all indexes from _%d to _%d '
                                    'are already used!' % (1, MAX_FILE_NAME_INDEX))
            log.info('Rotation: %s already exists, so %s name will be used for the log rotation.' %
                     (new_file_name, generated_name))
            new_file_name = generated_name

        try:
            self.log_map_lock.acquire()
            os.rename(old_file_name, new_file_name)

            log_object['size'] = 0  # Size of written data is cleared due to the file rotation.
            log_object['first_msg_ts'] = None      # The same is for the first message's timestamp.

            self.logs_map[log_name] = log_object
            rotation_success = True

            if not self.no_logs_compressing:
                self.logs_compressor.compress_async(new_file_name, self.compress_callback)

        except threading.ThreadError as e:
            log.error('Cannot acquire log map lock! Error %s' % e.message)
        except Exception as e:
            if e.message:
                msg = e.message
            else:
                msg = e.strerror  # For OSError exceptions
            log.error('Cannot rename %s to %s for log rotation. Error: %s' % (old_file_name, new_file_name, msg))
        finally:
            try:
                self.log_map_lock.release()
            except threading.ThreadError:
                pass  # Here we may try to release un-acquired lock by some reason
            return rotation_success

    def generate_temp_log_full_path(self, base_directory, log_name, token):
        """
        The method generates full path to the local log to be saved to disk + formatted name for it, which pattern
        uses host name, log's token and log's name. E.g.:
        For given "/tmp/logs", "localhost", "123456-7890-1234-1234-5678", "mail.log" the output will be:
        "/tmp/logs/amazon_s3_localhost_123456-7890-1234-1234-5678_mail.log"

        :param base_directory - str - the base directory which local logs to be saved to:
        :param log_name - str - name of the log file (usually, can be retrieved from the Follower):
        :param token - str - log's token:

        :return full log name - str - generated name for the local log and full path to it:
        """
        return base_directory + (ARCHIVING_BACKEND_LOCAL_LOG_NAME_TEMPLATE % (self.machine_name, token, log_name))

    def add_to_local_logs_map(self, log_name, token, first_msg_ts=None):
        """
        The method inserts new log item to the local logs map which is used to track current set of logs to which
        the backend saves data.

        :param log_name - str - log's file name, e.g. "mail.log", without path:
        :param token - str - log's token:
        :param first_msg_ts - long - first timestamp of the message itself. Used for rotation conditions checking.

        :return log object - dict - contains full path to the new log file + generated file name and it's token:
        """

        local_log_file = self.generate_temp_log_full_path(ARCHIVING_BACKEND_BASE_DIRECTORY, log_name, token)
        size = 0  # Current file's size in bytes

        if self.check_local_log_exists(local_log_file)['exists']:
            size = os.path.getsize(local_log_file)
            file_timestamp = AmazonS3ArchivingBackend._try_get_timestamp_from_file(local_log_file)
            if file_timestamp:
                first_msg_ts = file_timestamp

        new_object = {
            'local_log_file': local_log_file,
            'token': token,  # Log's token
            'size': size,  # Amount of data written to the log file in bytes
            # First timestamp got from the first message; used for checking rotation conditions.
            'first_msg_ts': first_msg_ts}
        self.logs_map[log_name] = new_object
        return new_object

    def remove_from_local_logs_map(self, log_name):
        """
        Removes given log object from local logs map.

        :param log_name - str - name of the log object to be removed:

        :return:
        """
        del self.logs_map[log_name]

    def put_data_to_local_log(self, log_name, token, data):
        """
        The method pushes given data (which is a string) to the data queue for given log, which is identified by
        lof_name, of the backend.

        Before placing new data to the queue the method checks if there is no such log file named by log_name
        value in the logs map; if there is no such log - creates it.

        :param log_name - str - name of the log file without the path to it (to reference it in the logs map):
        :param data - str - data to be pushed to the data queue:

        :return:
        """
        try:
            try:
                self.log_map_lock.acquire()

                if data is None:
                    return

                timestamp = TimeUtils.get_current_time_as_timestamp_as_ms()

                if self.logs_map.get(log_name) is None:  # New log - need to add it to the map
                    self.add_to_local_logs_map(log_name, token, timestamp)
                else:
                    # First message timestamp is set to None after log rotation.
                    if self.logs_map[log_name]['first_msg_ts'] is None:
                        self.logs_map[log_name]['first_msg_ts'] = timestamp
            finally:
                self.log_map_lock.release()

            if not self.no_timestamps:
                data = str(timestamp) + ' ' + data

            data_size = len(data)

            new_data_item = {'log_name': log_name, 'token': token, 'data': data, 'size': data_size,
                             'timestamp': timestamp}

            while len(self.data_queue) == self.data_queue.maxlen:
                time.sleep(0.1)

            self.data_queue.appendleft(new_data_item)

            self.data_queue_thread.data_consumer_event.set()
        except threading.ThreadError as e:
            log.error('Cannot acquire log write lock! Error %s' % e.message)
            raise
        except Exception as e:
            log.error('Cannot put the message to the data queue! Error: %s' % e.message)
            raise

    def flush_data_to_local_log_file(self, log_name, data):
        """
        Writes given data to the local log file in disk.

        :param log_name - log's name without the path to it; the path will be taken from the local logs map:
        :param data - str - the data to be written to the local log:

        :return:
        """
        log_object = self.logs_map.get(log_name)
        log_object['size'] += len(data)
        local_file = AmazonS3ArchivingBackend.check_local_log_exists(log_object['local_log_file'])
        with open(local_file['path'],
                  AmazonS3ArchivingBackend.local_log_file_open_modes[local_file['exists']]) as fd:
            fd.write(data)


    def _enumerate_existing_logs(self, logs_base_dir, callback=None):
        """
        The method returns all found *.log files in default logs storage directory and triggers need_to_compress
        event in order to compress existing *.log files.
        LOCAL_ROTATED_LOG_REGEXP reg.exp. is used to validate files names.

        :return :
        """
        files = []
        try:
            for (dir_path, dir_names, file_names) in os.walk(logs_base_dir):
                files.extend(file_names)
                break

            for file_path in files:
                if LOCAL_ROTATED_LOG_REGEXP.match(file_path):
                    path = logs_base_dir + file_path
                    self.logs_compressor.compress_async(path, callback)

        except Exception as e:
            message = e.message if e.message != '' else e.strerror
            log.error('Error while enumeration existing logs for archiving: %s' % message)

    def _enumerate_existing_archives(self, archives_base_dir):
        """
        The method returns all found *.log.gz files in all sub-directories of default logs storage directory
        and triggers compress_callback in order to upload existing archives.
        LOCAL_ARCHIVED_LOG_REGEXP reg.exp. is used to validate files names.

        :return :
        """
        try:
            for (dir_path, dir_names, file_names) in os.walk(archives_base_dir):
                for file_path in file_names:
                    if LOCAL_ARCHIVED_LOG_REGEXP.match(file_path):
                        # Logs are already compressed - just call the callback to upload them
                        self.compress_callback(None, os.path.join(dir_path, file_path))


        except Exception as e:
            message = e.message if e.message != '' else e.strerror
            log.error('Error while enumeration existing logs for archiving: %s' % message)

    @staticmethod
    def _try_get_timestamp_from_file(file_path):
        """
        The method opens given file and reads the very first timestamp from it. If succeeds - returns the timestamp as
        long or None otherwise.

        :param file_path - str - full path to the file to be parsed:
        :return timestamp - long - timestamp parsed from the file or None if failed to get one:
        """
        timestamp = None
        try:
            with open(file_path, 'r') as fd:
                head = fd.readline().split(' ')
                timestamp = long(head[0])
        except Exception as e:
            log.error('Cannot parse timestamp from ' + file_path + '. Error: ' + e.message)
        return timestamp