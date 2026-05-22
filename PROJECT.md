# PROJECT.md
> AI 협업용 프로젝트 개요 문서. 새 세션에서 빠르게 컨텍스트를 복원하기 위한 목적.

---

## 프로젝트 목적

**ToolForSiglus.exe** (시글러스 엔진 게임 번역 CLI 도구)를 사용자 친화적인 **포터블 GUI 래퍼**로 감싸는 프로젝트.

- 원본 도구: 한국 커뮤니티 제작, CLI 전용, 18개 옵션 (https://arca.live/b/yuzusoft/93895431)
- 용도: 일본 미연시 게임 (SiglusEngine) 한국어 패치 제작
- 배포 대상: 커뮤니티 패치 제작자 (코딩 지식 없음 가정)

---

## 기술 스택

```
언어:     Python 3.12+
GUI:      PySide6 (Qt6)
빌드:     Nuitka (Phase 3, 단일 .exe)
설정 저장: QSettings (exe 인접 또는 %APPDATA% 폴백)
로그:     JSONL 형식, logs/ 폴더 (7일 자동 삭제)
OS:       Windows 전용 (ToolForSiglus.exe가 Win32)
```

---

## 디렉토리 구조

```
C:\Temp\novel transtool\ToolForSiglus_ver101\   ← 운영자 작업 경로 (참고)
│
├── ToolForSiglus.exe          원본 CLI 도구 (래핑 대상, 수정 불가)
├── SiglusEngine_pure.exe
├── opencv_world460.dll        64MB, 의존성
├── opencv_videoio_msmf460_64.dll
├── openh264-1.8.0-win64.dll
│
├── main.py                    GUI 진입점
├── tfs_core.py                핵심 엔진
├── tfs_options.py             옵션 메타데이터
├── tfs_ui.py                  UI 위젯
│
├── keys/                      라이브러리 키 폴더 (<게임명>.bin)
├── backups/                   자동 백업 폴더 (<이름>_<타임스탬프>/)
└── logs/                      JSONL 진단 로그 (session_YYYY-MM-DD.log)
```

---

## 핵심 파일 설명

### `main.py` (597줄)
- `MainWindow(QMainWindow)`: 앱 메인 윈도우
- `_on_run_request(option, args)`: 모든 옵션 실행의 단일 진입점
  - 순서: 진행률 리셋 → 도구 검증 → -rt 사전 검증 → 키 검증 → 키-폴더 불일치 경고 → 자동 백업 → 실행
- `_on_finished(code)`: 실행 완료 후 F3 실패율 검증 + 로그 출력
- `_describe_backup_target()`: 옵션별 백업 대상 설명 생성

### `tfs_core.py` (886줄)
- `DiagnosticLogger`: JSONL 진단 로그. 카테고리별 deque 분리 보관
  - `session_start_event`: 영구 보관 (process_output 폭주에 밀리지 않음)
  - `gui_actions(maxlen=300)`, `process_outputs(maxlen=2000)`
  - `export_report()`: 마크다운 진단 보고서 생성
- `KeyManager`: 암호화 키 이중 모드 관리
  - `MODE_LIBRARY`: `keys/<id>.bin` 다중 보관, 활성화 추적
  - `MODE_SIMPLE`: `__key.bin` 단일 사용
  - `folder_matches_active_key()`: 키-폴더 불일치 사전 경고
  - `guess_key_id_from_path()`: 폴더명 기반 게임 식별자 추론
- `AutoBackup`: 타임스탬프 기반 백업 (파일/폴더)
- `GenericRunner(QObject)`: QProcess 기반 도구 실행 엔진
  - stdout: UTF-16 LE (no BOM), `\r\r\n` 줄바꿈
  - `decode_with_recovery()`: 바이트 정렬 깨짐 자동 복구 (CJK 빈도 휴리스틱)
  - 실패 latch: 파일별 1회 실패 카운트 (Finished. 시 리셋)

### `tfs_options.py` (592줄)
- `ToolOption(dataclass)`: 18개 옵션 메타데이터 (flag, group, label, args, inline_help 등)
- `OPTIONS tuple`: 18개 옵션 전체 정의
- `WIZARD_STEPS tuple`: 7단계 워크플로우 데이터 (Phase 2 위저드에서 사용)
- `Group(Enum)`: KEY / PACKAGE / TEXT / IMAGE / VIDEO / EXE

### `tfs_ui.py` (601줄)
- `DirectModeWidget`: 탭 기반 직접 모드 UI (Phase 1 메인)
- `OptionPanel`: 개별 옵션 패널 (인라인 안내문 포함)
- `KeyManagerWidget`: 키 라이브러리 UI (콤보박스 + 활성 키 라벨)
- `StatusPanel`: 진행률바 + 로그 콘솔 + 프롬프트 응답 버튼

---

## 도구 동작 핵심 사양

```
stdout 인코딩:    UTF-16 LE (no BOM)
줄바꿈:           \r\r\n (이중 CR, 정렬 복구 필요)
처리 단위 마커:   "[**] <파일> Finished."
진행률 마커:      "Finished." 라인 카운트
실패 마커:        "데이터가 깨졌습니다" / "Failed while reading"
스킵 마커:        "처리할 필요 없는 파일"
[j/k] 프롬프트:   .dbs 처리 시 발생 → stdin에 "j\n" or "k\n" 응답
__key.bin 위치:   도구 폴더 (게임 폴더 아님)
```

---

## 18개 옵션 그룹

```
KEY:     -xkey, -xmkey, -wkey
PACKAGE: -u, -p
TEXT:    -xat, -rat, -xt, -rt
IMAGE:   -xaimg, -raimg, -ximg, -rimg
VIDEO:   -xv, -rv, -xav, -rav
EXE:     -j2k
```

### 풀 사이클 (7단계 워크플로우)
```
1. -xkey / -xmkey  키 추출
2. -u              Scene.pck 언팩
3. -xat            텍스트 추출 (.ext.txt)
4. (외부)          번역 작업
5. -rat            텍스트 재삽입
6. -p              Scene 폴더 리팩 → Scene_new.pck
7. -j2k            한글 간격 패치 → SiglusEngine_patched.exe
```

### 게임 폴더 적용 (도구 밖 수동 작업)
```
Scene.pck.bak ← Scene.pck 백업
Scene_new.pck → Scene.pck (이름 변경)
SiglusEngine.exe.bak ← SiglusEngine.exe 백업
SiglusEngine_patched.exe → SiglusEngine.exe (이름 변경)
한글 폰트 교체 필수 (도구가 처리 안 함)
```

---

## 아키텍처 요약

```
[사용자]
  │
  ▼
[GUI Layer]          main.py + tfs_ui.py
  │ _on_run_request
  ▼
[Engine Layer]       tfs_core.py (GenericRunner)
  │ QProcess
  ▼
[Tool Layer]         ToolForSiglus.exe (수정 불가 CLI)
  │ stdout (UTF-16 LE)
  ▼
[Decode Layer]       decode_with_recovery() in tfs_core.py
```

---

## 주의사항 / 프로젝트 규칙

```
1. ToolForSiglus.exe는 절대 수정 불가. 래핑만.
2. GUI는 Windows 전용. 크로스플랫폼 고려 불필요.
3. Phase 3 빌드 전까지 관리자 권한 cmd에서 python main.py 실행 필요.
4. __key.bin은 도구 폴더 전용. 게임 폴더로 옮길 필요 없음.
5. stdout 바이트 정렬 깨짐은 도구 내부 버그. GUI가 복구.
6. .ext.txt는 반드시 UTF-16 LE 유지. 인코딩 변경 시 -rat/-rt 실패.
7. 신규 옵션 패널은 OptionPanel 패턴 그대로 재사용.
8. 핫픽스 발생 시 Phase 2 일시 중단 → 핫픽스 검증 → Phase 2 재개.
```
