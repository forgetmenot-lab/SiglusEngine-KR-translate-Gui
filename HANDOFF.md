# HANDOFF.md
> 다음 AI 세션에게 전달하는 압축 작업 메모.
> 이 파일 + PROJECT.md + Phase1 코드 4개 파일만 있으면 바로 이어서 작업 가능.

---

## 현재 컨텍스트

```
Phase 1 v1.0.3 완료 → Phase 2.1 (위저드 모드) 진입 직전
```

**운영자 정보**
- 코딩 전공, 실무 비코딩. 냉정·이성적 분석 선호.
- 실행요청 → 바로 실행. 사고 요청 → 소크라테스 모드.
- 구글 검색 교차검증 후 답변 요청.

---

## 다음 세션에서 바로 해야 할 일

### Step 1 — W1~W4 결정 합의 (운영자에게 질문)

```
W1. 위저드 진입점 디자인
    추천: 카드 4개 (풀 사이클 / 키 추출만 / 패치 검증 / 직접 모드)

W2. 알파롬 분기
    추천: -xkey 자동 시도 → NULL 키(16바이트 0x00) 감지 → -xmkey 폴백 제안

W3. 번역 외부 단계 처리
    추천: 4단계에서 일시정지 + "번역 완료" 버튼만 활성화

W4. 게임 폴더 적용 자동화
    추천: GUI가 백업+이름변경 자동화 + 한글 폰트 교체는 안내만
```

### Step 2 — `tfs_wizard.py` 신규 파일 작성 (~250줄)

7단계 흐름 (WIZARD_STEPS 데이터 활용):
```
1. 게임 폴더 선택
2. 키 추출 (-xkey → NULL 시 -xmkey 제안)
3. -u 언팩
4. -xat 추출 → [일시정지: 번역 완료 버튼]
5. -rat 재삽입
6. -p 리팩
7. -j2k 패치 → 게임 폴더 적용 안내
```

### Step 3 — `main.py`에 위저드 탭 통합

```python
# DirectModeWidget 옆에 WizardModeWidget 탭 추가
# 직접 모드는 그대로 유지 (회귀 없음)
```

---

## 수정 시 주의할 파일

| 파일 | 주의 사항 |
|---|---|
| `tfs_core.py` | `GenericRunner`와 `DiagnosticLogger`는 매우 복잡. 수정 전 전체 흐름 확인 필수. |
| `tfs_options.py` | `ToolOption(frozen=True)` — 필드 추가 시 전체 인스턴스 영향. 하위 호환 유지. |
| `main.py` | `_on_run_request` 순서 (①진행률 ②도구 ③-rt검증 ④키 ⑤키-폴더 ⑥백업 ⑦실행) 절대 변경 금지. |

---

## 건드리면 안 되는 구조

```
1. GenericRunner의 stdout 처리 파이프라인
   (byte_buffer → decode_with_recovery → text_buffer → line 단위 처리)
   → 바꾸면 정렬 복구 전체가 깨짐

2. KeyManager._active_key_id 추적 흐름
   → activate_library_key / store_to_library / delete_library_key 3개가 쌍으로 동작

3. DiagnosticLogger 카테고리 분리 구조 (H6)
   → session_start_event 별도 보관이 핵심. deque 단일화 금지.

4. _on_run_request 실행 전 검증 순서
   → 순서 바꾸면 사용자 경험 망가짐
```

---

## 현재 가장 중요한 이슈

```
1. [Phase 2 진입] W1~W4 합의 후 위저드 작성 — 다음 세션의 핵심 작업
2. [알파롬 게임] -xmkey/-wkey 미검증 — 위저드 2단계에서 자연 검증 예정
3. [Minor #1,#2] 카운트 ±2~3 불일치 — 결과물 정상이므로 Phase 2 통합 처리
```

---

## 다음 작업 순서

```
[Phase 2.1]  tfs_wizard.py 작성 (이번 세션)
             → 운영자 위저드 풀 사이클 검증
             → 통과 시 새 채팅으로 Phase 2.2

[Phase 2.2]  도움말 강화 (새 채팅)
             → 위저드 단계별 도움말 패널
             → 한글 폰트 교체 안내 통합

[Phase 2.3]  SHA256 매니페스트 (새 채팅)
             → 패치 배포 파일 무결성 검증 도구

[Phase 3]    Nuitka 빌드 + UAC + 배포 패키징 (새 채팅)
```

---

## 핫픽스 발생 시 처리

```
Phase 2 진행 중 Phase 1 결함 발견 시:
  1. Phase 2 일시 중단 (현재 단계 메모)
  2. v1.0.X 핫픽스 작성 + 검증
  3. Phase 2 재개

버전 분리:
  Phase 1 핫픽스 → v1.0.4, v1.0.5 ...
  Phase 2 릴리즈 → v1.1.0, v1.1.1 ...
```

---

## 첨부 파일 확인 목록

새 세션 시작 시 다음이 첨부돼 있어야 한다:

```
□ PROJECT.md      (이미 읽었으면 생략 가능)
□ HANDOFF.md      (이 파일)
□ main.py         (597줄, v1.0.3-phase1)
□ tfs_core.py     (886줄, v1.0.3-phase1)
□ tfs_ui.py       (601줄, v1.0.3-phase1)
□ tfs_options.py  (592줄, v1.0.3-phase1)
```
