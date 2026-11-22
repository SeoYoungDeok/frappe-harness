---
name: frappe-testing
description: How to verify Frappe changes on the Test site — applying shared code with migrate, running tests, and capturing real browser screenshots without passwords. Used by the Tester for any Frappe code or UI change.
---

# frappe-testing — Test 사이트에서 검증하는 방법

값은 프로젝트 `.frappe-harness.toml`에서 읽는다: `bench`(Bench 경로, 상대 경로면 이 파일 기준), `sites.test`, `test_server.port`.

## Dev/Test 공유 Bench 주의
- 코드는 공유, DB는 분리. DocType JSON 변경은 Test에 `bench --site <test> migrate`를 해야 반영된다.
- **기본 웹 서버(`:8000`)는 `serve_default_site`면 Host와 무관하게 Dev 사이트만 서빙할 수 있다.** Test 화면을 볼 때는 Test 전용 서버를 쓴다. 이미 떠 있는지 먼저 확인:
  ```bash
  curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:<port>/api/method/ping
  ```
  없으면 Bench 경로에서 백그라운드로 띄우고, 검증이 끝나면 내가 띄운 것만 종료한다:
  ```bash
  bench --site <test> serve --port <port> --noreload
  ```
- 사이트 확인: Test 세션 sid로 `/api/method/frappe.auth.get_logged_user`가 `Administrator`를 돌려주는지 본다(Dev sid는 거부돼야 함).

## 자동 테스트
- `bench --site <test> run-tests --app <app> [--module <module.path>]`. Dev 사이트에서 실행하지 않는다.
- v16: DB 필요 → `frappe.tests.IntegrationTestCase`, 순수 함수 → `frappe.tests.UnitTestCase` (`FrappeTestCase`는 폐기 예정).
- 테스트가 만든 데이터는 테스트가 정리한다.

## 브라우저 스크린샷 (비밀번호 없이)
1. Bench의 `sites/` 디렉터리에서 Test 사이트 Administrator 세션을 만든다(Test 사이트 전용, Dev 금지):
   ```bash
   cd <bench>/sites && ../env/bin/python - <<'EOF'
   import frappe
   from frappe.auth import LoginManager, CookieManager
   from frappe.utils import set_request
   frappe.init("<test>"); frappe.connect()
   set_request(path="/"); frappe.local.cookie_manager = CookieManager()
   LoginManager().login_as("Administrator", None, None)
   print(frappe.local.session_obj.sid); frappe.db.commit(); frappe.destroy()
   EOF
   ```
2. 설치된 Chrome/Chromium 헤드리스로 캡처(`?sid=`로 로그인). v16 Desk 경로는 `/desk/<doctype-slug>`.
   실행 파일: macOS `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`, Linux/WSL `google-chrome` 또는 `chromium`(`command -v`로 확인). 없으면 설치하지 말고 `UNVERIFIED`로 보고한다.
   ```bash
   "$CHROME" --headless=new --disable-gpu \
     --hide-scrollbars --window-size=1400,1000 --virtual-time-budget=20000 \
     --user-data-dir="$(mktemp -d)" --screenshot=<evidence>/<name>.png \
     "http://<test>:<port>/desk/<doctype-slug>/new?sid=<sid>"
   ```
3. 캡처한 이미지를 직접 열어 변경이 보이는지 확인한다. 로그인 화면이 찍혔으면 실패다(가짜 PASS 금지).
4. 필드 순서처럼 DOM으로 확인 가능한 것은 `--dump-dom` 결과에서 `data-fieldname` 순서를 함께 증거로 남긴다.
- sid는 보고서·로그에 남기지 않는다. 스크린샷에는 테스트 데이터만 나와야 한다.
