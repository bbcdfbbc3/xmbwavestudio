# 시각·기기 참고 자료

확인 날짜: 2026-10-18. 참고 이미지를 프로그램의 배경으로 재사용하지 않으며, 펌웨어나 원본 그래픽 코드를 포함하지 않는다.

## 웨이브

| 대상 | 1차 자료 | 사용 범위 |
|---|---|---|
| PSP Classic / Original | [Sony PSP 배경 설정](https://manuals.playstation.net/document/en/psp/current/settings/background.html) | Classic이 4.xx까지의 Original이라는 명칭 구분 |
| PSP 5.00 | [2008-10-13 공식 업데이트 안내](https://blog.playstation.com/2008/10/13/firmware-updates-ps3-v250-psp-v500/) | 배경 재설계 시점과 PSP-3000 화면 예시 |
| PS3 | [Sony XMB 사용 설명](https://manuals.playstation.net/document/en/ps3/current/basicoperations/xmb.html) | 화면 예시의 가로로 흐르는 반투명 띠와 층 구조 |
| PS3 테마·색상 | [Sony 테마 설정](https://manuals.playstation.net/document/en/ps3/current/settings/themesettings.html) | 배경색·밝기·Original / Classic 구분 |
| PS3 3.00 | [2009-08-18 공식 업데이트 안내](https://blog.playstation.com/2009/08/18/playstation-3-firmware-v3-00-update/) | XMB 외형 변경의 시점과 배경 맥락 |

현재 공식 문서에 있는 정지 화면은 형태·색 분포의 참고 자료다. v1은 자체 수식으로 만든 근사 재현이며 원본 펌웨어의 물리·음영·시간 변화와 일치하는 복제는 아니다. 특히 주기 보정은 원본 동작 위에 추가한 기능이다. 아래 영상 비교에서는 곡면의 움직임을 관찰했으며 Sony 원본의 수치적 타이밍이나 제어점 데이터를 추출하지 않았다.

### 기본값 2판: 이미지 검색으로 재비교

검색 결과에는 PS4 이미지, 팬 재현, 커스텀 테마가 함께 섞여 있으므로 실기 화면·당시 촬영 사진을 우선 확인했다. 참고 이미지는 프로그램 자산으로 추가하지 않고 브라우저에서 시각 비교만 진행했다.

| 대상 | 확인한 이미지 / 원문 | 반영한 특징 |
|---|---|---|
| PSP Classic | [2005년 PSP 1.50 업데이트 실기 촬영](https://av.watch.impress.co.jp/docs/20050324/scei.htm), [사진](https://av.watch.impress.co.jp/docs/20050324/scei02.jpg) | 5.00 이전 화면의 넓게 겹치는 부드러운 곡면, 은은한 밝은 경계. 가는 네온 선 여러 개 형태를 줄임. |
| PSP Original | [Classic / Original 비교 글](https://www.reddit.com/r/PSP/comments/1u4a0m0/release_wavezbg_custom_xmb_wave_colours/), [댓글의 Original 캡처](https://i.imgur.com/zXtuCSw.jpeg) | 하단을 채우는 큰 두 곡면, 어두운 상단에서 밝은 하단으로의 색 변화. 별도 리본 여러 겹 표현을 대체. |
| PSP Original 보조 | [메뉴 변화 기사](https://www.3djuegos.com/ps3/noticias/asi-ha-evolucionado-la-interfaz-de-las-consolas-playstation-201028-108740), [PSP 화면](https://i.blogs.es/juegos/13378/galer_a_de_im_genes/fotos/set/galer_a_de_im_genes-5282620.jpg) | 파란 상단·청록 하단의 색 분포, 아래쪽의 큰 곡면 배치 교차 확인. |
| PS3 실기 XMB | [Rodrigo Copetti의 하드웨어 분석과 캡처](https://www.copetti.org/writings/consoles/playstation-3/), [Friends 화면](https://www.copetti.org/images/consoles/ps3/xmb/friends.be5b95b6fef74496c7f810605eaa58fa4ee7782a2b3f825069f611a39820b5aa.jpg) | 얇게 겹치는 밝은 띠, 물결 주변에 더 많은 입자, 크기·선명도가 다른 빛점. |
| PS3 배경 보조 | [이미지 검색의 PS3 보라색 배경](https://wallpaperset.com/w/full/c/d/8/73503.jpg) | 어두운 하단과 상단의 색 번짐, 선명한 작은 입자와 흐릿한 큰 입자의 혼합. 배경 모음의 제작 출처는 확정하지 않아 보조 비교에만 사용. |

정지 이미지에서 관찰한 입자의 선명도 차이를 입자별 초점 거리로 **근사 표현**한다. 이것이 Sony 원본 엔진의 실제 구현 방식이라는 뜻은 아니다. 입자 흐림에는 넓은 원형 빛, 선명한 입자에는 작은 중심 빛과 가는 광선을 적용한다. 동작은 기존의 정확한 반복 주기를 유지한다.

실제 렌더링 비교 캡처와 초점·크기 검사는 검증 스크립트로 다시 생성할 수 있다.

### 사용자 첨부 화면과 유튜브 영상으로 형태 재구성

사용자가 제공한 PS3 보라색 배경(876×345)과 PSP Classic 파란 XMB 화면(869×482)을 가장 우선하는 형태 기준으로 삼았다. 사용자 첨부 원본이나 영상 프레임을 프로그램 자산으로 넣지 않는다. PSP Original은 사용자 요청에 따라 그대로 유지했다.

| 영상 | 실제 확인한 구간 | 출처와 관찰 |
|---|---|---|
| [PS3 XMB wave with sparkles (original wave)](https://www.youtube.com/watch?v=vxvlkczrMJQ), USRDIR1, 2023-08-13 | 브라우저 재생 후 12·16·20·24초에서 정지해 비교 | 게시자가 RPCS3에서 Rebug 4.86 LE 펌웨어를 구동해 녹화했다고 설명. 실물 PS3 촬영으로 표기하지 않는다. 서로 다른 폭의 반투명 면이 좁아졌다 펴지고 교차하며, 파티클은 작은 선명한 빛과 큰 흐린 빛이 함께 보인다. |
| [PSP classic waves background (FREE TO USE)](https://www.youtube.com/watch?v=LaaKs4WzfFA), Burcica | 브라우저 재생 후 5·9·13초에서 정지해 비교 | 설명에 Cross Launcher 재현 앱 녹화라고 명시되어 있어 보조 움직임 자료로만 사용. 위아래로 떨어진 넓은 면의 경계가 따로 이동하고 경계의 빛이 면 안쪽으로 퍼진다. PSP 실물의 정확한 타이밍 근거로 사용하지 않는다. |

- **Classic:** 중앙의 좁은 띠 세 개를 없애고, 첨부 화면에서 관찰되는 상단 약 1/4~1/3과 하단 약 2/3~7/8의 큰 경계를 구성했다. 파랑에서 청록으로 이어지는 색과 면의 경계 아래로 퍼지는 빛을 조정했다.
- **PS3:** 평행한 사인 곡선 대신 면마다 양쪽 경계를 다섯 기준점을 지나는 독립적인 3차 곡선 구간으로 구성했다. 첨부 화면의 왼쪽에서 퍼지고 한 번 낮아졌다가 중앙에서 올라와 겹친 뒤 오른쪽으로 내려가는 형태를 시작 위상의 기준으로 사용했다. 아래쪽을 검게 만드는 기존 배경을 바꾸고, 면 내부의 넓은 빛과 가는 경계의 빛을 따로 계산했다.
- **Original:** 배경·곡면 수식·기본값을 변경하지 않았으며 네 시점의 렌더링 픽셀이 수정 전과 일치하는지 확인했다.

영상에서 보이는 특징을 자체 주기 함수로 근사한 구현이다. 원본과 모든 시각에서 픽셀이 일치하거나 Sony의 실제 곡면 데이터를 재현했다고 주장하지 않는다.

### 겹침의 흰빛과 Classic 경계의 입체감

추가 피드백에 따라 같은 PS3 영상에서 12.000·12.033·12.067초, 16.000·16.033초, 20.000·20.033초, 24.000초의 선택 프레임을 브라우저로 탐색해 비교했다. 연속 구간은 `requestVideoFrameCallback`이 다음 프레임의 표시를 알릴 때마다 일시정지해 캡처했으며, 실제 `mediaTime`과 인접 이미지가 서로 달라진 것을 확인했다. 유튜브 플레이어가 제시한 프레임을 확인한 것이며 원본 영상 파일의 프레임을 내려받거나 전체 프레임을 분석한 것은 아니다. 적응형 재생의 실제 영상 크기는 앞 일곱 캡처에서 640×360, 마지막 캡처에서 1280×720이었다.

겹치는 접힘과 밝은 경계에서는 주변의 유색 면보다 색이 옅고 흰빛에 가까운 부분이 보인다. 기존 렌더링은 모든 빛에 같은 물결색을 곱해, 겹침이 밝아져도 같은 색이 남았다. 색이 있는 면의 빛을 유지하면서 면끼리 겹치는 기여도에 별도 흰빛을 더하도록 변경했다. 경계의 반사광도 약하게 흰빛을 포함한다.

Classic은 사용자가 첨부한 파란 화면의 상단 곡면과 하단 앞면 경계를 다시 비교했다. 흰 부분은 폭이 일정한 선 하나보다, 밝은 경계에서 면 안쪽으로 빠르게 줄어드는 얇은 그라데이션으로 해석했다. 경계의 기울기에 맞춘 얇은 흰빛과 비대칭 감쇠를 적용했다. 곡선 위치·움직임·기본값과 PSP Original은 이 음영 변경에서 유지했다.

### 지정 영상의 물결 이동과 형태 재구성

새 기준은 사용자가 지정한 [Sony PlayStation 3 Boot Animation](https://www.youtube.com/watch?v=LLRkpbAlCFQ), i12bretro 게시 영상이다. 게시자는 PS3 부팅 화면을 직접 캡처했다고 설명한다. 영상 길이는 약 16.08초이며, 처음의 검은 화면·밝기와 색 변화·로고·메뉴는 물결 애니메이션과 구분했다. 프로그램에는 물결만 자체 수식으로 재현하고 로고·메뉴·워터마크·영상 프레임은 자산으로 넣지 않는다.

- 브라우저의 실제 프레임 표시 콜백과 `mediaTime`을 사용해 3.470133~9.676333초의 물결 구간을 캡처했다. 최초 시간순 캡처는 181장이었으며, 중간에 건너뛴 6장을 개별 탐색해 보충했다. 640×360으로 제공된 유튜브 스트림의 프레임 번호 104~290, 총 187장을 확인했다. 이 스트림의 표시 간격은 약 1001/30000초이며 업로드 원본 파일의 모든 프레임을 확인했다는 뜻은 아니다.
- 큰 봉우리와 접힘이 왼쪽에서 오른쪽으로 이동하고, 그 뒤에 넓은 면이 이어진다. 이전 구현의 고정된 기준점별 상하 진동은 이 흐름과 달랐다.
- 후반부 선택 장면 7개의 가로 위치별 밝은 물결 중심 217점을 추출해 큰 파형을 근사했다. 맞춤 결과는 화면 너비당 약 5.29라디안, 시간당 약 0.52라디안/초, 이동률 약 0.098 화면 너비/초였다. 맞춤 잔차 약 0.010 화면 높이는 **추출한 중심점과 근사 곡선 사이의 값**이며, 완성 렌더링과 영상 전체의 픽셀 오차가 아니다. 일부 장면의 로고·색 변화와 저해상도 압축에 따른 불확실성도 있다.
- 보충한 187장 전체에서도 프레임별로 총 4,397개 열의 물결 중심을 추적했다. 로고가 보이는 초기 구간은 오른쪽 영역을 제외했다. 7초 이후 표시 프레임의 위상 변화로 다시 구한 이동률은 약 0.522라디안/초, 0.0987 화면 너비/초였다. 프레임별 시각·추적 위상·사용한 열 개수는 `test-results/ps3-motion/per-frame-motion.json`에 기록한다.
- 이 관찰을 바탕으로 공통 위상을 따라 움직이는 네 겹의 면으로 PS3 형태와 움직임을 다시 구성했다. 넓은 뒤쪽 면과 좁게 접히는 앞쪽 면, 희미한 위쪽 면의 곡률·반사광을 구분했다. 물결이 겹칠 때 흰빛이 강해지는 표현은 유지했다.
- 약 12초 주기를 속도 비교 기준으로 사용하되, 참고 영상에서 한 주기 전체가 뚜렷하게 확인된 것은 아니므로 원본의 정확한 반복 주기라고 단정하지 않는다. 저장 길이와 무중복 반복 조건은 기존대로 유지한다.

분석 기록은 `test-results/ps3-motion/sequence/all-frames.json`, 근사 맞춤 수치는 `test-results/ps3-motion/ridge-fit.json`에 보관한다. 대응 시각의 비교 화면은 형태를 보기 위해 두 화면을 동일한 비율로 자르고 명암으로 변환한 것이며 제품 출력은 선택한 색을 사용한다. PSP Classic과 PSP Original은 이 변경에서 유지했다.

### 레이어별 상대 움직임

추가 기준은 사용자가 지정한 [PS3 Startup 4K](https://www.youtube.com/watch?v=iLW2BWi2Cg0), Bjohn's Second Channel 게시 영상이다. 제목의 4K가 분석에 사용한 스트림 해상도나 PS3의 원래 출력 해상도를 의미하지는 않는다. 브라우저에서 확인한 제공 스트림은 854×480, 영상 길이는 약 60.90초였다.

17.461773초 부근에서 일시정지 후 유튜브의 프레임 이동 키로 15장씩 전진해 17.961773초와 18.461769초 장면을 확인하고, 22.461773초 장면과도 비교했다. 큰 파형은 같은 방향으로 흐르지만 안쪽 얇은 면 사이의 간격과 접힌 부분의 폭이 달라지는 것이 관찰된다. 후반에는 메뉴가 나타나므로 메뉴·자막·색 전환은 물결 형상과 구분한다. 모든 프레임을 분석하거나 Sony의 실제 레이어 개수를 확인했다는 뜻은 아니다.

이 관찰과 사용자의 피드백을 바탕으로 기존 네 면에 서로 다른 주기적 시간차·폭·굽힘 변화를 적용했다. 현재의 큰 흐름과 흰 겹침 음영을 유지하면서 상대 움직임만 추가한 자체 근사다. 고급 설정의 기본 강도 1을 비교 기준으로 사용한다. 영상 프레임·메뉴·로고를 제품 자산으로 포함하지 않는다.

## 기기 해상도

28개 기기의 세로 방향 패널 픽셀 크기와 공식 출처는 `xmbwavestudio/data/devices.json`에 기록한다. 둥근 모서리와 카메라 영역을 잘라내지 않은 직사각형 해상도다.

| 기기 | 가로 × 세로 |
|---|---|
| Galaxy S20 / S20+ / S20 Ultra | 1440 × 3200 |
| Galaxy S21 / S21+ | 1080 × 2400 |
| Galaxy S21 Ultra | 1440 × 3200 |
| Galaxy S22 / S22+ / S23 / S23+ | 1080 × 2340 |
| Galaxy S22 Ultra / S23 Ultra | 1440 × 3088 |
| Galaxy S24 / S25 / S26 | 1080 × 2340 |
| Galaxy S24+ / S24 Ultra / S25+ / S25 Ultra / S26+ / S26 Ultra | 1440 × 3120 |
| iPhone 16 | 1179 × 2556 |
| iPhone 16 Plus | 1290 × 2796 |
| iPhone 16 Pro / iPhone 17 / iPhone 17 Pro | 1206 × 2622 |
| iPhone 16 Pro Max / iPhone 17 Pro Max | 1320 × 2868 |

## 라이브러리와 파일 형식

- [Three.js WebGLRenderer](https://threejs.org/docs/pages/WebGLRenderer.html): WebGL2, sRGB 출력, 그래픽 초기화·크기 검사.
- [Three.js ShaderMaterial](https://threejs.org/docs/pages/ShaderMaterial.html): 자체 셰이더 작성. 프로젝트에는 Three.js 0.180.0과 MIT 라이선스 원문을 포함한다.
- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/): 로컬 프레임 전송·연결 종료 처리.
- [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg): FFmpeg 실행 파일 제공. 별도 인코더의 사용 조건은 해당 배포본을 따른다.
- [FFmpeg](https://ffmpeg.org/ffmpeg.html): raw RGBA 입력, H.264 인코딩.
- [Apple Live Photo 배경화면 안내](https://support.apple.com/en-ae/120734): MP4 파일 제작과 iPhone 잠금화면 적용은 별도 기능이다. v1은 Live Photo 변환을 제공하지 않는다.
