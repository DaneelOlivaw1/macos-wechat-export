#!/bin/sh
set -eu
cd "$(dirname "$0")"
xcrun swiftc -parse-as-library -D LIBRARY WeChatUI.swift Send.swift Tests.swift -o wechat-ui-tests
./wechat-ui-tests
