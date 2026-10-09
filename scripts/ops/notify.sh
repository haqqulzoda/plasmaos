#!/usr/bin/env bash
# Send one operations message to Telegram.
#
#   scripts/ops/notify.sh "text"            (or the text on stdin: ... | scripts/ops/notify.sh)
#   scripts/ops/notify.sh --unit NAME       systemd OnFailure= helper: "<unit> failed" + its last journal lines
#
# Needs OPS_TELEGRAM_BOT_TOKEN and OPS_TELEGRAM_CHAT_ID (from /etc/plasma/ops.env on the host).
# The token never appears in arguments, logs or output: curl reads the URL from a config on
# stdin. Messages are prefixed with OPS_HOST_LABEL (default: the host name).
# Exit status: 0 sent, 3 not configured (the text is printed instead), 1 Telegram refused it.
set -uo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

API="${OPS_TELEGRAM_API:-https://api.telegram.org}"
LABEL="${OPS_HOST_LABEL:-$(hostname -s 2>/dev/null || echo host)}"

if [ "${1:-}" = "--unit" ]; then
  unit="${2:?--unit needs a unit name}"
  tail_lines="$(journalctl -u "$unit" -n 12 --no-pager -o cat 2>/dev/null | tail -n 12 || true)"
  text="$(printf '%s failed on %s\n%s' "$unit" "$LABEL" "$tail_lines")"
elif [ "$#" -gt 0 ]; then
  text="$*"
else
  text="$(cat)"
fi
[ -n "$text" ] || die "nothing to send"
text="[$LABEL] $text"
# Telegram's limit is 4096 characters.
text="${text:0:3900}"

if [ -z "${OPS_TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${OPS_TELEGRAM_CHAT_ID:-}" ]; then
  log "telegram not configured (OPS_TELEGRAM_BOT_TOKEN / OPS_TELEGRAM_CHAT_ID); message not sent:"
  printf '%s\n' "$text" >&2
  exit 3
fi

response="$(printf 'url = "%s/bot%s/sendMessage"\n' "$API" "$OPS_TELEGRAM_BOT_TOKEN" \
  | curl -sS --max-time 20 -K - \
      --data-urlencode "chat_id=$OPS_TELEGRAM_CHAT_ID" \
      --data-urlencode "text=$text" \
      --data-urlencode "disable_web_page_preview=true" 2>&1)"
if printf '%s' "$response" | grep -q '"ok":true'; then
  exit 0
fi
# Never echo the response verbatim: on some errors curl prints the URL (with the token).
log "telegram did not accept the message: $(printf '%s' "$response" | sed -n 's/.*"description":"\([^"]*\)".*/\1/p' | head -c 200)"
exit 1
