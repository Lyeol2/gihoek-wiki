#!/usr/bin/env python3
"""배포판 만들기 (맥이면 맥 앱, 윈도우면 윈도우 앱).

    python3 scripts/build.py --version 0.1.0

결과물은 dist/release/ 에 모인다.
    맥      gihoek-wiki-<버전>-mac.dmg
    윈도우  gihoek-wiki-<버전>-windows-setup.exe   (Inno Setup이 있을 때)
            gihoek-wiki-<버전>-windows-portable.zip

필요한 것: pip install pyinstaller / 맥은 Xcode(swiftc) / 윈도우 설치 파일은 Inno Setup 6
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
RELEASE = os.path.join(DIST, "release")
SLUG = "gihoek-wiki"
APP_NAME = "기획위키"
BUNDLE_ID = "io.github.lyeol2.gihoek-wiki"
RELEASE_PORT = 4317


def run(cmd, **kw):
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def pyinstaller(version, extra):
    with open(os.path.join(BUILD, "version.txt"), "w", encoding="utf-8") as f:
        f.write(version)
    sep = os.pathsep
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", os.path.join(BUILD, "pyi"), "--workpath", os.path.join(BUILD, "pyi-work"),
         "--specpath", BUILD,
         "--add-data", f"{os.path.join(ROOT, 'public')}{sep}public",
         "--add-data", f"{os.path.join(BUILD, 'version.txt')}{sep}.",
         *extra, os.path.join(ROOT, "server.py")], cwd=ROOT)


# ------------------------------------------------------------------ mac

INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>{name}</string>
  <key>CFBundleDisplayName</key><string>{name}</string>
  <key>CFBundleIdentifier</key><string>{bundle_id}</string>
  <key>CFBundleExecutable</key><string>GihoekWiki</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>{version}</string>
  <key>CFBundleVersion</key><string>{version}</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSHumanReadableCopyright</key><string>게임 기획 위키</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key><true/>
    <key>NSAllowsArbitraryLoads</key><true/>
  </dict>
</dict>
</plist>
"""


def build_mac(version):
    pyinstaller(version, ["--onefile", "--name", "wiki-server"])
    shell = os.path.join(BUILD, "GihoekWiki")
    run(["swiftc", "-O", "-swift-version", "5", os.path.join(ROOT, "macapp", "main.swift"), "-o", shell])

    app = os.path.join(DIST, f"{APP_NAME}.app")
    shutil.rmtree(app, ignore_errors=True)
    macos, res = os.path.join(app, "Contents", "MacOS"), os.path.join(app, "Contents", "Resources")
    os.makedirs(macos)
    os.makedirs(res)
    shutil.copy2(shell, os.path.join(macos, "GihoekWiki"))
    shutil.copy2(os.path.join(BUILD, "pyi", "wiki-server"), os.path.join(macos, "wiki-server"))
    shutil.copy2(os.path.join(ROOT, "assets", "icon.icns"), os.path.join(res, "AppIcon.icns"))
    with open(os.path.join(res, "app-config.json"), "w", encoding="utf-8") as f:
        json.dump({"bundled": True, "port": RELEASE_PORT}, f)
    with open(os.path.join(app, "Contents", "Info.plist"), "w", encoding="utf-8") as f:
        f.write(INFO_PLIST.format(name=APP_NAME, bundle_id=BUNDLE_ID, version=version))
    run(["codesign", "--force", "--deep", "-s", "-", app])

    stage = os.path.join(BUILD, "dmg")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    run(["ditto", app, os.path.join(stage, f"{APP_NAME}.app")])
    os.symlink("/Applications", os.path.join(stage, "Applications"))
    dmg = os.path.join(RELEASE, f"{SLUG}-{version}-mac.dmg")
    run(["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", stage, "-ov", "-format", "UDZO", dmg])
    return [dmg]


# ------------------------------------------------------------------ windows

ISS = r"""
[Setup]
AppId={{{{7C1B5E2A-4F3D-4B8E-9A61-2D5C8E0F3B47}}
AppName={name}
AppVersion={version}
AppVerName={name} {version}
AppPublisher={name}
DefaultDirName={{localappdata}}\Programs\GihoekWiki
DefaultGroupName={name}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={outdir}
OutputBaseFilename={outname}
SetupIconFile={icon}
UninstallDisplayIcon={{app}}\GihoekWiki.exe
UninstallDisplayName={name}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
{languages}
[Tasks]
Name: "desktopicon"; Description: "{desktop_label}"

[Files]
Source: "{src}\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{autoprograms}}\{name}"; Filename: "{{app}}\GihoekWiki.exe"
Name: "{{autodesktop}}\{name}"; Filename: "{{app}}\GihoekWiki.exe"; Tasks: desktopicon

[Run]
Filename: "{{app}}\GihoekWiki.exe"; Description: "{run_label}"; Flags: nowait postinstall skipifsilent
"""


def find_iscc():
    for c in [shutil.which("iscc"),
              os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Inno Setup 6", "ISCC.exe"),
              os.path.join(os.environ.get("ProgramFiles", ""), "Inno Setup 6", "ISCC.exe"),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe")]:
        if c and os.path.isfile(c):
            return c
    return None


def build_windows(version):
    pyinstaller(version, ["--onedir", "--noconsole", "--name", "GihoekWiki",
                          "--icon", os.path.join(ROOT, "assets", "icon.ico"), "--hidden-import", "launcher_win", "--hidden-import", "updater"])
    src = os.path.join(BUILD, "pyi", "GihoekWiki")
    out = []

    portable = os.path.join(RELEASE, f"{SLUG}-{version}-windows-portable.zip")
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED) as z:
        for path in glob.glob(os.path.join(src, "**", "*"), recursive=True):
            if os.path.isfile(path):
                z.write(path, os.path.join("GihoekWiki", os.path.relpath(path, src)))
    out.append(portable)

    iscc = find_iscc()
    if not iscc:
        print("! Inno Setup이 없어서 설치 파일은 건너뜁니다 (portable zip만 만듦)", flush=True)
        return out
    korean = os.path.join(os.path.dirname(iscc), "Languages", "Korean.isl")
    languages = '[Languages]\nName: "ko"; MessagesFile: "compiler:Languages\\Korean.isl"\n' if os.path.isfile(korean) else ""
    name = f"{SLUG}-{version}-windows-setup"
    iss = os.path.join(BUILD, "setup.iss")
    with open(iss, "w", encoding="utf-8-sig") as f:
        f.write(ISS.format(name=APP_NAME, version=version, outdir=RELEASE, outname=name, src=src,
                           icon=os.path.join(ROOT, "assets", "icon.ico"), languages=languages,
                           desktop_label="바탕화면에 바로가기 만들기", run_label="기획위키 실행"))
    run([iscc, iss])
    out.append(os.path.join(RELEASE, name + ".exe"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="0.0.0-dev")
    version = ap.parse_args().version.lstrip("v")
    os.makedirs(BUILD, exist_ok=True)
    shutil.rmtree(RELEASE, ignore_errors=True)
    os.makedirs(RELEASE)
    if sys.platform == "darwin":
        files = build_mac(version)
    elif os.name == "nt":
        files = build_windows(version)
    else:
        sys.exit("맥 또는 윈도우에서 실행하세요.")
    print("\n완료:")
    for f in files:
        print(f"  {f}  ({os.path.getsize(f) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
