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
#
# Startup grace: clamd can also die before it ever answers (a first boot that updated the
# signatures while clamd loaded them crossed the 1.5 GiB limit in the Deploy 2 rehearsal).
# If clamd has not answered PING within CLAMD_STARTUP_GRACE seconds of the start (default
# 900 = 15 minutes; a normal start answers within ~1-4 minutes), the wrapper exits too.
set -eu

INTERVAL="${CLAMD_WATCHDOG_INTERVAL:-30}"
MAX_FAILURES="${CLAMD_WATCHDOG_FAILURES:-5}"
STARTUP_GRACE="${CLAMD_STARTUP_GRACE:-900}"
INIT="${CLAMAV_INIT:-/init}"  # overridable for tests only

sh "$INIT" "$@" &
init_pid=$!

# Arguments mean "run this command instead of the daemons" (see /init): nothing to watch.
if [ "$#" -gt 0 ]; then
  wait "$init_pid"
  exit $?
fi

begun="$(date +%s)"
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
  if [ "$started" = "0" ]; then
    # Still loading signatures, unless the startup grace has run out.
    if [ $(( $(date +%s) - begun )) -ge "$STARTUP_GRACE" ]; then
      echo "clamav watchdog: clamd did not answer PING within ${STARTUP_GRACE}s of the start; exiting so the container restarts"
      exit 1
    fi
    continue
  fi
  failures=$((failures + 1))
  echo "clamav watchdog: clamd did not answer PING ($failures/$MAX_FAILURES)"
  if [ "$failures" -ge "$MAX_FAILURES" ]; then
    echo "clamav watchdog: clamd is down; exiting so the container restarts"
    exit 1
  fi
done
