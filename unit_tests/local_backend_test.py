import unittest
import os
from src.s3_archiving_backend import *
import random
from time import sleep
import socket
import threading
from src.utils import TimeUtils
from os import walk
import gzip

DEFAULT_LOGS_DIRECTORY = '/tmp/Logentries/Agent/S3/'  # Set it the one that is used by the backend to store temp logs
ARCHIVING_BACKEND_LOCAL_LOG_NAME_TEMPLATE = 'amazon_3_%s_%s_%s'

random.seed(None)  # Use current system time as a random seed
host_name = socket.getfqdn().split('.')[0]  # Host name - used as a part of log's name

LOG_LE_AGENT = 'logentries.com'
log = logging.getLogger(LOG_LE_AGENT)
if not log:
    report("Cannot open log output")
    sys.exit(-1)

log.setLevel(logging.INFO)

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)
stream_handler.setFormatter(logging.Formatter("%(message)s"))
log.addHandler(stream_handler)


if not os.path.exists(DEFAULT_LOGS_DIRECTORY):
    os.makedirs(DEFAULT_LOGS_DIRECTORY)

# Miscellaneous functions to provide necessary support for testing

def check_file_exists(path):
    return os.path.exists(path) and os.path.isfile(path)


def generate_temp_log_full_path(base_directory, log_name, token):
    return base_directory + (ARCHIVING_BACKEND_LOCAL_LOG_NAME_TEMPLATE % (host_name, token, log_name))


def generate_message(i, predef_time=None):
    if predef_time is None:
        time_str = str(TimeUtils.get_current_time_as_timestamp_as_ms())
    else:
        time_str = predef_time
    return time_str + ' - Message - ' + str(i) + ' - ' + str(random.random()) + '\n'


def generate_huge_message(char='A', size=512000):
    return TimeUtils.get_utc_time_str() + ' - ' + char * size


def check_saved_log(reference_msg_list, log_to_check, token):
    try:
        log_full_path = generate_temp_log_full_path(DEFAULT_LOGS_DIRECTORY, log_to_check, token)
        with open(log_full_path, 'rb') as fd:
            log_data = fd.read().split('\n')
        log_data.remove('')  # Remove last empty element that left after data splitting.
        if len(reference_msg_list) != len(log_data):
            raise IndexError
        for i in range(0, len(log_data)):
            # We need to add \n to the end, because it is removed by split()
            if reference_msg_list[i] != log_data[i] + '\n':
                return False
        return True
    except IndexError:
        log.error('Arrays sizes do not match each other!')
        return False
    except Exception as e:
        log.error(e.message)
        return False


def contains_same_timestamps(file1, file2):
    with open(file1, 'rb') as fd1:
        data1 = fd1.read().split('\n')
    data1.remove('')

    with open(file2, 'rb') as fd2:
        data2 = fd2.read().split('\n')
    data2.remove('')

    cmp = lambda x1, x2: len(x1) if len(x1) <= len(x2) else len(x2)

    for i in range(0, cmp(data1, data2) - 1):
        t_stamp1 = TimeUtils.get_time_from_log_msg(data1[i])  # We need UTC string from the message
        t_stamp2 = TimeUtils.get_time_from_log_msg(data2[i])  # We need UTC string from the message
        if t_stamp1 == t_stamp2:
            return True  # Files contain at least 1 entry of the same timestamp
    return False


def get_files_dirs_list_in_dir(dir):
    files = []
    dirs = []
    for (dir_path, dir_names, file_names) in walk(dir):
        files.extend(file_names)
        dirs.extend(dir_names)
        break
    return files, dirs


def remove_files(dir, files_list):
    for file in files_list:
        try:
            full_path = dir + file
            os.remove(full_path)
        except OSError as e:
            if e.strerror.find('[Error 3]') != -1:  # Not found
                log.error(e.strerror)
                raise
        except Exception as e:
            log.error(e.message)
            raise


def clean_up():
    files, dirs = get_files_dirs_list_in_dir(DEFAULT_LOGS_DIRECTORY)
    remove_files(DEFAULT_LOGS_DIRECTORY, files)
    try:
        os.rmdir(DEFAULT_LOGS_DIRECTORY)
    except:
        pass


class FakeFollower(threading.Thread):
    def __init__(self, log_name, token, backend, msg_count=100, msg='', iteration_wait_period=0.01):  # 10 ms
        threading.Thread.__init__(self)

        self.log_name = log_name
        self.token = token
        self.backend = backend

        self.msg = msg
        self.msg_count = msg_count
        self.wait_period = iteration_wait_period

        self.generated_messages = []

        self.stop_event = threading.Event()

    def run(self):
        for i in range(self.msg_count):
            if not self.msg:
                msg = generate_message(i)
            else:
                msg = self.msg + '\n'
                msg = str(i) + ' ' + msg  # For debugging purposes - visually separates message's number from date and
                                          # the rest of the message.
            self.backend.put_data_to_local_log(self.log_name, self.token, msg)
            self.generated_messages.append(msg)
            sleep(self.wait_period)

        self.stop_event.set()

    def get_stop_event(self):
        return self.stop_event


# Test cases
class TestSequenceFunctions(unittest.TestCase):
    def setUp(self):
        log.info('Setting up...')
        clean_up()

    def test_check_logs_output_dir(self):
        if not os.path.exists(DEFAULT_LOGS_DIRECTORY):
            os.makedirs(DEFAULT_LOGS_DIRECTORY)
        self.assertEqual(AmazonS3ArchivingBackend.check_or_create_local_logs_dir(), DEFAULT_LOGS_DIRECTORY)

        try:
            os.rmdir(DEFAULT_LOGS_DIRECTORY)
        except:
            pass

        self.assertEqual(AmazonS3ArchivingBackend.check_or_create_local_logs_dir(), DEFAULT_LOGS_DIRECTORY)
        dir_exists = os.path.exists(DEFAULT_LOGS_DIRECTORY) and os.path.isdir(ARCHIVING_BACKEND_BASE_DIRECTORY)
        self.assertTrue(dir_exists)

        try:
            os.rmdir(DEFAULT_LOGS_DIRECTORY)
        except:
            pass

        fake_dir_file = DEFAULT_LOGS_DIRECTORY[:-1]
        open(fake_dir_file, 'wb+').close()

        try:
            self.assertRaises(Exception, AmazonS3ArchivingBackend.check_or_create_local_logs_dir())
        except:
            pass
        finally:
            try:
                os.remove(fake_dir_file)
            except:
                pass

    def test_check_log_existence(self):
        test_log = DEFAULT_LOGS_DIRECTORY + 'Log1.log'
        try:
            if not os.path.exists(DEFAULT_LOGS_DIRECTORY):
                os.makedirs(DEFAULT_LOGS_DIRECTORY)

            open(test_log, 'wb+').close()
            self.assertTrue(AmazonS3ArchivingBackend.check_local_log_exists(test_log)['exists'])

            os.remove(test_log)

            self.assertFalse(AmazonS3ArchivingBackend.check_local_log_exists(test_log)['exists'])
        finally:
            try:
                os.remove(test_log)
            except:
                pass

    def test_with_one_follower_sequential_write(self):
        log.info('AmazonS3ArchingBackend - test_with_one_follower_sequential_write:')

        backend = AmazonS3ArchivingBackend(True, True, True)  # No rotation, no timestamps

        test_data_list1 = []
        test_data_list2 = []
        test_data_list3 = []

        for i in range(0, 100):  # Flush 100 messages to three logs sequentially.
            msg = generate_message(i)
            test_data_list1.append(msg)
            backend.put_data_to_local_log('TestLog1.log', '111111111111', msg)

            msg = generate_message(i)
            test_data_list2.append(msg)
            backend.put_data_to_local_log('TestLog2.log', '222222222222', msg)

            msg = generate_message(i)
            test_data_list3.append(msg)
            backend.put_data_to_local_log('TestLog3.log', '333333333333', msg)

        log.info('Now will wait until the backend flushes it\'s data queue to the disk.')
        try:
            while backend.data_queue:
                log.info('Backend data queue is not empty - waiting for 1 second...')
                log.info('Current data queue size is: %d ' % len(backend.data_queue))
                sleep(1)
        except KeyboardInterrupt:
            pass

        backend.shutdown()

        log.info('Comparing data saved by the backend with the reference sets...')
        self.assertTrue(check_saved_log(test_data_list1, 'TestLog1.log', '111111111111'))
        self.assertTrue(check_saved_log(test_data_list2, 'TestLog2.log', '222222222222'))
        self.assertTrue(check_saved_log(test_data_list3, 'TestLog3.log', '333333333333'))

    def test_with_three_followers(self):
        log.info('AmazonS3ArchingBackend - test_with_three_followers:')

        backend = AmazonS3ArchivingBackend(True, True, True)  # No rotation, no timestamps

        follower1 = FakeFollower('TestLog1.log', '111111111111', backend)
        follower2 = FakeFollower('TestLog2.log', '222222222222', backend)
        follower3 = FakeFollower('TestLog3.log', '333333333333', backend)

        follower1.setDaemon(True)
        follower2.setDaemon(True)
        follower3.setDaemon(True)

        follower1.start()
        follower2.start()
        follower3.start()

        follower1.get_stop_event().wait()
        follower2.get_stop_event().wait()
        follower3.get_stop_event().wait()

        log.info('Now will wait until the backend flushes it\'s data queue to the disk.')
        try:
            while backend.data_queue:
                log.info('Backend data queue is not empty - waiting for 1 second...')
                log.info('Current data queue size is: %d ' % len(backend.data_queue))
                sleep(1)
        except KeyboardInterrupt:
            pass

        backend.shutdown()

        self.assertTrue(check_saved_log(follower1.generated_messages, 'TestLog1.log', '111111111111'))
        self.assertTrue(check_saved_log(follower2.generated_messages, 'TestLog2.log', '222222222222'))
        self.assertTrue(check_saved_log(follower3.generated_messages, 'TestLog3.log', '333333333333'))

    def test_with_three_followers_stress_512K_chars(self):
        # The same as above, but with huge 512K chars messages.
        # The whole file is about 50Mb total
        log.info('AmazonS3ArchingBackend - test_with_three_followers_stress_512K_chars:')

        backend = AmazonS3ArchivingBackend(True, True, True)  # No rotation, no timestamps

        msg1 = generate_huge_message('A')
        msg2 = generate_huge_message('B')
        msg3 = generate_huge_message('C')

        follower1 = FakeFollower('TestLog1.log', '111111111111', backend, 100, msg1)
        follower2 = FakeFollower('TestLog2.log', '222222222222', backend, 100, msg2)
        follower3 = FakeFollower('TestLog3.log', '333333333333', backend, 100, msg3)

        follower1.setDaemon(True)
        follower2.setDaemon(True)
        follower3.setDaemon(True)

        follower1.start()
        follower2.start()
        follower3.start()

        follower1.get_stop_event().wait()
        follower2.get_stop_event().wait()
        follower3.get_stop_event().wait()

        log.info('Now will wait until the backend flushes it\'s data queue to the disk.')
        try:
            while backend.data_queue:
                log.info('Backend data queue is not empty - waiting for 1 second...')
                log.info('Current data queue size is: %d ' % len(backend.data_queue))
                sleep(1)
        except KeyboardInterrupt:
            pass

        backend.shutdown()

        self.assertTrue(check_saved_log(follower1.generated_messages, 'TestLog1.log', '111111111111'))
        self.assertTrue(check_saved_log(follower2.generated_messages, 'TestLog2.log', '222222222222'))
        self.assertTrue(check_saved_log(follower3.generated_messages, 'TestLog3.log', '333333333333'))

    def test_with_three_followers_stress_512K_chars_zero_delay(self):
        # 512K chars messages + zero delay between requests
        # The whole file is about 50Mb total
        log.info('AmazonS3ArchingBackend - test_with_three_followers_stress_512K_chars_zero_delay:')

        backend = AmazonS3ArchivingBackend(True, True, True)  # No rotation, no timestamps

        msg1 = generate_huge_message('A')
        msg2 = generate_huge_message('B')
        msg3 = generate_huge_message('C')

        follower1 = FakeFollower('TestLog1.log', '111111111111', backend, 100, msg1, 0)
        follower2 = FakeFollower('TestLog2.log', '222222222222', backend, 100, msg2, 0)
        follower3 = FakeFollower('TestLog3.log', '333333333333', backend, 100, msg3, 0)

        follower1.setDaemon(True)
        follower2.setDaemon(True)
        follower3.setDaemon(True)

        follower1.start()
        follower2.start()
        follower3.start()

        follower1.get_stop_event().wait()
        follower2.get_stop_event().wait()
        follower3.get_stop_event().wait()

        log.info('Now will wait until the backend flushes it\'s data queue to the disk.')
        try:
            while backend.data_queue:
                log.info('Backend data queue is not empty - waiting for 1 second...')
                log.info('Current data queue size is: %d ' % len(backend.data_queue))
                sleep(1)
        except KeyboardInterrupt:
            pass

        backend.shutdown()

        self.assertTrue(check_saved_log(follower1.generated_messages, 'TestLog1.log', '111111111111'))
        self.assertTrue(check_saved_log(follower2.generated_messages, 'TestLog2.log', '222222222222'))
        self.assertTrue(check_saved_log(follower3.generated_messages, 'TestLog3.log', '333333333333'))

    def test_with_ten_followers_stress_512K_chars_zero_delay(self):
        # 512K chars messages + zero delay between requests - 10 threads each sends 100 messages
        # The whole file is about 50Mb total
        log.info('AmazonS3ArchingBackend - test_with_ten_followers_stress_512K_chars_zero_delay:')

        backend = AmazonS3ArchivingBackend(True, True, True)  # No rotation, no timestamps

        msg1 = generate_huge_message('A')
        msg2 = generate_huge_message('B')
        msg3 = generate_huge_message('C')
        msg4 = generate_huge_message('D')
        msg5 = generate_huge_message('E')
        msg6 = generate_huge_message('F')
        msg7 = generate_huge_message('G')
        msg8 = generate_huge_message('H')
        msg9 = generate_huge_message('I')
        msg10 = generate_huge_message('J')

        follower1 = FakeFollower('TestLog1.log', '111111111111', backend, 100, msg1, 0)
        follower2 = FakeFollower('TestLog2.log', '222222222222', backend, 100, msg2, 0)
        follower3 = FakeFollower('TestLog3.log', '333333333333', backend, 100, msg3, 0)
        follower4 = FakeFollower('TestLog4.log', '444444444444', backend, 100, msg4, 0)
        follower5 = FakeFollower('TestLog5.log', '555555555555', backend, 100, msg5, 0)
        follower6 = FakeFollower('TestLog6.log', '666666666666', backend, 100, msg6, 0)
        follower7 = FakeFollower('TestLog7.log', '777777777777', backend, 100, msg7, 0)
        follower8 = FakeFollower('TestLog8.log', '888888888888', backend, 100, msg8, 0)
        follower9 = FakeFollower('TestLog9.log', '999999999999', backend, 100, msg9, 0)
        follower10 = FakeFollower('TestLog10.log', '000000000000', backend, 100, msg10, 0)

        follower1.setDaemon(True)
        follower2.setDaemon(True)
        follower3.setDaemon(True)
        follower4.setDaemon(True)
        follower5.setDaemon(True)
        follower6.setDaemon(True)
        follower7.setDaemon(True)
        follower8.setDaemon(True)
        follower9.setDaemon(True)
        follower10.setDaemon(True)

        follower1.start()
        follower2.start()
        follower3.start()
        follower4.start()
        follower5.start()
        follower6.start()
        follower7.start()
        follower8.start()
        follower9.start()
        follower10.start()

        follower1.get_stop_event().wait()
        follower2.get_stop_event().wait()
        follower3.get_stop_event().wait()
        follower4.get_stop_event().wait()
        follower5.get_stop_event().wait()
        follower6.get_stop_event().wait()
        follower7.get_stop_event().wait()
        follower8.get_stop_event().wait()
        follower9.get_stop_event().wait()
        follower10.get_stop_event().wait()

        log.info('Now will wait until the backend flushes it\'s data queue to the disk.')
        try:
            while backend.data_queue:
                log.info('Backend data queue is not empty - waiting for 1 second...')
                log.info('Current data queue size is: %d ' % len(backend.data_queue))
                sleep(1)
        except KeyboardInterrupt:
            pass

        backend.shutdown()

        self.assertTrue(check_saved_log(follower1.generated_messages, 'TestLog1.log', '111111111111'))
        self.assertTrue(check_saved_log(follower2.generated_messages, 'TestLog2.log', '222222222222'))
        self.assertTrue(check_saved_log(follower3.generated_messages, 'TestLog3.log', '333333333333'))
        self.assertTrue(check_saved_log(follower4.generated_messages, 'TestLog4.log', '444444444444'))
        self.assertTrue(check_saved_log(follower5.generated_messages, 'TestLog5.log', '555555555555'))
        self.assertTrue(check_saved_log(follower6.generated_messages, 'TestLog6.log', '666666666666'))
        self.assertTrue(check_saved_log(follower7.generated_messages, 'TestLog7.log', '777777777777'))
        self.assertTrue(check_saved_log(follower8.generated_messages, 'TestLog8.log', '888888888888'))
        self.assertTrue(check_saved_log(follower9.generated_messages, 'TestLog9.log', '999999999999'))
        self.assertTrue(check_saved_log(follower10.generated_messages, 'TestLog10.log', '000000000000'))

    def test_with_three_followers_zero_delay(self):
        log.info('AmazonS3ArchingBackend - test_with_three_followers_zero_delay:')

        backend = AmazonS3ArchivingBackend(True, True, True)  # No rotation, no timestamps

        follower1 = FakeFollower('TestLog1.log', '111111111111', backend, 100, '', 0)
        follower2 = FakeFollower('TestLog2.log', '222222222222', backend, 100, '', 0)
        follower3 = FakeFollower('TestLog3.log', '333333333333', backend, 100, '', 0)

        follower1.setDaemon(True)
        follower2.setDaemon(True)
        follower3.setDaemon(True)

        follower1.start()
        follower2.start()
        follower3.start()

        follower1.get_stop_event().wait()
        follower2.get_stop_event().wait()
        follower3.get_stop_event().wait()

        log.info('Now will wait until the backend flushes it\'s data queue to the disk.')
        try:
            while backend.data_queue:
                log.info('Backend data queue is not empty - waiting for 1 second...')
                log.info('Current data queue size is: %d ' % len(backend.data_queue))
                sleep(1)
        except KeyboardInterrupt:
            pass

        backend.shutdown()

        self.assertTrue(check_saved_log(follower1.generated_messages, 'TestLog1.log', '111111111111'))
        self.assertTrue(check_saved_log(follower2.generated_messages, 'TestLog2.log', '222222222222'))
        self.assertTrue(check_saved_log(follower3.generated_messages, 'TestLog3.log', '333333333333'))

    def test_check_rotation_conditions_by_size(self):
        log.info('AmazonS3ArchingBackend - test_check_rotation_conditions_by_size:')

        ONE_KBYTE = 1024

        # Some fake log object to test with.
        log_obj = {
            'local_log_file': '/var/log/log1.log',
            'token': '1234567890-123456-1234-1234-12345678901234',  # Log's token
            'size': 0,
            'first_msg_ts': 0}  # Amount of data written to the log file in bytes; for the new file equals zero.

        # Test with some small data size = 1024 bytes. AmazonS3ArchivingBackend.check_rotation_needed() should return
        # False here, because given size is less than the rotation threshold. Last zero is the timestamp which is
        # ignored for this test.
        self.assertFalse(AmazonS3ArchivingBackend.check_rotation_needed(log_obj, ONE_KBYTE, 0))

        # Test with large data size = 50Mb. AmazonS3ArchivingBackend.check_rotation_needed() should return
        # False here, because given size is exactly equal to the rotation threshold (rotation should occur if the size
        # is bigger then the threshold). Last zero is the timestamp which is ignored for this test.
        self.assertFalse(AmazonS3ArchivingBackend.check_rotation_needed(log_obj, LOG_FILE_MAX_SIZE, 0))  # Exactly 50 Mb

        # Test with large data size = 50Mb + 1byte. AmazonS3ArchivingBackend.check_rotation_needed() should return
        # True here, because given size is bigger than the rotation threshold (rotation should occur if the size
        # is bigger then the threshold). Last zero is the timestamp which is ignored for this test.
        self.assertTrue(
            AmazonS3ArchivingBackend.check_rotation_needed(log_obj, LOG_FILE_MAX_SIZE + 1, 0))  # 50 Mb + 1 byte

    def test_check_rotation_conditions_by_time_diff_3h(self):
        log.info('AmazonS3ArchingBackend - test_check_rotation_conditions_by_time_diff_3h:')

        log_obj = {
            'local_log_file': '/var/log/log1.log',
            'token': '1234567890-123456-1234-1234-12345678901234',  # Log's token
            'size': 0, # Amount of data written to the log file in bytes; for the new file equals zero.
            'first_msg_ts': 0}

        TIMESTAMP1 = 1419249757000  # 22 Dec 2014 - 12:02:37
        TIMESTAMP2 = 1419249757000  # 22 Dec 2014 - 12:02:37
        log_obj['first_msg_ts'] = TIMESTAMP1  # First timestamp of the log - it's the reference for timestamps comparing

        # The method should return False here, because diff. between given dates is less than 3 hours.
        self.assertFalse(AmazonS3ArchivingBackend.check_rotation_needed(log_obj, 0, TIMESTAMP2))

        TIMESTAMP1 = 1419249757000  # 22 Dec 2014 - 12:02:37
        TIMESTAMP2 = 1419260557000  # 22 Dec 2014 - 15:02:37 - 3 hours difference
        log_obj['first_msg_ts'] = TIMESTAMP1  # First timestamp of the log - it's the reference for timestamps comparing

        # The method should return True here, because diff. between given dates exactly equals to 3 hours.
        self.assertTrue(AmazonS3ArchivingBackend.check_rotation_needed(log_obj, 0, TIMESTAMP2))

    def test_check_rotation_conditions_the_same_day_detection(self):
        log.info('AmazonS3ArchingBackend - test_check_rotation_conditions_the_same_day_detection:')

        log_obj = {
            'local_log_file': '/var/log/log1.log',
            'token': '1234567890-123456-1234-1234-12345678901234',  # Log's token
            'size': 0,
            'first_msg_ts': 0}  # Amount of data written to the log file in bytes; for the new file equals zero.

        TIMESTAMP1 = 1419249757000  # 22 Dec 2014 - 12:02:37
        TIMESTAMP2 = 1419339818000  # 23 Dec 2014 - 13:03:38
        log_obj['first_msg_ts'] = TIMESTAMP1

        # Should return True here, because days for given dates differ explicitly (e.g. in "days" placeholders)
        self.assertTrue(AmazonS3ArchivingBackend.check_rotation_needed(log_obj, 0, TIMESTAMP2))

        TIMESTAMP1 = 1419638399000  # Fri, 26 Dec 2014 23:59:59 GMT
        TIMESTAMP2 = 1419638400000  # Sat, 27 Dec 2014 00:00:00 GMT - next day
        log_obj['first_msg_ts'] = TIMESTAMP1

        # Should return True here, because of new day even if "days" placeholders are equal here.
        self.assertTrue(AmazonS3ArchivingBackend.check_rotation_needed(log_obj, 0, TIMESTAMP2))

    def test_rotation_by_size(self):
        log.info('AmazonS3ArchingBackend - test_rotation_by_size:')
        backend = AmazonS3ArchivingBackend(False, False, True)    # No compressing

        msg = generate_huge_message('A')
        follower = FakeFollower('TestLog1.log', '111111111111', backend, 200, msg)  # About 100 Mb totally
        follower.setDaemon(True)
        follower.start()
        follower.get_stop_event().wait()

        log.info('Now will wait until the backend flushes it\'s data queue to the disk.')
        try:
            while backend.data_queue:
                log.info('Backend data queue is not empty - waiting for 1 second...')
                log.info('Current data queue size is: %d ' % len(backend.data_queue))
                sleep(1)
        except KeyboardInterrupt:
            pass

        backend.shutdown()

        files, dirs = get_files_dirs_list_in_dir(DEFAULT_LOGS_DIRECTORY)

        log.info('\nDirectory contents after file rotating:')
        for file in files:
            log.info(file)

        is_split = len(files) > 1  # The file during rotating has been split at least to two parts

        self.assertTrue(is_split)

        log.info('\nChecking sizes of parts... (Rotation threshold is %d bytes)' % LOG_FILE_MAX_SIZE)

        for file in files:
            path = DEFAULT_LOGS_DIRECTORY + file
            size = os.path.getsize(path)
            log.info('File %s has size %d bytes.' % (file, size))
            not_greater = size <= LOG_FILE_MAX_SIZE
            self.assertTrue(not_greater)


    def test_log_compressing(self):
        log.info('AmazonS3ArchingBackend - test_log_compressing:')

        test_pattern = 'This is a test 1234567890'
        test_file = DEFAULT_LOGS_DIRECTORY + 'Test1.log'
        archive = test_file + '.gz'
        check_str = ''

        os.mkdir(DEFAULT_LOGS_DIRECTORY)
        with open(test_file, 'wb+') as fd:
            fd.write(test_pattern)

        LogsArchiver.compress(test_file)

        open_gz_error = False
        try:
            with gzip.open(archive, 'rb') as fd:
                check_str = fd.read()
        except Exception as e:
            open_gz_error = True
            message = e.message if e.message != '' else e.strerror
            log.error('Error while opening %s: %s' % (archive, message))

        self.assertFalse(open_gz_error)
        self.assertTrue(check_str == test_pattern)

    def test_logs_rotation_compressing(self):
        log.info('AmazonS3ArchingBackend - test_logs_rotation_compressing:')
        ROTATED_LOG_REGEXP = re.compile('[0-9_]+\.log\.gz', re.IGNORECASE)

        backend = AmazonS3ArchivingBackend()

        msg1 = generate_huge_message('A')
        msg2 = generate_huge_message('B')
        msg3 = generate_huge_message('C')

        follower1 = FakeFollower('TestLog1.log', '111111111111', backend, 200, msg1, 0)
        follower2 = FakeFollower('TestLog2.log', '222222222222', backend, 200, msg2, 0)
        follower3 = FakeFollower('TestLog3.log', '333333333333', backend, 200, msg3, 0)

        follower1.setDaemon(True)
        follower2.setDaemon(True)
        follower3.setDaemon(True)

        follower1.start()
        follower2.start()
        follower3.start()

        follower1.get_stop_event().wait()
        follower2.get_stop_event().wait()
        follower3.get_stop_event().wait()

        log.info('Now will wait until the backend flushes it\'s data queue to the disk.')
        try:
            while backend.data_queue:
                log.info('Backend data queue is not empty - waiting for 1 second...')
                log.info('Current data queue size is: %d ' % len(backend.data_queue))
                sleep(1)
        except KeyboardInterrupt:
            pass

        backend.shutdown()

        files, dirs = get_files_dirs_list_in_dir(DEFAULT_LOGS_DIRECTORY)
        archives = []

        log.info('Checking for archives...')
        for file in files:
            if ROTATED_LOG_REGEXP.match(file):
                path = DEFAULT_LOGS_DIRECTORY + file
                archives.append(path)

        self.assertTrue(len(archives) > 0)

        log.info('Found archives are:')
        for archive in archives:
            log.info(archive)

    def test_compress_existing_logs(self):
        log.info('AmazonS3ArchingBackend - test_logs_rotation_compressing:')

        test_pattern = 'This is a test 1234567890'
        test_files = [DEFAULT_LOGS_DIRECTORY + '1111111111111.log',
                      DEFAULT_LOGS_DIRECTORY + '2222222222222.log',
                      DEFAULT_LOGS_DIRECTORY + '3333333333333_1.log']

        os.mkdir(DEFAULT_LOGS_DIRECTORY)

        for file in test_files:
            with open(file, 'wb+') as fd:
                fd.write(test_pattern)

        backend = AmazonS3ArchivingBackend()
        log.info('Wait 5 seconds till the backend compresses found logs...')
        sleep(5)
        backend.shutdown()

        total_err_count = 0
        log.info('Checking archives...')
        for file in test_files:
            try:
                err = False
                with gzip.open(file + '.gz', 'rb') as fd:
                    check_str = fd.read()
                if check_str != test_pattern:
                    total_err_count += 1
                    err = True
                log.info('%s - %s' % (file + '.gz', {True: 'Failure', False: 'OK'}[err]))
            except Exception as e:
                total_err_count += 1
                message = e.message if e.message != '' else e.strerror
                log.error('Error while opening %s: %s' % (file, message))

        self.assertTrue(total_err_count == 0)

    def tearDown(self):
        log.info('Finishing test sequence...\n--------------------------------------------\n')
        clean_up()


if __name__ == '__main__':
    unittest.main()