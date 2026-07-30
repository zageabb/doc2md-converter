#!/bin/sh
cd "$(dirname "$0")" || exit 1
exec python3 -m doc2md_watcher --gui --initial "$@"
