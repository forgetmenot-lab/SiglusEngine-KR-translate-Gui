# -*- coding: utf-8 -*-
"""
tfs_ui.py
=========
공통 위젯 + 직접 모드 UI.
위저드 모드는 Phase 2에서 추가.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Callable

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QFont, QTextCursor, QAction
)
from PySide6.QtWidgets import (
    QWidget, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout, QGridLayout,
    QLabel, QPlainTextEdit, QProgressBar, QCheckBox, QFrame, QFileDialog,
    QMessageBox, QGroupBox, QComboBox, QDialog, QDialogButtonBox,
    QTextBrowser, QTabWidget, QSizePolicy, QToolButton, QInputDialog,
    QRadioButton, QButtonGroup, QScrollArea
)

from tfs_options import (
    OPTIONS, OPTION_BY_FLAG, GROUP_LABEL, options_in_group,
    Group, ToolOption, ArgKind, ArgSpec
)
from tfs_core import (
    GenericRunner, KeyManager, RecentPaths, AutoBackup, DiagnosticLogger,
    validate_tool_exe, count_files,
    TARGET_TEXT_EXT, TARGET_IMG_EXT, TARGET_VID_EXT,
)


# ============================================================
# 1. 드래그앤드롭 LineEdit
# ============================================================
class DropFolderEdit(QLineEdit):
    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e: QDragEnterEvent):
        urls = e.mimeData().urls() if e.mimeData().hasUrls() else []
        if len(urls) == 1 and urls[0].isLocalFile() and Path(urls[0].toLocalFile()).is_dir():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e: QDropEvent):
        self.setText(e.mimeData().urls()[0].toLocalFile())


class DropFileEdit(QLineEdit):
    def __init__(self, ext_filter, placeholder="", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setAcceptDrops(True)
        self.ext_filter = tuple(e.lower() for e in (
            ext_filter if isinstance(ext_filter, (list, tuple)) else [ext_filter]
        ))

    def dragEnterEvent(self, e: QDragEnterEvent):
        urls = e.mimeData().urls() if e.mimeData().hasUrls() else []
        if len(urls) == 1 and urls[0].isLocalFile():
            p = Path(urls[0].toLocalFile())
            if p.is_file() and p.suffix.lower() in self.ext_filter:
                e.acceptProposedAction()
                return
        e.ignore()

    def dropEvent(self, e: QDropEvent):
        self.setText(e.mimeData().urls()[0].toLocalFile())


# ============================================================
# 2. 옵션별 도움말 다이얼로그
# ============================================================
class OptionHelpDialog(QDialog):
    def __init__(self, option: ToolOption, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{option.flag} — {option.label}")
        self.resize(560, 480)
        v = QVBoxLayout(self)

        browser = QTextBrowser()
        html = f"""
        <h3>{option.flag} &nbsp; {option.label}</h3>
        <p><b>요약</b>: {option.summary}</p>
        <hr>
        <p><b>상세 설명</b></p>
        <p>{option.detailed_help.replace(chr(10), '<br>')}</p>
        """
        if option.warnings:
            html += "<hr><p><b>주의 사항</b></p><ul>"
            for w in option.warnings:
                html += f"<li>{w}</li>"
            html += "</ul>"
        if option.related_flags:
            html += "<hr><p><b>관련 옵션</b>: "
            html += ", ".join(f"<code>{f}</code>" for f in option.related_flags)
            html += "</p>"
        if option.requires_key:
            html += '<hr><p>🔑 <b>이 옵션은 __key.bin 파일이 필요합니다.</b></p>'
        if option.has_stdin_prompt:
            html += '<p>💬 <b>실행 중 언어 선택 프롬프트가 발생할 수 있습니다.</b></p>'
        if option.overwrites_input:
            html += '<p>⚠ <b>입력 파일이 직접 수정됩니다. 자동 백업이 권장됩니다.</b></p>'

        browser.setHtml(html)
        v.addWidget(browser)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        v.addWidget(btns)


# ============================================================
# 3. 인자 입력 위젯 (옵션 동적 생성)
# ============================================================
class ArgInputRow(QWidget):
    """ArgSpec 1개에 해당하는 행: [라벨] [입력] [찾아보기]"""

    EXT_BY_KIND = {
        ArgKind.FILE_EXE: (".exe",),
        ArgKind.FILE_PCK: (".pck",),
        ArgKind.FILE_SCN: (".scn",),
        ArgKind.FILE_DAT: (".scn", ".dbs", ".dat"),
        ArgKind.FILE_G00: (".g00",),
        ArgKind.FILE_OMV: (".omv",),
    }

    FILTER_BY_KIND = {
        ArgKind.FILE_EXE: "실행 파일 (*.exe)",
        ArgKind.FILE_PCK: "Scene 패키지 (*.pck)",
        ArgKind.FILE_SCN: "Scene 파일 (*.scn)",
        ArgKind.FILE_DAT: "Scene/DB/DAT 파일 (*.scn *.dbs *.dat)",
        ArgKind.FILE_G00: "이미지 파일 (*.g00)",
        ArgKind.FILE_OMV: "영상 파일 (*.omv)",
    }

    def __init__(self, spec: ArgSpec, recent: RecentPaths, recent_key: str, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.recent = recent
        self.recent_key = recent_key
        # I4: 행 자체가 가로로 늘어날 수 있도록
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(f"{spec.label} :")
        lbl.setMinimumWidth(110)
        lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        h.addWidget(lbl)

        if spec.kind in (ArgKind.FOLDER_IN, ArgKind.FOLDER_OUT):
            self.edit = DropFolderEdit(spec.placeholder)
        else:
            exts = self.EXT_BY_KIND.get(spec.kind, ())
            self.edit = DropFileEdit(list(exts), spec.placeholder)
        self.edit.setText(recent.get(recent_key, ""))
        # I4: LineEdit이 충분한 최소 너비를 가지고 가로로 늘어나도록
        self.edit.setMinimumWidth(280)
        self.edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        h.addWidget(self.edit, 1)

        b = QPushButton("찾아보기")
        b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        b.clicked.connect(self._browse)
        h.addWidget(b)

    def _browse(self):
        if self.spec.kind == ArgKind.FOLDER_IN:
            path = QFileDialog.getExistingDirectory(self, f"{self.spec.label} 선택")
        elif self.spec.kind == ArgKind.FOLDER_OUT:
            path = QFileDialog.getExistingDirectory(self, f"{self.spec.label} 선택")
        else:
            filt = self.FILTER_BY_KIND.get(self.spec.kind, "모든 파일 (*.*)")
            path, _ = QFileDialog.getOpenFileName(self, f"{self.spec.label} 선택", "", filt)
        if path:
            self.edit.setText(path)

    def value(self) -> str:
        return self.edit.text().strip()

    def commit_recent(self):
        v = self.value()
        if v:
            self.recent.set(self.recent_key, v)


# ============================================================
# 4. 키 관리 위젯 (라이브러리 모드)
# ============================================================
class KeyManagerWidget(QWidget):
    """직접 모드 화면 상단에 표시되는 키 관리 영역."""
    key_activated = Signal(str)  # key_id

    def __init__(self, key_mgr: KeyManager, parent=None):
        super().__init__(parent)
        self.key_mgr = key_mgr

        self.box = QGroupBox("키 관리")
        self.box.setStyleSheet("QGroupBox { font-weight: bold; }")
        v = QVBoxLayout(self.box)

        # 모드 전환
        h_mode = QHBoxLayout()
        h_mode.addWidget(QLabel("정책:"))
        self.rb_lib    = QRadioButton("라이브러리 (게임별 키 보관)")
        self.rb_simple = QRadioButton("단순 (매번 추출)")
        self.mode_grp  = QButtonGroup(self)
        self.mode_grp.addButton(self.rb_lib, 0)
        self.mode_grp.addButton(self.rb_simple, 1)
        if key_mgr.mode == KeyManager.MODE_LIBRARY:
            self.rb_lib.setChecked(True)
        else:
            self.rb_simple.setChecked(True)
        self.rb_lib.toggled.connect(self._on_mode_changed)
        h_mode.addWidget(self.rb_lib)
        h_mode.addWidget(self.rb_simple)
        h_mode.addStretch()
        v.addLayout(h_mode)

        # 라이브러리 키 콤보박스 행
        self.lib_row = QWidget()
        h_lib = QHBoxLayout(self.lib_row)
        h_lib.setContentsMargins(0, 0, 0, 0)
        h_lib.addWidget(QLabel("키 이름:"))
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setMinimumWidth(220)
        self._refresh_combo()
        h_lib.addWidget(self.combo)
        b_load = QPushButton("불러오기")
        b_load.clicked.connect(self._activate)
        h_lib.addWidget(b_load)
        b_save = QPushButton("현재 키 저장")
        b_save.clicked.connect(self._save_current)
        h_lib.addWidget(b_save)
        b_del = QPushButton("삭제")
        b_del.clicked.connect(self._delete)
        h_lib.addWidget(b_del)
        h_lib.addStretch()
        v.addWidget(self.lib_row)

        # 상태 표시
        self.status = QLabel()
        self._refresh_status()
        v.addWidget(self.status)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.box)
        self._update_visibility()

    def _refresh_combo(self):
        cur = self.combo.currentText()
        self.combo.clear()
        self.combo.addItems(self.key_mgr.list_library_keys())
        if cur:
            self.combo.setCurrentText(cur)

    def _refresh_status(self):
        if not self.key_mgr.has_active_key():
            self.status.setText("⚠ __key.bin 없음 — 키 추출이 필요합니다.")
            self.status.setStyleSheet("color: #b54708; font-weight: bold;")
            return

        active_id = self.key_mgr.active_key_id
        if active_id == "(직접 추출)":
            self.status.setText(
                "✅ 활성 키: (직접 추출 — 라이브러리 미연결)\n"
                "   원하면 '현재 키 저장'으로 라이브러리에 보관할 수 있습니다."
            )
            self.status.setStyleSheet("color: #1a7f37;")
        elif active_id == "(외부)":
            self.status.setText(
                "⚠ 활성 키: (식별자 불명) — 어느 게임 키인지 알 수 없습니다.\n"
                "   라이브러리에서 키를 다시 활성화하거나, 새로 추출하세요."
            )
            self.status.setStyleSheet("color: #b54708; font-weight: bold;")
        elif active_id:
            self.status.setText(f"✅ 활성 키: {active_id}")
            self.status.setStyleSheet("color: #1a7f37; font-weight: bold;")
        else:
            self.status.setText("✅ 활성 키: __key.bin (식별자 미설정)")
            self.status.setStyleSheet("color: #1a7f37;")

    def _on_mode_changed(self):
        new_mode = (KeyManager.MODE_LIBRARY if self.rb_lib.isChecked()
                    else KeyManager.MODE_SIMPLE)
        self.key_mgr.set_mode(new_mode)
        self._update_visibility()

    def _update_visibility(self):
        self.lib_row.setVisible(self.key_mgr.mode == KeyManager.MODE_LIBRARY)

    def _activate(self):
        key_id = self.combo.currentText().strip()
        if not key_id:
            QMessageBox.warning(self, "확인", "키 이름을 선택하거나 입력해주세요.")
            return
        if not self.key_mgr.has_library_key(key_id):
            QMessageBox.warning(self, "확인", f"'{key_id}' 키가 라이브러리에 없습니다.")
            return
        if self.key_mgr.activate_library_key(key_id):
            QMessageBox.information(self, "완료", f"'{key_id}' 키가 활성화되었습니다.")
            self._refresh_status()
            self.key_activated.emit(key_id)

    def _save_current(self):
        if not self.key_mgr.has_active_key():
            QMessageBox.warning(self, "확인",
                "__key.bin이 없습니다.\n먼저 -xkey 또는 -xmkey로 키를 추출해주세요.")
            return
        key_id, ok = QInputDialog.getText(self, "키 이름", "라이브러리에 저장할 키 이름:")
        if not ok or not key_id.strip():
            return
        key_id = key_id.strip()
        if self.key_mgr.has_library_key(key_id):
            r = QMessageBox.question(self, "확인",
                f"'{key_id}'가 이미 존재합니다. 덮어쓰시겠습니까?")
            if r != QMessageBox.Yes:
                return
        if self.key_mgr.store_to_library(key_id):
            QMessageBox.information(self, "완료", f"'{key_id}'로 저장되었습니다.")
            self._refresh_combo()

    def _delete(self):
        key_id = self.combo.currentText().strip()
        if not key_id or not self.key_mgr.has_library_key(key_id):
            return
        r = QMessageBox.question(self, "확인", f"'{key_id}' 키를 삭제하시겠습니까?")
        if r == QMessageBox.Yes:
            self.key_mgr.delete_library_key(key_id)
            # H1: 콤보박스뿐 아니라 활성 키 라벨도 함께 갱신
            #     (삭제된 키가 활성 키였다면 라벨이 옛 식별자를 그대로 표시하던 버그)
            self._refresh_combo()
            self._refresh_status()

    def refresh(self):
        self._refresh_combo()
        self._refresh_status()


# ============================================================
# 5. 단일 옵션 패널 (인자 + 실행 버튼 + 도움말)
# ============================================================
class OptionPanel(QWidget):
    """그룹 탭 내부에 표시되는 개별 옵션 카드."""

    request_run = Signal(object, list)  # ToolOption, args[]

    def __init__(self, option: ToolOption, recent: RecentPaths, parent=None):
        super().__init__(parent)
        self.option = option
        self.recent = recent
        # I4: 옵션 패널은 가로로 확장, 세로는 컨텐츠에 맞춤
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)

        # 헤더
        h_head = QHBoxLayout()
        ttl = QLabel(f"<b>{option.flag}</b> &nbsp; {option.label}")
        ttl.setTextFormat(Qt.RichText)
        h_head.addWidget(ttl)

        b_help = QToolButton()
        b_help.setText("ⓘ")
        b_help.setToolTip("이 옵션의 상세 설명 보기")
        b_help.clicked.connect(self._show_help)
        h_head.addWidget(b_help)
        h_head.addStretch()
        v.addLayout(h_head)

        # 요약
        sub = QLabel(option.summary)
        sub.setStyleSheet("color: #666; font-size: 9pt;")
        sub.setWordWrap(True)
        v.addWidget(sub)

        # H3+H4: 인라인 안내문 (옵션이 inline_help를 가진 경우만)
        if option.inline_help:
            help_box = QLabel(option.inline_help)
            help_box.setStyleSheet(
                "background-color: #f0f6ff; "
                "border: 1px solid #c8d8ec; "
                "border-radius: 4px; "
                "padding: 6px 8px; "
                "color: #234; "
                "font-size: 9pt;"
            )
            help_box.setWordWrap(True)
            v.addWidget(help_box)

        # 인자 입력 행들
        self.arg_rows: list[ArgInputRow] = []
        for i, spec in enumerate(option.args):
            recent_key = f"{option.flag}/arg{i}"
            row = ArgInputRow(spec, recent, recent_key)
            self.arg_rows.append(row)
            v.addWidget(row)

        # 실행 버튼
        h_act = QHBoxLayout()
        h_act.addStretch()
        self.btn_run = QPushButton(f"실행  ({option.flag})")
        self.btn_run.setMinimumWidth(160)
        self.btn_run.clicked.connect(self._on_run_clicked)
        h_act.addWidget(self.btn_run)
        v.addLayout(h_act)

        # 경고 표시
        if option.warnings:
            warn = QLabel("⚠ " + "  ".join(option.warnings))
            warn.setStyleSheet("color: #b54708; font-size: 9pt;")
            warn.setWordWrap(True)
            v.addWidget(warn)

    def _show_help(self):
        OptionHelpDialog(self.option, self).exec()

    def _on_run_clicked(self):
        args = []
        for row in self.arg_rows:
            v = row.value()
            if not v:
                QMessageBox.warning(self, "확인",
                    f"'{row.spec.label}' 항목을 입력해주세요.")
                return
            args.append(v)
            row.commit_recent()
        self.request_run.emit(self.option, args)

    def set_running(self, running: bool):
        self.btn_run.setEnabled(not running)
        for row in self.arg_rows:
            row.setEnabled(not running)


# ============================================================
# 6. 직접 모드 위젯 (그룹별 탭)
# ============================================================
class DirectModeWidget(QWidget):
    """탭 = 그룹, 탭 내부 = 옵션 패널 다수."""

    request_run = Signal(object, list)  # 위로 전달

    def __init__(self, key_mgr: KeyManager, recent: RecentPaths, parent=None):
        super().__init__(parent)
        self.key_mgr = key_mgr
        self.recent = recent

        v = QVBoxLayout(self)

        # 키 관리 위젯
        self.key_widget = KeyManagerWidget(key_mgr)
        v.addWidget(self.key_widget)

        # 그룹 탭
        self.tabs = QTabWidget()
        self.panels: list[OptionPanel] = []
        for grp in (Group.KEY, Group.PACKAGE, Group.TEXT,
                    Group.IMAGE, Group.VIDEO, Group.EXE):
            # I4: 각 탭 페이지를 QScrollArea로 감싸서 작은 창에서도 스크롤 가능
            page_inner = QWidget()
            pv = QVBoxLayout(page_inner)
            pv.setSpacing(12)
            for opt in options_in_group(grp):
                panel = OptionPanel(opt, recent)
                panel.request_run.connect(self.request_run.emit)
                self.panels.append(panel)

                frame = QFrame()
                frame.setFrameShape(QFrame.StyledPanel)
                # I4: 패널이 가로로 늘어나되, 세로는 컨텐츠에 맞도록
                frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
                fl = QVBoxLayout(frame)
                fl.setContentsMargins(0, 0, 0, 0)
                fl.addWidget(panel)
                pv.addWidget(frame)
            pv.addStretch()  # 빈 공간을 마지막에 흡수 → 위젯들이 위에 쌓임

            scroll = QScrollArea()
            scroll.setWidget(page_inner)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.tabs.addTab(scroll, GROUP_LABEL[grp])
        v.addWidget(self.tabs, 1)

    def set_running(self, running: bool):
        for p in self.panels:
            p.set_running(running)

    def refresh_keys(self):
        self.key_widget.refresh()


# ============================================================
# 7. 공통 로그뷰 + 진행률 + 프롬프트 바
# ============================================================
class StatusPanel(QWidget):
    """창 하단 공통 영역 — 진행률 / 프롬프트 / 로그뷰 / 취소 버튼."""

    cancel_requested = Signal()
    prompt_response  = Signal(str, bool)  # choice, remember

    def __init__(self, parent=None):
        super().__init__(parent)

        v = QVBoxLayout(self)

        # 진행률 + 취소
        h_prog = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("대기 중")
        h_prog.addWidget(self.progress, 1)
        self.btn_cancel = QPushButton("취소")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_requested.emit)
        h_prog.addWidget(self.btn_cancel)
        v.addLayout(h_prog)

        # 프롬프트 바 (숨김)
        self.prompt_frame = QFrame()
        self.prompt_frame.setFrameShape(QFrame.StyledPanel)
        self.prompt_frame.setStyleSheet("background-color: #fff8dc; padding: 6px;")
        ph = QHBoxLayout(self.prompt_frame)
        ph.addWidget(QLabel("⚠ 비-UTF16 .dbs 발견. 원본 언어를 선택:"))
        self.btn_jap = QPushButton("일본어 (j)")
        self.btn_kor = QPushButton("한국어 (k)")
        self.chk_remember = QCheckBox("이후 동일 응답 자동 적용")
        self.btn_jap.clicked.connect(lambda: self._respond("j"))
        self.btn_kor.clicked.connect(lambda: self._respond("k"))
        ph.addStretch()
        ph.addWidget(self.btn_jap)
        ph.addWidget(self.btn_kor)
        ph.addWidget(self.chk_remember)
        self.prompt_frame.hide()
        v.addWidget(self.prompt_frame)

        # 로그뷰
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        f = QFont("Consolas")
        if not f.exactMatch():
            f = QFont("Courier New")
        f.setPointSize(9)
        self.log_view.setFont(f)
        self.log_view.setMinimumHeight(220)
        v.addWidget(self.log_view, 1)

    def _respond(self, choice: str):
        self.prompt_response.emit(choice, self.chk_remember.isChecked())
        self.prompt_frame.hide()

    def append_log(self, line: str):
        self.log_view.appendPlainText(line)
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_view.setTextCursor(cursor)

    def clear_log(self):
        self.log_view.clear()

    def set_progress(self, current: int, total: int, status_text: str = ""):
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(current)
        if status_text:
            self.progress.setFormat(status_text)

    def set_progress_indeterminate(self, status_text: str = ""):
        # H8: 펄싱 모드 진입 전 값 명시 리셋. 이전 옵션의 카운트가
        # 잔존하지 않도록 (예: -xat 1402/1404 끝낸 후 -rt 시작 시).
        self.progress.setValue(0)
        self.progress.setRange(0, 0)
        if status_text:
            self.progress.setFormat(status_text)

    def show_prompt(self):
        self.prompt_frame.show()

    def hide_prompt(self):
        self.prompt_frame.hide()

    def set_running(self, running: bool):
        self.btn_cancel.setEnabled(running)
        if not running:
            self.hide_prompt()
