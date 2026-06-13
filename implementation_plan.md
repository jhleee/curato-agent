# Naver 뉴스 이슈 스크래퍼 구현 계획

기존 네이버 뉴스 검색 API 기반 수집 방식을 비활성화하고, 사용자가 지정한 이슈(Issue) 페이지들을 직접 웹 스크래핑하여 기사를 수집하는 방식으로 변경합니다.

## User Review Required
> [!WARNING]
> `https://media.naver.com/press/001/issue`와 같은 언론사별 홈 이슈 페이지는 브라우저 스크립트(JS)를 통해 동적으로 기사 목록을 불러오기 때문에 단순 파이썬 스크립트(requests + BeautifulSoup)만으로는 기사 URL들을 온전히 수집하기 어렵습니다. 
> 반면, `https://media.naver.com/issue/092/492` 와 같은 특정 주제 이슈 페이지는 서버에서 직접 HTML 내에 기사 링크들을 렌더링해주므로 한 번에 수백 건의 링크를 성공적으로 추출할 수 있습니다. 
> **따라서 이번 구현에서는 `https://media.naver.com/issue/...` 형태의 이슈 링크들을 config.yaml에 배열 형태로 등록해두고, 해당 링크들을 순회하며 수집하는 방식**으로 진행하고자 합니다. 괜찮으신가요?

## Proposed Changes

### `config.yaml`
- `collectors.naver` 항목을 `false`로 비활성화.
- `collectors.naver_issue` 항목을 `true`로 신규 추가.
- `naver_issue_urls` 항목을 배열 형태로 추가하여 수집할 대상 URL 목록을 관리.

### `curato/pipeline/collector.py`
#### [NEW] `NaverIssueCollector`
- `BaseCollector`를 상속받은 새 크롤러 작성.
- `config.yaml`에 정의된 `naver_issue_urls`를 순회.
- `https://media.naver.com/issue/OID/IID` 형태의 URL에서 BeautifulSoup을 사용하여 `<a href=".../article/OID/AID">` 형태의 기사 링크들을 모두 추출.
- 추출된 링크들을 `https://n.news.naver.com/article/print/OID/AID` 형태의 인쇄용 페이지 URL로 변환.
- 변환된 인쇄용 페이지들을 병렬(또는 지연) 요청하여 제목과 본문(`#articeBody`) 추출 후 `FeedItem` 객체로 변환 및 반환.

### `curato/pipeline/runner.py`
#### [MODIFY] `PipelineRunner`
- `_stage_collect` 단계의 활성 수집기 목록(`all_collectors`)에 `NaverIssueCollector`를 추가하고, 기존 `NaverNewsCollector`의 사용을 옵션에 맞게 처리.

### `curato/tui/app.py`
#### [MODIFY] `CuratoApp`
- `COLLECTOR_INFO`에 `naver_issue` 크롤러 정보를 추가하여 TUI의 **수집** 탭에 표시되도록 설정.
- 기존 설정 탭 편집기에서 새로운 `naver_issue_urls` 배열을 관리할 수 있도록 렌더링.

## Verification Plan
1. 새로운 `NaverIssueCollector`만 단독 실행 (`python -m curato.main --collect-only` 등 또는 TUI 수동 수집 버튼)하여 인쇄 페이지에서 본문이 정상적으로 파싱되는지 확인.
2. 수집된 내용이 DB에 정상 삽입되고, 클러스터링 단계에서 적절한 크기의 본문(`snippet`)으로 활용되는지 검증.
