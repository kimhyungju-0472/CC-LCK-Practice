"""
LCK 경기 결과 Discord 알림 (Webhook 방식, 초보자용)

이 파일은 1단계에서 만든 lck_match_results.json의 **실제 데이터만** 읽어서
Discord 채널로 보냅니다. 봇 계정, 봇 토큰, 추가 라이브러리는 필요 없습니다.

보안 규칙
  * 웹훅 URL은 코드에 절대 적지 않습니다.
  * 로컬: 환경 변수 DISCORD_WEBHOOK_URL 사용
  * Colab: Secrets(보안 비밀)의 DISCORD_WEBHOOK_URL 사용
  * URL이 없으면 전송하지 않고 설정 방법만 안내합니다.
  * URL이나 토큰이 화면/오류 메시지에 노출되지 않도록 Always redact()를 거칩니다.

오류 규칙
  * 인증 실패(401), 권한 부족(403), 웹훅 없음(404), 요청 제한(429) -> 즉시 중단
  * 접근 제한을 우회하지 않고, 가짜 데이터를 만들지 않습니다.
  * Liquipedia API를 다시 호출하거나 다른 사이트를 탐색하지 않습니다.

실행 방법(로컬 PowerShell 예시):
    $env:DISCORD_WEBHOOK_URL="여기에_웹훅_URL_입력"
    python discord_bot.py
"""

# %% CELL: 설정
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

DATA_FILE = Path("lck_match_results.json")
WEBHOOK_ENV_NAME = "DISCORD_WEBHOOK_URL"  # 값은 코드에 쓰지 않고 환경/Secrets에서 읽는다.

# Discord 제한값 (공식 문서 기준)
MAX_CONTENT_LENGTH = 2000   # 메시지 본문
MAX_EMBEDS = 10             # 메시지 1개당 Embed 개수
MAX_EMBED_TOTAL = 6000      # Embed 전체 글자 수 합계
MAX_TITLE_LENGTH = 256
MAX_DESCRIPTION_LENGTH = 4096
MAX_FIELD_NAME_LENGTH = 256
MAX_FIELD_VALUE_LENGTH = 1024

DISCORD_MAX_RETRIES = 2     # 일시적 네트워크/5xx 오류만 재시도
RETRY_DELAY_SECONDS = 2
DISCORD_TIMEOUT_SECONDS = 15
DISCORD_USER_AGENT = "CC-LCK-Practice-Discord/1.0 (https://github.com/kimhyungju-0472/CC-LCK-Practice)"
REDACTED = "[웹훅 URL 숨김]"


# %% CELL: 보안과 데이터 읽기
class DiscordError(Exception):
    """사용자에게 보고해야 하는 Discord 알림 오류."""

    def __init__(self, stage: str, message: str, cause: str, solution: str):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.cause = cause
        self.solution = solution


def redact(text, webhook_url: str = "") -> str:
    """웹훅 URL/토큰을 어떤 출력에도 남기지 않는다."""
    safe = str(text)
    if webhook_url:
        safe = safe.replace(webhook_url, REDACTED)
    # requests 오류 메시지에 URL 경로가 들어가는 경우도 있다.
    safe = re.sub(r"https?://(?:canary\.)?discord(?:app)?\.com/api/webhooks/\S+", REDACTED, safe)
    return safe


def get_webhook_url() -> str:
    """로컬 환경 변수 -> Colab Secrets 순서로 웹훅 URL을 읽는다."""
    url = os.environ.get(WEBHOOK_ENV_NAME, "").strip()
    if url:
        return url

    # Colab에서는 좌측 🔑(Secrets)에 같은 이름으로 저장해 둔다.
    try:
        from google.colab import userdata
        url = (userdata.get(WEBHOOK_ENV_NAME) or "").strip()
        return url
    except Exception:
        # Colab이 아니거나 비밀이 아직 없으면 빈 문자열로 처리한다.
        return ""


def print_setup_guide() -> None:
    """웹훅 URL이 없을 때 설정 방법만 안내한다(가짜 URL은 만들지 않는다)."""
    print("전송 결과: 건너뜀 (실제 전송하지 않았습니다)")
    print(f"설정 방법 ({WEBHOOK_ENV_NAME}):")
    print("  - 로컬 PowerShell: $env:DISCORD_WEBHOOK_URL='여기에_웹훅_URL_입력'")
    print("  - 로컬 macOS/Linux: export DISCORD_WEBHOOK_URL='여기에_웹훅_URL_입력'")
    print("  - Colab: 왼쪽 🔑 Secrets에 DISCORD_WEBHOOK_URL 추가 후 '노트북 액세스' 허용")
    print("  - Discord: 채널 설정 → 연동 → 웹후크 → 새 웹후크 → URL 복사")


def discord_print_error_report(error: DiscordError, webhook_url: str = "") -> None:
    """오류 단계/실제 내용/원인/해결 방법을 한글로 보고한다."""
    print("\n" + "=" * 68)
    print("Discord 알림을 중단했습니다. (가짜 데이터/우회 시도 없음)")
    print("=" * 68)
    print(f"1) 발생 단계 : {redact(error.stage, webhook_url)}")
    print(f"2) 실제 내용 : {redact(error.message, webhook_url)}")
    print(f"3) 원인      : {redact(error.cause, webhook_url)}")
    print(f"4) 해결 방법 : {redact(error.solution, webhook_url)}")
    print("전송 결과: 실패")
    print("=" * 68)


def validate_webhook_url(url: str) -> None:
    """Discord 웹훅 형식인지 확인한다. URL 값은 절대 출력하지 않는다."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed_hosts = {"discord.com", "discordapp.com", "canary.discord.com"}
    if (
        parsed.scheme != "https"
        or host not in allowed_hosts
        or not parsed.path.startswith("/api/webhooks/")
    ):
        raise DiscordError(
            "웹훅 URL 확인",
            "설정된 값이 Discord Webhook 주소 형식이 아닙니다. (값은 표시하지 않습니다)",
            "환경 변수/Secrets에 Discord 웹후크 URL이 아닌 값이 들어갔습니다.",
            "Discord 채널 설정에서 복사한 웹후크 URL을 다시 설정하세요.",
        )


def load_results() -> dict:
    """1단계에서 저장한 JSON만 읽는다(API 호출 없음)."""
    if not DATA_FILE.exists():
        raise DiscordError(
            "JSON 읽기",
            f"결과 파일이 없습니다: {DATA_FILE.name}",
            "lck_collector.py를 먼저 실행하지 않았거나 파일 위치가 다릅니다.",
            "python lck_collector.py 실행 후 다시 시도하세요.",
        )
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise DiscordError(
            "JSON 읽기",
            redact(str(exc)),
            "JSON 파일이 깨졌거나 읽을 수 없습니다.",
            "lck_collector.py로 결과를 다시 저장하세요.",
        ) from exc

    if not isinstance(data, dict) or not isinstance(data.get("경기결과"), list):
        raise DiscordError(
            "JSON 확인",
            "경기결과 목록을 찾을 수 없습니다.",
            "JSON 구조가 예상과 다릅니다.",
            "lck_match_results.json에 '경기결과' 배열이 있는지 확인하세요.",
        )
    return data


# %% CELL: 메시지 만들기
def cut(text, limit: int) -> str:
    """Discord 글자 제한에 맞게 자른다."""
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def team_names(match: dict) -> tuple[str, str]:
    teams = match.get("팀", [])
    if isinstance(teams, list) and len(teams) == 2:
        return str(teams[0]), str(teams[1])
    return "팀 정보 없음", "팀 정보 없음"


def make_fields(data: dict) -> list[dict]:
    """경기 1건을 Discord Embed 필드 1개로 바꾼다."""
    fields = []
    for index, match in enumerate(data.get("경기결과", []), 1):
        team1, team2 = team_names(match)
        date = match.get("날짜_KST") or "날짜 확인 불가"
        score = match.get("최종점수") or "점수 정보 없음"
        winner = match.get("승리팀") or "승리팀 정보 없음"
        link = match.get("출처링크") or ""

        name = cut(f"{index}. {date} | {team1} {score} {team2}", MAX_FIELD_NAME_LENGTH)
        value = f"🏆 승리: **{cut(winner, 200)}**"
        if link:
            value += f"\n🔗 [경기 출처]({cut(link, 300)})"
        fields.append({"name": name, "value": cut(value, MAX_FIELD_VALUE_LENGTH), "inline": False})
    return fields


def build_embeds(data: dict) -> list[dict]:
    """필드를 여러 Embed로 나눠 Discord 전체 길이 제한(6000자)을 지킨다."""
    tournament = data.get("대회", {}) if isinstance(data.get("대회"), dict) else {}
    title = cut(f"🏆 {tournament.get('이름', '대회명 정보 없음')} 경기 결과", MAX_TITLE_LENGTH)
    description = cut(
        f"종료일 {tournament.get('종료일', '종료일 정보 없음')} · 최신 {len(data.get('경기결과', []))}건",
        MAX_DESCRIPTION_LENGTH,
    )
    footer_text = cut(data.get("출처_표기", "자료 출처: Liquipedia (CC BY-SA 3.0)"), 200)

    def make_embed(group: list[dict]) -> dict:
        return {
            "title": title,
            "description": description,
            "color": 0x5865F2,  # Discord 블루
            "fields": group,
            "footer": {"text": footer_text},
        }

    def fixed_size() -> int:
        return len(title) + len(description) + len(footer_text)

    embeds = []
    group = []
    group_size = 0
    total_size = 0

    for field in make_fields(data):
        field_size = len(field["name"]) + len(field["value"])
        would_exceed = (
            len(group) >= 5
            or fixed_size() + group_size + field_size > MAX_EMBED_TOTAL
            or total_size + fixed_size() + group_size + field_size > MAX_EMBED_TOTAL
        )
        if group and would_exceed:
            embeds.append(make_embed(group))
            total_size += fixed_size() + group_size
            group, group_size = [], 0
        group.append(field)
        group_size += field_size

    if group:
        embeds.append(make_embed(group))

    if not embeds:
        raise DiscordError(
            "메시지 구성",
            "보낼 경기 결과가 0건입니다.",
            "JSON의 경기결과가 비어 있습니다.",
            "lck_collector.py로 경기 결과를 다시 수집하세요.",
        )
    if len(embeds) > MAX_EMBEDS:
        raise DiscordError(
            "메시지 구성",
            f"Embed가 {len(embeds)}개로 Discord 제한({MAX_EMBEDS}개)을 넘었습니다.",
            "경기 수가 너무 많습니다.",
            "json의 경기결과를 5건 이하로 줄이거나 메시지를 나눠 보내세요.",
        )
    return embeds


def build_payload(data: dict) -> dict:
    """최종 Discord 전송 데이터를 만든다."""
    tournament = data.get("대회", {}) if isinstance(data.get("대회"), dict) else {}
    count = len(data.get("경기결과", []))
    name = tournament.get("이름", "대회명 정보 없음")
    content = cut(f"📢 LCK 경기 결과 알림 · {name} · {count}건", MAX_CONTENT_LENGTH)
    return {"content": content, "embeds": build_embeds(data)}


# %% CELL: 전송과 실행
def send_webhook(url: str, payload: dict) -> None:
    """웹훅으로 POST 전송한다. 성공/실패 여부를 화면에 출력한다."""
    for attempt in range(DISCORD_MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json", "User-Agent": DISCORD_USER_AGENT},
                timeout=DISCORD_TIMEOUT_SECONDS,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt < DISCORD_MAX_RETRIES:
                print(f"  [재시도 {attempt + 1}/{DISCORD_MAX_RETRIES}] 일시적 네트워크 오류")
                time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
                continue
            raise DiscordError(
                "Discord 전송",
                redact(str(exc), url),
                "일시적인 네트워크 오류가 재시도 후에도 해결되지 않았습니다.",
                "인터넷 연결을 확인하고 잠시 후 다시 실행하세요.",
            ) from exc

        if response.status_code in (200, 204):
            print(f"✅ Discord 전송 성공 (HTTP {response.status_code})")
            print("전송 결과: 성공")
            return

        body = redact(response.text[:300], url)
        status = response.status_code
        if status in (401, 403, 404, 429):
            raise DiscordError(
                "Discord 전송",
                f"HTTP {status}: {body}",
                "인증 실패, 권한 부족, 웹훅 접근 제한 또는 요청 제한입니다.",
                "웹훅 URL과 채널 권한을 확인하고 잠시 후 다시 시도하세요. 우회 시도는 하지 마세요.",
            )
        if 500 <= status <= 599 and attempt < DISCORD_MAX_RETRIES:
            print(f"  [재시도 {attempt + 1}/{DISCORD_MAX_RETRIES}] Discord 서버 오류 (HTTP {status})")
            time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
            continue
        if status == 400:
            raise DiscordError(
                "Discord 전송",
                f"HTTP {status}: {body}",
                "메시지 형식이 Discord 제한을 넘었습니다.",
                "Embed 길이와 개수를 줄이세요(본문 2000자, Embed 합계 6000자).",
            )
        raise DiscordError(
            "Discord 전송",
            f"HTTP {status}: {body}",
            "Discord가 요청을 처리하지 못했습니다.",
            "상태 코드를 확인하고 잠시 후 다시 실행하세요.",
        )


def discord_main():
    """URL 확인 -> JSON 읽기 -> 메시지 구성 -> 전송."""
    url = get_webhook_url()
    if not url:
        print("❌ Discord 전송을 건너뜁니다. 웹훅 URL이 설정되지 않았습니다.")
        print_setup_guide()
        return None  # 실패도 성공도 아닌 '미전송'

    try:
        validate_webhook_url(url)
        data = load_results()
        payload = build_payload(data)
        print(
            f"메시지 구성 완료: 본문 {len(payload['content'])}자 / "
            f"Embed {len(payload['embeds'])}개 / 경기 {len(data.get('경기결과', []))}건"
        )
        send_webhook(url, payload)
        return True
    except DiscordError as error:
        discord_print_error_report(error, url)
        return False


def discord_notebook_main():
    """Colab 노트북에서 호출하는 진입점."""
    return discord_main()


# %% SCRIPT_ONLY
if __name__ == "__main__":
    result = discord_main()
    sys.exit(0 if result is not False else 1)
