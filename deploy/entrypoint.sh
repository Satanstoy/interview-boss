#!/bin/bash
set -e

# The image declares USER appuser. Keep this wrapper deliberately
# non-privileged so a bind mount cannot turn startup into a root shell.
exec "$@"
