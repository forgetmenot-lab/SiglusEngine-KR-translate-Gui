# -*- coding: utf-8 -*-
"""
tfs_options.py
==============
ToolForSiglus의 17개 CLI 옵션을 메타데이터로 정의.
GUI는 이 데이터를 기반으로 위저드/직접 모드 UI를 자동 생성.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ArgKind(Enum):
    NONE        = "none"          # 인자 없음 (-xmkey)
    FILE_EXE    = "file_exe"      # .exe 파일
    FILE_PCK    = "file_pck"      # .pck 파일
    FILE_SCN    = "file_scn"      # .scn 파일 (단일)
    FILE_DAT    = "file_dat"      # .dat 파일 (Gameexe.dat)
    FILE_G00    = "file_g00"      # .g00 파일 (단일)
    FILE_OMV    = "file_omv"      # .omv 파일 (단일)
    FOLDER_IN   = "folder_in"     # 입력 폴더
    FOLDER_OUT  = "folder_out"    # 출력 폴더 또는 .scn 폴더 등


class Group(Enum):
    KEY      = "key"        # 키 관리
    PACKAGE  = "package"    # Scene.pck 언팩/리팩
    TEXT     = "text"       # 텍스트 추출/교체
    IMAGE    = "image"      # g00 이미지
    VIDEO    = "video"      # omv 영상
    EXE      = "exe"        # 실행파일 패치


@dataclass(frozen=True)
class ArgSpec:
    kind:        ArgKind
    label:       str          # UI 라벨 (예: "입력 폴더")
    placeholder: str = ""      # placeholder 힌트


@dataclass(frozen=True)
class ToolOption:
    flag:              str
    group:             Group
    label:             str           # 짧은 표시명 (예: "텍스트 일괄 추출")
    args:              tuple         # (ArgSpec, ...)
    requires_key:      bool          # __key.bin 필요 여부
    has_stdin_prompt:  bool          # [j/k] 발생 가능 여부
    estimated_speed:   str           # "fast" / "medium" / "slow"
    overwrites_input:  bool          # 입력 파일을 덮어쓰는가 (백업 필요)
    summary:           str           # 1줄 (툴팁용)
    detailed_help:     str           # 다단락 (ⓘ 모달용)
    warnings:          tuple = ()
    related_flags:     tuple = ()    # 짝 옵션 (-xat ↔ -rat)
    output_pattern:    str = ""      # 결과 탐색용 (예: "{out}/*.ext.txt")
    # H3+H4: 패널 안에 항상 표시되는 짧은 안내문 (ⓘ 모달과 별개).
    # 사용자가 ⓘ를 안 열어도 핵심 동작 규칙이 한눈에 보이도록.
    # 빈 문자열이면 표시 안 함.
    inline_help:       str = ""


# ============================================================
# 17개 옵션 정의
# ============================================================

OPTIONS = (

    # ========== KEY ==========
    ToolOption(
        flag="-xkey",
        group=Group.KEY,
        label="실행파일에서 키 추출",
        args=(ArgSpec(ArgKind.FILE_EXE, "SiglusEngine.exe", "게임의 SiglusEngine.exe"),),
        requires_key=False,
        has_stdin_prompt=False,
        estimated_speed="fast",
        overwrites_input=False,
        summary="게임 실행파일에서 암호화 키를 추출하여 __key.bin 생성",
        detailed_help=(
            "게임의 SiglusEngine.exe 파일에서 직접 키 데이터를 읽어 "
            "도구 폴더에 __key.bin으로 저장합니다.\n\n"
            "이 키는 Scene.pck 언팩, .scn 텍스트 추출 등 "
            "거의 모든 후속 작업에 필수적입니다.\n\n"
            "주의: 알파롬(AlphaROM) 등 프로텍터가 적용된 실행파일에서는 "
            "이 옵션이 실패할 수 있습니다. 그 경우 -xmkey 옵션을 사용하세요."
        ),
        warnings=("프로텍터가 걸린 실행파일에서는 동작하지 않습니다.",),
        related_flags=("-xmkey", "-wkey"),
        output_pattern="__key.bin",
    ),

    ToolOption(
        flag="-xmkey",
        group=Group.KEY,
        label="실행 중 프로세스에서 키 추출",
        args=(),
        requires_key=False,
        has_stdin_prompt=False,
        estimated_speed="medium",
        overwrites_input=False,
        summary="현재 실행 중인 SiglusEngine 프로세스에서 키를 추출",
        detailed_help=(
            "이름에 'SiglusEngine'이 포함된 실행 중 프로세스의 메모리에서 "
            "키 데이터를 추출합니다.\n\n"
            "사용 시점: 알파롬 등의 프로텍터로 인해 -xkey가 실패할 때.\n\n"
            "절차:\n"
            "1. 이 옵션 실행 → 도구가 대기 모드 진입\n"
            "2. AlphaROMdiE 등으로 게임 강제 실행\n"
            "3. 도구가 자동으로 키를 추출하고 __key.bin 생성\n\n"
            "주의: 프로세스 메모리 접근이 필요하므로 관리자 권한이 요구될 수 있습니다."
        ),
        warnings=(
            "관리자 권한이 필요할 수 있습니다.",
            "게임을 별도로 실행해야 합니다.",
        ),
        related_flags=("-xkey", "-wkey"),
        output_pattern="__key.bin",
    ),

    ToolOption(
        flag="-wkey",
        group=Group.KEY,
        label="키 데이터 이식",
        args=(ArgSpec(ArgKind.FILE_EXE, "이식 대상 .exe", "보통 SiglusEngine_pure.exe"),),
        requires_key=True,
        has_stdin_prompt=False,
        estimated_speed="fast",
        overwrites_input=False,
        summary="__key.bin의 키를 다른 실행파일에 이식",
        detailed_help=(
            "현재 도구 폴더의 __key.bin 데이터를 지정한 .exe에 이식하여 "
            "_key_modified.exe 파일을 생성합니다.\n\n"
            "주된 용도:\n"
            "프로텍터가 걸린 원본 SiglusEngine.exe 대신 "
            "동봉된 SiglusEngine_pure.exe(순정 버전)에 키를 이식하면, "
            "프로텍터 없이 게임을 실행할 수 있고 -j2k 옵션도 적용 가능합니다."
        ),
        warnings=("__key.bin 파일이 사전에 준비되어 있어야 합니다.",),
        related_flags=("-xmkey", "-j2k"),
        output_pattern="*_key_modified.exe",
    ),

    # ========== PACKAGE ==========
    ToolOption(
        flag="-u",
        group=Group.PACKAGE,
        label="Scene.pck 언팩",
        args=(ArgSpec(ArgKind.FILE_PCK, "Scene.pck"),),
        requires_key=True,
        has_stdin_prompt=False,
        estimated_speed="medium",
        overwrites_input=False,
        summary="Scene.pck를 풀어 .scn 파일 다수가 든 폴더로 변환",
        detailed_help=(
            "Scene.pck 파일을 언팩하여 같은 이름의 폴더(Scene/)에 "
            ".scn 파일들로 분해합니다.\n\n"
            "이후 -xat 옵션으로 .scn 파일들에서 텍스트를 추출할 수 있습니다.\n\n"
            "키(__key.bin)가 필요합니다."
        ),
        related_flags=("-p", "-xat"),
        output_pattern="<pck파일명>/",
    ),

    ToolOption(
        flag="-p",
        group=Group.PACKAGE,
        label="Scene 폴더 리팩",
        args=(ArgSpec(ArgKind.FOLDER_IN, "Scene 폴더", ".scn 파일들이 있는 폴더"),),
        requires_key=True,
        has_stdin_prompt=False,
        estimated_speed="medium",
        overwrites_input=False,
        summary=".scn 파일들을 모아 _new.pck 패키지 생성",
        detailed_help=(
            ".scn 파일이 들어있는 폴더를 다시 .pck 형태로 패키징합니다.\n\n"
            "결과 파일명은 <폴더명>_new.pck 입니다.\n\n"
            "이 파일을 게임 폴더에 Scene.pck로 이름을 바꿔 넣으면 "
            "번역된 텍스트가 적용됩니다."
        ),
        warnings=(
            "원본 Scene.pck를 자동으로 백업해두는 것을 권장합니다.",
        ),
        related_flags=("-u",),
        output_pattern="*_new.pck",
    ),

    # ========== TEXT ==========
    ToolOption(
        flag="-xat",
        group=Group.TEXT,
        label="폴더 일괄 텍스트 추출",
        args=(
            ArgSpec(ArgKind.FOLDER_IN,  "입력 폴더",  "Scene 또는 dat 폴더"),
            ArgSpec(ArgKind.FOLDER_OUT, "출력 폴더",  "추출된 .ext.txt 저장 위치"),
        ),
        requires_key=True,
        has_stdin_prompt=True,
        estimated_speed="fast",
        overwrites_input=False,
        summary="폴더 내 모든 .scn/.dbs/.dat에서 텍스트 추출",
        detailed_help=(
            "입력 폴더(서브폴더 포함)의 모든 .scn/.dbs/.dat 파일에서 "
            "번역 가능한 텍스트를 추출하여 출력 폴더에 .ext.txt 형식으로 저장합니다.\n\n"
            "출력 형식: UTF-16 LE, 각 텍스트 블록은 [◆]본문[◆]로 감싸짐.\n\n"
            "비-UTF16 .dbs 파일이 발견되면 GUI가 언어 선택 프롬프트를 표시합니다 "
            "(원본이 일본어면 'j', 한국어면 'k')."
        ),
        warnings=("__key.bin이 필요합니다.",),
        related_flags=("-rat", "-xt"),
        output_pattern="{out}/*.ext.txt",
        inline_help=(
            "📤 추출 흐름: 원본 폴더 → 출력 폴더로 .ext.txt 생성\n"
            "  • 출력 .ext.txt는 UTF-16 LE 인코딩, [◆]본문[◆] 형식\n"
            "  • 인코딩/줄바꿈 변경 금지 (메모장보다 Notepad++/VS Code 권장)\n"
            "  • 같은 게임의 키가 활성화돼 있어야 정상 추출됨"
        ),
    ),

    ToolOption(
        flag="-rat",
        group=Group.TEXT,
        label="폴더 일괄 텍스트 교체",
        args=(
            ArgSpec(ArgKind.FOLDER_IN,  "원본 폴더",  "원본 .scn/.dbs/.dat 폴더"),
            ArgSpec(ArgKind.FOLDER_OUT, "텍스트 폴더", "번역된 .ext.txt 폴더"),
        ),
        requires_key=True,
        has_stdin_prompt=False,
        estimated_speed="fast",
        overwrites_input=True,
        summary="번역된 텍스트로 .scn/.dbs/.dat 파일들 일괄 교체",
        detailed_help=(
            "출력 폴더에 보관된 번역 .ext.txt 파일들의 내용으로 "
            "원본 폴더 내 .scn/.dbs/.dat 파일들의 텍스트를 교체합니다.\n\n"
            "원본 파일이 직접 수정되므로, 작업 전 자동 백업이 권장됩니다."
        ),
        warnings=("원본 파일이 수정됩니다. 백업 권장.",),
        related_flags=("-xat", "-rt"),
        output_pattern="(원본 파일 수정됨)",
        inline_help=(
            "📥 재삽입 흐름: 텍스트 폴더의 .ext.txt 내용으로 원본 .scn 갱신\n"
            "  • 원본 폴더의 .scn 파일이 직접 수정됨 (자동 백업 권장)\n"
            "  • 두 폴더의 파일명이 정확히 매칭되어야 함\n"
            "  • -rat 실행 후 게임에 적용하려면 -p로 다시 패키징 필요"
        ),
    ),

    ToolOption(
        flag="-xt",
        group=Group.TEXT,
        label="단일 파일 텍스트 추출",
        args=(ArgSpec(ArgKind.FILE_DAT, ".scn/.dbs/.dat 파일"),),
        requires_key=True,
        has_stdin_prompt=True,
        estimated_speed="fast",
        overwrites_input=False,
        summary="단일 .scn/.dbs/.dat에서 텍스트 추출 (Gameexe.dat 등)",
        detailed_help=(
            "단일 파일에서 텍스트를 추출하여 같은 위치에 .ext.ini 또는 .ext.txt로 저장합니다.\n\n"
            "주된 용도: Gameexe.dat (게임 타이틀, 시스템 메시지 등) 같은 "
            "독립 파일을 처리할 때.\n\n"
            "Scene 폴더 안의 다수 파일은 -xat을 사용하세요."
        ),
        related_flags=("-rt", "-xat"),
        output_pattern="*.ext.ini 또는 *.ext.txt",
        inline_help=(
            "📤 단일 파일 추출 흐름: .scn/.dat 옆에 .ext.txt(.ext.ini) 생성\n"
            "  • 출력 위치는 입력 파일과 동일 폴더 (사용자가 지정 불가)\n"
            "  • .scn → .ext.txt / .dat → .ext.ini 자동 결정\n"
            "  • 폴더 일괄은 -xat (출력 폴더 별도 지정 가능)"
        ),
    ),

    ToolOption(
        flag="-rt",
        group=Group.TEXT,
        label="단일 파일 텍스트 교체",
        args=(ArgSpec(ArgKind.FILE_DAT, ".scn/.dbs/.dat 파일"),),
        requires_key=True,
        has_stdin_prompt=False,
        estimated_speed="fast",
        overwrites_input=True,
        summary="단일 파일의 텍스트를 .ext.* 파일로 교체",
        detailed_help=(
            "단일 파일에 대해 -rat과 동일한 동작을 수행합니다.\n\n"
            "원본 파일과 같은 위치에 동명의 .ext.ini 또는 .ext.txt가 있어야 하며, "
            "그 내용으로 원본 텍스트를 교체합니다."
        ),
        warnings=("원본 파일이 수정됩니다. 백업 권장.",),
        related_flags=("-xt",),
        output_pattern="(원본 파일 수정됨)",
        inline_help=(
            "📥 단일 파일 재삽입 흐름: 입력 .scn/.dat을 갱신\n"
            "  • 입력은 .scn/.dbs/.dat (텍스트 파일이 아님!)\n"
            "  • 도구가 같은 폴더의 동명 .ext.txt(.ext.ini)를 자동으로 찾음\n"
            "  ★ 입력 파일과 같은 폴더에 동명의 .ext.txt가 미리 있어야 합니다\n"
            "    (없으면 먼저 -xt로 추출하거나 .ext.txt를 같은 위치에 복사)\n"
            "  • 폴더 일괄 + 다른 폴더의 .ext.txt를 쓰려면 -rat 사용"
        ),
    ),

    # ========== IMAGE ==========
    ToolOption(
        flag="-xaimg",
        group=Group.IMAGE,
        label="폴더 일괄 이미지 추출",
        args=(
            ArgSpec(ArgKind.FOLDER_IN,  "입력 폴더",  "g00 파일들이 있는 폴더"),
            ArgSpec(ArgKind.FOLDER_OUT, "출력 폴더",  "추출된 .png/.dir 저장 위치"),
        ),
        requires_key=False,
        has_stdin_prompt=False,
        estimated_speed="slow",
        overwrites_input=False,
        summary="폴더 내 모든 .g00 파일에서 이미지 추출",
        detailed_help=(
            "폴더 내 모든 .g00 파일에서 이미지를 추출합니다.\n\n"
            "단일 이미지: <이름>.ext.png\n"
            "다중 레이어:  <이름>.ext.dir/0.png, 1.png, ...\n\n"
            "주의: g00 파일이 많으면 시간이 오래 걸립니다. "
            "필요한 파일만 별도 폴더로 복사한 후 처리하는 것을 권장합니다."
        ),
        warnings=("처리 시간이 길 수 있습니다.",),
        related_flags=("-raimg", "-ximg"),
        output_pattern="{out}/*.ext.png 또는 {out}/*.ext.dir/",
    ),

    ToolOption(
        flag="-raimg",
        group=Group.IMAGE,
        label="폴더 일괄 이미지 교체",
        args=(
            ArgSpec(ArgKind.FOLDER_IN,  "원본 g00 폴더"),
            ArgSpec(ArgKind.FOLDER_OUT, "이미지 폴더", "번역된 .png/.dir 폴더"),
        ),
        requires_key=False,
        has_stdin_prompt=False,
        estimated_speed="slow",
        overwrites_input=True,
        summary="번역된 이미지로 .g00 파일들 일괄 교체",
        detailed_help=(
            "출력 폴더의 .ext.png/.ext.dir 파일들로 원본 .g00 파일들의 "
            "이미지 데이터를 교체합니다."
        ),
        warnings=("원본 .g00 파일이 수정됩니다. 백업 권장.",),
        related_flags=("-xaimg",),
        output_pattern="(원본 g00 파일 수정됨)",
    ),

    ToolOption(
        flag="-ximg",
        group=Group.IMAGE,
        label="단일 이미지 추출",
        args=(ArgSpec(ArgKind.FILE_G00, ".g00 파일"),),
        requires_key=False,
        has_stdin_prompt=False,
        estimated_speed="fast",
        overwrites_input=False,
        summary="단일 .g00 파일에서 이미지 추출",
        detailed_help=(
            "단일 .g00 파일에서 이미지를 추출하여 동일 폴더에 "
            ".ext.png 또는 .ext.dir/로 저장합니다."
        ),
        related_flags=("-rimg", "-xaimg"),
        output_pattern="*.ext.png 또는 *.ext.dir/",
    ),

    ToolOption(
        flag="-rimg",
        group=Group.IMAGE,
        label="단일 이미지 교체",
        args=(ArgSpec(ArgKind.FILE_G00, ".g00 파일"),),
        requires_key=False,
        has_stdin_prompt=False,
        estimated_speed="fast",
        overwrites_input=True,
        summary="단일 .g00의 이미지를 .ext.png/.ext.dir로 교체",
        detailed_help=(
            "원본 .g00 파일과 같은 위치에 동명의 .ext.png 또는 .ext.dir/가 있어야 하며, "
            "그 내용으로 원본 이미지를 교체합니다."
        ),
        warnings=("원본 .g00 파일이 수정됩니다. 백업 권장.",),
        related_flags=("-ximg",),
        output_pattern="(원본 g00 파일 수정됨)",
    ),

    # ========== VIDEO ==========
    ToolOption(
        flag="-xv",
        group=Group.VIDEO,
        label="단일 영상 추출",
        args=(ArgSpec(ArgKind.FILE_OMV, ".omv 파일"),),
        requires_key=False,
        has_stdin_prompt=False,
        estimated_speed="slow",
        overwrites_input=False,
        summary="단일 .omv 영상을 .mp4로 추출",
        detailed_help=(
            ".omv 파일에서 영상 데이터를 추출하여 .ext.mp4로 저장합니다.\n\n"
            "32비트 알파 채널 포함 영상의 경우 .ext.dir/ 폴더에 "
            "프레임별 이미지로 추출됩니다.\n\n"
            "주의: 추출 결과물의 용량은 원본 대비 매우 클 수 있습니다 "
            "(트랜스코딩 특성). 영상 편집 후 재교체 시에는 1.5~2배 수준으로 정상화됩니다."
        ),
        warnings=(
            "처리 시간이 매우 깁니다 (수십 분 단위).",
            "추출 결과물 용량이 원본 대비 큽니다.",
        ),
        related_flags=("-rv",),
        output_pattern="*.ext.mp4 또는 *.ext.dir/",
    ),

    ToolOption(
        flag="-rv",
        group=Group.VIDEO,
        label="단일 영상 교체",
        args=(ArgSpec(ArgKind.FILE_OMV, ".omv 파일"),),
        requires_key=False,
        has_stdin_prompt=False,
        estimated_speed="slow",
        overwrites_input=True,
        summary="번역/편집된 영상으로 .omv 교체",
        detailed_help=(
            "원본 .omv와 같은 위치의 .ext.mp4 또는 .ext.dir/ 내용으로 "
            "원본 영상을 교체합니다.\n\n"
            "이 작업은 17개 옵션 중 가장 시간이 많이 걸립니다."
        ),
        warnings=(
            "원본 .omv 파일이 수정됩니다. 백업 권장.",
            "처리 시간이 매우 깁니다 (omv 1개당 수십 분).",
        ),
        related_flags=("-xv",),
        output_pattern="(원본 omv 파일 수정됨)",
    ),

    ToolOption(
        flag="-xav",
        group=Group.VIDEO,
        label="폴더 일괄 영상 추출",
        args=(
            ArgSpec(ArgKind.FOLDER_IN,  "입력 폴더",  "omv 파일들이 있는 폴더"),
            ArgSpec(ArgKind.FOLDER_OUT, "출력 폴더",  "추출 영상 저장 위치"),
        ),
        requires_key=False,
        has_stdin_prompt=False,
        estimated_speed="slow",
        overwrites_input=False,
        summary="폴더 내 모든 .omv 영상을 일괄 추출",
        detailed_help=(
            "폴더 내 모든 .omv 파일에서 영상을 추출합니다.\n\n"
            "주의: omv 한 개당 수십 분이 걸리므로 다수 파일에는 매우 오랜 시간이 소요됩니다. "
            "원본 가이드에서는 단일 파일 처리(-xv)를 권장합니다."
        ),
        warnings=(
            "처리 시간이 매우 깁니다 (omv 1개당 수십 분).",
            "원본 가이드에서는 -xv 단일 처리를 권장합니다.",
        ),
        related_flags=("-xv", "-rav"),
        output_pattern="{out}/*.ext.mp4 또는 {out}/*.ext.dir/",
    ),

    ToolOption(
        flag="-rav",
        group=Group.VIDEO,
        label="폴더 일괄 영상 교체",
        args=(
            ArgSpec(ArgKind.FOLDER_IN,  "원본 omv 폴더"),
            ArgSpec(ArgKind.FOLDER_OUT, "영상 폴더", "번역된 .mp4/.dir 폴더"),
        ),
        requires_key=False,
        has_stdin_prompt=False,
        estimated_speed="slow",
        overwrites_input=True,
        summary="번역/편집된 영상으로 .omv 파일들 일괄 교체",
        detailed_help=(
            "출력 폴더의 .ext.mp4/.ext.dir 데이터로 원본 .omv 파일들의 영상을 교체합니다.\n\n"
            "주의: omv 한 개당 수십 분이 걸리므로 다수 파일에는 매우 오랜 시간이 소요됩니다."
        ),
        warnings=(
            "원본 .omv 파일이 수정됩니다. 백업 권장.",
            "처리 시간이 매우 깁니다.",
        ),
        related_flags=("-rv",),
        output_pattern="(원본 omv 파일 수정됨)",
    ),

    # ========== EXE ==========
    ToolOption(
        flag="-j2k",
        group=Group.EXE,
        label="한글 간격 패치",
        args=(ArgSpec(ArgKind.FILE_EXE, "SiglusEngine.exe"),),
        requires_key=False,
        has_stdin_prompt=False,
        estimated_speed="fast",
        overwrites_input=False,
        summary="실행파일에 한글 출력 간격 보정 패치 적용",
        detailed_help=(
            "원본 시글러스 게임은 한글 출력 시 글자 간격이 붙어 나오는 문제가 있습니다. "
            "이 옵션은 실행파일에 패치를 적용하여 한글 간격을 정상화합니다.\n\n"
            "결과 파일: <원본>_patched.exe\n\n"
            "주의: 알파롬 등 프로텍터가 걸린 실행파일에는 적용할 수 없습니다. "
            "그 경우 SiglusEngine_pure.exe에 -wkey로 키를 이식한 후 -j2k를 적용하세요."
        ),
        warnings=("프로텍터가 걸린 실행파일에는 적용 불가.",),
        related_flags=("-wkey",),
        output_pattern="*_patched.exe",
    ),

)


# ============================================================
# 조회 헬퍼
# ============================================================
OPTION_BY_FLAG = {opt.flag: opt for opt in OPTIONS}

GROUP_LABEL = {
    Group.KEY:     "키 관리",
    Group.PACKAGE: "Scene.pck 패키지",
    Group.TEXT:    "텍스트",
    Group.IMAGE:   "이미지 (g00)",
    Group.VIDEO:   "영상 (omv)",
    Group.EXE:     "실행파일 패치",
}

def options_in_group(group: Group):
    return tuple(o for o in OPTIONS if o.group == group)


# ============================================================
# 위저드 모드용 7단계 워크플로우
# ============================================================
WIZARD_STEPS = (
    {
        "step":  1,
        "title": "키 추출",
        "desc":  "게임 실행파일 또는 실행 중인 프로세스에서 암호화 키를 얻습니다.",
        "flags": ("-xkey", "-xmkey"),
        "skip_allowed": True,
        "skip_reason":  "키가 이미 있으면 건너뛸 수 있습니다.",
    },
    {
        "step":  2,
        "title": "Scene.pck 언팩",
        "desc":  "메인 시나리오 파일을 .scn 파일들로 분해합니다.",
        "flags": ("-u",),
        "skip_allowed": False,
        "skip_reason":  "",
    },
    {
        "step":  3,
        "title": "텍스트 추출",
        "desc":  "Scene 폴더의 .scn 파일들과 dat 폴더의 .dbs 파일들에서 텍스트를 뽑습니다.",
        "flags": ("-xat", "-xt"),
        "skip_allowed": False,
        "skip_reason":  "",
    },
    {
        "step":  4,
        "title": "(외부 작업) 텍스트 번역",
        "desc":  "추출된 .ext.txt 파일들을 번역합니다. 이 도구는 번역 기능을 포함하지 않습니다.",
        "flags": (),
        "skip_allowed": False,
        "skip_reason":  "",
    },
    {
        "step":  5,
        "title": "텍스트 재삽입",
        "desc":  "번역된 텍스트를 원본 .scn/.dbs/.dat 파일들에 다시 넣습니다.",
        "flags": ("-rat", "-rt"),
        "skip_allowed": False,
        "skip_reason":  "",
    },
    {
        "step":  6,
        "title": "Scene 폴더 리팩",
        "desc":  ".scn 파일들을 모아 _new.pck 파일로 다시 패키징합니다.",
        "flags": ("-p",),
        "skip_allowed": False,
        "skip_reason":  "",
    },
    {
        "step":  7,
        "title": "한글 간격 패치",
        "desc":  "실행파일에 한글 간격 정상화 패치를 적용합니다.",
        "flags": ("-j2k", "-wkey"),
        "skip_allowed": True,
        "skip_reason":  "한글이 이미 정상 출력된다면 건너뛸 수 있습니다.",
    },
)
