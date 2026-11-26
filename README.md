# CC-LCK-Practice (GDGoC C&C 오픈세션 실습)

초보자를 위한 **LCK 경기 결과 수집 + Discord 알림 + GitHub Actions 자동화** 실습 프로젝트입니다.

- 자료 출처: Liquipedia League of Legends Wiki (CC BY-SA 3.0)
- 수집 방식: Liquipedia **MediaWiki API** (API 키 없음)
- 알림 방식: **Discord Webhook** (봇 계정/봇 토큰 없음)

> **이용약관 주의**
> Liquipedia는 MediaWiki API의 비(非)편집 목적 사용을 공식 지원하지 않고, 데이터 목적은 승인된
> LiquipediaDB API를 권장합니다. 이 프로젝트는 접근이 실제로 막히면 즉시 중단하도록 만들어진
> **실습용**입니다. 실제 서비스에서는 API 키 신청이 필요합니다.

---

## 현재 단계

| 단계 | 상태 | 내용 |
|---|---|---|
| 1단계 | 완료 | `lck_collector.py`로 최근 종료된 LCK 대회 경기 5건 수집 → `lck_match_results.json` 저장 |
| 2단계 | 완료 | `discord_bot.py`가 위 JSON을 읽어 Discord Webhook으로 전송 (로컬 실제 전송 확인됨) |
| 3단계 | 구현 완료 | GitHub Actions 수동 실행용 워크플로 추가. **초기에는 기존 JSON 전송만 활성화** |

---

## 파일 설명

| 파일 | 설명 |
|---|---|
| `lck_collector.py` | 1단계 데이터 수집기. API 요청 간격(2초/parse 30초), 캐시, 오류 중단 규칙 포함 |
| `lck_match_results.json` | 실제 수집 결과. Discord 알림과 Actions 테스트가 이 파일을 사용 |
| `lck_collector_colab.ipynb` | Google Colab용 노트북. 수집 셀 + Discord 전송 셀 포함 |
| `discord_bot.py` | 2단계 Discord Webhook 알림. 환경 변수/Secrets에서 URL 읽기, 토큰 숨김 처리 |
| `requirements.txt` | `requests`, `beautifulsoup4` (Discord는 별도 라이브러리 불필요) |
| `.github/workflows/lck_discord.yml` | 3단계 GitHub Actions 워크플로 (수동 실행 기본, 스케줄은 주석) |
| `.gitignore` | `lck_cache/` 등 자동 생성 폴더 제외 |
| `README.md` | 이 문서 |

---

## 로컬에서 실행하기

### 1. 라이브러리 설치

```powershell
python -m pip install -r requirements.txt
```

### 2. 데이터 수집 (1단계)

```powershell
python lck_collector.py
```

성공하면 `lck_match_results.json`이 갱신되고 화면에 경기 5건이 출력됩니다.

### 3. Discord 알림 (2단계)

Discord 채널 설정 → **연동 → 웹후크 → 새 웹후크**에서 URL을 복사한 뒤:

```powershell
$env:DISCORD_WEBHOOK_URL="여기에_복사한_웹훅_URL_입력"
python discord_bot.py
```

- 성공하면 `✅ Discord 전송 성공 (HTTP 204)`가 출력됩니다.
- URL이 없으면 전송하지 않고 설정 방법만 안내합니다.
- **웹훅 URL은 절대 코드나 JSON에 저장하지 마세요.**

Colab에서는 왼쪽 🔑(Secrets)에 `DISCORD_WEBHOOK_URL`을 등록하고 **노트북 액세스**를 허용한 뒤,
`lck_collector_colab.ipynb`의 7단계 셀을 실행합니다.

---

## GitHub Desktop으로 Commit & Push 하기

처음 파일을 올릴 때 순서입니다.

1. **GitHub Desktop**을 실행하고 이 저장소(`CC-LCK-Practice`)를 엽니다.
   - 저장소가 목록에 없다면 `File → Add Local Repository`에서 이 폴더를 선택합니다.
2. 왼쪽 **Changes** 탭에서 추가/수정된 파일에 체크합니다.
   - 예: `README.md`, `.github/workflows/lck_discord.yml`, `discord_bot.py` 등
   - `lck_cache/`와 `__pycache__/`는 `.gitignore` 때문에 표시되지 않습니다(정상).
3. 아래 **Summary**에 변경 내용을 한 줄로 씁니다.
   - 예: `Add GitHub Actions workflow and README`
4. **Commit to main** (또는 현재 브랜치 이름) 버튼을 누릅니다.
5. 오른쪽 위 **Push origin** 버튼을 누릅니다.
6. 브라우저에서 `https://github.com/<본인계정>/CC-LCK-Practice`에 접속해 파일이 올라갔는지 확인합니다.
7. **Actions** 탭을 누르면 워크플로가 보입니다.

> Commit은 내 컴퓨터에 기록을 남기는 것, Push는 GitHub에 올리는 것입니다. 둘 다 해야 Actions가 실행됩니다.

---

## GitHub Repository Secrets 등록 (DISCORD_WEBHOOK_URL)

Actions에서 Discord로 전송하려면 웹훅 URL을 **저장소 비밀**로 등록해야 합니다.

1. GitHub 저장소 페이지 → **Settings** 클릭
2. 왼쪽 메뉴에서 **Secrets and variables → Actions** 클릭
3. **New repository secret** 클릭
4. 이름에 정확히 `DISCORD_WEBHOOK_URL` 입력
5. Secret 값에 Discord에서 복사한 웹훅 URL 붙여넣기
6. **Add secret** 클릭

주의 사항

- 이름의 오타(예: `DISCORD_WEBHOOK`)는 동작하지 않습니다.
- 등록된 값은 다시 화면에 표시되지 않습니다.
- Actions 로그에서도 GitHub가 자동으로 마스킹하고, 코드에서도 값을 출력하지 않습니다.
- URL이 로그에 보이면 즉시 Discord에서 웹훅을 삭제하고 새로 만들어 다시 등록하세요.

---

## GitHub Actions 수동 실행 방법

1. 저장소 → **Actions** 탭 클릭
2. 왼쪽 목록에서 **LCK 수집 및 Discord 알림** 클릭
3. 오른쪽 **Run workflow** 버튼 클릭
4. 브랜치 선택 (보통 `main`)
5. 입력값 선택
   - **mode**
     - `notify-only` **(기본, 처음에는 이것만 사용)**: 저장소에 있는 기존 `lck_match_results.json`을 읽어 Discord로 전송합니다. 신규 수집은 하지 않습니다.
     - `collect-and-notify`: 신규 데이터를 수집한 뒤 전송합니다. 초기에는 비활성화되어 있어 실행하면 안내 메시지와 함께 중단됩니다.
   - **force_notify**: 같은 JSON이어도 알림을 다시 보내고 싶을 때만 체크합니다.
6. **Run workflow** 클릭
7. 실행 목록에서 맨 위 실행을 클릭한 뒤 **lck-discord** 작업을 클릭하면 단계별 로그가 보입니다.

---

## 실행 결과 및 오류 확인 방법

- 초록색 ✅ : 단계 성공 / 빨간색 ❌ : 단계 실패
- 각 단계를 클릭하면 실제 로그가 열립니다.
  - `실행 모드: notify-only`
  - `사용할 JSON: 경기 5건 / 대회 LCK 2026 Season`
  - `✅ Discord 전송 성공 (HTTP 204)`
- 실행 페이지 아래/오른쪽 **Summary**에 요약(모드, 데이터 해시 앞 12자리, 전송 여부)이 표시됩니다.
- `::error::`로 시작하는 빨간 메시지는 중단 이유입니다.

자주 보는 메시지

| 로그 메시지 | 원인 | 해결 방법 |
|---|---|---|
| `신규 데이터 수집이 아직 비활성화되어 있습니다` | `collect-and-notify`를 선택했지만 변수가 꺼져 있음 | `notify-only`로 다시 실행하거나, 활성화 절차 진행 |
| `Repository Secrets에 DISCORD_WEBHOOK_URL이 없습니다` | Secret 미등록/오타 | 위 Secrets 등록 절차 확인 |
| `HTTP 401 / 403 / 404 / 429` | 웹훅 권한·주소·요청 제한 문제 | 웹훅을 다시 만들거나 잠시 후 재시도. 우회 금지 |
| `수집 결과가 갱신되지 않았습니다` | 수집 실패로 오래된 JSON이 남음 | 오래된 JSON을 전송하지 않고 중단됨. 수집 로그 확인 |
| `동일한 JSON이 이미 전송되었습니다` | 중복 알림 방지가 작동함 | 의도적으로 다시 보내려면 `force_notify` 체크 |

웹훅 URL이나 토큰은 코드·YAML·로그 어디에도 출력되지 않습니다.

---

## 중복 실행 및 중복 알림 방지

- **중복 실행 방지**: 워크플로에 `concurrency`를 설정했습니다. 같은 워크플로가 동시에 실행되면 새 실행이 대기하고, 진행 중인 실행을 취소하지 않습니다.
- **중복 알림 방지**: `lck_match_results.json`의 SHA-256 해시를 계산해 GitHub Actions 캐시에 저장합니다. 같은 JSON이면 Discord 전송 단계를 건너뜁니다.
- **강제 전송**: Run workflow에서 `force_notify`를 체크한 경우에만 중복 검사를 건너뜁니다.

## 오래된 데이터 전송 방지

- `collect-and-notify` 모드에서는 수집 시작 시각을 기록한 뒤, 수집 후 JSON 수정 시각이 더 최신인지 확인합니다.
- 수집이 실패하면 `lck_collector.py`가 JSON을 덮어쓰지 않고 종료되며, 다음 단계(전송)는 실행되지 않습니다.
- `notify-only` 모드는 **테스트용**으로 기존 JSON을 의도적으로 사용합니다. 새 결과로 오인하지 마세요.

---

## 자동 실행 활성화 조건과 방법

### 활성화 전 확인할 조건

1. **Liquipedia 이용정책/사용 권한 확인**
   - MediaWiki API는 비편집 목적 사용이 공식 지원되지 않습니다.
   - 계속 접근이 거부되면 수집기는 즉시 중단됩니다. 우회하지 마세요.
   - 실제 서비스에서는 승인된 LiquipediaDB API(키 필요)로 전환해야 합니다.
2. **Discord Webhook 정상 동작 확인**
   - 로컬에서 `python discord_bot.py`가 HTTP 204로 성공하는지 확인합니다.
   - Repository Secrets에 `DISCORD_WEBHOOK_URL`이 등록되어 있어야 합니다.
3. **수동 `collect-and-notify` 1회 성공 확인**

### 활성화 방법

1. 저장소 **Settings → Secrets and variables → Variables → New repository variable**
2. 이름 `ENABLE_LCK_COLLECTION`, 값 `true` 등록
3. `.github/workflows/lck_discord.yml`에서 아래 주석을 해제합니다.

   ```yaml
   schedule:
     - cron: '0 0 * * *'   # 매일 오전 9시 KST (UTC 00:00)
   ```

4. GitHub Desktop으로 Commit & Push 합니다.
5. Actions에서 수동으로 `collect-and-notify`를 한 번 더 실행해 확인합니다.
6. 다음 날 오전 9시(KST)에 자동 실행되는지 확인합니다.

다시 끄려면 `ENABLE_LCK_COLLECTION`을 `false`로 바꾸거나 `schedule`을 다시 주석 처리하고 Push하세요.

---

## 이번 단계 범위

- **포함**: GitHub Actions 워크플로(`notify-only` 수동 실행), README
- **제외**: 웹사이트 제작, 실제 GitHub Actions 실행, Commit/Push, Secrets/Variables 등록
  (이 단계는 사용자가 직접 진행합니다.)
- 기존 데이터 수집기와 Discord 알림 코드는 수정하지 않았습니다.
