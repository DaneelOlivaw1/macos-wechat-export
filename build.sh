#!/bin/sh
set -eu
cd "$(dirname "$0")"
xcrun swiftc -parse-as-library -O -target "$(uname -m)-apple-macosx14.0" WeChatUI.swift Send.swift -o wechat-ui
./wechat-ui self-test
