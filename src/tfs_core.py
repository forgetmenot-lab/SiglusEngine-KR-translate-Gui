# -*- coding: utf-8 -*-
"""
tfs_core.py
===========
핵심 비즈니스 로직 — UI 비의존.

주요 클래스:
    GenericRunner       : 모든 옵션을 실행하는 단일 Runner (PoC의 XatRunner 일반화)
    DiagnosticLogger    : 세션 단위 구조화 로깅 + 진단 보고서 생성
    KeyManager          : 키 관리 정책 A (라이브러리) + B (단순) 듀얼 모드
    RecentPaths         : QSettings 기반 최근 경로 영속화
    AutoBackup          : -rat / -p / -rimg / -rv 등 덮어쓰기 옵션 시 백업

검증된 기술 사양 (실측):
    stdout 인코딩: UTF-16 LE (no BOM)
    줄바꿈     : \\r\\r\\n (이중 CR)
    프롬프트   : '[j/k]' 라인에 stdin LF 응답
    정렬 깨짐  : narrow/wide 출력 혼용 시 +1 byte misalignment 발생
"""

from __future__ import annotations

import datetime as _dt
import json as _json
import os
import re
import shutil
import sys
import traceback
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, QProcess, QSettings, QStandardPaths

from tfs_options import ToolOption, ArgKind


APP_NAME    = "ToolForSiglusGUI"
APP_ORG     = "tfsgui"
APP_VERSION = "1.0.3-phase1"

PROMPT_PATTERN = re.compile(r"\[j/k\]")


def _safe_enum_int(val) -> int:
    """
    PySide6의 ProcessError/ProcessState enum을 안전하게 int로 변환.
    Qt enum은 int()로 직접 변환되지 않을 수 있으므로 .value 접근 또는 폴백.
    """
    try:
        if hasattr(val, "value"):
            return int(val.value)
        return int(val)
    except Exception:
        try:
            # 마지막 수단: enum 이름의 해시 (식별자로만 사용)
            return -1
        except Exception:
            return -1


# ============================================================
# 1. 정렬 깨짐 감지 + 디코드
# ============================================================
def _looks_misaligned(text: str) -> bool:
    """라인 1줄을 보고 1바이트 시프트로 깨진 패턴인지 판정."""
    if len(text) < 4:
        return False
    ascii_n = sum(1 for c in text if ord(c) < 0x80)
    cjk_a   = sum(1 for c in text if 0x3400 <= ord(c) < 0xA000)
    return cjk_a >= 5 and ascii_n < cjk_a


def decode_with_recovery(raw: bytes) -> tuple[str, bool]:
    """
    UTF-16LE 디코드. 깨진 패턴이면 +1 byte 시프트로 재시도.
    반환: (디코드된 텍스트, 복구 발생 여부)
    """
    primary = raw.decode("utf-16-le", errors="replace")
    if not _looks_misaligned(primary):
        return primary, False
    if len(raw) >= 3:
        alt = raw[1:].decode("utf-16-le", errors="replace")
        if not _looks_misaligned(alt):
            return alt, True
    return primary, False


# ============================================================
# 2. 도구 검증
# ============================================================
def validate_tool_exe(exe_path: str) -> tuple[bool, str]:
    """선택된 .exe가 ToolForSiglus인지 PE 시그니처 검사."""
    p = Path(exe_path)
    if not p.is_file() or p.suffix.lower() != ".exe":
        return False, "유효한 .exe 파일이 아닙니다."
    try:
        with open(exe_path, "rb") as f:
            head = f.read(1024 * 1024)
        sig = "ToolForSiglus".encode("utf-16-le")
        if sig in head:
            return True, "ToolForSiglus 시그니처 확인됨."
        return False, (
            f"'{p.name}' 파일에 ToolForSiglus 시그니처가 없습니다.\n"
            "ToolForSiglus.exe가 아닌 다른 프로그램으로 보입니다."
        )
    except Exception as ex:
        return False, f"파일 읽기 실패: {ex}"


# ============================================================
# 3. 진단 로거
# ============================================================
@dataclass
class LogEvent:
    timestamp: _dt.datetime
    kind:      str         # session_start / gui_action / process_start / ...
    payload:   dict


class DiagnosticLogger:
    """
    세션 단위 구조화 로깅.
    - logs/session_<YYYY-MM-DD_HH-MM-SS>.log 파일에 1줄 1 JSON 누적
    - 메모리에도 최근 1000건 보유 (진단 보고서 즉시 생성용)
    - 7일 이상 된 로그 자동 삭제
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.log_dir  = base_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session_id   = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.session_file = self.log_dir / f"session_{self.session_id}.log"

        # H6: 카테고리별 분리 보관. process_output이 폭주해도
        # session_start, gui_action 등 핵심 메타가 밀려나지 않도록.
        self.session_start_event: Optional[LogEvent] = None
        self.gui_actions:     deque[LogEvent] = deque(maxlen=300)   # 사용자 액션
        self.process_starts:  deque[LogEvent] = deque(maxlen=100)
        self.process_outputs: deque[LogEvent] = deque(maxlen=2000)  # 가장 큰 비중
        self.process_finishes:deque[LogEvent] = deque(maxlen=100)
        self.exceptions:      deque[LogEvent] = deque(maxlen=50)
        self.warnings:        deque[LogEvent] = deque(maxlen=100)
        self.recovery_events: list[dict] = []

        self._cleanup_old_logs(days=7)
        self.log("session_start", {
            "version":   APP_VERSION,
            "python":    sys.version.split()[0],
            "platform":  sys.platform,
            "argv":      sys.argv,
        })

    def log(self, kind: str, payload: dict):
        ev = LogEvent(_dt.datetime.now(), kind, payload)
        # H6: kind에 따라 카테고리별 보관 (deque 한도 분리)
        if kind == "session_start":
            self.session_start_event = ev
        elif kind == "gui_action":
            self.gui_actions.append(ev)
        elif kind == "process_start":
            self.process_starts.append(ev)
        elif kind == "process_output":
            self.process_outputs.append(ev)
        elif kind == "process_finish":
            self.process_finishes.append(ev)
        elif kind == "exception":
            self.exceptions.append(ev)
        elif kind == "warning":
            self.warnings.append(ev)
        # decode_recovery는 recovery_events에 별도 보관 (log_recovery에서 처리)
        # 그 외 알 수 없는 kind도 파일에는 기록되지만 메모리 보관 생략

        try:
            with open(self.session_file, "a", encoding="utf-8") as f:
                f.write(_json.dumps({
                    "ts":      ev.timestamp.isoformat(timespec="seconds"),
                    "kind":    ev.kind,
                    "payload": ev.payload,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 로그 기록 실패는 앱 동작에 영향 주지 않음

    def log_recovery(self, line_num: int, raw_hex: str, recovered: str):
        evt = {
            "ts":        _dt.datetime.now().isoformat(timespec="seconds"),
            "line_num":  line_num,
            "raw_hex":   raw_hex,
            "recovered": recovered[:80],
        }
        self.recovery_events.append(evt)
        self.log("decode_recovery", evt)

    def log_exception(self, where: str, ex: Exception):
        self.log("exception", {
            "where":     where,
            "type":      type(ex).__name__,
            "message":   str(ex),
            "traceback": traceback.format_exc(),
        })

    def _cleanup_old_logs(self, days: int):
        cutoff = _dt.datetime.now() - _dt.timedelta(days=days)
        try:
            for p in self.log_dir.glob("session_*.log"):
                if _dt.datetime.fromtimestamp(p.stat().st_mtime) < cutoff:
                    p.unlink(missing_ok=True)
        except Exception:
            pass

    # ---------- 진단 보고서 생성 ----------
    def export_report(self, out_path: Path,
                      include_stdout_lines: int = 50,
                      error_context: int = 10) -> Path:
        """
        Phase 1 합의된 형식: 마지막 50줄 + 에러 컨텍스트 ±10줄.
        H6: 카테고리별 deque에서 직접 읽어 데이터 누락 방지.
        """
        lines = []
        lines.append("# ToolForSiglus GUI 진단 보고서")
        lines.append(f"세션 ID: {self.session_id}  |  내보낸 시각: "
                     f"{_dt.datetime.now().strftime('%H:%M:%S')}")
        lines.append("")

        # ===== 환경 =====
        lines.append("## 환경")
        if self.session_start_event:
            p = self.session_start_event.payload
            lines.append(f"- GUI 버전:  {p.get('version', '?')}")
            lines.append(f"- Python:    {p.get('python', '?')}")
            lines.append(f"- Platform:  {p.get('platform', '?')}")
        else:
            lines.append("- (session_start 이벤트가 보존되지 않음)")
        lines.append("")

        # ===== 키 관리 통계 =====
        lib_hits = sum(1 for e in self.gui_actions
                       if e.payload.get("action") == "key_mode_used"
                       and e.payload.get("mode") == "library")
        simple_hits = sum(1 for e in self.gui_actions
                          if e.payload.get("action") == "key_mode_used"
                          and e.payload.get("mode") == "simple")
        if lib_hits + simple_hits > 0:
            lines.append("## 키 관리 통계 (현재 세션)")
            lines.append(f"- 라이브러리 모드 사용: {lib_hits}회")
            lines.append(f"- 단순 모드 사용: {simple_hits}회")
            lines.append("")

        # ===== 사용자 액션 =====
        actions = list(self.gui_actions)
        lines.append(f"## 사용자 액션 (최근 {min(20, len(actions))}건)")
        for i, ev in enumerate(actions[-20:], 1):
            t = ev.timestamp.strftime("%H:%M:%S")
            act = ev.payload.get("action", "?")
            extras = {k: v for k, v in ev.payload.items() if k != "action"}
            extra_s = (" " + ", ".join(f"{k}={v}" for k, v in extras.items())) if extras else ""
            lines.append(f"{i}. [{t}] {act}{extra_s}")
        lines.append("")

        # ===== 프로세스 출력 =====
        proc_lines = list(self.process_outputs)
        if proc_lines:
            lines.append(f"## 프로세스 출력 (마지막 {include_stdout_lines}줄)")
            lines.append("```")
            for ev in proc_lines[-include_stdout_lines:]:
                lines.append(ev.payload.get("line", ""))
            lines.append("```")
            lines.append("")

            # 에러 라인 ±컨텍스트
            err_idx = [i for i, e in enumerate(proc_lines)
                       if any(k in e.payload.get("line", "")
                              for k in ("아닙니다", "Error", "error", "ERROR",
                                        "fail", "Fail", "데이터가 깨졌"))]
            if err_idx:
                lines.append(f"## 에러 라인 컨텍스트 (±{error_context}줄)")
                shown = set()
                for idx in err_idx[:5]:  # 최대 5개 에러 위치
                    lo = max(0, idx - error_context)
                    hi = min(len(proc_lines), idx + error_context + 1)
                    if any(i in shown for i in range(lo, hi)):
                        continue
                    lines.append(f"--- 위치 {idx} ---")
                    lines.append("```")
                    for i in range(lo, hi):
                        marker = " >> " if i == idx else "    "
                        lines.append(f"{marker}{proc_lines[i].payload.get('line', '')}")
                    lines.append("```")
                    shown.update(range(lo, hi))
                lines.append("")

        # ===== 정렬 복구 =====
        if self.recovery_events:
            lines.append(f"## 디코드 정렬 복구 ({len(self.recovery_events)}건)")
            for r in self.recovery_events[:10]:
                lines.append(f"- [{r['ts']}] line {r['line_num']}: {r['recovered']!r}")
            lines.append("")

        # ===== 예외 =====
        excs = list(self.exceptions)
        if excs:
            lines.append(f"## 예외 발생 ({len(excs)}건)")
            for e in excs[-5:]:
                p = e.payload
                lines.append(f"### {p.get('type', '?')} @ {p.get('where', '?')}")
                lines.append("```")
                lines.append(p.get("traceback", ""))
                lines.append("```")
            lines.append("")

        # ===== 경고 =====
        warns = list(self.warnings)
        if warns:
            lines.append(f"## 경고 ({len(warns)}건)")
            for w in warns[-10:]:
                p = w.payload
                msg = p.get("message", "?")
                t = w.timestamp.strftime("%H:%M:%S")
                extras = {k: v for k, v in p.items() if k != "message"}
                extra_s = (" — " + ", ".join(f"{k}={v}" for k, v in extras.items())) if extras else ""
                lines.append(f"- [{t}] {msg}{extra_s}")
            lines.append("")

        # ===== 종료 =====
        finishes = list(self.process_finishes)
        if finishes:
            lines.append("## 프로세스 종료 이력")
            for f_ev in finishes[-10:]:
                p = f_ev.payload
                lines.append(f"- [{f_ev.timestamp.strftime('%H:%M:%S')}] "
                             f"flag={p.get('flag', '?')}, exit={p.get('exit_code', '?')}, "
                             f"processed={p.get('processed', '?')}/{p.get('total', '?')}, "
                             f"failure={p.get('failure', 0)}, "
                             f"recovered={p.get('recovered', 0)}")
            lines.append("")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines), encoding="utf-8")
        return out_path


# ============================================================
# 4. 키 관리자 (듀얼 모드)
# ============================================================
class KeyManager:
    """
    모드 A (library): keys/<식별자>.bin 다중 보관, 작업 시작 시 __key.bin 으로 복사
    모드 B (simple) : __key.bin 단일 사용, 작업 종료 시 자동 삭제 (옵션)

    GUI는 KeyManager 인스턴스 1개를 공유하며, 모드 전환은 set_mode().
    """

    MODE_LIBRARY = "library"
    MODE_SIMPLE  = "simple"

    def __init__(self, tool_dir: Path, settings: QSettings, logger: DiagnosticLogger):
        self.tool_dir   = tool_dir
        self.settings   = settings
        self.logger     = logger
        self.lib_dir    = tool_dir.parent / "keys"  # GUI 폴더 기준
        self.lib_dir.mkdir(parents=True, exist_ok=True)
        self.active_key_path = tool_dir / "__key.bin"
        self.mode = settings.value("key_mode", self.MODE_LIBRARY)
        # F1: 활성 키 식별 추적. 다음 4가지 값 중 하나:
        #   - "<key_id>"        : 라이브러리에서 활성화된 키
        #   - "(직접 추출)"      : -xkey/-xmkey로 직접 추출한 키 (라이브러리 미연결)
        #   - "(외부)"          : __key.bin 존재하지만 GUI가 추적 못 한 상태
        #   - None              : __key.bin 없음
        self._active_key_id: Optional[str] = None
        self._init_active_key_status()
        # F2: 세션 동안 무시한 키-폴더 조합 (불일치 경고 재표시 방지)
        self._dismissed_warnings: set[tuple[str, str]] = set()

    def _init_active_key_status(self):
        """앱 시작 시 __key.bin 존재 여부와 settings 기반으로 식별자 초기화."""
        if not self.active_key_path.is_file():
            self._active_key_id = None
            return
        # 설정에서 마지막 활성 키 ID 복원 시도
        saved = self.settings.value("active_key_id", "") or ""
        if saved == "(직접 추출)":
            self._active_key_id = "(직접 추출)"
        elif saved and (self.lib_dir / f"{saved}.bin").is_file():
            self._active_key_id = saved
        else:
            self._active_key_id = "(외부)"

    @property
    def active_key_id(self) -> Optional[str]:
        return self._active_key_id

    def _set_active_key_id(self, key_id: Optional[str]):
        self._active_key_id = key_id
        if key_id is None:
            self.settings.remove("active_key_id")
        else:
            self.settings.setValue("active_key_id", key_id)

    def set_mode(self, mode: str):
        if mode not in (self.MODE_LIBRARY, self.MODE_SIMPLE):
            return
        self.mode = mode
        self.settings.setValue("key_mode", mode)
        self.logger.log("gui_action", {"action": "key_mode_changed", "mode": mode})

    # ---------- 라이브러리 모드 ----------
    def list_library_keys(self) -> list[str]:
        return sorted(p.stem for p in self.lib_dir.glob("*.bin"))

    def has_library_key(self, key_id: str) -> bool:
        return (self.lib_dir / f"{key_id}.bin").is_file()

    def activate_library_key(self, key_id: str) -> bool:
        """라이브러리 키를 __key.bin으로 복사."""
        src = self.lib_dir / f"{key_id}.bin"
        if not src.is_file():
            return False
        try:
            shutil.copy2(src, self.active_key_path)
            self._set_active_key_id(key_id)
            self.logger.log("gui_action", {
                "action": "key_activated",
                "mode":   "library",
                "key_id": key_id,
            })
            self.logger.log("gui_action", {"action": "key_mode_used", "mode": "library"})
            return True
        except Exception as ex:
            self.logger.log_exception("activate_library_key", ex)
            return False

    def store_to_library(self, key_id: str) -> bool:
        """현재 __key.bin을 라이브러리에 <key_id>.bin으로 보관."""
        if not self.active_key_path.is_file():
            return False
        try:
            dst = self.lib_dir / f"{key_id}.bin"
            shutil.copy2(self.active_key_path, dst)
            # 저장 후에는 그 키가 곧 활성 키와 동일하다는 의미. 추적 갱신.
            self._set_active_key_id(key_id)
            self.logger.log("gui_action", {
                "action": "key_stored_to_library",
                "key_id": key_id,
            })
            return True
        except Exception as ex:
            self.logger.log_exception("store_to_library", ex)
            return False

    def delete_library_key(self, key_id: str) -> bool:
        try:
            (self.lib_dir / f"{key_id}.bin").unlink(missing_ok=True)
            # H1: 활성 키였다면 추적 정보 무효화. __key.bin 자체가 살아있다면 "(외부)"로
            # 격하 표시(어느 게임 키인지 알 수 없음 경고).
            invalidated = False
            if self._active_key_id == key_id:
                new_state = "(외부)" if self.active_key_path.is_file() else None
                self._set_active_key_id(new_state)
                invalidated = True
            self.logger.log("gui_action", {
                "action": "key_deleted_from_library",
                "key_id": key_id,
                "active_invalidated": invalidated,
            })
            return True
        except Exception as ex:
            self.logger.log_exception("delete_library_key", ex)
            return False

    # ---------- 단순 모드 ----------
    def has_active_key(self) -> bool:
        return self.active_key_path.is_file()

    def clear_active_key(self):
        """단순 모드 종료 시 __key.bin 삭제."""
        try:
            self.active_key_path.unlink(missing_ok=True)
            self._set_active_key_id(None)
            self.logger.log("gui_action", {"action": "active_key_cleared"})
        except Exception as ex:
            self.logger.log_exception("clear_active_key", ex)

    def mark_simple_used(self):
        self.logger.log("gui_action", {"action": "key_mode_used", "mode": "simple"})

    def mark_direct_extraction(self):
        """-xkey/-xmkey로 직접 추출한 직후 호출. 활성 키를 '직접 추출'로 표시."""
        if self.active_key_path.is_file():
            self._set_active_key_id("(직접 추출)")

    # ---------- F2: 키-폴더 일치 검증 ----------
    def is_warning_dismissed(self, key_id: str, folder_id: str) -> bool:
        return (key_id, folder_id) in self._dismissed_warnings

    def dismiss_warning(self, key_id: str, folder_id: str):
        self._dismissed_warnings.add((key_id, folder_id))

    def folder_matches_active_key(self, folder_path: str) -> tuple[bool, str, str]:
        """
        입력 폴더와 활성 키 식별자가 일치하는지 판정.
        반환: (일치 여부, 활성 키 식별자, 폴더 식별자)
        활성 키가 라이브러리 키가 아닐 경우 (직접 추출/외부) 항상 일치 처리.
        """
        active = self._active_key_id
        folder_id = self.guess_key_id_from_path(folder_path)
        if not active or active in ("(직접 추출)", "(외부)"):
            return True, active or "", folder_id
        # 단순 비교 (대소문자 구분)
        return active == folder_id, active, folder_id

    # ---------- 게임명 추정 ----------
    @staticmethod
    def guess_key_id_from_path(folder_or_file: str) -> str:
        """입력 경로에서 키 식별자 후보를 추정 (폴더명 기반)."""
        if not folder_or_file:
            return ""
        # 백슬래시 → 슬래시 통일 (Windows 환경 외에도 안전)
        normalized = folder_or_file.replace("\\", "/")
        p = Path(normalized)
        # 파일 경로면 부모로 (확장자 유무로 판단 — 미존재 경로/타플랫폼에서도 동작)
        if p.suffix:
            p = p.parent
        # Scene/dat 같은 일반 서브폴더명이면 부모로 한 단계 올라감
        common = {"scene", "dat", "g00", "mov", "bgm", "voice", "se"}
        if p.name.lower() in common:
            p = p.parent
        return p.name


# ============================================================
# 5. 최근 경로
# ============================================================
class RecentPaths:
    """QSettings 기반. 옵션별로 마지막 사용 경로 저장."""

    def __init__(self, settings: QSettings):
        self.settings = settings

    def get(self, key: str, default: str = "") -> str:
        return self.settings.value(f"recent/{key}", default) or default

    def set(self, key: str, value: str):
        if value:
            self.settings.setValue(f"recent/{key}", value)


# ============================================================
# 6. 자동 백업
# ============================================================
class AutoBackup:
    """
    덮어쓰기 옵션 실행 전 원본 백업.
    backup_dir/<원본명>_<YYYY-MM-DD_HH-MM-SS>.<ext> 형식.
    """

    def __init__(self, base_dir: Path, logger: DiagnosticLogger):
        self.backup_dir = base_dir / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger

    def backup_file(self, src_path: str) -> Optional[Path]:
        try:
            src = Path(src_path)
            if not src.is_file():
                return None
            ts = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            dst = self.backup_dir / f"{src.stem}_{ts}{src.suffix}"
            shutil.copy2(src, dst)
            self.logger.log("gui_action", {
                "action":   "auto_backup",
                "src":      str(src),
                "dst":      str(dst),
            })
            return dst
        except Exception as ex:
            self.logger.log_exception("backup_file", ex)
            return None

    def backup_folder(self, src_dir: str) -> Optional[Path]:
        try:
            src = Path(src_dir)
            if not src.is_dir():
                return None
            ts = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            dst = self.backup_dir / f"{src.name}_{ts}"
            shutil.copytree(src, dst)
            self.logger.log("gui_action", {
                "action": "auto_backup_folder",
                "src":    str(src),
                "dst":    str(dst),
            })
            return dst
        except Exception as ex:
            self.logger.log_exception("backup_folder", ex)
            return None


# ============================================================
# 7. 범용 Runner (모든 옵션 지원)
# ============================================================
class GenericRunner(QObject):
    """
    PoC의 XatRunner를 일반화. 모든 17개 옵션을 동일한 인터페이스로 실행.
    옵션별 특수 처리(stdin 프롬프트 등)는 ToolOption 메타데이터로 분기.
    """
    log_emitted      = Signal(str)
    progress_changed = Signal(int, int)
    prompt_required  = Signal()
    finished_signal  = Signal(int)
    error_signal     = Signal(str)

    def __init__(self, logger: DiagnosticLogger, parent=None):
        super().__init__(parent)
        self.logger = logger
        self.proc: Optional[QProcess] = None
        self.byte_buffer  = bytearray()
        self.text_buffer  = ""
        self.auto_answer: Optional[str] = None
        self.processed_count = 0
        self.total_count     = 0
        self.recovered_count = 0
        self.line_num        = 0
        self.current_option: Optional[ToolOption] = None
        self.start_time:     Optional[_dt.datetime] = None

    def start(self, tool_path: str, option: ToolOption,
              args: list[str], total_files: int = 0):
        self._reset_state(total_files, option)

        cli_args = [option.flag] + args

        self.proc = QProcess(self)
        self.proc.setProgram(tool_path)
        self.proc.setArguments(cli_args)
        self.proc.setWorkingDirectory(str(Path(tool_path).parent))
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._on_stdout)
        self.proc.finished.connect(self._on_finished)
        self.proc.errorOccurred.connect(self._on_error)

        self.start_time = _dt.datetime.now()

        # 디버그용: 실제 OS에 전달될 명령행 문자열 추정
        try:
            displayed_cmd = " ".join(
                f'"{a}"' if (" " in a or "\t" in a) else a
                for a in [tool_path] + cli_args
            )
        except Exception:
            displayed_cmd = "(could not format)"

        self.logger.log("process_start", {
            "flag":       option.flag,
            "args":       args,
            "tool":       tool_path,
            "cwd":        str(Path(tool_path).parent),
            "total":      total_files,
            "displayed_cmd": displayed_cmd,
        })

        self.proc.start()

        # waitForStarted: OS가 프로세스 생성을 완료할 때까지 대기 (5초 타임아웃)
        # 실패 시 errorOccurred 시그널이 별도로 발생하므로 여기서는 추가 진단만
        if not self.proc.waitForStarted(5000):
            error_str = ""
            try:
                error_str = self.proc.errorString()
            except Exception:
                pass
            err_state = {
                "errorString": error_str,
                "state":       _safe_enum_int(self.proc.state()),
                "error_enum":  _safe_enum_int(self.proc.error()),
                "displayed_cmd": displayed_cmd,
                "tool_exists": Path(tool_path).is_file(),
                "cwd_exists":  Path(tool_path).parent.is_dir(),
            }
            self.logger.log("process_start_failed", err_state)
            # errorOccurred 핸들러가 별도로 처리하지만, 보강 메시지 발신
            self.error_signal.emit(
                f"프로세스 시작 실패 (5초 타임아웃)\n"
                f"OS 메시지: {error_str or '(없음)'}\n"
                f"명령행:    {displayed_cmd}"
            )

    def send_response(self, choice: str):
        if self.proc is None:
            return
        self.proc.write((choice + "\n").encode("ascii"))
        self.proc.waitForBytesWritten(1000)
        self.log_emitted.emit(f"[GUI] stdin 응답 송신: '{choice}'")
        self.logger.log("prompt", {"choice": choice, "auto": False})

    def set_auto_answer(self, choice: Optional[str]):
        self.auto_answer = choice

    def cancel(self):
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.proc.kill()
            self.log_emitted.emit("[GUI] 사용자 요청으로 작업 취소.")
            self.logger.log("gui_action", {"action": "process_cancel"})

    def _reset_state(self, total_files: int, option: ToolOption):
        self.byte_buffer.clear()
        self.text_buffer = ""
        self.processed_count = 0
        self.total_count = total_files
        self.recovered_count = 0
        self.line_num = 0
        self.current_option = option
        # F3: -xat 결과 검증용. 파일 단위 카운트 (중복 방지를 위해 latch 사용).
        self.failure_count = 0
        self.skip_count    = 0
        self._current_file_failed = False  # I3: 현재 처리 중 파일에서 이미 실패 마커를 봤는가

    def _on_stdout(self):
        if self.proc is None:
            return
        try:
            chunk = bytes(self.proc.readAllStandardOutput())
        except Exception as ex:
            self.logger.log_exception("readAllStandardOutput", ex)
            return
        if not chunk:
            return
        self.byte_buffer.extend(chunk)

        usable = len(self.byte_buffer) - (len(self.byte_buffer) % 2)
        if usable == 0:
            return

        raw_slice = bytes(self.byte_buffer[:usable])
        try:
            text, recovered = decode_with_recovery(raw_slice)
        except Exception as ex:
            self.logger.log_exception("decode_with_recovery", ex)
            del self.byte_buffer[:usable]
            return
        del self.byte_buffer[:usable]

        if recovered:
            self.recovered_count += 1
            self.logger.log_recovery(
                self.line_num,
                raw_slice[:32].hex(),
                text[:80],
            )

        text = re.sub(r"\r+\n", "\n", text).replace("\r", "")
        text = text.lstrip("\x00")
        self.text_buffer += text

        while "\n" in self.text_buffer:
            line, _, self.text_buffer = self.text_buffer.partition("\n")
            line = line.strip("\x00").strip()
            if not line:
                continue
            self.line_num += 1
            self.log_emitted.emit(line)
            self.logger.log("process_output", {"line": line, "n": self.line_num})

            if "Finished." in line:
                self.processed_count += 1
                self.progress_changed.emit(self.processed_count, self.total_count)
                # I3: 다음 파일 처리를 위해 실패 latch 리셋
                self._current_file_failed = False

            # F3+I3: -xat 결과 검증을 위한 실패/스킵 카운트
            # 한 파일에서 여러 실패 마커가 나와도 중복 카운트 방지 (latch 사용).
            # 마커 종류:
            #   - "텍스트 데이터가 깨졌습니다"      (data corruption)
            #   - "정적 변수 데이터가 깨졌습니다"   (static variable corruption)
            #   - "Failed while reading"           (general read failure)
            elif ("데이터가 깨졌습니다" in line
                  or "Failed while reading" in line):
                if not self._current_file_failed:
                    self.failure_count += 1
                    self._current_file_failed = True
            elif "처리할 필요 없는 파일" in line:
                self.skip_count += 1

            if (self.current_option and self.current_option.has_stdin_prompt
                    and PROMPT_PATTERN.search(line)):
                if self.auto_answer:
                    self.send_response(self.auto_answer)
                    self.logger.log("prompt", {"choice": self.auto_answer, "auto": True})
                else:
                    self.prompt_required.emit()

    def _on_finished(self, code: int, status):
        self._on_stdout()
        if self.text_buffer:
            for ln in self.text_buffer.splitlines():
                ln = ln.strip("\x00").strip()
                if ln:
                    self.log_emitted.emit(ln)
                    self.logger.log("process_output", {"line": ln})
            self.text_buffer = ""

        elapsed = (
            (_dt.datetime.now() - self.start_time).total_seconds()
            if self.start_time else 0.0
        )
        self.logger.log("process_finish", {
            "flag":       self.current_option.flag if self.current_option else "?",
            "exit_code":  code,
            "processed":  self.processed_count,
            "total":      self.total_count,
            "recovered":  self.recovered_count,
            "failure":    self.failure_count,
            "skipped":    self.skip_count,
            "elapsed_s":  round(elapsed, 1),
        })
        self.finished_signal.emit(code)

    def _on_error(self, err):
        # err는 QProcess.ProcessError enum
        error_string = ""
        program       = ""
        arguments     = []
        cwd           = ""
        try:
            if self.proc:
                error_string = self.proc.errorString() or ""
                program      = self.proc.program() or ""
                arguments    = list(self.proc.arguments() or [])
                cwd          = self.proc.workingDirectory() or ""
        except Exception:
            pass

        msg = (
            f"프로세스 오류: {err}\n"
            f"  OS 메시지: {error_string or '(없음)'}\n"
            f"  실행파일:  {program}\n"
            f"  인자:      {arguments}\n"
            f"  작업폴더:  {cwd}"
        )
        self.error_signal.emit(msg)
        self.logger.log("warning", {
            "message":      f"프로세스 오류: {err}",
            "error_enum":   _safe_enum_int(err),
            "error_string": error_string,
            "program":      program,
            "arguments":    arguments,
            "cwd":          cwd,
            "program_exists": Path(program).is_file() if program else False,
            "cwd_exists":     Path(cwd).is_dir() if cwd else False,
        })


# ============================================================
# 8. 입력 폴더 사전 카운트
# ============================================================
# F4: -xat은 .json 파일도 처리(스킵)하므로 카운트에 포함해야 processed/total 일치
TARGET_TEXT_EXT = {".scn", ".dbs", ".dat", ".json"}
TARGET_IMG_EXT  = {".g00"}
TARGET_VID_EXT  = {".omv"}

def count_files(folder: str, exts: set[str]) -> int:
    n = 0
    try:
        for p in Path(folder).rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                n += 1
    except Exception:
        pass
    return n


# ============================================================
# 9. QSettings 헬퍼
# ============================================================
def make_settings() -> QSettings:
    """포터블 원칙: 실행파일 폴더의 settings.ini 사용."""
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    ini_path = base / "settings.ini"
    return QSettings(str(ini_path), QSettings.IniFormat)


def app_base_dir() -> Path:
    """logs/, keys/, backups/ 의 기준 폴더 (포터블)."""
    return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
