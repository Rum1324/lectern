#!/bin/bash
# Double-click in Finder to start Lectern.
cd "$(dirname "$0")"
exec /usr/bin/env python3 lectern.py "$@"
