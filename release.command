#!/bin/bash
# 새 버전 내보내기: 더블클릭 → 버전 확인 → GitHub에 태그를 올리면 자동으로 맥/윈도우 앱이 빌드되어 릴리즈된다.
set -euo pipefail
cd "$(dirname "$0")"

if [ -n "$(git status --porcelain)" ]; then
  echo "아직 커밋하지 않은 변경이 있어요. 먼저 커밋하고 다시 실행해 주세요."
  git status --short
  read -r -p "엔터를 누르면 닫힙니다." _; exit 1
fi

git fetch --tags --quiet
LAST="$(git tag --list 'v*' --sort=-v:refname | head -n1)"
LAST="${LAST:-v0.0.0}"
IFS=. read -r MA MI PA <<<"${LAST#v}"
NEXT="v$MA.$MI.$((PA + 1))"

echo "지금 버전: $LAST"
read -r -p "새 버전 [$NEXT]: " IN
VER="${IN:-$NEXT}"
[[ "$VER" == v* ]] || VER="v$VER"

git push origin HEAD
git tag "$VER"
git push origin "$VER"
URL="$(gh repo view --json url -q .url 2>/dev/null || true)"
echo ""
echo "$VER 태그를 올렸어요. 10분쯤 뒤 릴리즈 페이지에 앱 파일이 올라옵니다."
[ -n "$URL" ] && echo "진행 상황: $URL/actions" && echo "릴리즈:    $URL/releases"
read -r -p "엔터를 누르면 닫힙니다." _
