#!/usr/bin/env bats

@test "Linux Agent installation test" {
   cd /tmp/test-suites/installation
   run sudo pybot --name AgentInstallation --pythonpath /tmp/test-suites/common/ --loglevel DEBUG gherkin.txt
   [ "$status" -eq 0 ]
}

@test "Linux Agent one-shot file following test" {
   cd /tmp/test-suites/following-one-shot
   run sudo pybot --name AgentFollowing --pythonpath /tmp/test-suites/common/ --loglevel DEBUG gherkin.txt
   [ "$status" -eq 0 ]
}

@test "Linux Agent continuous file following test" {
   cd /tmp/test-suites/following-continuous
   run sudo pybot --name AgentFollowingContinuous --pythonpath /tmp/test-suites/common/ --loglevel DEBUG gherkin.txt
   [ "$status" -eq 0 ]
}
