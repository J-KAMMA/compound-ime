#!/bin/bash
# コンパウンドIME 新版のお知らせ（マック用）
# curl と osascript（display notification）を使う。
# 失敗したときは黙って終わる。外部に送るのは GitHub の releases API への GET だけ。

UA="CompoundIME-update-check"
API_URL="https://api.github.com/repos/J-KAMMA/compound-ime/releases?per_page=5"
PLIST="/Library/Input Methods/CompoundIME.app/Contents/Info.plist"
DATA_DIR="$HOME/Library/Application Support/CompoundIME"
STATE_FILE="$DATA_DIR/update_check"
SETTINGS_FILE="$DATA_DIR/settings"
RELEASE_BASE="https://github.com/J-KAMMA/compound-ime/releases/tag/"

# $1 が $2 より新しければ 1、そうでなければ 0 を出す（4つの数字）
ver_gt() {
  awk -v a="$1" -v b="$2" 'BEGIN{
    split(a, x, "."); split(b, y, ".");
    for (i = 1; i <= 4; i++) {
      if (x[i] + 0 > y[i] + 0) { print 1; exit }
      if (x[i] + 0 < y[i] + 0) { print 0; exit }
    }
    print 0
  }'
}

main() {
  # 止める設定
  if [ -f "$SETTINGS_FILE" ] && grep -Eq '^[[:space:]]*update_check[[:space:]]*=[[:space:]]*0[[:space:]]*$' "$SETTINGS_FILE"; then
    return 0
  fi

  command -v curl >/dev/null 2>&1 || return 0
  command -v osascript >/dev/null 2>&1 || return 0

  # 今入っている版（CFBundleVersion）
  [ -f "$PLIST" ] || return 0
  raw=$(plutil -extract CFBundleVersion raw -o - "$PLIST" 2>/dev/null)
  if [ -z "$raw" ]; then
    raw=$(defaults read "${PLIST%.plist}" CFBundleVersion 2>/dev/null)
  fi
  installed=$(printf '%s' "$raw" | grep -Eo '[0-9]+(\.[0-9]+){3}' | head -n 1)
  [ -n "$installed" ] || return 0

  # 状態の読み出し（1日1回まで）
  checked=0
  notified=""
  if [ -f "$STATE_FILE" ]; then
    checked=$(sed -n 's/^checked=\([0-9][0-9]*\)$/\1/p' "$STATE_FILE" | head -n 1)
    notified=$(sed -n 's/^notified=\(.*\)$/\1/p' "$STATE_FILE" | head -n 1)
    [ -n "$checked" ] || checked=0
  fi
  now=$(date +%s)
  if [ "$checked" -gt 0 ] && [ "$now" -ge "$checked" ] && [ $((now - checked)) -lt 86400 ]; then
    return 0
  fi

  # 問い合わせる前に時刻を記録する（失敗しても1日は再試行しない）
  mkdir -p "$DATA_DIR" 2>/dev/null || return 0
  printf 'checked=%s\nnotified=%s\n' "$now" "$notified" > "$STATE_FILE" 2>/dev/null || return 0

  # API（GET のみ、10秒）
  json=$(curl -fsS --connect-timeout 10 --max-time 10 -A "$UA" \
    -H "Accept: application/vnd.github+json" "$API_URL" 2>/dev/null) || return 0
  [ -n "$json" ] || return 0

  # 下書きでない中で一番新しい tag_name（試用版も含む）
  latest=$(printf '%s' "$json" | tr ',' '\n' | awk '
    /"tag_name"[[:space:]]*:/ { t=$0; sub(/.*"tag_name"[[:space:]]*:[[:space:]]*"/, "", t); sub(/".*/, "", t); next }
    /"draft"[[:space:]]*:/ { if ($0 ~ /false/ && t != "") print t; t=""; next }
  ' | sed 's/^v//' | grep -E '^[0-9]+(\.[0-9]+){3}$' \
    | awk -F. '{ printf "%d %d %d %d v%s\n", $1, $2, $3, $4, $0 }' \
    | sort -n -k1,1 -k2,2 -k3,3 -k4,4 | tail -n 1 | awk '{ print $5 }')
  [ -n "$latest" ] || return 0
  latest_ver="${latest#v}"

  [ "$(ver_gt "$latest_ver" "$installed")" = "1" ] || return 0
  # 同じ版は1回だけ
  [ "$notified" != "$latest" ] || return 0

  url="${RELEASE_BASE}${latest}"
  # 押して開くのは難しいので、文に URL を入れる
  msg="コンパウンドIMEの新しい版（${latest_ver}）があります。配布ページ: ${url}"

  if osascript \
      -e 'on run argv' \
      -e 'display notification (item 1 of argv) with title "コンパウンドIME"' \
      -e 'end run' -- "$msg" >/dev/null 2>&1; then
    printf 'checked=%s\nnotified=%s\n' "$now" "$latest" > "$STATE_FILE" 2>/dev/null
  fi
  return 0
}

main "$@" >/dev/null 2>&1
exit 0
