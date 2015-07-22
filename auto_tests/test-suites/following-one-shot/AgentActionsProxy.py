import logging
from common_utils import *
import re

class AgentActionsProxy(object):
    # Logger name
    LOGGER_NAME = "LinuxAgentTestFramework"

    # Constants area
    AGENT_FOLLOW_COMMAND = "le follow %s"
    LOG_CHECK_URI = 'http://api.logentries.com/%s/hosts/%s/'
    MAIN_SECTION = 'Main'
    CONFIG_NAME = 'config'
    HOST_KEY_PARAM = 'agent-key'
    USER_KEY_PARAM = 'user-key'

    def __init__(self):
        self.log = logging.getLogger(AgentActionsProxy.LOGGER_NAME)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        self.log.addHandler(ch)

        self.utils = CommonUtils()

        # Action states containers
        self.agent_host_key = ''
        self.agent_user_key = ''
        self.following_result = ''

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
            if self.agent_user_key and self.agent_host_key:
                break
        self.log.info('User key is ' + self.agent_user_key)
        self.log.info('Host key is ' + self.agent_host_key)

    def create_log_file(self, file_path):
        self.utils.create_log_file(file_path)

    def invoke_agent_to_follow(self, file_path):
        status, output = self.utils.execute_cmd(AgentActionsProxy.AGENT_FOLLOW_COMMAND % file_path)
        self.following_result = output

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
            raise AssertionError('Failed to get log set contents for host ' + self.agent_host_key + '. Response is ' + result)
