#!/usr/bin/env bats

@test "git binary is found in PATH" {
  run which git
  [ "$status" -eq 0 ]
}

@test "PIP binary is found in PATH" {
  run which pip
  [ "$status" -eq 0 ]
}
