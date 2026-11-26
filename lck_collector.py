"""
LCK 경기 결과 수집기 (초보자용)

이 스크립트는 Liquipedia 리그오브레전드 위키의 MediaWiki API만 사용합니다.
API 키는 필요 없지만, 아래 이용 규칙을 반드시 지킵니다.

  * 일반 요청: 2초에 1번 이하 / action=parse 요청: 30초에 1번 이하
  * 요청 결과는 lck_cache/ 폴더에 캐시해 재요청을 줄입니다.
  * 사용자 이름(User-Agent)에 프로젝트와 연락처를 넣습니다.
  * 접근 거부(401/403/429)나 인증 요구가 나오면 즉시 중단합니다.
  * 일시적인 오류(네트워크 끊김, 5xx)만 2번까지 재시도합니다.
  * 다른 수집처로 바꾸거나 가짜 데이터를 만들지 않습니다.

주의(중요): Liquipedia 공식 이용약관은 "MediaWiki API의 비(非)편집 목적 사용은
지원하지 않는다"고 안내합니다(데이터 목적은 승인된 LiquipediaDB API 사용 권장).
이 실습은 키 없이 접근이 가능한 MediaWiki API의 기술적 제한을 지키며 수행되며,
접근이 제한되는 순간 즉시 멈추도록 만들어졌습니다. 실제 서비스에서는
LiquipediaDB API 키를 신청하는 것을 권장합니다.

실행 방법:
    pip install -r requirements.txt
    python lck_collector.py

결과 파일: lck_match_results.json
"""

# %% CELL: 설정
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

# ---- 자주 바꾸는 설정값 ----------------------------------------------------
API_URL = "https://liquipedia.net/leagueoflegends/api.php"
WIKI_BASE = "https://liquipedia.net"
KST = timezone(timedelta(hours=9))  # 한국 표준시(UTC+9)

# 다른 사람이 사용한다면 아래 연락처를 본인 것(예: GitHub 이슈 주소)으로 바꿔 주세요.
USER_AGENT = (
    "CC-LCK-Practice-Study/1.0 "
    "(https://github.com/kimhyungju-0472/CC-LCK-Practice; contact: GitHub Issues)"
)

MATCH_COUNT = 5                       # 수집할 경기 수
CACHE_DIR = Path("lck_cache")         # API 응답 캐시 폴더
OUTPUT_FILE = Path("lck_match_results.json")
CACHE_TTL_SECONDS = 24 * 60 * 60      # 캐시 유효 기간: 24시간
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 2                       # 일시적 오류 재시도 횟수
DATE_UNKNOWN = "날짜 확인 불가"


# %% CELL: 오류와 요청 관리
class CollectorError(Exception):
    """수집 중 사용자가 확인해야 하는 오류를 담는다."""

    def __init__(self, stage: str, message: str, cause: str, solution: str):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.cause = cause
        self.solution = solution


class AccessBlockedError(CollectorError):
    """인증/권한/요청 제한처럼 즉시 멈춰야 하는 오류."""

    def __init__(self, stage: str, message: str):
        super().__init__(
            stage=stage,
            message=message,
            cause="Liquipedia API가 접근을 거부했습니다. (인증 요구, 권한 부족, 요청 제한 등)",
            solution=(
                "요청 간격(일반 2초, parse 30초)을 지키고 캐시를 사용하세요. "
                "계속 거부되면 Liquipedia 관리자에게 문의하거나 승인된 LiquipediaDB API를 신청하세요. "
                "접근 제한을 우회하는 시도는 하지 마세요."
            ),
        )


def print_error_report(error: CollectorError) -> None:
    """오류 발생 단계/실제 메시지/원인/해결 방법을 한글로 출력한다."""
    print("\n" + "=" * 68)
    print("데이터 수집을 중단했습니다. (가짜 데이터는 만들지 않습니다)")
    print("=" * 68)
    print(f"1) 발생 단계     : {error.stage}")
    print(f"2) 실제 오류     : {error.message}")
    print(f"3) 원인          : {error.cause}")
    print(f"4) 해결 방법     : {error.solution}")
    print("=" * 68)


class RateLimiter:
    """API 종류별 최소 요청 간격을 지킨다."""

    # 이용약관: 일반 1 req/2s, action=parse 1 req/30s (여유초를 더함)
    MIN_INTERVAL = {"query": 2.2, "parse": 30.5}
    DENIED_MARKERS = ("auth", "permission", "forbidden", "blocked", "denied", "rate limit")

    def __init__(self):
        self.last_request = {"query": 0.0, "parse": 0.0}

    def wait(self, kind: str) -> None:
        if kind not in self.MIN_INTERVAL:
            kind = "query"
        gap = self.MIN_INTERVAL[kind] - (time.monotonic() - self.last_request[kind])
        if gap > 0:
            time.sleep(gap)
        self.last_request[kind] = time.monotonic()


class LiquipediaClient:
    """캐시와 재시도를 곁들인 아주 작은 API 클라이언트."""

    def __init__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.limiter = RateLimiter()
        self.session = requests.Session()  # 연결을 재사용한다(이용약관 권장)

    def _cache_path(self, params: dict) -> Path:
        key = json.dumps(params, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return CACHE_DIR / (hashlib.sha256(key).hexdigest()[:20] + ".json")

    def _read_cache(self, path: Path):
        if not path.exists():
            return None
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - saved.get("saved_at", 0) < CACHE_TTL_SECONDS:
                return saved["payload"]
        except (ValueError, KeyError, OSError):
            pass  # 깨진 캐시는 무시하고 새로 요청한다
        return None

    def _write_cache(self, path: Path, payload: dict) -> None:
        try:
            path.write_text(
                json.dumps({"saved_at": time.time(), "payload": payload}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass  # 캐시 저장 실패는 수집 자체를 막지 않는다

    def get(self, params: dict, stage: str, kind: str = "query") -> dict:
        """GET 요청을 보내고 JSON을 돌려준다. 접근 거부는 즉시 예외를 던진다."""
        request_params = dict(params, format="json", formatversion=2)
        cache_path = self._cache_path(request_params)
        cached = self._read_cache(cache_path)
        if cached is not None:
            print(f"  [캐시 사용] {stage}")
            return cached

        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            self.limiter.wait(kind)
            try:
                response = self.session.get(
                    API_URL,
                    params=request_params,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept-Encoding": "gzip, deflate",  # 응답 크기 줄이기
                        "Accept": "application/json",
                    },
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = response.json()
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else "?"
                body = exc.response.text[:400] if exc.response is not None else ""
                detail = f"HTTP {status}: {exc} / 응답 앞부분: {body}"
                if status in (401, 403, 429):
                    raise AccessBlockedError(stage, detail) from exc
                if isinstance(status, int) and 500 <= status <= 599 and attempt < MAX_RETRIES:
                    last_error = detail
                    print(f"  [재시도 {attempt + 1}/{MAX_RETRIES}] 서버 오류: {detail[:120]}")
                    continue
                raise CollectorError(
                    stage,
                    detail,
                    "서버가 요청을 처리하지 못했습니다.",
                    "잠시 후 다시 실행해 보세요. 요청 간격은 자동으로 지켜집니다.",
                ) from exc
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = str(exc)
                if attempt < MAX_RETRIES:
                    print(f"  [재시도 {attempt + 1}/{MAX_RETRIES}] 네트워크 오류: {exc}")
                    continue
                raise CollectorError(
                    stage,
                    str(exc),
                    "일시적인 네트워크 오류가 2회 재시도 후에도 해결되지 않았습니다.",
                    "인터넷 연결을 확인하고 잠시 후 다시 실행하세요.",
                ) from exc
            except ValueError as exc:
                raise CollectorError(
                    stage,
                    str(exc),
                    "API가 JSON 대신 다른 형식을 반환했습니다.",
                    "Liquipedia API 상태를 확인하고 잠시 후 다시 실행하세요.",
                ) from exc

            if isinstance(payload, dict) and "error" in payload:
                api_error = payload["error"]
                message = api_error.get("message", str(api_error)) if isinstance(api_error, dict) else str(api_error)
                if any(word in message.lower() for word in self.limiter.DENIED_MARKERS):
                    raise AccessBlockedError(stage, f"API 오류: {message}")
                raise CollectorError(
                    stage,
                    f"API 오류: {message}",
                    "API가 요청을 거부했습니다.",
                    "요청 파라미터와 이용약관을 확인하세요.",
                )

            self._write_cache(cache_path, payload)
            return payload

        raise CollectorError(
            stage,
            str(last_error),
            "재시도 후에도 응답을 받지 못했습니다.",
            "네트워크 상태를 확인하고 잠시 후 다시 실행하세요.",
        )


# %% CELL: 대회 찾기
def get_wikitext(client: LiquipediaClient, title: str, stage: str) -> str:
    """문서의 위키 텍스트(원본 문법)를 가져온다. 없는 문서는 빈 문자열."""
    payload = client.get(
        {
            "action": "query",
            "titles": title,
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
        },
        stage=stage,
    )
    pages = payload.get("query", {}).get("pages", [])
    if not pages:
        return ""
    content = pages[0].get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("content", "")
    return content or ""


def find_latest_completed_tournament(client: LiquipediaClient):
    """오늘(KST) 기준으로 이미 끝난 가장 최근 LCK 대회를 찾는다."""
    today = datetime.now(KST).date()

    # LCK/2026, LCK/2026/Cup 처럼 '대회 대표 문서'만 후보로 본다.
    # 아카데미/통계/선수 문서는 제외된다.
    for year in range(today.year, today.year - 6, -1):
        candidates = []
        for suffix in ("", "/Cup"):
            title = f"LCK/{year}{suffix}"
            wikitext = get_wikitext(client, title, f"대회 확인 ({title})")
            if not wikitext:
                continue

            end_match = re.search(r"\|\s*edate\s*=\s*(\d{4}-\d{2}-\d{2})", wikitext)
            if not end_match:
                continue
            end_date = datetime.strptime(end_match.group(1), "%Y-%m-%d").date()
            if end_date > today:  # 아직 끝나지 않은 대회는 제외
                continue

            name_match = re.search(r"\|\s*name\s*=\s*([^\n|}]+)", wikitext)
            name = name_match.group(1).strip() if name_match else title.replace("/", " ")

            candidates.append(
                {
                    "name": name,
                    "page": title,
                    "end_date": end_date.isoformat(),
                    "url": f"{WIKI_BASE}/leagueoflegends/{quote(title.replace(' ', '_'))}",
                    "wikitext": wikitext,
                }
            )

        if candidates:
            latest = max(candidates, key=lambda item: item["end_date"])
            print(f"대회 선택: {latest['name']} (종료일 {latest['end_date']}, {latest['page']})")
            return latest

    raise CollectorError(
        "대회 선택",
        "최근 6년 안에서 종료일이 확인되는 LCK 대회를 찾지 못했습니다.",
        "위키 문서에 edate(종료일)가 없거나 아직 진행 중인 대회뿐입니다.",
        "위키 문서 구조를 확인하거나 날짜가 지난 뒤 다시 실행하세요.",
    )


def extract_stage_titles(tournament: dict) -> list[str]:
    """대회 문서의 탭 링크에서 경기 단계(하위 문서) 제목을 뽑는다."""
    links = re.findall(r"\|\s*link\d+\s*=\s*/([^\n|}]+)", tournament["wikitext"])
    stages = []
    for link in links:
        stage = link.strip().replace("_", " ")
        if not stage or stage.startswith("{"):
            continue
        title = f"{tournament['page']}/{stage}"
        if title not in stages:
            stages.append(title)
    return stages


# %% CELL: 경기 결과 파싱
def kst_date_from_timestamp(timestamp: str | None, timer_text: str) -> str:
    """경기 시각을 KST 날짜(YYYY-MM-DD)로 바꾼다. 확인 불가면 정해진 문구."""
    if timestamp:
        try:
            dt = datetime.fromtimestamp(int(timestamp), timezone.utc).astimezone(KST)
            return dt.strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError, OverflowError):
            pass

    # 데이터 속성이 없을 때: 화면에 보이는 'September 13, 2026 ... KST'를 사용
    match = re.search(r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", timer_text)
    if match and "KST" in timer_text:
        try:
            return datetime.strptime(match.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
    return DATE_UNKNOWN


def parse_matches(html: str, page_title: str) -> list[dict]:
    """action=parse가 돌려준 HTML에서 경기 결과를 읽는다."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for block in soup.select("div.brkts-match"):
        # 한 경기는 팀 2개가 들어 있는 블록이다.
        entries = block.find_all("div", class_="brkts-opponent-entry", recursive=False)
        if len(entries) != 2:
            continue

        names, scores = [], []
        for entry in entries:
            name_tag = (
                entry.select_one(".team-name")
                or entry.select_one(".team-bracketname")
                or entry.select_one(".team-shortname")
            )
            score_tag = entry.select_one(".brkts-opponent-score-inner")
            names.append(name_tag.get_text(" ", strip=True) if name_tag else "")
            scores.append(score_tag.get_text(strip=True) if score_tag else "")

        # 이름/점수가 빠진 경기는 추측하지 않고 건너뛴다.
        if not all(names) or not all(scores):
            continue

        winner_index = None
        for index, entry in enumerate(entries):
            if entry.select_one(".brkts-opponent-win"):
                winner_index = index
                break
        if winner_index is None and scores[0] != scores[1]:
            # 승리 표시가 없으면 점수로 판단한다(추측이 아니라 명시된 점수 사용).
            winner_index = 0 if int(scores[0]) > int(scores[1]) else 1

        winner = names[winner_index] if winner_index is not None else "승리팀 확인 불가"

        timer = block.select_one(".timer-object")
        timer_text = timer.get_text(" ", strip=True) if timer else ""
        date_kst = kst_date_from_timestamp(timer.get("data-timestamp") if timer else None, timer_text)
        try:
            timestamp = int(timer["data-timestamp"]) if timer and timer.get("data-timestamp") else None
        except (TypeError, ValueError):
            timestamp = None

        match_link = block.select_one('a[href*="Match:"]')
        source_url = (
            urljoin(WIKI_BASE, match_link["href"])
            if match_link and match_link.get("href")
            else f"{WIKI_BASE}/leagueoflegends/{quote(page_title.replace(' ', '_'))}"
        )

        results.append(
            {
                "날짜_KST": date_kst,
                "팀": names,
                "최종점수": f"{scores[0]}:{scores[1]}",
                "승리팀": winner,
                "출처링크": source_url,
                "_timestamp": timestamp,
            }
        )
    return results


def collect_matches(client: LiquipediaClient, tournament: dict, stages: list[str]) -> list[dict]:
    """가장 최근 단계부터 경기를 모아 최신 5건을 고른다."""
    stage_titles = stages or [tournament["page"]]  # 하위 문서가 없으면 대회 문서 자체
    collected = []
    seen_links = set()

    # 탭 순서가 오래된 단계 -> 최신 단계이므로 뒤에서부터 본다.
    for stage in reversed(stage_titles):
        if len(collected) >= MATCH_COUNT:
            break
        payload = client.get(
            {"action": "parse", "page": stage, "prop": "text"},
            stage=f"경기 결과 확인 ({stage})",
            kind="parse",
        )
        html = payload.get("parse", {}).get("text", "")
        if not html:
            raise CollectorError(
                f"경기 결과 확인 ({stage})",
                f"페이지 HTML을 받지 못했습니다: {str(payload)[:300]}",
                "action=parse 응답에 text 항목이 없습니다.",
                "위키 문서가 삭제되었는지 확인하고 잠시 후 다시 실행하세요.",
            )

        matches = parse_matches(html, stage)
        print(f"  {stage}: 경기 {len(matches)}건 확인")
        for match in matches:
            if match["출처링크"] in seen_links:
                continue
            seen_links.add(match["출처링크"])
            collected.append(match)

    collected.sort(
        key=lambda item: (item["_timestamp"] is not None, item["_timestamp"] or 0),
        reverse=True,
    )
    return [{k: v for k, v in item.items() if not k.startswith("_")} for item in collected[:MATCH_COUNT]]


# %% CELL: 수집 실행
def print_summary(result: dict) -> None:
    """결과를 사람이 보기 좋게 출력한다."""
    tournament = result["대회"]
    print("\n" + "=" * 68)
    print(f"대회: {tournament['이름']} (종료일 {tournament['종료일']})")
    print(f"수집: {result['수집건수']}건 / 요청 {result['요청건수']}건")
    print("=" * 68)
    for index, match in enumerate(result["경기결과"], 1):
        team1, team2 = match["팀"]
        print(
            f"{index}. {match['날짜_KST']} | {team1} {match['최종점수']} {team2} "
            f"| 승리: {match['승리팀']}"
        )
        print(f"   출처: {match['출처링크']}")
    print(f"\nJSON 저장: {OUTPUT_FILE.resolve()}")
    print("출처 표기: " + result["출처_표기"])


def main():
    """전체 수집 과정을 실행하고 결과 JSON을 저장한다."""
    try:
        client = LiquipediaClient()
        tournament = find_latest_completed_tournament(client)
        stages = extract_stage_titles(tournament)
        print(f"확인할 단계: {', '.join(stages) if stages else '(대회 문서 자체)'}")

        matches = collect_matches(client, tournament, stages)
        if len(matches) < MATCH_COUNT:
            print(f"[알림] 확인된 경기가 {len(matches)}건뿐입니다. 가짜 데이터는 채우지 않습니다.")

        result = {
            "수집시각_KST": datetime.now(KST).isoformat(timespec="seconds"),
            "요청건수": MATCH_COUNT,
            "수집건수": len(matches),
            "대회": {
                "이름": tournament["name"],
                "종료일": tournament["end_date"],
                "위키페이지": tournament["page"],
                "링크": tournament["url"],
            },
            "출처_표기": "자료 출처: Liquipedia League of Legends Wiki (CC BY-SA 3.0)",
            "이용약관_메모": (
                "MediaWiki API는 비편집 목적 사용이 공식 지원되지 않습니다. "
                "접근 제한 시 중단하며, 실제 서비스는 승인된 LiquipediaDB API를 사용하세요."
            ),
            "경기결과": matches,
        }
        OUTPUT_FILE.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print_summary(result)
        return result
    except CollectorError as error:
        print_error_report(error)
        return None


# %% NOTEBOOK_ONLY
def notebook_main():
    """Colab 노트북에서 호출하는 진입점."""
    return main()


# %% SCRIPT_ONLY
if __name__ == "__main__":
    result = main()
    sys.exit(0 if result else 1)
