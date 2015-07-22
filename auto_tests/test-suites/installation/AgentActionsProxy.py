import logging
from common_utils import *


class AgentActionsProxy(object):
    # Logger name
    LOGGER_NAME = "LinuxAgentTestFramework"

    # Constants area
    GITHUB_PROBE_COMMAND = "which git"
    GITHUB_CLONE_COMMAND = "git clone %s %s"
    AGENT_REGISTER_COMMAND = "le register"
    USER_KEY_PARAM = " --user-key=%s"
    HOST_KEY_CHECK_URI = 'http://api.logentries.com/%s/hosts/%s'
    MAIN_SECTION = 'Main'
    HOST_KEY_PARAM = 'agent-key'
    CONFIG_NAME = 'config'

    def __init__(self):
        self.log = logging.getLogger(AgentActionsProxy.LOGGER_NAME)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        self.log.addHandler(ch)

        self.utils = CommonUtils()

        # Test data members
        self.github_repo = ''
        self.download_dest = ''

        # Action states containers
        self.agent_downloaded = False  # GitHub clone result
        self.agent_registered = False
        self.agent_host_key = ''
        self.agent_user_key = ''

    # ************************* Keywords implementations ********************************
    def download_agent(self):
        self.agent_downloaded = self.utils.clone_from_githib(self.github_repo, self.download_dest)

    def set_github_repository(self, github_repo):
        self.github_repo = github_repo

    def check_and_set_download_destination(self, download_dest):
        if not os.path.exists(download_dest):
            try:
                os.makedirs(download_dest)
            except Exception as e:
                raise Exception("Cannot create %s; error is %s" % (download_dest, e.message))
        self.download_dest = download_dest

    def register_agent_with_email(self, e_mail, password):
        self.utils.execute_cmd(AgentActionsProxy.AGENT_REGISTER_COMMAND)

    def register_agent(self, user_key):
        self.agent_user_key = user_key
        self.utils.execute_cmd(AgentActionsProxy.AGENT_REGISTER_COMMAND + AgentActionsProxy.USER_KEY_PARAM % user_key)

    def get_host_key_from_config(self, config_path, config_name):
        info_store = self.utils.get_info_from_python_config(config_path + '/' + config_name)
        main_section = info_store[AgentActionsProxy.MAIN_SECTION]
        for param in main_section:
            name, value = param
            if name == AgentActionsProxy.HOST_KEY_PARAM:
                self.agent_host_key = value
                break

    def check_agent_registration_on_site(self):
        conf_dir = self.utils.get_le_config_dir()
        self.get_host_key_from_config(conf_dir, AgentActionsProxy.CONFIG_NAME)
        resp = CommonUtils.make_get_request(AgentActionsProxy.HOST_KEY_CHECK_URI % (self.agent_user_key,
                                                                                    self.agent_host_key))
        self.agent_registered = True if '"response":"ok"' in resp else False

    # ****************************** Assertions ***************************************** 

    def download_result_must_be(self, result):
        res_code = {True: "success", False: "failure"}[self.agent_downloaded]
        print(result)
        if res_code != result.lower():
            raise AssertionError("%s != %s" % (res_code, result.lower()))

    def registration_result_must_be(self, result):
        res_code = {True: "success", False: "failure"}[self.agent_registered]
        print(result)
        if res_code != result.lower():
            raise AssertionError("%s != %s" % (res_code, result.lower()))
