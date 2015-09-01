# coding: utf-8
# vim: set ts=4 sw=4 et:

__author__ = 'Logentries'

__all__ = ['FormatPlain', 'FormatSyslog']

import datetime
import socket


class FormatPlain(object):
    """Formats lines as plain text, prepends each line with token."""

    def __init__(self, token):
        self._token = token

    def format_line(self, line):
        return self._token + line


class FormatSyslog(object):
    SYSLOG_MSG_FORMAT = '%s<14>1 %sZ %s %s - %s - hostname=%s appname=%s %s'

    """Formats lines according to Syslog format RFC 5424. Hostname is taken
    from configuration or current hostname is used."""

    def __init__(self, hostname, appname, token, send_datahub=False):
        if hostname:
            self._hostname = hostname
        else:
            self._hostname = socket.gethostname()
        self._appname = appname
        self._token = token
        self.send_datahub = send_datahub

    def format_line(self, line, msgid='-', token=''):
        if not token:
            token = self._token

        if not self.send_datahub:
            token_str_param = token
        else:
            token_str_param = ''

        return FormatSyslog.SYSLOG_MSG_FORMAT % (
            token_str_param,
            datetime.datetime.utcnow().isoformat('T'),
            self._hostname, self._appname,
            msgid,
            self._hostname, self._appname,
            line)
