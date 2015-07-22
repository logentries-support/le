import ConfigParser
import os
import pexpect
import subprocess
import urllib2

class CommonUtils(object):

    # Constants area
    GITHUB_PROBE_COMMAND = "which git"
    GITHUB_CLONE_COMMAND = "git clone %s %s"

    # Agent-related stuff
    CONFIG_DIR_SYSTEM = '/etc/le'
    CONFIG_DIR_USER = '.le'

    def __init__(self):
        pass

    @staticmethod
    def execute_cmd(command):
        """
        This method executes given command and returns tuple of (process_exit_code, process_stdout_messages)
        """
        process = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
        status = process.wait()
        output = process.communicate()[0]
        result = (status, output) if output is not None else ""
        return result

    @staticmethod
    def manipulate_interactive(executable_path, prompt_data_pairs):
        child = pexpect.spawn(executable_path)
        for control_item in prompt_data_pairs:
            prompt_text, data_to_input = control_item
            if child.expect([pexpect.TIMEOUT, prompt_text]) == 0:
                raise RuntimeError('Got unexpected output from the child process %s %s' %
                                   (child.before, child.after))
            else:
                child.sendline(data_to_input)
        return child.read()

    @staticmethod
    def get_le_config_dir():
        if os.geteuid() == 0:
            c_dir = CommonUtils.CONFIG_DIR_SYSTEM
        else:
            c_dir = os.path.expanduser('~') + '/' + CommonUtils.CONFIG_DIR_USER
        return c_dir + '/'

    @staticmethod
    def get_info_from_python_config(path_to_config):
        parsed_config = {}
        config = ConfigParser.SafeConfigParser()
        config.read(path_to_config)
        sections = config.sections()

        for section in sections:
            params = config.items(section)
            if params:
                param_vals = []
                for param in params:
                    param_vals.append(param)
                parsed_config[section] = param_vals      
        return parsed_config

    @staticmethod
    def probe_github_installation():
        status, path = CommonUtils.execute_cmd(CommonUtils.GITHUB_PROBE_COMMAND)
        return True if path else False

    @staticmethod
    def clone_from_githib(what_to_clone, where_to_clone):
        if not CommonUtils.probe_github_installation():
            return False
        try:
            status, output = CommonUtils.execute_cmd(CommonUtils.GITHUB_CLONE_COMMAND
                                              % (what_to_clone, where_to_clone))
            return True if status >= 0 else False
        except:
            return False

    @staticmethod
    def make_get_request(get_uri):
        result = ''
        try:
            result = urllib2.urlopen(get_uri).read()
        except:
            pass
        return result

    @staticmethod
    def create_log_file(file_path):
        parent_dir, file_name = os.path.split(file_path)
        if os.path.exists(file_path):
            if not os.path.isfile(file_path):
                raise AssertionError(file_path + ' is not a regular file.')
            os.remove(file_path)
        else:
            if not os.path.exists(parent_dir):
                os.makedirs(parent_dir)
        open(file_path, "w+").close()

    @staticmethod
    def populate_from_feed(file_path, feed_uri, append=False):
        sample_text = CommonUtils.make_get_request(feed_uri)
        if not sample_text:
            raise AssertionError('Cannot get sample text from ' + feed_uri)

        with open(file_path, "a" if append else "w") as fd:
            fd.writelines(sample_text)

    @staticmethod
    def make_get_request(get_uri):
        result = ''
        try:
            result = urllib2.urlopen(get_uri).read()
        except:
            pass
        return result

    @staticmethod
    def convert_expression_to_regexp(expr):
        return expr.replace('\\', '\\\\').replace('.', '\.')