package "git"
package "python"
package "python-pip"

execute "Install Robot Framework" do
  command "pip install robotframework"
  action :run
end

execute "Install pexpect" do
  command "pip install pexpect"
  action :run
end
