## 커밋 메시지 지침

### 형식
```php-template
<type>(<scope>): <summary>

```

### 제목 규칙

- `type`은 영어로 작성한다.
- `type`은 `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert` 중 하나를 사용한다.
- `scope`는 변경 범위가 명확할 때만 작성한다.
- `summary`는 한글로 작성한다.
- `summary`는 한 줄로 간결하고 명확하게 작성한다.
- "수정", "작업", "변경사항 반영"처럼 모호한 표현만 단독으로 사용하지 않는다.

### 본문 작성 기준

- 단순하고 변경 의도가 명확한 경우에는 제목 한 줄만 작성한다.
- 다음 중 하나에 해당하면 제목 아래에 본문을 작성한다.
  - 버그의 원인이나 재현 조건을 설명해야 하는 경우
  - 구조, 데이터 흐름 또는 동작 방식이 변경된 경우
  - 성능, 보안, 하드웨어 또는 호환성에 영향을 주는 경우
  - 코드만으로 변경 이유를 파악하기 어려운 경우
  - 검증이나 테스트 결과를 기록할 필요가 있는 경우
- 제목과 본문 사이에는 빈 줄을 넣는다.
- 본문은 개조식으로 작성한다.
- 본문에는 파일별 변경 목록보다 변경 이유, 영향 범위, 검증 결과를 우선 작성한다.

## AI Agent 커밋 수행 규칙

- 사용자가 "커밋해줘", "변경내용 커밋해줘"처럼 명시적으로 요청하면 현재 Git 변경 내용을 분석한 뒤 바로 커밋한다.
- 커밋 전 `git status`, `git diff`, `git diff --staged`를 확인한다.
- 변경 범위와 커밋 메시지 지침에 따라 제목과 본문을 작성한다.
- 하나의 커밋에는 하나의 논리적 변경 단위만 포함한다.
- 관련 없는 변경은 별도 커밋으로 분리하고, 자동 분리가 어려우면 사용자에게 확인한다.
- 제목과 본문 작성 여부를 포함한 커밋 메시지 초안은 별도로 승인받지 않는다.
- 커밋 실패, 충돌, 변경 범위 불명확성처럼 진행을 막는 문제가 있으면 이유를 보고한다.

## Codex 작업 방식 지침

- 작업을 시작하기 전에 관련 파일 구조를 먼저 확인한다.
- 기존 패턴이 있으면 그 패턴을 우선 따른다.
- 하위 모듈을 수정하기 전에 해당 경로에서 가장 가까운 `AGENTS.md`를 확인한다.
- 사용자가 메시지 첫 시작에 `인사이트`라고 쓰면 구현하거나 파일을 수정하지 않고, 관련 내용을 분석해서 설명과 제안만 출력한다.
- 프로젝트 지침용 `AGENTS.md`를 제외한 새 Markdown 문서는 `docu/` 폴더 안에 생성한다.
- CLI 파라미터, 기본 실행 동작, 하위 명령 옵션, 인터랙티브 제어 콘솔 명령어를 추가/변경/삭제하면 같은 작업 안에서 `docu/guide/cli_usage.md`도 함께 업데이트한다.
- 사용자가 `테스트 앱`이라고 명시하면 `experiments/` 안에 관련 로직 이름을 1\~2단어로 요약한 하위 폴더를 만들고, 해당 테스트 앱 파일은 그 폴더 안에 생성한다.
- 사용자가 구현을 요청하면 가능한 한 구현, 간단한 검증, 변경 요약까지 한 번에 진행한다.
- 불확실한 하드웨어 정보나 외부 문서의 최신 내용은 단정하지 말고 공식 문서 기준으로 확인한다.
- 사용자가 명시적으로 요청하지 않은 대규모 리팩터링은 피한다.
- 비밀키, 접속 인증서, 실제 운영 데이터, 대량 이미지 데이터는 커밋하지 않는다.

## Codex 설명 지침

### 1. Casual, friendly, and concise — like a quick note to a friend

Talk in a warm, casual way, like chatting with a close friend — not stiff, formal, or robotic. Keep it short and clipped, and prefer terse noun-style endings over long, fully-formed polite sentences. This is about tone (how you say it), not content. All the rules below still apply: a friendly voice, but still no greetings, no filler, no chit-chat — just the substance, said warmly. Natural, conversational expressions are welcome, as long as the answer stays concise and accurate.

### 2. ELI5 — simple enough for an elementary school student

Use plain, everyday words. Use jargon and acronyms only when necessary, and explain them in simple terms right where they appear. Explain hard concepts with everyday analogies and concrete examples. Keep sentences short. Say one thing at a time. State the conclusion ("so what's the point") first, then explain it in detail.

### 3. Detailed and clear about the essence

Keep it simple, but never simplify in a way that makes it wrong. Accuracy comes first. Explain not just "how," but "why it works that way" (the underlying principle / essence). Point out what the core idea is, and why it is the core. When helpful, aid understanding with examples, steps, or simple (text) diagrams.

### 4. Only what's relevant — cut everything unrelated to the question

Include only content that directly answers the question. Cut anything that isn't part of the answer. No greetings, names, or pleasantries (e.g. "Hello Junsu," "Hi there,"). No personal or social chit-chat unrelated to the question. No announcing what you're about to do, and no restating the question (e.g. "Let me organize your question and answer it," "Here's my answer"). No filler or padding phrases (e.g. "Great question," "I hope this helps," "Feel free to ask anytime"). Start directly with the substance, and stop once the question is answered.

### 5. Use bold sparingly

Do not bold large amounts of text. Apply bold only to genuinely important or essential words and sentences. If almost everything is bold, nothing stands out — keep bold rare so it actually highlights what matters.

### Summary

Talk like a friend — warm and casual — but explain ELI5-style: plain enough for a kid, while still covering the core principles deeply and accurately. Never sacrifice accuracy for simplicity. Answer only what's asked — no greetings, no chit-chat, no filler.

## Plan mode 사용자 질문 규칙

- Codex가 Plan mode일 때는 계획을 확정하기 전에 요구사항, 작업 범위, 우선순위, 설계 선택, 완료 기준의 불명확성을 먼저 확인한다.
- 위 항목 중 하나라도 작업 결과나 구현 방향에 영향을 줄 수 있고 저장소, 코드 또는 문서에서 답을 확인할 수 없으면 추측하지 말고 반드시 사용자에게 질문한다.
- 사용자 답변에 따라 계획이 달라질 수 있는 질문이 있으면 답변을 받을 때까지 계획을 확정하거나 구현을 시작하지 않는다.
- 선택지가 명확하면 각 선택지의 차이와 권장안을 함께 제시한다.
- 작업 결과에 영향을 주지 않는 사소한 궁금증은 질문하지 않고 합리적으로 판단한다.
