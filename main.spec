# -*- mode: python ; coding: utf-8 -*-
# One-file, windowless build: dist/InterviewCopilot.exe
# The app writes .env / prompt.txt / settings.json next to the exe on first run.

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('app/static', 'app/static')],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops.auto',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan.on',
        'websockets',
        'multipart',
        'pypdf',
        'docx',
        'pystray._win32',
        'PIL.Image',
        'PIL.ImageDraw',
        'pyaudiowpatch',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='InterviewCopilot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
