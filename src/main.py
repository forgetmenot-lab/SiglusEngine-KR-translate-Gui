# -*- coding: utf-8 -*-
"""
main.py
=======
ToolForSiglus GUI — Phase 1 엔트리 포인트.
직접 모드 + 진단 보고서 + 키 관리(듀얼) + 자동 백업 통합.
위저드 모드는 Phase 2에서 추가됨.
"""

from __future__ import annotations

import os
import sys
import datetime as _dt
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui  import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QSplitter,
    QFileDialog, QMessageBox, QHBoxLayout, QLabel, QPushButton, QStatusBar,
    QCheckBox
)

from tfs_options import OPTIONS, OPTION_BY_FLAG, ToolOption, ArgKind
from tfs_core import (
    GenericRunner, KeyManager, RecentPaths, AutoBackup, DiagnosticLogger,
    validate_tool_exe, count_files, make_settings, app_base_dir,
    APP_NAME, APP_VERSION,
    TARGET_TEXT_EXT, TARGET_IMG_EXT, TARGET_VID_EXT,
)
from tfs_ui import (
    DropFileEdit, DirectModeWidget, StatusPanel
)


WINDOW_TITLE = f"{APP_NAME}  v{APP_VERSION}"


# ============================================================
# 메인 윈도우
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(960, 800)

        # ----- 핵심 객체 초기화 -----
        self.base_dir = app_base_dir()
        self.settings = make_settings()
        self.recent   = RecentPaths(self.settings)
        self.logger   = DiagnosticLogger(self.base_dir)

        # ----- 도구 경로 설정 (자동 탐지 + 영속화) -----
        self.tool_path = self._resolve_tool_path()
        if not self.tool_path:
            self._show_tool_picker_blocking()
        if not self.tool_path:
            QMessageBox.critical(self, "도구 미선택",
                "ToolForSiglus.exe를 지정해야 GUI를 사용할 수 있습니다.\n프로그램을 종료합니다.")
            sys.exit(1)

        self.key_mgr = KeyManager(Path(self.tool_path).parent, self.settings, self.logger)
        self.backup  = AutoBackup(self.base_dir, self.logger)

        self.runner = GenericRunner(self.logger, self)
        self.runner.log_emitted.connect(self._append_log)
        self.runner.progress_changed.connect(self._on_progress)
        self.runner.prompt_required.connect(self._on_prompt_required)
        self.runner.finished_signal.connect(self._on_finished)
        self.runner.error_signal.connect(self._on_error)

        # ----- UI -----
        self._build_menus()
        self._build_central()
        self._update_tool_status_bar()

        self.logger.log("gui_action", {
            "action":    "main_window_ready",
            "tool":      self.tool_path,
        })

    # ---------- 도구 경로 해결 ----------
    def _resolve_tool_path(self) -> str | None:
        # 1) 영속 설정
        saved = self.settings.value("tool_path", "")
        if saved and Path(saved).is_file():
            ok, _ = validate_tool_exe(saved)
            if ok:
                return saved

        # 2) 동일 폴더 자동 탐지
        candidates = [
            self.base_dir / "ToolForSiglus.exe",
            Path(sys.executable).parent / "ToolForSiglus.exe",
        ]
        for c in candidates:
            if c.is_file():
                ok, _ = validate_tool_exe(str(c))
                if ok:
                    self.settings.setValue("tool_path", str(c))
                    return str(c)
        return None

    def _show_tool_picker_blocking(self):
        """도구 미발견 시 시작 단계에서 모달로 묻는다."""
        QMessageBox.information(self, "도구 선택 필요",
            "ToolForSiglus.exe 위치를 지정해주세요.\n"
            "(GUI 폴더에 같이 두면 다음 실행부터는 자동 인식됩니다.)")
        path, _ = QFileDialog.getOpenFileName(
            self, "ToolForSiglus.exe 선택", "", "실행 파일 (*.exe)")
        if not path:
            return
        ok, msg = validate_tool_exe(path)
        if not ok:
            QMessageBox.critical(self, "검증 실패", msg)
            return
        self.tool_path = path
        self.settings.setValue("tool_path", path)

    # ---------- 메뉴 ----------
    def _build_menus(self):
        bar = self.menuBar()

        m_file = bar.addMenu("파일")
        a_change_tool = QAction("도구 경로 변경...", self)
        a_change_tool.triggered.connect(self._action_change_tool)
        m_file.addAction(a_change_tool)
        m_file.addSeparator()
        a_open_logs = QAction("로그 폴더 열기", self)
        a_open_logs.triggered.connect(lambda: self._open_in_explorer(self.base_dir / "logs"))
        m_file.addAction(a_open_logs)
        a_open_keys = QAction("키 라이브러리 폴더 열기", self)
        a_open_keys.triggered.connect(lambda: self._open_in_explorer(self.base_dir / "keys"))
        m_file.addAction(a_open_keys)
        a_open_backups = QAction("백업 폴더 열기", self)
        a_open_backups.triggered.connect(lambda: self._open_in_explorer(self.base_dir / "backups"))
        m_file.addAction(a_open_backups)
        m_file.addSeparator()
        a_exit = QAction("종료", self)
        a_exit.triggered.connect(self.close)
        m_file.addAction(a_exit)

        m_help = bar.addMenu("도움말")
        a_export = QAction("진단 보고서 내보내기...", self)
        a_export.triggered.connect(self._action_export_report)
        m_help.addAction(a_export)
        a_about = QAction(f"{APP_NAME} 정보", self)
        a_about.triggered.connect(self._action_about)
        m_help.addAction(a_about)

    # ---------- 중앙 위젯 ----------
    def _build_central(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        v = QVBoxLayout(cw)

        splitter = QSplitter(Qt.Vertical)

        # 상단: 직접 모드
        self.direct = DirectModeWidget(self.key_mgr, self.recent)
        self.direct.request_run.connect(self._on_run_request)
        splitter.addWidget(self.direct)

        # 하단: 상태 패널
        self.status_panel = StatusPanel()
        self.status_panel.cancel_requested.connect(self.runner.cancel)
        self.status_panel.prompt_response.connect(self._on_prompt_response)
        splitter.addWidget(self.status_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        v.addWidget(splitter)

        sb = QStatusBar()
        self.setStatusBar(sb)

    def _update_tool_status_bar(self):
        if self.tool_path:
            self.statusBar().showMessage(f"도구: {self.tool_path}")
        else:
            self.statusBar().showMessage("도구 미설정")

    # ---------- 메뉴 액션 ----------
    def _action_change_tool(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "ToolForSiglus.exe 선택", "", "실행 파일 (*.exe)")
        if not path:
            return
        ok, msg = validate_tool_exe(path)
        if not ok:
            QMessageBox.critical(self, "검증 실패", msg)
            return
        self.tool_path = path
        self.settings.setValue("tool_path", path)
        # KeyManager는 도구 폴더 변경 시 재생성이 안전
        self.key_mgr = KeyManager(Path(path).parent, self.settings, self.logger)
        self.direct.key_mgr = self.key_mgr
        self.direct.refresh_keys()
        self._update_tool_status_bar()
        self.logger.log("gui_action", {"action": "tool_path_changed", "path": path})
        QMessageBox.information(self, "완료", f"도구 경로 변경됨:\n{path}")

    def _action_export_report(self):
        ts = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        default_name = f"diagnostic_report_{ts}.md"
        path, _ = QFileDialog.getSaveFileName(
            self, "진단 보고서 저장",
            str(self.base_dir / default_name),
            "Markdown (*.md)")
        if not path:
            return
        try:
            out = self.logger.export_report(Path(path))
            # 클립보드에도 복사
            content = out.read_text(encoding="utf-8")
            QGuiApplication.clipboard().setText(content)
            QMessageBox.information(self, "완료",
                f"진단 보고서가 저장되었으며 클립보드에도 복사되었습니다:\n{out}")
            self.logger.log("gui_action", {"action": "report_exported", "path": str(out)})
        except Exception as ex:
            self.logger.log_exception("export_report", ex)
            QMessageBox.critical(self, "실패", f"보고서 생성 실패: {ex}")

    def _action_about(self):
        QMessageBox.about(self, f"{APP_NAME} 정보",
            f"<h3>{APP_NAME}</h3>"
            f"<p>버전: {APP_VERSION}</p>"
            f"<p>ToolForSiglus의 GUI 래퍼.<br>"
            f"시글러스 엔진 게임 한국어 패치 작업용.</p>"
            f"<p>도구 경로: <code>{self.tool_path}</code></p>")

    # ---------- 옵션 실행 ----------
    def _on_run_request(self, option: ToolOption, args: list[str]):
        # H8: 새 옵션 시작 시 이전 진행률 즉시 리셋 (사전 검증/다이얼로그 단계에서
        # 이전 옵션의 카운트가 보이는 혼동 방지)
        self.status_panel.set_progress(0, 1, "준비 중...")

        # 1) 도구 검증
        ok, msg = validate_tool_exe(self.tool_path)
        if not ok:
            QMessageBox.critical(self, "도구 검증 실패", msg)
            return

        # 2) 키 요구사항 확인
        if option.requires_key and not self.key_mgr.has_active_key():
            r = QMessageBox.question(
                self, "키 파일 없음",
                f"이 옵션({option.flag})은 __key.bin이 필요합니다.\n"
                f"현재 도구 폴더에 키 파일이 없습니다.\n\n"
                "그래도 계속하시겠습니까?",
                QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return

        # H2: -rt 사전 검증 — .ext.txt/.ext.ini 존재 여부.
        #     도구는 입력 .scn/.dat과 같은 폴더에서 동명의 .ext.* 파일을 자동으로 찾음.
        #     없으면 "파일을 열 수 없거나 형식이 잘못되었습니다"로 실패하므로 미리 차단.
        if option.flag == "-rt" and len(args) >= 1:
            target = Path(args[0])
            ext_txt = target.parent / f"{target.stem}.ext.txt"
            ext_ini = target.parent / f"{target.stem}.ext.ini"
            if not ext_txt.exists() and not ext_ini.exists():
                QMessageBox.warning(
                    self, "텍스트 파일 없음",
                    f"-rt는 입력 파일과 같은 폴더에 동명의 .ext.txt 또는 .ext.ini가 미리 있어야 합니다.\n\n"
                    f"  입력 파일:    {target.name}\n"
                    f"  필요한 파일:  {ext_txt.name}  또는  {ext_ini.name}\n"
                    f"  찾은 위치:    {target.parent}\n"
                    f"  존재 여부:    ❌ 없음\n\n"
                    "권장 절차:\n"
                    "  1) 먼저 -xt 옵션으로 .ext.txt를 생성하세요\n"
                    "  2) 메모장으로 .ext.txt를 수정하세요 (UTF-16 LE 인코딩 유지)\n"
                    "  3) 그 후 -rt 옵션으로 .scn에 재삽입하세요\n\n"
                    "또는 텍스트 폴더를 별도로 관리하고 싶다면 -rat 옵션을 사용하세요."
                )
                self.logger.log("gui_action", {
                    "action": "rt_precheck_aborted",
                    "target": str(target),
                    "missing": [ext_txt.name, ext_ini.name],
                })
                return

        # F2: 키-폴더 식별자 일치 검증 (라이브러리 키일 때만)
        # 입력 폴더가 있는 옵션 한정 (단일 파일 옵션은 검증 생략)
        if option.requires_key and self.key_mgr.has_active_key() and args:
            folder_arg = self._extract_folder_for_validation(option, args)
            if folder_arg:
                matches, active_id, folder_id = self.key_mgr.folder_matches_active_key(folder_arg)
                if not matches:
                    if not self.key_mgr.is_warning_dismissed(active_id, folder_id):
                        msg_box = QMessageBox(self)
                        msg_box.setIcon(QMessageBox.Warning)
                        msg_box.setWindowTitle("키-폴더 불일치 가능성")
                        msg_box.setText(
                            f"활성 키 식별자와 입력 폴더의 게임명이 일치하지 않을 수 있습니다.\n\n"
                            f"  활성 키:    {active_id}\n"
                            f"  입력 폴더:  {folder_id}\n\n"
                            "다른 게임의 키로 작업하면 모든 .scn 파일이 깨진 데이터로 처리됩니다.\n"
                            "그래도 진행하시겠습니까?"
                        )
                        chk = QCheckBox("이 키-폴더 조합에 대해 다시 묻지 않기")
                        msg_box.setCheckBox(chk)
                        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                        msg_box.setDefaultButton(QMessageBox.No)
                        r = msg_box.exec()
                        if r != QMessageBox.Yes:
                            self.logger.log("gui_action", {
                                "action":     "key_folder_mismatch_aborted",
                                "active_key": active_id,
                                "folder_id":  folder_id,
                            })
                            return
                        if chk.isChecked():
                            self.key_mgr.dismiss_warning(active_id, folder_id)
                            self.logger.log("gui_action", {
                                "action":     "key_folder_warning_dismissed",
                                "active_key": active_id,
                                "folder_id":  folder_id,
                            })

        # 3) 사전 파일 카운트 (텍스트/이미지/영상 폴더 옵션)
        total = 0
        if option.flag in ("-xat", "-rat") and len(args) >= 1:
            total = count_files(args[0], TARGET_TEXT_EXT)
            if total == 0:
                r = QMessageBox.question(self, "대상 파일 없음",
                    f"입력 폴더에 .scn/.dbs/.dat 파일이 없습니다.\n그래도 실행하시겠습니까?",
                    QMessageBox.Yes | QMessageBox.No)
                if r != QMessageBox.Yes:
                    return
        elif option.flag in ("-xaimg", "-raimg") and len(args) >= 1:
            total = count_files(args[0], TARGET_IMG_EXT)

        # 4) 자동 백업 (overwrites_input + 기본 ON)
        if option.overwrites_input:
            # H7: 백업 대상과 위치를 구체적으로 표시
            backup_desc = self._describe_backup_target(option, args)
            r = QMessageBox.question(self, "자동 백업",
                f"이 옵션({option.flag})은 입력 파일을 직접 수정합니다.\n\n"
                f"{backup_desc}\n\n"
                "  백업 위치:    "
                f"{Path(self.tool_path).parent / 'backups'}\\<타임스탬프>\n\n"
                "작업 전 자동 백업을 수행하시겠습니까? (강력 권장)",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes)
            if r == QMessageBox.Cancel:
                return
            if r == QMessageBox.Yes:
                self._perform_backup(option, args)

        # 5) 출력 폴더 정규화 (상대경로 → 도구 폴더 기준 절대경로)
        normalized_args = self._normalize_args(option, args)

        # 6) 키 모드 사용 카운팅
        if option.requires_key:
            if self.key_mgr.mode == KeyManager.MODE_LIBRARY:
                self.logger.log("gui_action", {"action": "key_mode_used", "mode": "library"})
            else:
                self.key_mgr.mark_simple_used()

        # 7) 실행
        self.status_panel.clear_log()
        self._append_log(f"[GUI] 옵션: {option.flag} ({option.label})")
        self._append_log(f"[GUI] 인자: {normalized_args}")
        self._append_log(f"[GUI] 도구: {self.tool_path}")
        self._append_log(f"[GUI] 작업폴더: {Path(self.tool_path).parent}")
        if total > 0:
            self._append_log(f"[GUI] 대상 파일 사전 카운트: {total}개")
        self._append_log("─" * 60)

        self._set_running(True, total)
        self.runner.start(self.tool_path, option, normalized_args, total)

        self.logger.log("gui_action", {
            "action": "run_started",
            "flag":   option.flag,
            "args":   normalized_args,
        })

    def _describe_backup_target(self, option: ToolOption, args: list[str]) -> str:
        """
        H7: 자동 백업 다이얼로그에 표시할 옵션별 백업 대상 설명.
        실제 _perform_backup의 분기와 동기화되어 있어야 함.
        """
        if not args:
            return "  백업 대상:    (인자 없음)"
        flag = option.flag
        if flag in ("-rat", "-raimg"):
            return f"  백업 대상:    원본 폴더 전체\n  대상 경로:    {args[0]}"
        if flag in ("-rt", "-rimg", "-rv") and len(args) >= 1:
            return f"  백업 대상:    단일 입력 파일\n  대상 경로:    {args[0]}"
        if flag == "-p":
            parent = Path(args[0]).parent
            pck = parent / "Scene.pck"
            if pck.is_file():
                return f"  백업 대상:    기존 Scene.pck (있을 경우)\n  대상 경로:    {pck}"
            return f"  백업 대상:    기존 Scene.pck (없으므로 백업 생략)"
        return f"  백업 대상:    {args[0]}"

    def _perform_backup(self, option: ToolOption, args: list[str]):
        """옵션별 백업 대상 결정."""
        try:
            if option.flag in ("-rat", "-raimg") and len(args) >= 1:
                # 폴더 백업
                self._append_log(f"[GUI] 폴더 백업 중: {args[0]}")
                dst = self.backup.backup_folder(args[0])
                if dst:
                    self._append_log(f"[GUI] 백업 완료: {dst}")
            elif option.flag in ("-rt", "-rimg", "-rv") and len(args) >= 1:
                # 단일 파일 백업
                self._append_log(f"[GUI] 파일 백업 중: {args[0]}")
                dst = self.backup.backup_file(args[0])
                if dst:
                    self._append_log(f"[GUI] 백업 완료: {dst}")
            elif option.flag == "-p" and len(args) >= 1:
                # _new.pck 생성이지만 사용자가 같은 이름으로 덮을 가능성 대비
                # 폴더의 부모에 Scene.pck가 있으면 백업
                parent = Path(args[0]).parent
                pck = parent / "Scene.pck"
                if pck.is_file():
                    self._append_log(f"[GUI] Scene.pck 백업 중...")
                    dst = self.backup.backup_file(str(pck))
                    if dst:
                        self._append_log(f"[GUI] 백업 완료: {dst}")
        except Exception as ex:
            self.logger.log_exception("perform_backup", ex)
            self._append_log(f"[GUI][경고] 백업 실패: {ex}")

    def _extract_folder_for_validation(self, option: ToolOption, args: list[str]) -> str:
        """
        F2: 키-폴더 일치 검증을 위해 옵션 인자에서 '게임 식별 폴더'를 추출.
        - 폴더 인자(FOLDER_IN)가 있으면 그 첫 번째.
        - 단일 파일 옵션의 경우 그 파일의 부모 폴더.
        - .pck 파일의 경우 .pck가 든 폴더 (게임 루트일 가능성 높음).
        """
        from tfs_options import ArgKind
        for i, spec in enumerate(option.args):
            if i >= len(args):
                break
            if spec.kind == ArgKind.FOLDER_IN:
                return args[i]
            # 입력 파일 옵션 — 부모 폴더 사용
            if spec.kind in (ArgKind.FILE_PCK, ArgKind.FILE_SCN, ArgKind.FILE_DAT):
                p = Path(args[i])
                return str(p.parent) if p.is_file() else ""
        return ""

    def _normalize_args(self, option: ToolOption, args: list[str]) -> list[str]:
        """출력 인자가 상대경로면 도구 폴더 기준으로 절대화."""
        if not args:
            return args
        out = list(args)
        for i, spec in enumerate(option.args):
            if i >= len(out):
                break
            if spec.kind == ArgKind.FOLDER_OUT:
                p = Path(out[i])
                if not p.is_absolute():
                    p = Path(self.tool_path).parent / p
                out[i] = str(p.resolve())
        return out

    # ---------- Runner 시그널 핸들러 ----------
    def _append_log(self, line: str):
        self.status_panel.append_log(line)

    def _on_progress(self, current: int, total: int):
        self.status_panel.set_progress(current, total, f"진행 중 ({current}/{total}) — %p%")

    def _on_prompt_required(self):
        self.status_panel.show_prompt()

    def _on_prompt_response(self, choice: str, remember: bool):
        if remember:
            self.runner.set_auto_answer(choice)
            self._append_log(f"[GUI] 이후 동일 응답 자동 적용: '{choice}'")
        self.runner.send_response(choice)

    def _on_finished(self, code: int):
        self._append_log("─" * 60)
        processed = self.runner.processed_count
        total     = self.runner.total_count
        recovered = self.runner.recovered_count
        failure   = getattr(self.runner, "failure_count", 0)
        skipped   = getattr(self.runner, "skip_count", 0)
        flag      = self.runner.current_option.flag if self.runner.current_option else ""

        # F1: -xkey/-xmkey 직후 활성 키를 "직접 추출"로 표시
        if flag in ("-xkey", "-xmkey") and self.key_mgr.has_active_key():
            self.key_mgr.mark_direct_extraction()
            self.direct.refresh_keys()

        # F3: -xat 실패율 검증
        # 처리 시도된 파일 = .scn/.dbs/.dat (json은 스킵 카운트로 분리)
        attempted = max(processed - skipped, 0)
        if flag == "-xat" and attempted > 0:
            failure_rate = failure / attempted
            if failure_rate >= 0.5:
                self._append_log(
                    f"[GUI][경고] 처리 실패율 {failure_rate*100:.1f}% "
                    f"({failure}/{attempted}건 실패).\n"
                    f"           활성 키와 입력 폴더가 같은 게임의 것인지 확인하세요.\n"
                    f"           현재 활성 키: {self.key_mgr.active_key_id or '(없음)'}"
                )
                self.logger.log("warning", {
                    "message":      "high_failure_rate",
                    "flag":         flag,
                    "failure_rate": failure_rate,
                    "failure":      failure,
                    "attempted":    attempted,
                    "active_key":   self.key_mgr.active_key_id,
                })

        if code == 0 and total > 0 and processed == 0:
            self._append_log(
                "[GUI][경고] exit 0이지만 처리된 파일이 0건입니다. "
                "키 파일 누락이나 입력 경로 문제 가능성을 확인해주세요.")
        elif code == 0:
            summary = f"[GUI] 완료. exit code = 0, 처리 {processed}/{total}건"
            if skipped > 0:
                summary += f" (스킵 {skipped}건)"
            if failure > 0:
                summary += f" (실패 {failure}건)"
            self._append_log(summary)
            if recovered > 0:
                self._append_log(
                    f"[GUI] 디코드 정렬 복구 {recovered}회 (진단 보고서 자동 기록됨)")
        else:
            self._append_log(f"[GUI] 비정상 종료. exit code = {code}")

        self.status_panel.set_progress(processed, total, f"완료 ({processed}/{total})")
        self._set_running(False, 0)

        # 키 단순 모드 + .scn 후처리: 작업 종료 후 __key.bin 자동 삭제 안 함
        # (사용자 명시적 액션이 아닌 경우 자동 삭제는 위험. 메뉴에서 별도 제공)

    def _on_error(self, msg: str):
        self._append_log(f"[GUI][ERROR] {msg}")
        self._set_running(False, 0)

    def _set_running(self, running: bool, total: int):
        self.direct.set_running(running)
        self.status_panel.set_running(running)
        if running:
            if total > 0:
                self.status_panel.set_progress(0, total, f"진행 중 (0/{total}) — %p%")
            else:
                self.status_panel.set_progress_indeterminate("진행 중...")
        # 메뉴 비활성화는 생략 — 사용자가 다른 설정은 볼 수 있어야 함

    # ---------- 헬퍼 ----------
    def _open_in_explorer(self, path: Path):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # noqa: pragma: no cover
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}"')
        except Exception as ex:
            QMessageBox.warning(self, "열기 실패", f"폴더 열기 실패: {ex}")

    def closeEvent(self, e):
        self.logger.log("gui_action", {"action": "main_window_closed"})
        super().closeEvent(e)


# ============================================================
# 엔트리 포인트
# ============================================================
def install_excepthook(logger: DiagnosticLogger):
    def hook(exc_type, exc_value, exc_tb):
        try:
            logger.log_exception("uncaught", exc_value)
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = hook


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("tfsgui")

    win = MainWindow()
    install_excepthook(win.logger)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
