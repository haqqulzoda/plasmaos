#!/bin/sh
# Entrypoint wrapper for the clamav/clamav image.
#
# The image's /init starts clamd in the background and then blocks on `tail -f /dev/null`,
# so when clamd dies (typically the kernel OOM killer while it loads or reloads its
# ~1.3 GB signature set) the container keeps running with no scanner: the healthcheck
# turns "unhealthy", Docker does nothing, and every private-document upload stays
# unscanned until someone restarts the container by hand.
#
# This wrapper runs the unchanged /init and exits when clamd stops answering PING on
# TCP 3310 for CLAMD_WATCHDOG_FAILURES consecutive checks, so the Compose restart policy
# brings the whole container (clamd and freshclam) back.
set -eu

INTERVAL="${CLAMD_WATCHDOG_INTERVAL:-30}"
MAX_FAILURES="${CLAMD_WATCHDOG_FAILURES:-5}"

sh /init "$@" &
init_pid=$!

# Arguments mean "run this command instead of the daemons" (see /init): nothing to watch.
if [ "$#" -gt 0 ]; then
  wait "$init_pid"
  exit $?
fi

started=0
failures=0
while :; do
  sleep "$INTERVAL"
  if ! kill -0 "$init_pid" 2>/dev/null; then
    echo "clamav watchdog: init exited; exiting so the container restarts"
    exit 1
  fi
  if [ "$(echo PING | nc localhost 3310 2>/dev/null)" = "PONG" ]; then
    started=1
    failures=0
    continue
  fi
  # Before the first PONG clamd is still loading signatures (/init allows CLAMD_STARTUP_TIMEOUT).
  [ "$started" = "1" ] || continue
  failures=$((failures + 1))
  echo "clamav watchdog: clamd did not answer PING ($failures/$MAX_FAILURES)"
  if [ "$failures" -ge "$MAX_FAILURES" ]; then
    echo "clamav watchdog: clamd is down; exiting so the container restarts"
    exit 1
  fi
done
