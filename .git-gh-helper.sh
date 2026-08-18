#!/bin/sh
# Temporary credential helper for this repo: HTTPS + gh CLI token.
# Used via: git -c credential.helper=<abs-path> <command>
case "$1" in
  get)
    echo "username=x-access-token"
    echo "password=$(gh auth token)"
    ;;
esac
