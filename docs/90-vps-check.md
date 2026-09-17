# Проверка VPS: доступность VK и Telegram

Один раз до деплоя: вставь блок ниже в терминал VPS целиком (подставь токены).
Скрипт проверяет ровно те хосты, с которыми работает KPIBALAGANCHIKBOT:
`api.vk.com` (методы), Long Poll-сервер сообщества, `api.telegram.org` (Bot API).

## Скрипт

```bash
#!/usr/bin/env bash
# Проверка доступности VK и Telegram с VPS (для KPIBALAGANCHIKBOT)
set -u

VK_TOKEN="СЮДА_ТОКЕН_СООБЩЕСТВА"
VK_GROUP_ID="241483738"
TG_TOKEN="СЮДА_ТОКЕН_БОТА_TELEGRAM"

echo "=== 1. DNS ==="
for h in api.vk.com imv4.vk.com lp.vk.com api.telegram.org; do
  ip=$(getent ahostsv4 "$h" 2>/dev/null | awk 'NR==1{print $1}')
  echo "$h -> ${ip:-НЕ РЕЗОЛВИТСЯ}"
done

echo
echo "=== 2. HTTPS: VK API (api.vk.com) ==="
code=$(curl -sS -o /tmp/vk_api.json -w "%{http_code}" \
  --connect-timeout 5 --max-time 10 \
  "https://api.vk.com/method/users.get?v=5.199")
echo "HTTP $code; ответ: $(head -c 120 /tmp/vk_api.json)"
# HTTP 200 с JSON-ошибкой «user authorization failed» — это НОРМА (мы без токена),
# главное — рукопожатие TLS и ответ сервера.

echo
echo "=== 3. VK: токен сообщества + Long Poll сервер ==="
resp=$(curl -sS --connect-timeout 5 --max-time 10 \
  "https://api.vk.com/method/groups.getLongPollServer?group_id=${VK_GROUP_ID}&access_token=${VK_TOKEN}&v=5.199")
echo "Ответ API: $(echo "$resp" | head -c 400)"
lp_host=$(echo "$resp" | grep -o '"server":"[^"]*"' | head -1 \
  | sed 's/"server":"//; s/"$//; s/\\//g')
if [ -n "$lp_host" ]; then
  code=$(curl -sS -o /dev/null -w "%{http_code}" \
    --connect-timeout 5 --max-time 10 "$lp_host")
  echo "Long Poll сервер ($lp_host): HTTP $code — любой код = доступен"
else
  echo "Long Poll сервер не получен — смотри ошибку в ответе выше."
fi

echo
echo "=== 4. Telegram Bot API (api.telegram.org) ==="
if [ "$TG_TOKEN" = "СЮДА_ТОКЕН_БОТА_TELEGRAM" ]; then
  echo "Токен не вставлен: проверю только доступность хоста."
  code=$(curl -sS -o /dev/null -w "%{http_code}" \
    --connect-timeout 5 --max-time 10 "https://api.telegram.org/")
  echo "api.telegram.org: HTTP $code — любой код = доступен."
else
  echo "Ответ getMe (должен быть JSON с ok:true и username бота):"
  curl -sS --connect-timeout 5 --max-time 10 \
    "https://api.telegram.org/bot${TG_TOKEN}/getMe"
  echo
fi

echo
echo "=== 5. TCP 443 (на случай, если curl нет/сломан) ==="
for h in api.vk.com:443 api.telegram.org:443; do
  host=${h%:*}; port=${h#*:}
  timeout 5 bash -c "cat < /dev/null > /dev/tcp/$host/$port" 2>/dev/null \
    && echo "$h: TCP OK" || echo "$h: TCP НЕ ОТКРЫВАЕТСЯ"
done
```

Сохранить и запустить:

```bash
nano vps_check.sh        # вставить скрипт, подставить токены
bash vps_check.sh
```

## Как читать результат

| Вывод | Значение |
|---|---|
| Все DNS-имена резолвятся | сеть + DNS в порядке |
| `api.vk.com: HTTP 200` + JSON с ошибкой авторизации | VK API доступен (это нормальный ответ без токена) |
| `groups.getLongPollServer` вернул `response.server` | токен сообщества рабочий, права на Long Poll есть |
| Long Poll-сервер ответил любым HTTP-кодом | долгий опрос дотянется |
| `getMe` вернул `ok:true` + username | Telegram Bot API доступен напрямую |
| `getMe` завис / `Could not connect` / timeout | **Telegram заблокирован с этого VPS** (типично для РФ-хостеров) |

## Что делать, если Telegram недоступен

1. **Проще всего — VPS за пределами РФ** (Hetzer/FIN, DO Амстердам и т.п.): и VK, и TG доступны напрямую.
2. Оставить РФ-VPS и пойти через HTTPS-прокси: в `.env` добавить
   `HTTPS_PROXY=http://user:pass@host:port` — клиенты бота уже поддерживают это
   (`trust_env=True`), отдельная проверка не нужна, просто перезапуск.
3. Временный обход `CERTIFICATE_VERIFY_FAILED` (антивирус/прокси подменяет
   сертификаты): `SSL_VERIFY=false` или `SSL_CA_BUNDLE=/путь/к/ca.pem` в `.env`.

VK с РФ-VPS доступен всегда — проверка нужна в основном ради Telegram.
