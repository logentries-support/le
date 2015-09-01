import unittest
import os
from src.s3_comm_wrapper import *
import boto


# Test constants.
# For testing AWS S3 functionality, place your S3 credentials and bucket name here:
AWS_S3_ACCOUNT_ID = 'AKIAIKVX3UXMSOM2SSZQ'
AWS_S3_SECRET_KEY = '4E25vMihNiU8GbPLx6mOPvSmKtKynwbh8IOzBqSy'
AWS_S3_BUCKET_NAME = 'python-sdk-sample'

# The test file.
TEST_FILE_NAME = 'Sample.log'

# Some test data that within the test file will be uploaded to S3
TEST_PATTERN = 'Hello, World! This is a test. 1234567890'

TEST_TOKEN = '1b58bfbd-9f3b-4872-a995-b549c4b448ce'  # Some random token for testing purposes

class FakeGeneralConfig:
    def __init__(self):
        self.agent_key = 'TEST_MACHINE_1234567890'
        self.use_config_log_paths = True

class FakeLocalConfig:
    def __init__(self):
        self.s3_account_id = AWS_S3_ACCOUNT_ID
        self.s3_secret_key = AWS_S3_SECRET_KEY
        self.s3_bucket_name = AWS_S3_BUCKET_NAME

    def get_s3_bucket_name(self):
        return self.s3_bucket_name

    def get_s3_account_id(self):
        return self.s3_account_id

    def get_s3_secret_key(self):
        return self.s3_secret_key

class TestSequenceFunctions(unittest.TestCase):

    def setUp(self):
        print('Setting up...')

    def test_put_file_with_valid_credentials(self):
        try:
            print('AmazonS3ConnectionWrapper - test_put_file_with_valid_credentials:')
            general_config = FakeGeneralConfig()
            local_config = FakeLocalConfig()
            s3_conn = AmazonS3ConnectionWrapper(local_config, general_config)
            test_file = open(TEST_FILE_NAME, 'wb')
            test_file.write(TEST_PATTERN)
            test_file.close()
            test_file_path = os.path.abspath(TEST_FILE_NAME)
            self.assertTrue(s3_conn.put_log(TEST_TOKEN, test_file_path))
        finally:
            os.remove(test_file_path)

    def test_put_file_with_invalid_credentials(self):
        try:
            print('AmazonS3ConnectionWrapper - test_put_file_with_invalid_credentials:')
            general_config = FakeGeneralConfig()
            local_config = FakeLocalConfig()

            local_config.s3_account_id = 'SOMEFAKEIDHERE123456'
            local_config.s3_secret_key = 'SOMEFAKESECRETKEYHERE1234567890ABCDEFGHI'

            s3_conn = AmazonS3ConnectionWrapper(local_config, general_config)
            test_file = open(TEST_FILE_NAME, 'wb')
            test_file.write(TEST_PATTERN)
            test_file.close()
            test_file_path = os.path.abspath(TEST_FILE_NAME)
            self.assertFalse(s3_conn.put_log(TEST_TOKEN, test_file_path))
        finally:
            os.remove(test_file_path)

    def test_put_file_with_empty_credentials(self):
        try:
            print('AmazonS3ConnectionWrapper - test_put_file_with_empty_credentials:')
            general_config = FakeGeneralConfig()
            local_config = FakeLocalConfig()

            local_config.s3_account_id = ''
            local_config.s3_secret_key = ''

            s3_conn = AmazonS3ConnectionWrapper(local_config, general_config)
            test_file = open(TEST_FILE_NAME, 'wb')
            test_file.write(TEST_PATTERN)
            test_file.close()
            test_file_path = os.path.abspath(TEST_FILE_NAME)
            self.assertFalse(s3_conn.put_log(TEST_TOKEN, test_file_path))
        finally:
            os.remove(test_file_path)

    def test_put_file_in_non_local_mode(self):
        try:
            print('AmazonS3ConnectionWrapper - test_put_file_in_non_local_mode:')
            general_config = FakeGeneralConfig()
            general_config.use_config_log_paths = False
            local_config = FakeLocalConfig()
            s3_conn = AmazonS3ConnectionWrapper(local_config, general_config)
            test_file = open(TEST_FILE_NAME, 'wb')
            test_file.write(TEST_PATTERN)
            test_file.close()
            test_file_path = os.path.abspath(TEST_FILE_NAME)
            self.assertFalse(s3_conn.put_log(TEST_TOKEN, test_file_path))
        finally:
            os.remove(test_file_path)\


    def test_decode_not_found_err(self):
        print('AmazonS3ConnectionWrapper - test_decode_not_found_err:')
        general_config = FakeGeneralConfig()
        local_config = FakeLocalConfig()
        s3_conn = AmazonS3ConnectionWrapper(local_config, general_config)

        create_error_response = boto.exception.S3ResponseError
        create_error_response.status = 404
        create_error_response.message = 'Not Found'

        self.assertEqual(s3_conn.decode_error(create_error_response),
                         s3_conn.S3Errors.S3_NOT_FOUND)

    def test_decode_unknown_err(self):
        print('AmazonS3ConnectionWrapper - test_decode_unknown_err:')
        general_config = FakeGeneralConfig()
        local_config = FakeLocalConfig()
        s3_conn = AmazonS3ConnectionWrapper(local_config, general_config)

        create_error_response = boto.exception.S3ResponseError
        create_error_response.status = 666
        create_error_response.message = 'Access Denied'

        self.assertEqual(s3_conn.decode_error(create_error_response),
                         '')

    def test_try_to_decode_non_s3_err(self):
        print('AmazonS3ConnectionWrapper - test_try_to_decode_non_s3_err:')
        general_config = FakeGeneralConfig()
        local_config = FakeLocalConfig()
        s3_conn = AmazonS3ConnectionWrapper(local_config, general_config)

        create_error_response = Exception()

        self.assertEqual(s3_conn.decode_error(create_error_response),
                         '')

    def test_decode_access_denied(self):
        print('AmazonS3ConnectionWrapper - test_decode_access_denied:')
        general_config = FakeGeneralConfig()
        local_config = FakeLocalConfig()
        s3_conn = AmazonS3ConnectionWrapper(local_config, general_config)

        create_error_response = boto.exception.S3ResponseError
        create_error_response.status = 403
        create_error_response.message = 'Access Denied'

        self.assertEqual(s3_conn.decode_error(create_error_response),
                         s3_conn.S3Errors.S3_ACCESS_DENIED)

    def test_get_non_existent_bucket(self):
        try:
            print('AmazonS3ConnectionWrapper - test_get_non_existent_bucket:')
            general_config = FakeGeneralConfig()
            local_config = FakeLocalConfig()

            local_config.s3_bucket_name = 'somefakebucket1234'

            s3_conn = AmazonS3ConnectionWrapper(local_config, general_config)
            test_file = open(TEST_FILE_NAME, 'wb')
            test_file.write(TEST_PATTERN)
            test_file.close()
            test_file_path = os.path.abspath(TEST_FILE_NAME)
            self.assertFalse(s3_conn.put_log(TEST_TOKEN, test_file_path))
        finally:
            os.remove(test_file_path)

    def test_get_malformed_bucket_name(self):
        # Amazon bucket names cannot have upper-case characters, except for special SDK working modes
        try:
            print('AmazonS3ConnectionWrapper - test_get_malformed_bucket_name:')
            general_config = FakeGeneralConfig()
            local_config = FakeLocalConfig()

            local_config.s3_bucket_name = 'soMeFakeBuCkEt1234'

            s3_conn = AmazonS3ConnectionWrapper(local_config, general_config)
            test_file = open(TEST_FILE_NAME, 'wb')
            test_file.write(TEST_PATTERN)
            test_file.close()
            test_file_path = os.path.abspath(TEST_FILE_NAME)
            self.assertFalse(s3_conn.put_log(TEST_TOKEN, test_file_path))
        finally:
            os.remove(test_file_path)

    def test_get_empty_bucket_name(self):
        try:
            print('AmazonS3ConnectionWrapper - test_get_empty_bucket_name:')
            general_config = FakeGeneralConfig()
            local_config = FakeLocalConfig()

            local_config.s3_bucket_name = ''

            s3_conn = AmazonS3ConnectionWrapper(local_config, general_config)
            test_file = open(TEST_FILE_NAME, 'wb')
            test_file.write(TEST_PATTERN)
            test_file.close()
            test_file_path = os.path.abspath(TEST_FILE_NAME)
            self.assertFalse(s3_conn.put_log(TEST_TOKEN, test_file_path))
        finally:
            os.remove(test_file_path)

    def tearDown(self):
        print('Finishing test sequence...\n--------------------------------------------\n')

if __name__ == '__main__':
    unittest.main()