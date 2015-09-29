import os
import logging
import sys

LOG_LE_AGENT = 'logentries.com'
log = logging.getLogger(LOG_LE_AGENT)

boto_available = True
if sys.version_info >= (2, 6):
    try:
        import boto
        from boto.s3.key import Key
        from boto.s3.connection import S3Connection
    except ImportError, e:
        log.warn('Cannot import boto package: %s. AWS S3 archiving feature will not be used. Please, install boto '
                 'package by running "pip install boto" and restart the Agent' % e.message)
        boto_available = False
else:
    version = sys.version_info
    log.warn('Cannot import boto package for the current version of Python %d.%d.%d. To use AWS S3 archiving feature '
             'you need Python interpreter at least of version 2.6. AWS S3 archiving feature will not be used.' %
             (version[0], version[1], version[2]))  # Major, minor and micro components of the current version.
    boto_available = False


# AWS S3 related logic

class AmazonS3ConnectionWrapper:
    # AWS S3 - related error messages
    aws_s3_empty_credentials_err = 'Warning: one or more items of S3 credentials are empty. AWS S3 archiving won\'t ' \
                                   'be available.'
    aws_s3_not_enabled = 'Note: Currently AWS S3 archiving is not enabled. If the Agent is currently not in local ' \
                         'configuration mode, please set --use-config-log-paths=true to enable S3 archiving. If you do ' \
                         'not have "boto" package installed, please, install it and restart the Agent.'
    aws_s3_bad_credentials = 'Error: cannot perform required operation on S3 service, maybe given credentials ' \
                             'are invalid.'
    aws_s3_misc_error = 'Error while working with S3 service. Error: %s'
    aws_s3_no_bucket = 'Error: cannot get bucket %s. Make sure that the bucket exists and given credentials are valid.'
    aws_s3_bad_permissions = 'Error: it seems that the given account is not permitted to access %s bucket.'
    aws_s3_uploading_error = 'Error while uploading %s. Original log size is %d bytes, uploaded %d bytes.'

    class S3Errors:
        S3_ACCESS_DENIED = "Access denied"
        S3_NOT_FOUND = "Not found"

    def __init__(self, general_config, print_aws_statuses=True):
        try:
            self.is_enabled = general_config.has_s3_enabled and boto_available

            self.account_id = general_config.get_s3_account_id()
            self.secret_key = general_config.get_s3_secret_key()
            self.bucket_name = general_config.get_s3_bucket_name()

            # Determines whether the module should log AWS S3 error statuses
            self.print_aws_statuses = print_aws_statuses

            self.s3_connection = None  # Connection to S3 service
            self.bucket = None  # Bucket instance

            if self.is_enabled:
                if not self.check_s3_credentials_not_empty():  # If credentials or bucket name is empty - we cannot
                    # do anything with S3.
                    log.info(AmazonS3ConnectionWrapper.aws_s3_empty_credentials_err)
                    self.is_enabled = False
            else:
                    log.info(AmazonS3ConnectionWrapper.aws_s3_not_enabled)
        except Exception, e:
            log.error(e.message)

    @staticmethod
    def decode_error(exception_object):
        """
        Gets error type from given error string.

        :param exception_object - object - an exception got from boto calls:
        :return error - str - one of constants from AmazonS3ConnectionWrapper.S3Errors class; empty str if unknown:
        """
        # Known error codes; may be expanded in future.
        error_codes = {
            403: AmazonS3ConnectionWrapper.S3Errors.S3_ACCESS_DENIED,
            404: AmazonS3ConnectionWrapper.S3Errors.S3_NOT_FOUND,
        }

        err_code = -1

        if hasattr(exception_object, 'status'):
            err_code = exception_object.status

        error = error_codes.get(err_code)
        if error is None:
            return ''  # Unknown error
        return error

    def check_s3_credentials_not_empty(self):
        """
        Checks that all required credentials and bucket name re not empty.

        :return validity - boolean:
        """
        return self.account_id and self.secret_key and self.bucket_name

    def login(self):
        """
        Logs to the specified AWS S3 account.
        Returns True if logged in successfully, otherwise returns False.

        :return login success - boolean:
        """
        if not self.is_enabled:
            return False

        if self.s3_connection:
            return True  # Already logged in

        try:
            log.info('Login to AWS S3 Service started...')
            self.s3_connection = S3Connection(self.account_id, self.secret_key)
        except boto.exception.S3ResponseError, e:
            log.info(AmazonS3ConnectionWrapper.aws_s3_misc_error % e.message)
            return False
        except Exception, e:
            log.info(AmazonS3ConnectionWrapper.aws_s3_misc_error % e.message)
            return False
        return True

    def get_bucket(self, bucket_name):
        """
        The method tries to get the bucket defined by "bucket_name".
        If succeeded - returns the bucket instance.

        :param bucket name - str - name of the bucket to be accessed:
        :return bucket instance - object - if succeeds; None otherwise.
        """
        if not self.is_enabled:
            return self.bucket  # Which is None if S3 is not enabled

        if self.bucket:
            return self.bucket  # Already have a bucket instance

        try:
            self.bucket = self.s3_connection.get_bucket(bucket_name)
        except boto.exception.S3ResponseError, e:
            if AmazonS3ConnectionWrapper.decode_error(e) == AmazonS3ConnectionWrapper.S3Errors.S3_NOT_FOUND:
                # For this case it may be that the bucket does not exist
                log.info(AmazonS3ConnectionWrapper.aws_s3_no_bucket % self.bucket_name)
            elif AmazonS3ConnectionWrapper.decode_error(e) == AmazonS3ConnectionWrapper.S3Errors.S3_ACCESS_DENIED:
                # No permissions to access this bucket?
                log.info(AmazonS3ConnectionWrapper.aws_s3_bad_permissions % self.bucket_name)
            if self.print_aws_statuses:
                log.info('Status returned by AWS S3: ' + e.message)
        except Exception, e:
            log.info(AmazonS3ConnectionWrapper.aws_s3_misc_error % e.message)
        return self.bucket

    def upload_log_to(self, log_full_path, dst_path):
        """
        Puts given log file to predefined bucket to the path in dst_path

        :param log_full_path - str - full path to the the log file:
        :param dst_path - str - destination path on Amazon S3:
        :return operation status - True if uploading finished successfully; False otherwise:
        """
        try:
            if not self.is_enabled:
                return False

            if not self.login():
                log.info(AmazonS3ConnectionWrapper.aws_s3_misc_error)
                return False

            log.info('Accessing bucket %s ...' % self.bucket_name)
            bucket = self.get_bucket(self.bucket_name)
            if not bucket:
                log.info('Error: no bucket instance obtained for %s.' % self.bucket_name)
                return False

            key = Key(bucket)
            log_name = os.path.basename(log_full_path)
            key.key = dst_path
            file_size = os.path.getsize(log_full_path)
            log.info('Uploading %s to %s ...' % (log_name, self.bucket_name))
            uploaded_size = key.set_contents_from_filename(log_full_path)
            if uploaded_size != file_size:
                log.info(AmazonS3ConnectionWrapper.aws_s3_uploading_error % (log_full_path, file_size, uploaded_size))
                return False
            return True
        except boto.exception.S3ResponseError, e:
            log.info(AmazonS3ConnectionWrapper.aws_s3_misc_error % e.message)
            if self.print_aws_statuses:
                log.info('Status returned by AWS S3: ' + e.message)
        except Exception, e:
            log.info(AmazonS3ConnectionWrapper.aws_s3_misc_error % e.message)
        return False


