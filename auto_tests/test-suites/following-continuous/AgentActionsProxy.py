import logging
import threading
import time
import signal
from common_utils import *
import re
import subprocess
from Queue import Queue, Empty
import sys


class AgentActionsProxy(object):
    # Logger name
    LOGGER_NAME = "LinuxAgentTestFramework"

    # Constants area
    AGENT_FOLLOW_COMMAND = "le follow %s"
    LOG_CHECK_URI = 'http://api.logentries.com/%s/hosts/%s/'
    LOG_PULL_URI = 'http://pull.logentries.com/%s/hosts/%s/%s/'
    MAIN_SECTION = 'Main'
    CONFIG_NAME = 'config'
    HOST_KEY_PARAM = 'agent-key'
    USER_KEY_PARAM = 'user-key'
    MONITOR_COMMAND = 'le monitor'

    AGENT_LOG = 'agent_log.log'

    SHUTDOWN_TIMEOUT = 10  # Monitoring thread shutdown timeout

    class LogPopulatingThread(threading.Thread):
        def __init__(self, path_to_log, feed_uri, work_time_sec, cycle_delay_sec=1):
            threading.Thread.__init__(self)
            self.path_to_log = path_to_log
            self.work_time_sec = work_time_sec
            self.cycle_delay_sec = cycle_delay_sec
            self.feed_uri = feed_uri

        def run(self):
            start_time = time.time()
            while time.time() - start_time < self.work_time_sec:
                CommonUtils.populate_from_feed(self.path_to_log, self.feed_uri, True)
                time.sleep(self.cycle_delay_sec)

    class AgentLaunchTread(threading.Thread):
        def __init__(self, command, shutdown_evt):
            threading.Thread.__init__(self)
            self.command = command
            self.process = None
            self.shutdown_evt = shutdown_evt

        def run(self):
            log_file = open(AgentActionsProxy.AGENT_LOG, 'w+')
            self.process = subprocess.Popen(self.command, shell=True, bufsize=1, stdout=log_file,
                                            stderr=subprocess.STDOUT, preexec_fn=os.setsid)
            status = self.process.wait()
            if status != 0 and status != -2:  # -2 - status, returned by the agent if terminated by ^C or SIGINT
                raise AssertionError('The Agent did not quit normally. Exit code is:  ' + str(status))
            log_file.flush()
            self.shutdown_evt.set()

    def __init__(self):
        self.log = logging.getLogger(AgentActionsProxy.LOGGER_NAME)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        self.log.addHandler(ch)

        self.log_populating_thread = None
        self.agent_monitoring_thread = None

        self.utils = CommonUtils()

        # Action states containers
        self.agent_host_key = ''
        self.agent_user_key = ''
        self.following_result = ''
        self.is_log_not_empty = False

    # ************************* Keywords implementations ********************************

    def get_host_user_keys(self):
        config_path = self.utils.get_le_config_dir() + AgentActionsProxy.CONFIG_NAME
        info_store = self.utils.get_info_from_python_config(config_path)
        main_section = info_store[AgentActionsProxy.MAIN_SECTION]
        for param in main_section:
            name, value = param
            if name == AgentActionsProxy.HOST_KEY_PARAM:
                self.agent_host_key = value
                self.log.info(self.agent_host_key)
                continue
            if name == AgentActionsProxy.USER_KEY_PARAM:
                self.agent_user_key = value
                self.log.info(self.agent_user_key)
                continue
            if self.agent_host_key and self.agent_user_key:
                break
        self.log.info('User key is ' + self.agent_user_key)
        self.log.info('Host key is ' + self.agent_host_key)

    def create_log_file(self, file_path):
        self.utils.create_log_file(file_path)

    def populate_file_from_feed_continuously(self, feed_uri, path_to_file, time_in_seconds):
        if self.log_populating_thread:
            raise AssertionError('Previous file populating thread has not finished; cannot start another instance.')
        if self.agent_monitoring_thread:
            raise AssertionError('Previous agent monitoring thread has not finished; cannot start another instance.')

        self.log_populating_thread = AgentActionsProxy.LogPopulatingThread(path_to_file, feed_uri, int(time_in_seconds))
        shutdown_evt = threading.Event()
        self.agent_monitoring_thread = AgentActionsProxy.AgentLaunchTread(AgentActionsProxy.MONITOR_COMMAND,
                                                                          shutdown_evt)

        self.agent_monitoring_thread.daemon = True
        self.log_populating_thread.daemon = True

        self.agent_monitoring_thread.start()
        self.log_populating_thread.start()

        self.log_populating_thread.join()

        os.killpg(self.agent_monitoring_thread.process.pid, signal.SIGINT)  # Emulate user interaction
        shutdown_evt.wait(AgentActionsProxy.SHUTDOWN_TIMEOUT)

        agent_msgs = None
        with open(AgentActionsProxy.AGENT_LOG, 'r') as fd:
            agent_msgs = fd.readlines()

        AgentActionsProxy.analyze_agent_output(agent_msgs)

    def invoke_agent_to_follow(self, file_path):
        status, output = self.utils.execute_cmd(AgentActionsProxy.AGENT_FOLLOW_COMMAND % file_path)
        self.following_result = output

    def pull_log_from_server(self, name_on_server):
        result = self.utils.make_get_request(AgentActionsProxy.LOG_PULL_URI % (self.agent_user_key,
                                                                               self.agent_host_key,
                                                                               name_on_server))
        if result:
            if '"response":"error"' not in result:
                self.is_log_not_empty = True
            else:
                raise AssertionError('Cannot pull log ' + name_on_server)  # Failed to get log's contents
        else:
            self.is_log_not_empty = False

    def check_whether_log_is_not_empty(self):
        if not self.is_log_not_empty:
            raise AssertionError('Log is empty on site')

    # ****************************** Assertions ***************************************** 

    def match_agent_output_with_pattern(self, agent_output_msg):
        pattern = re.compile('.*' + self.utils.convert_expression_to_regexp(agent_output_msg) + '.*',
                             re.IGNORECASE)
        if not pattern.match(self.following_result):
            raise AssertionError("%s does not match %s pattern" % (self.following_result, agent_output_msg))

    def check_log_presence_on_site(self, log_name):
        self.get_host_user_keys()
        result = self.utils.make_get_request(AgentActionsProxy.LOG_CHECK_URI % (self.agent_user_key,
                                                                                self.agent_host_key))
        if '"response":"ok"' in result:
            if log_name not in result:
                raise AssertionError(log_name + ' is not present in the current log set')
        else:
            raise AssertionError(
                'Failed to get log set contents for host ' + self.agent_host_key + '. Response is ' + result)

    @staticmethod
    def analyze_agent_output(agent_msgs):
        bad_msgs = re.compile('.*(stack|trace|error|fail|unable|cannot|except|traceback|interrupt).*', re.IGNORECASE)
        if True:
            for msg in agent_msgs:
                if bad_msgs.match(msg.lower()):
                    raise AssertionError('"Bad" status marker found in Agent''s output: ' + msg)
