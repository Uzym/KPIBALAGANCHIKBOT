"""E2E проверка всех API endpoints через urllib (без curl — фикс кодировки)."""
import json
import sys
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8080/api"

def call(method, path, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_body": e.read().decode("utf-8", errors="replace")[:200]}
    except Exception as e:
        return {"_error": str(e)}

results = []

def check(name, method, path, body=None, expect_keys=None):
    resp = call(method, path, body)
    ok = True
    issues = []
    if isinstance(resp, dict) and "_http_error" in resp:
        ok = False
        issues.append(f"HTTP {resp['_http_error']}: {resp.get('_body', '')[:100]}")
    elif isinstance(resp, dict):
        if expect_keys:
            for k in expect_keys:
                if k not in resp:
                    ok = False
                    issues.append(f"нет ключа: {k}")
        err = resp.get("error")
        if err is not None and isinstance(err, str) and method != "GET":
            ok = False
            issues.append(f"error: {err}")
    status = "✓" if ok else "✗"
    results.append((status, name, "; ".join(issues) if issues else "OK"))
    return resp

# ── здоровье ──
check("health", "GET", "/health", expect_keys=["status"])

# ── события: CRUD ──
r = check("GET events", "GET", "/events")
if isinstance(r, list):
    print(f"  → {len(r)} событий")

created = check("POST create event", "POST", "/events", {
    "title": "E2E тест события",
    "starts_at": "2026-12-01 19:00",
    "place": "Тестовый зал",
}, expect_keys=["ok", "id"])
eid = created.get("id") if isinstance(created, dict) else None

if eid:
    check("GET event by id", "GET", f"/events/{eid}", expect_keys=["id", "title"])
    check("PUT update event", "PUT", f"/events/{eid}", {"title": "E2E v2"})
    check("POST vote", "POST", f"/events/{eid}/vote", {"answer": "yes", "user_id": 1})
    check("POST close event", "POST", f"/events/{eid}/close")
    check("POST reopen event", "POST", f"/events/{eid}/reopen")
    check("POST announce", "POST", f"/events/{eid}/announce", {"text": "e2e тест объявления"})
    check("POST cancel event", "POST", f"/events/{eid}/cancel")
    check("DELETE event", "DELETE", f"/events/{eid}")

# ── опросы: CRUD ──
r = check("GET polls", "GET", "/polls")
if isinstance(r, list):
    print(f"  → {len(r)} опросов")

created = check("POST create poll", "POST", "/polls", {
    "question": "E2E опрос",
    "options": ["Да", "Нет", "Может быть"],
    "multichoice": True,
})
pid = created.get("id") if isinstance(created, dict) else None

if pid:
    check("GET polls after create", "GET", "/polls")
    check("PUT update poll", "PUT", f"/polls/{pid}", {"question": "E2E v2"})
    check("POST poll vote", "POST", f"/polls/{pid}/vote", {"option_id": 0})
    check("POST close poll", "POST", f"/polls/{pid}/close")
    check("POST reopen poll", "POST", f"/polls/{pid}/reopen")
    check("DELETE poll", "DELETE", f"/polls/{pid}")

# ── оплата ──
check("GET fees", "GET", "/fees?person_id=1", expect_keys=["my_debt", "monthly"])
check("POST fee report", "POST", "/fees/report", {"amount": 200})

# ── админ ──
stats = check("GET admin stats", "GET", "/admin/stats",
    expect_keys=["active_events", "subscribers", "total_debt", "collected_month"])
if isinstance(stats, dict):
    print(f"  → {stats.get('active_events')} событий, {stats.get('subscribers')} подписчиков, {stats.get('collected_month')}₽ собрано")

people = check("GET admin people", "GET", "/admin/people")
if isinstance(people, list):
    print(f"  → {len(people)} людей")

pid1 = people[0]["id"] if isinstance(people, list) and people else 1
check("POST payment", "POST", "/admin/fees/payment",
    {"person_id": pid1, "amount": 100, "label": "e2e платёж"})
check("POST charge", "POST", "/admin/fees/charge",
    {"person_id": pid1, "amount": 50, "label": "e2e трата"})

# ── вывод ──
print()
passed = sum(1 for s, _, _ in results if s == "✓")
failed = sum(1 for s, _, _ in results if s == "✗")
for status, name, detail in results:
    print(f"  {status} {name}: {detail}")
print(f"\n{'='*50}")
print(f"  {passed} passed, {failed} failed, {len(results)} total")
if failed:
    sys.exit(1)
print("  ВСЕ E2E API ТЕСТЫ ПРОЙДЕНЫ ✓")
