
# coding: utf-8
# vim: set ts=4 sw=4 et:

import errno
import httplib
import os
import re
import socket
import sys
from backports import match_hostname, CertificateError

import logging

import time
import datetime
import _strptime
import commands

# If we're running Python 2.4, then we may not have UUID module to import.
has_uuid_module = True
try:
    import uuid
except ImportError:
    has_uuid_module = False

__author__ = 'Logentries'

__all__ = ["EXIT_OK", "EXIT_NO", "EXIT_HELP", "EXIT_ERR", "EXIT_TERMINATED",
           "ServerHTTPSConnection", "LOG_LE_AGENT", "create_conf_dir",
           "default_cert_file", "system_cert_file", "domain_connect",
           "no_more_args", "find_hosts", "find_logs", "find_api_obj_by_key", "find_api_obj_by_name", "die",
           "rfile", 'TCP_TIMEOUT', "rm_pidfile", "set_proc_title", "uuid_parse", "report"]

# Return codes
EXIT_OK = 0
EXIT_NO = 1
EXIT_ERR = 3
EXIT_HELP = 4
EXIT_TERMINATED = 5  # Terminated by user (Ctrl+C)

LE_CERT_NAME = 'ca-certs.pem'

TCP_TIMEOUT = 10  # TCP timeout for the socket in seconds


authority_certificate_files = [  # Debian 5.x, 6.x, 7.x, Ubuntu 9.10, 10.4, 13.0
                                 "/etc/ssl/certs/ca-certificates.crt",
                                 # Fedora 12, Fedora 13, CentOS 5
                                 "/usr/share/purple/ca-certs/GeoTrust_Global_CA.pem",
                                 # Amazon AMI
                                 "/etc/pki/tls/certs/ca-bundle.crt",
]

LOG_LE_AGENT = 'logentries.com'

log = logging.getLogger(LOG_LE_AGENT)


class TimeUtils:
    UTC_STR_FORMAT = '%Y-%m-%dT%H:%M:%SZ'
    UTC_STR_PATTERN = '\d+'

    def __init__(self):
        pass

    @staticmethod
    def get_utc_time_str(timestamp=None):
        """
        The method returns current UTC formatted date-time string if "timestamp" value is not given
        (equals to None). If timestamp is not none the method returns UTC string representation
        for the given timestamp.

        :param timestamp (int) or None:

        :return current time - str - UTC formatted current time (like 2014-12-01T12:10:01Z):
        """
        return time.strftime(TimeUtils.UTC_STR_FORMAT, time.gmtime(timestamp))

    @staticmethod
    def get_current_time_as_timestamp_as_ms():
        """
        The method returns timestamp with millisecond resolution for the current time.

        :return timestamp - long:
        """
        timestamp = int(round(time.time() * 1000))
        return long(timestamp)

    @staticmethod
    def is_same_day(timestr1, timestr2):
        """
        The method checks whether given timestr1 and timestr2 are within the same day.
        timestr1 and timestr2 are timestamps.

        :param timestr1 - int - string:
        :param timestr2 - int - timestamp:

        :return is the same day - boolean - states whether given timestr1 and timestr2 are within the same day:
        """
        td1 = datetime.datetime.utcfromtimestamp(timestr1/1000)
        td2 = datetime.datetime.utcfromtimestamp(timestr2/1000)
        return td1.day == td2.day

    @staticmethod
    def get_diff(date1, date2):
        """
        The method returns the difference between given date1 and date2 as a tuple which holds these diff. parts:
        (days, hours, minutes, seconds).
        date1 and date2 may be given either as UTC-formatted strings or as timestamps.
        This can be defined by stating use_timestamps value to True or False -
        1) use_timestamps=False (default value) - date1 and date2 are UTC strings;
        2) use_timestamps=True - date1 and date2 are timestamps.

        :param date1 - str or int - UTC-formatted string or timestamp:
        :param date2 - str or int - UTC-formatted string or timestamp:
        :param use_timestamps - boolean - states whether given date1 and date2 should be threaten as timestamps:

        :return diff as (days, hours, minutes, seconds) - tuple - difference between date1 and date2:
        """
        td1 = datetime.datetime.utcfromtimestamp(date1/1000)
        td2 = datetime.datetime.utcfromtimestamp(date2/1000)
        if td2 >= td1:
            t_delta = td2 - td1
        else:
            t_delta = td1 - td2
        hours, remainder = divmod(t_delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        return t_delta.days, hours, minutes, seconds

    @staticmethod
    def get_time_from_log_msg(msg):
        """
        The method parses given string and returns either UTC-formatted string or timestamp (return type is defined
        by the value assigned to return_utc_string; if True - UTC-formatted string is returned, timestamp is returned
        otherwise). If ms_precision is set to True - the method returns "fake" millisecond-resolution timestamp
        (if return_utc_string=False) which is the same timestamp, but multiplied 1000 times; just to adjust the
        exponent of the timestamp.

        :param message - str - some string which contains UTC-formatted time:
        :param return_utc_string - boolean - if set to True - the method returns timestamp:
        :param ms_precision - boolean - if set to True - the method returns timestamp with "fake" ms. precision:

        :return UTC-formatted - str or timestamp - long:
        """
        time_tuple = re.search(TimeUtils.UTC_STR_PATTERN, msg).regs[0]
        start, end = time_tuple
        time_str = msg[start:end]
        return long(time_str)


try:
    import ssl

    wrap_socket = ssl.wrap_socket
    FEAT_SSL = True
    FEAT_SSL_CONTEXT = sys.version_info >= (2, 7, 9)
except ImportError:
    FEAT_SSL = False
    FEAT_SSL_CONTEXT = False

    def wrap_socket(sock, ca_certs=None, cert_reqs=None):
        return socket.ssl(sock)

def report(what):
    print >> sys.stderr, what

class ServerHTTPSConnection(httplib.HTTPSConnection):

    """
    A slight modification of HTTPSConnection to verify the certificate
    """

    def __init__(self, config, server, cert_file):
        self.no_ssl = config.suppress_ssl or not FEAT_SSL
        if self.no_ssl:
            httplib.HTTPSConnection.__init__(self, server)
        else:
            self.cert_file = cert_file
            if FEAT_SSL_CONTEXT:
                context = ssl.create_default_context(cafile=cert_file)
                httplib.HTTPSConnection.__init__(self, server, context=context)
            else:
                httplib.HTTPSConnection.__init__(self, server, cert_file=cert_file)

    def connect(self):
        if FEAT_SSL_CONTEXT:
            httplib.HTTPSConnection.connect(self)
        else:
            if self.no_ssl:
                return httplib.HTTPSConnection.connect(self)
            sock = create_connection(self.host, self.port)
            try:
                if self._tunnel_host:
                    self.sock = sock
                    self._tunnel()
            except AttributeError:
                pass
            self.sock = wrap_socket(
                sock, ca_certs=self.cert_file, cert_reqs=ssl.CERT_REQUIRED)
            try:
                match_hostname(self.sock.getpeercert(), self.host)
            except CertificateError, ce:
                die("Could not validate SSL certificate for {0}: {1}".format(
                    self.host, ce.message))


def default_cert_file_name(config):
    """
    Construct full file name to the default certificate file.
    """
    return config.config_dir_name + LE_CERT_NAME


def create_conf_dir(config):
    """
    Creates directory for the configuration file.
    """
    # Create logentries config
    try:
        os.makedirs(config.config_dir_name)
    except OSError, e:
        if e.errno != errno.EEXIST:
            if e.errno == errno.EACCES:
                die("You don't have permission to create logentries config file. Please run logentries agent as root.")
            die('Error: %s' % e)


def write_default_cert_file(config, authority_certificate):
    """
    Writes default certificate file in the configuration directory.
    """
    create_conf_dir(config)
    cert_filename = default_cert_file_name(config)
    f = open(cert_filename, 'wb')
    f.write(authority_certificate)
    f.close()


def default_cert_file(config):
    """
    Returns location of the default certificate file or None. It tries to write the
    certificate file if it is not there or it is outdated.
    """
    cert_filename = default_cert_file_name(config)
    try:
        # If the certificate file is not there, create it
        if not os.path.exists(cert_filename):
            write_default_cert_file(config, authority_certificate)
            return cert_filename

        # If it is there, check if it is outdated
        curr_cert = rfile(cert_filename)
        if curr_cert != authority_certificate:
            write_default_cert_file(config, authority_certificate)
    except IOError:
        # Cannot read/write certificate file, ignore
        return None
    return cert_filename


def system_cert_file():
    """
    Finds the location of our lovely site's certificate on the system or None.
    """
    for f in authority_certificate_files:
        if os.path.exists(f):
            return f
    return None


def create_connection(host, port):
    """
    A simplified version of socket.create_connection from Python 2.6.
    """
    for addr_info in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
        af, stype, proto, cn, sa = addr_info
        soc = None
        try:
            soc = socket.socket(af, stype, proto)
            soc.settimeout(TCP_TIMEOUT)
            soc.connect(sa)
            return soc
        except socket.error:
            if socket:
                soc.close()

    raise socket.error, "Cannot make connection to %s:%s" % (host, port)


def make_https_connection(config, s):
    """
    Makes HTTPS connection. Tried all available certificates.
    """
    if not config.use_ca_provided:
        # Try to connect with system certificate
        try:
            cert_file = system_cert_file()
            if cert_file:
                return ServerHTTPSConnection(config, s, cert_file)
        except socket.error:
            pass

    # Try to connect with our default certificate
    cert_file = default_cert_file(config)
    if not cert_file:
        die('Error: Cannot find suitable CA certificate.')
    return ServerHTTPSConnection(config, s, cert_file)


def domain_connect(config, domain, Domain):
    """
    Connects to the domain specified.
    """
    # Find the correct server address
    s = domain
    if Domain == Domain.API:
        if config.force_domain:
            s = config.force_domain
        elif config.force_api_host:
            s = config.force_api_host
        else:
            s = Domain.API

    # Special case for local debugging
    if config.debug_local:
        if Domain == Domain.API:
            s = Domain.API_LOCAL
        else:
            s = Domain.MAIN_LOCAL

    # Determine if to use SSL for connection
    # Never use SSL for debugging, always use SSL with main server
    use_ssl = True
    if config.debug_local:
        use_ssl = False
    elif Domain == Domain.API:
        use_ssl = not config.suppress_ssl

    # Connect to server with SSL in untrusted network
    if use_ssl:
        port = 443
    else:
        port = 80
    if config.debug_local:
        if Domain == Domain.API:
            port = 8000
        else:
            port = 8081
    s = '%s:%s' % (s, port)
    log.debug('Connecting to %s', s)

    # Pass the connection
    if use_ssl:
        return make_https_connection(config, s)
    else:
        return httplib.HTTPConnection(s)


def no_more_args(args):
    """
    Exits if there are any arguments given.
    """
    if len(args) != 0:
        die("No more than one argument is expected.")


def expr_match(expr, text):
    """
    Returns True if the text matches with expression. If the expression
    starts with / it is a regular expression.
    """
    if expr[0] == '/':
        if re.match(expr[1:], text):
            return True
    else:
        if expr[0:2] == '\/':
            return text == expr[1:]
        else:
            return text == expr
    return False


def find_hosts(expr, hosts):
    """
    Finds host name among hosts.
    """
    result = []
    for host in hosts:
        if uuid_match(expr, host['key']) or expr_match(expr, host['name']) or expr_match(expr, host['hostname']):
            result.append(host)
    return result


def log_match(expr, log_item):
    """
    Returns true if the expression given matches the log. Expression is either
    a simple word or a regular expression if it starts with '/'.

    We perform the test on UUID, log name, and file name.
    """
    return uuid_match(
        expr, log_item['key']) or expr_match(expr, log_item['name']) or expr_match(expr,
                                                                                   log_item['filename'])


def find_logs(expr, hosts):
    """
    Finds log name among hosts. The searching expresion have to parts: host
    name and logs name. Both parts are divided by :.
    """
    # Decode expression
    l = expr.find(':')
    if l != -1:
        host_expr = expr[0:l]
        log_expr = expr[l + 1:]
    else:
        host_expr = '/.*'
        log_expr = expr

    adepts = find_hosts(host_expr, hosts)
    logs = []
    for host in adepts:
        for xlog in host['logs']:
            if log_match(log_expr, xlog):
                logs.append(xlog)
    return logs


def find_api_obj_by_name(obj_list, name):
    """
    Finds object in a list by its name parameter. List of objects must conform
    to that of a log or host entity from api.
    """
    result = None
    for obj in obj_list:
        if obj['name'] == name:
            result = obj
            break
    return result


def find_api_obj_by_key(obj_list, key):
    """
    Finds object in a list by its key parameter. List of objects must conform
    to that of a log or host entity from api.
    """
    result = None
    for obj in obj_list:
        if obj['key'] == key:
            result = obj
            break
    return result


def die(cause, exit_code=EXIT_ERR):
    log.critical(cause)
    sys.exit(exit_code)


def rfile(name):
    """
    Returns content of the file, without trailing newline.
    """
    x = open(name).read()
    if len(x) != 0 and x[-1] == '\n':
        x = x[0:len(x) - 1]
    return x


def rm_pidfile(config):
    """
    Removes PID file. Called when the agent exits.
    """
    try:
        if config.pid_file:
            os.remove(config.pid_file)
    except OSError:
        pass


def set_proc_title(title):
    try:
        import setproctitle

        setproctitle.setproctitle(title)
    except ImportError:
        pass


def uuid_match(uuid, text):
    """
    Returns True if the uuid given is uuid and it matches to the text.
    """
    return is_uuid(uuid) and uuid == text


def is_uuid(x):
    """
    Returns true if the string given appears to be UUID.
    """
    return re.match(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', x)


def uuid_parse(text):
    """Returns uuid given or None in case of syntax error.
    """
    try:
        if has_uuid_module:
            return uuid.UUID(text).__str__()
        else:
            if is_uuid(text):
                return text
    except ValueError:
        return None

def generate_uuid():
    # This is kinda hack to generate an UUID even if we do not have uuid module available.
    return commands.getoutput('uuidgen')

#
# Authority certificate
#
# Used if not provided by the underlying system
#

authority_certificate = """-----BEGIN CERTIFICATE-----
MIIDIDCCAomgAwIBAgIENd70zzANBgkqhkiG9w0BAQUFADBOMQswCQYDVQQGEwJV
UzEQMA4GA1UEChMHRXF1aWZheDEtMCsGA1UECxMkRXF1aWZheCBTZWN1cmUgQ2Vy
dGlmaWNhdGUgQXV0aG9yaXR5MB4XDTk4MDgyMjE2NDE1MVoXDTE4MDgyMjE2NDE1
MVowTjELMAkGA1UEBhMCVVMxEDAOBgNVBAoTB0VxdWlmYXgxLTArBgNVBAsTJEVx
dWlmYXggU2VjdXJlIENlcnRpZmljYXRlIEF1dGhvcml0eTCBnzANBgkqhkiG9w0B
AQEFAAOBjQAwgYkCgYEAwV2xWGcIYu6gmi0fCG2RFGiYCh7+2gRvE4RiIcPRfM6f
BeC4AfBONOziipUEZKzxa1NfBbPLZ4C/QgKO/t0BCezhABRP/PvwDN1Dulsr4R+A
cJkVV5MW8Q+XarfCaCMczE1ZMKxRHjuvK9buY0V7xdlfUNLjUA86iOe/FP3gx7kC
AwEAAaOCAQkwggEFMHAGA1UdHwRpMGcwZaBjoGGkXzBdMQswCQYDVQQGEwJVUzEQ
MA4GA1UEChMHRXF1aWZheDEtMCsGA1UECxMkRXF1aWZheCBTZWN1cmUgQ2VydGlm
aWNhdGUgQXV0aG9yaXR5MQ0wCwYDVQQDEwRDUkwxMBoGA1UdEAQTMBGBDzIwMTgw
ODIyMTY0MTUxWjALBgNVHQ8EBAMCAQYwHwYDVR0jBBgwFoAUSOZo+SvSspXXR9gj
IBBPM5iQn9QwHQYDVR0OBBYEFEjmaPkr0rKV10fYIyAQTzOYkJ/UMAwGA1UdEwQF
MAMBAf8wGgYJKoZIhvZ9B0EABA0wCxsFVjMuMGMDAgbAMA0GCSqGSIb3DQEBBQUA
A4GBAFjOKer89961zgK5F7WF0bnj4JXMJTENAKaSbn+2kmOeUJXRmm/kEd5jhW6Y
7qj/WsjTVbJmcVfewCHrPSqnI0kBBIZCe/zuf6IWUrVnZ9NA2zsmWLIodz2uFHdh
1voqZiegDfqnc1zqcPGUIWVEX/r87yloqaKHee9570+sB3c4
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIIDVDCCAjygAwIBAgIDAjRWMA0GCSqGSIb3DQEBBQUAMEIxCzAJBgNVBAYTAlVT
MRYwFAYDVQQKEw1HZW9UcnVzdCBJbmMuMRswGQYDVQQDExJHZW9UcnVzdCBHbG9i
YWwgQ0EwHhcNMDIwNTIxMDQwMDAwWhcNMjIwNTIxMDQwMDAwWjBCMQswCQYDVQQG
EwJVUzEWMBQGA1UEChMNR2VvVHJ1c3QgSW5jLjEbMBkGA1UEAxMSR2VvVHJ1c3Qg
R2xvYmFsIENBMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA2swYYzD9
9BcjGlZ+W988bDjkcbd4kdS8odhM+KhDtgPpTSEHCIjaWC9mOSm9BXiLnTjoBbdq
fnGk5sRgprDvgOSJKA+eJdbtg/OtppHHmMlCGDUUna2YRpIuT8rxh0PBFpVXLVDv
iS2Aelet8u5fa9IAjbkU+BQVNdnARqN7csiRv8lVK83Qlz6cJmTM386DGXHKTubU
1XupGc1V3sjs0l44U+VcT4wt/lAjNvxm5suOpDkZALeVAjmRCw7+OC7RHQWa9k0+
bw8HHa8sHo9gOeL6NlMTOdReJivbPagUvTLrGAMoUgRx5aszPeE4uwc2hGKceeoW
MPRfwCvocWvk+QIDAQABo1MwUTAPBgNVHRMBAf8EBTADAQH/MB0GA1UdDgQWBBTA
ephojYn7qwVkDBF9qn1luMrMTjAfBgNVHSMEGDAWgBTAephojYn7qwVkDBF9qn1l
uMrMTjANBgkqhkiG9w0BAQUFAAOCAQEANeMpauUvXVSOKVCUn5kaFOSPeCpilKIn
Z57QzxpeR+nBsqTP3UEaBU6bS+5Kb1VSsyShNwrrZHYqLizz/Tt1kL/6cdjHPTfS
tQWVYrmm3ok9Nns4d0iXrKYgjy6myQzCsplFAMfOEVEiIuCl6rYVSAlk6l5PdPcF
PseKUgzbFbS9bZvlxrFUaKnjaZC2mqUPuLk/IH2uSrW4nOQdtqvmlKXBx4Ot2/Un
hw4EbNX/3aBd7YdStysVAq45pmp06drE57xNNB6pXE0zX5IJL4hmXXeXxx12E6nV
5fEWCRE11azbJHFwLJhWC9kXtNHjUStedejV0NxPNO3CBWaAocvmMw==
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIID2TCCAsGgAwIBAgIDAjbQMA0GCSqGSIb3DQEBBQUAMEIxCzAJBgNVBAYTAlVT
MRYwFAYDVQQKEw1HZW9UcnVzdCBJbmMuMRswGQYDVQQDExJHZW9UcnVzdCBHbG9i
YWwgQ0EwHhcNMTAwMjE5MjIzOTI2WhcNMjAwMjE4MjIzOTI2WjBAMQswCQYDVQQG
EwJVUzEXMBUGA1UEChMOR2VvVHJ1c3QsIEluYy4xGDAWBgNVBAMTD0dlb1RydXN0
IFNTTCBDQTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAJCzgMHk5Uat
cGA9uuUU3Z6KXot1WubKbUGlI+g5hSZ6p1V3mkihkn46HhrxJ6ujTDnMyz1Hr4Gu
FmpcN+9FQf37mpc8oEOdxt8XIdGKolbCA0mEEoE+yQpUYGa5jFTk+eb5lPHgX3UR
8im55IaisYmtph6DKWOy8FQchQt65+EuDa+kvc3nsVrXjAVaDktzKIt1XTTYdwvh
dGLicTBi2LyKBeUxY0pUiWozeKdOVSQdl+8a5BLGDzAYtDRN4dgjOyFbLTAZJQ50
96QhS6CkIMlszZhWwPKoXz4mdaAN+DaIiixafWcwqQ/RmXAueOFRJq9VeiS+jDkN
d53eAsMMvR8CAwEAAaOB2TCB1jAOBgNVHQ8BAf8EBAMCAQYwHQYDVR0OBBYEFEJ5
VBthzVUrPmPVPEhX9Z/7Rc5KMB8GA1UdIwQYMBaAFMB6mGiNifurBWQMEX2qfWW4
ysxOMBIGA1UdEwEB/wQIMAYBAf8CAQAwOgYDVR0fBDMwMTAvoC2gK4YpaHR0cDov
L2NybC5nZW90cnVzdC5jb20vY3Jscy9ndGdsb2JhbC5jcmwwNAYIKwYBBQUHAQEE
KDAmMCQGCCsGAQUFBzABhhhodHRwOi8vb2NzcC5nZW90cnVzdC5jb20wDQYJKoZI
hvcNAQEFBQADggEBANTvU4ToGr2hiwTAqfVfoRB4RV2yV2pOJMtlTjGXkZrUJPji
J2ZwMZzBYlQG55cdOprApClICq8kx6jEmlTBfEx4TCtoLF0XplR4TEbigMMfOHES
0tdT41SFULgCy+5jOvhWiU1Vuy7AyBh3hjELC3DwfjWDpCoTZFZnNF0WX3OsewYk
2k9QbSqr0E1TQcKOu3EDSSmGGM8hQkx0YlEVxW+o78Qn5Rsz3VqI138S0adhJR/V
4NwdzxoQ2KDLX4z6DOW/cf/lXUQdpj6HR/oaToODEj+IZpWYeZqF6wJHzSXj8gYE
TpnKXKBuervdo5AaRTPvvz7SBMS24CqFZUE+ENQ=
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIIDfTCCAuagAwIBAgIDErvmMA0GCSqGSIb3DQEBBQUAME4xCzAJBgNVBAYTAlVT
MRAwDgYDVQQKEwdFcXVpZmF4MS0wKwYDVQQLEyRFcXVpZmF4IFNlY3VyZSBDZXJ0
aWZpY2F0ZSBBdXRob3JpdHkwHhcNMDIwNTIxMDQwMDAwWhcNMTgwODIxMDQwMDAw
WjBCMQswCQYDVQQGEwJVUzEWMBQGA1UEChMNR2VvVHJ1c3QgSW5jLjEbMBkGA1UE
AxMSR2VvVHJ1c3QgR2xvYmFsIENBMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIB
CgKCAQEA2swYYzD99BcjGlZ+W988bDjkcbd4kdS8odhM+KhDtgPpTSEHCIjaWC9m
OSm9BXiLnTjoBbdqfnGk5sRgprDvgOSJKA+eJdbtg/OtppHHmMlCGDUUna2YRpIu
T8rxh0PBFpVXLVDviS2Aelet8u5fa9IAjbkU+BQVNdnARqN7csiRv8lVK83Qlz6c
JmTM386DGXHKTubU1XupGc1V3sjs0l44U+VcT4wt/lAjNvxm5suOpDkZALeVAjmR
Cw7+OC7RHQWa9k0+bw8HHa8sHo9gOeL6NlMTOdReJivbPagUvTLrGAMoUgRx5asz
PeE4uwc2hGKceeoWMPRfwCvocWvk+QIDAQABo4HwMIHtMB8GA1UdIwQYMBaAFEjm
aPkr0rKV10fYIyAQTzOYkJ/UMB0GA1UdDgQWBBTAephojYn7qwVkDBF9qn1luMrM
TjAPBgNVHRMBAf8EBTADAQH/MA4GA1UdDwEB/wQEAwIBBjA6BgNVHR8EMzAxMC+g
LaArhilodHRwOi8vY3JsLmdlb3RydXN0LmNvbS9jcmxzL3NlY3VyZWNhLmNybDBO
BgNVHSAERzBFMEMGBFUdIAAwOzA5BggrBgEFBQcCARYtaHR0cHM6Ly93d3cuZ2Vv
dHJ1c3QuY29tL3Jlc291cmNlcy9yZXBvc2l0b3J5MA0GCSqGSIb3DQEBBQUAA4GB
AHbhEm5OSxYShjAGsoEIz/AIx8dxfmbuwu3UOx//8PDITtZDOLC5MH0Y0FWDomrL
NhGc6Ehmo21/uBPUR/6LWlxz/K7ZGzIZOKuXNBSqltLroxwUCEm2u+WR74M26x1W
b8ravHNjkOR/ez4iyz0H7V84dJzjA1BOoa+Y7mHyhD8S
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIIFSjCCBDKgAwIBAgIDBQMSMA0GCSqGSIb3DQEBBQUAMGExCzAJBgNVBAYTAlVT
MRYwFAYDVQQKEw1HZW9UcnVzdCBJbmMuMR0wGwYDVQQLExREb21haW4gVmFsaWRh
dGVkIFNTTDEbMBkGA1UEAxMSR2VvVHJ1c3QgRFYgU1NMIENBMB4XDTEyMDkxMDE5
NTI1N1oXDTE2MDkxMTIxMjgyOFowgcExKTAnBgNVBAUTIEpxd2ViV3RxdzZNblVM
ek1pSzNiL21hdktiWjd4bEdjMRMwEQYDVQQLEwpHVDAzOTM4NjcwMTEwLwYDVQQL
EyhTZWUgd3d3Lmdlb3RydXN0LmNvbS9yZXNvdXJjZXMvY3BzIChjKTEyMS8wLQYD
VQQLEyZEb21haW4gQ29udHJvbCBWYWxpZGF0ZWQgLSBRdWlja1NTTChSKTEbMBkG
A1UEAxMSYXBpLmxvZ2VudHJpZXMuY29tMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A
MIIBCgKCAQEAxcmFqgE2p6+N9lM2GJhe8bNUO0qmcw8oHUVrsneeVA66hj+qKPoJ
AhGKxC0K9JFMyIzgPu6FvuVLahFZwv2wkbjXKZLIOAC4o6tuVb4oOOUBrmpvzGtL
kKVN+sip1U7tlInGjtCfTMWNiwC4G9+GvJ7xORgDpaAZJUmK+4pAfG8j6raWgPGl
JXo2hRtOUwmBBkCPqCZQ1mRETDT6tBuSAoLE1UMlxWvMtXCUzeV78H+2YrIDxn/W
xd+eEvGTSXRb/Q2YQBMqv8QpAlarcda3WMWj8pkS38awyBM47GddwVYBn5ZLEu/P
DiRQGSmLQyFuk5GUdApSyFETPL6p9MfV4wIDAQABo4IBqDCCAaQwHwYDVR0jBBgw
FoAUjPTZkwpHvACgSs5LdW6gtrCyfvwwDgYDVR0PAQH/BAQDAgWgMB0GA1UdJQQW
MBQGCCsGAQUFBwMBBggrBgEFBQcDAjAdBgNVHREEFjAUghJhcGkubG9nZW50cmll
cy5jb20wQQYDVR0fBDowODA2oDSgMoYwaHR0cDovL2d0c3NsZHYtY3JsLmdlb3Ry
dXN0LmNvbS9jcmxzL2d0c3NsZHYuY3JsMB0GA1UdDgQWBBRaMeKDGSFaz8Kvj+To
j7eMOtT/zTAMBgNVHRMBAf8EAjAAMHUGCCsGAQUFBwEBBGkwZzAsBggrBgEFBQcw
AYYgaHR0cDovL2d0c3NsZHYtb2NzcC5nZW90cnVzdC5jb20wNwYIKwYBBQUHMAKG
K2h0dHA6Ly9ndHNzbGR2LWFpYS5nZW90cnVzdC5jb20vZ3Rzc2xkdi5jcnQwTAYD
VR0gBEUwQzBBBgpghkgBhvhFAQc2MDMwMQYIKwYBBQUHAgEWJWh0dHA6Ly93d3cu
Z2VvdHJ1c3QuY29tL3Jlc291cmNlcy9jcHMwDQYJKoZIhvcNAQEFBQADggEBAAo0
rOkIeIDrhDYN8o95+6Y0QhVCbcP2GcoeTWu+ejC6I9gVzPFcwdY6Dj+T8q9I1WeS
VeVMNtwJt26XXGAk1UY9QOklTH3koA99oNY3ARcpqG/QwYcwaLbFrB1/JkCGcK1+
Ag3GE3dIzAGfRXq8fC9SrKia+PCdDgNIAFqe+kpa685voTTJ9xXvNh7oDoVM2aip
v1xy+6OfZyGudXhXag82LOfiUgU7hp+RfyUG2KXhIRzhMtDOHpyBjGnVLB0bGYcC
566Nbe7Alh38TT7upl/O5lA29EoSkngtUWhUnzyqYmEMpay8yZIV4R9AuUk2Y4HB
kAuBvDPPm+C0/M4RLYs=
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIID+jCCAuKgAwIBAgIDAjbSMA0GCSqGSIb3DQEBBQUAMEIxCzAJBgNVBAYTAlVT
MRYwFAYDVQQKEw1HZW9UcnVzdCBJbmMuMRswGQYDVQQDExJHZW9UcnVzdCBHbG9i
YWwgQ0EwHhcNMTAwMjI2MjEzMjMxWhcNMjAwMjI1MjEzMjMxWjBhMQswCQYDVQQG
EwJVUzEWMBQGA1UEChMNR2VvVHJ1c3QgSW5jLjEdMBsGA1UECxMURG9tYWluIFZh
bGlkYXRlZCBTU0wxGzAZBgNVBAMTEkdlb1RydXN0IERWIFNTTCBDQTCCASIwDQYJ
KoZIhvcNAQEBBQADggEPADCCAQoCggEBAKa7jnrNpJxiV9RRMEJ7ixqy0ogGrTs8
KRMMMbxp+Z9alNoGuqwkBJ7O1KrESGAA+DSuoZOv3gR+zfhcIlINVlPrqZTP+3RE
60OUpJd6QFc1tqRi2tVI+Hrx7JC1Xzn+Y3JwyBKF0KUuhhNAbOtsTdJU/V8+Jh9m
cajAuIWe9fV1j9qRTonjynh0MF8VCpmnyoM6djVI0NyLGiJOhaRO+kltK3C+jgwh
w2LMpNGtFmuae8tk/426QsMmqhV4aJzs9mvIDFcN5TgH02pXA50gDkvEe4GwKhz1
SupKmEn+Als9AxSQKH6a9HjQMYRX5Uw4ekIR4vUoUQNLIBW7Ihq28BUCAwEAAaOB
2TCB1jAOBgNVHQ8BAf8EBAMCAQYwHQYDVR0OBBYEFIz02ZMKR7wAoErOS3VuoLaw
sn78MB8GA1UdIwQYMBaAFMB6mGiNifurBWQMEX2qfWW4ysxOMBIGA1UdEwEB/wQI
MAYBAf8CAQAwOgYDVR0fBDMwMTAvoC2gK4YpaHR0cDovL2NybC5nZW90cnVzdC5j
b20vY3Jscy9ndGdsb2JhbC5jcmwwNAYIKwYBBQUHAQEEKDAmMCQGCCsGAQUFBzAB
hhhodHRwOi8vb2NzcC5nZW90cnVzdC5jb20wDQYJKoZIhvcNAQEFBQADggEBADOR
NxHbQPnejLICiHevYyHBrbAN+qB4VqOC/btJXxRtyNxflNoRZnwekcW22G1PqvK/
ISh+UqKSeAhhaSH+LeyCGIT0043FiruKzF3mo7bMbq1vsw5h7onOEzRPSVX1ObuZ
lvD16lo8nBa9AlPwKg5BbuvvnvdwNs2AKnbIh+PrI7OWLOYdlF8cpOLNJDErBjgy
YWE5XIlMSB1CyWee0r9Y9/k3MbBn3Y0mNhp4GgkZPJMHcCrhfCn13mZXCxJeFu1e
vTezMGnGkqX2Gdgd+DYSuUuVlZzQzmwwpxb79k1ktl8qFJymyFWOIPllByTMOAVM
IIi0tWeUz12OYjf+xLQ=
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIIF4TCCA8mgAwIBAgIJAMuLUWygLQmXMA0GCSqGSIb3DQEBCwUAMIGGMQswCQYD
VQQGEwJJRTEQMA4GA1UECAwHSXJlbGFuZDEPMA0GA1UEBwwGRHVibGluMRgwFgYD
VQQKDA9KbGl6YXJkIExpbWl0ZWQxEzARBgNVBAMMCkxvZ2VudHJpZXMxJTAjBgkq
hkiG9w0BCQEWFnN1cHBvcnRAbG9nZW50cmllcy5jb20wHhcNMTQwMjI0MjA1MzQ2
WhcNMTkwMjIzMjA1MzQ2WjCBhjELMAkGA1UEBhMCSUUxEDAOBgNVBAgMB0lyZWxh
bmQxDzANBgNVBAcMBkR1YmxpbjEYMBYGA1UECgwPSmxpemFyZCBMaW1pdGVkMRMw
EQYDVQQDDApMb2dlbnRyaWVzMSUwIwYJKoZIhvcNAQkBFhZzdXBwb3J0QGxvZ2Vu
dHJpZXMuY29tMIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAymhjhWPh
gz7tuk5Jj+ohRfjUMNoUKCvTPVCl5LPon7seXmt+FC0Cyf68VoGY8m5fuahWseKr
uyw7Bk7Q18vFBvsGp38q7NvQYlcQ2pCj7Ln6AvSlYvoweS4pz1C9C479ODNj9U2I
RcqNxfZX2alxZGsoGg0u/KS3RbXFZzyMGPSXbugzMAYFyoIJM1U1iGhrjj8yAGes
pP1BeDwrK9qHOv2Uy3yF8UtNKRm+hYE0E+yv0+s8vQLYnHaaZFwt1hulo0CGDjpJ
vZtmR5U0qRjdFE6RZJsetfPNYeUYYeyG8qwEKMK86K3Jj8J9MR4l21Q+rIzK7JMm
4P3Rh/L4klWEKm48WhfAhlv43CSpt/6HWhBq3B400effQzudl2O6VfC1OIlKWQ3x
jmAKZToIlIVeF7X/5z04Azhy2SVpQ1DNVGShlKIiyTIA04ny3udMdDr0InvmXHtn
rQexpaw5uFYno2tmOSJiElx5c7fMQtOmXO6qd/s9TFsNH8hwJ9g+Vgof11gTOo6o
MEEgzeVfMOPd5JOtPXOD+S9X0Vt0dUlCD4xbjpwH1kJ5hfTcLtmANDOAIjF+P9pY
ajDLE9phYM9qydyRaTawyOS7GA7XaW/WPZzgbSZ3T9KNJIUU1c1OZd3JD4BsDOBD
ZTRxHxanHeg2pAAmiNX1rIBwz5O8Zm13rT8CAwEAAaNQME4wHQYDVR0OBBYEFDk6
qPSf6apMD0hAGrYutT+wdnqhMB8GA1UdIwQYMBaAFDk6qPSf6apMD0hAGrYutT+w
dnqhMAwGA1UdEwQFMAMBAf8wDQYJKoZIhvcNAQELBQADggIBADQg6tx70qwG74dj
af9QDXKHhGvp8SoGMNvioQGREhrAXb0JTFiEQAECJghiP8OH4PIOjsN/ON4YI+WW
ZPdGlcPkUgFQ/bdB7eEyKtGa7hDfH1PLL1FqVhZjoLC6poCJJVo/Q9J2dlkGaksK
/R6+QV4SYnzfPH4cKQoN4Q/F0VuzelonSVTk9BG72RsY1fQPrm6tA/sN5Nzl+a4W
d1UnK4KXajQH1Qsnv8VTXyBc+8wM3C12m/lsqc2npgIqU/xlQQXgDBR087+A/dX3
osXMzZfGhh6D/NyCKs7VuAsb7hRTPP/6WMgM3c9lSc05xZyXzEZ7FL4GYg3Gjsdg
PFQMkgfMyiECBPudVzU2RyWuXdId+i0ezl1mBSrowa+eNCx2pI5Er7OAjvEQOAlC
v50jvvwSU9dT39XkGNh+q5uxaFLxyr6WidT09xHi17RZhgcMzWkiShRRqum/rOfL
TUPMGFvOjLiMiRZvHYhB3XjPqO5z3DEWT6Ux8IUN0aqNWCSLV2DOc/2riflxtExc
V1XUj6wWPCNqNPvdXeuQl/yqOZM5ekBlPCpPyxztba8SrJZKVWRXJl3RxuKPuWIE
XI7Mr8xQHVr1HLt/SU+by7Y7im6nyZUfOzTNMkic0RXgI0fqztetDpfLedN8Xlwn
/1NE/L7egzmDtcwoSQYUTu8g5rI4
-----END CERTIFICATE-----
"""
