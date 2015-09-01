import unittest
import re
from src.utils import TimeUtils

UTC_STR_PATTERN = '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z'

class TestSequenceFunctions(unittest.TestCase):

    def setUp(self):
        pass

    def test_get_utc_current_time_string(self):
        print('TimeUtils - test_get_utc_current_time_string:')
        time_str = TimeUtils.get_utc_time_str()
        pattern = re.compile(UTC_STR_PATTERN, re.IGNORECASE)
        print('Current time as UTC string: ' + time_str)
        self.assertTrue(pattern.match(time_str))

    def test_parse_time_from_msg_to_timestamp(self):
        print('TimeUtils - test_parse_time_from_msg_to_timestamp:')
        TIME = '1419266852'
        MSG = 'This is a test message: ' + TIME + '. Time is in the middle.'
        TIMESTAMP = 1419266852L
        timestamp2 = TimeUtils.get_time_from_log_msg(MSG)

        self.assertEqual(timestamp2, TIMESTAMP)

    def test_parse_time_from_msg_to_utc_string(self):
        print('TimeUtils - test_parse_time_from_msg_to_utc_string:')
        TIME = 1419266852L
        MSG = '1419266852 This is a test message'

        self.assertEqual(TimeUtils.get_time_from_log_msg(MSG), TIME)

    def test_is_the_same_day_timestamps(self):
        print('TimeUtils - test_is_the_same_day_timestamps:')
        TIMESTAMP1 = 1419242557  # 22 Dec 2014 - 10:02:37
        TIMESTAMP2 = 1419249757  # 22 Dec 2014 - 12:02:37

        self.assertTrue(TimeUtils.is_same_day(TIMESTAMP1, TIMESTAMP2))

        TIMESTAMP1 = 1419242557  # 22 Dec 2014 - 10:02:37
        TIMESTAMP2 = 1419336157  # 23 Dec 2014 - 12:02:37

        self.assertFalse(TimeUtils.is_same_day(TIMESTAMP1, TIMESTAMP2))

    def test_time_diff_timestamps(self):
        print('TimeUtils - test_time_diff_timestamps:')
        TIMESTAMP1 = 1419249757  # 22 Dec 2014 - 12:02:37
        TIMESTAMP2 = 1419249757  # 22 Dec 2014 - 12:02:37

        self.assertEqual(TimeUtils.get_diff(TIMESTAMP1, TIMESTAMP2), (0, 0, 0, 0))  # Days, hours, minutes, seconds

        TIMESTAMP1 = 1419249757  # 22 Dec 2014 - 12:02:37
        TIMESTAMP2 = 1419249758  # 22 Dec 2014 - 12:02:38

        self.assertEqual(TimeUtils.get_diff(TIMESTAMP1, TIMESTAMP2), (0, 0, 0, 1))  # Days, hours, minutes, seconds

        TIMESTAMP1 = 1419249757  # 22 Dec 2014 - 12:02:37
        TIMESTAMP2 = 1419249818  # 22 Dec 2014 - 12:03:38

        self.assertEqual(TimeUtils.get_diff(TIMESTAMP1, TIMESTAMP2), (0, 0, 1, 1))  # Days, hours, minutes, seconds

        TIMESTAMP1 = 1419249757  # 22 Dec 2014 - 12:02:37
        TIMESTAMP2 = 1419253418  # 22 Dec 2014 - 13:03:38

        self.assertEqual(TimeUtils.get_diff(TIMESTAMP1, TIMESTAMP2), (0, 1, 1, 1))  # Days, hours, minutes, seconds

        TIMESTAMP1 = 1419249757  # 22 Dec 2014 - 12:02:37
        TIMESTAMP2 = 1419339818  # 23 Dec 2014 - 13:03:38

        self.assertEqual(TimeUtils.get_diff(TIMESTAMP1, TIMESTAMP2), (1, 1, 1, 1))  # Days, hours, minutes, seconds

        TIMESTAMP1 = 1419249757  # Mon, 22 Dec 2014 12:02:37 GMT
        TIMESTAMP2 = 1419249697  # Mon, 22 Dec 2014 12:01:37 GMT

        self.assertEqual(TimeUtils.get_diff(TIMESTAMP1, TIMESTAMP2), (-1, 23, 59, 0)) # Days, hours, minutes, seconds

    def tearDown(self):
        pass

if __name__ == '__main__':
    unittest.main()