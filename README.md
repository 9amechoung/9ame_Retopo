# 9ame Retopo

zRail 스타일의 Maya 리토폴로지 도구입니다. 레일 두 개 사이에 쿼드 스트립을 만들고, 하이폴리 표면에 스냅하고, 엣지 루프를 추가하고, 브러시로 릴랙스할 수 있습니다.

- 대상: Maya 2022 이상 (Python 3, PySide2/PySide6)
- 구현: Python + OpenMaya 2.0, 모든 작업은 Ctrl+Z 한 번으로 되돌릴 수 있습니다.

## 설치

1. 이 저장소를 원하는 위치에 받아둡니다.
2. `install.py` 를 Maya 뷰포트에 드래그 앤 드롭합니다.
3. 메인 메뉴바에 **9ame Retopo** 메뉴가 생깁니다. 다음 실행부터는 모듈 파일 `nine_retopo.mod` 로 자동 로드됩니다.

## 삭제 / 업데이트

- **삭제**: `uninstall.py` 를 뷰포트에 드래그 앤 드롭하거나 **9ame Retopo → Uninstall** 을 누릅니다. 플러그인 언로드, 메뉴·창 제거, 모듈 파일 삭제까지 처리하므로 그 다음 폴더를 지우면 됩니다.
- **업데이트**: 언인스톨 → 기존 폴더 삭제 → 새 버전 폴더의 `install.py` 드래그 앤 드롭. Maya 재시작은 필요 없습니다. 새 폴더의 `install.py` 만 바로 드롭해도 이전 버전을 먼저 정리합니다.

## 사용법

| 기능 | 방법 |
|---|---|
| **Live Surface** | 하이폴리 메쉬 선택 → *Set From Selection*. 스냅 기준이 되고, `makeLive` 로 Maya 커브 툴도 표면에 붙습니다. |
| **Draw Rails** | zRail 방식 드로잉 툴입니다. 하이폴리 위에 드래그해서 레일을 그리면 두 번째 레일부터 스트립이 자동으로 생기고, 이후 레일은 직전 스트립 끝에서 계속 이어집니다. |
| **Build Strip** | 레일 2개 선택 → 버튼. 레일은 NURBS 커브(Live 상태에서 그린 커브)나 리토폴 메쉬의 엣지 체인 모두 가능합니다. |
| **Insert Edge Loop** | 엣지 하나 선택 → 링 전체에 루프 추가 후 새 버텍스를 표면에 스냅합니다. |
| **Relax Selection** | 버텍스/엣지/페이스/메쉬 선택 → 라플라시안 릴랙스 후 표면에 재투영합니다. |
| **Snap To Surface** | 선택한 버텍스를 표면으로 투영합니다. |
| **Relax Brush** | 리토폴 메쉬 선택 → 활성화 → 뷰포트에서 드래그합니다. 반경은 월드 단위입니다. |

### Draw Rails (zRail 방식)

1. 하이폴리를 Live Surface로 설정합니다.
2. **Draw Rails**를 누르고 뷰포트에서 하이폴리 위에 드래그합니다.
   - 첫 번째 스트로크는 노란 가이드 레일로 남습니다.
   - 두 번째 스트로크를 놓는 순간 두 레일 사이에 스트립이 생깁니다.
   - 계속 그리면 직전 스트립의 끝 엣지에서 이어지고, 하나의 메쉬로 웰드됩니다.
3. **Shift + 드래그**로 그리면 새 체인을 시작합니다. 버튼 **New Chain**도 같은 동작입니다.
4. 기존 리토폴 메쉬에서 이어 그리려면 테두리 엣지를 선택한 상태에서 Draw Rails를 켭니다.
5. 시작점과 끝점이 가까운 스트로크는 닫힌 레일로 처리됩니다. 닫힌 레일 두 개를 그리면 원통형 스트립이 됩니다.
6. Ctrl+Z는 스트로크 단위로 되돌립니다. 되돌린 뒤 이어 붙이기가 어긋나면 New Chain으로 새로 시작하세요.

옵션(Spans along / Spans across / Stroke smoothing)은 툴 창의 Rail Strip 그룹에서 바꿉니다. Spans along이 `0`이면 첫 스트립은 정사각형에 가까운 쿼드로 나누고, 이어지는 스트립은 앞 스트립과 같은 분할 수를 씁니다.

### Build Strip 옵션

- **Spans along**: 레일 방향 분할 수입니다. `0` 이면 자동으로 정해집니다. 엣지 레일이 있으면 그 엣지 수에 맞추고, 없으면 정사각형에 가까운 쿼드가 되도록 계산합니다.
- **Spans across**: 두 레일 사이 분할 수입니다.
- **Merge into edge rail mesh**: 엣지 레일을 쓴 경우 새 스트립을 해당 메쉬에 합치고 버텍스를 웰드합니다. 기존 메쉬에서 이어서 확장하는 작업 흐름입니다.
- 닫힌 레일 두 개(예: 원형 커브 두 개, 닫힌 엣지 루프 두 개)를 고르면 원통형 스트립이 만들어집니다.
- 노멀은 Live Surface 바깥쪽을 향하도록 자동으로 정렬됩니다.

## 구조

```
install.py                  드래그 앤 드롭 설치
uninstall.py                드래그 앤 드롭 삭제
plug-ins/nineRetopo.py      플러그인 (메뉴 등록)
scripts/nine_retopo/
  geometry.py               Maya 비의존 기하 계산 (리샘플, 정렬, 그리드, 릴랙스)
  mesh_utils.py             메쉬 읽기/쓰기, 선택 처리, undo
  surface.py                Live Surface 와 투영
  strip.py                  레일 → 스트립
  rail_tool.py              zRail 방식 레일 드로잉 툴 (draggerContext)
  viewport.py               화면 좌표 → 메쉬 레이캐스트
  loops.py                  엣지 루프 삽입
  relax.py                  릴랙스
  brush.py                  뷰포트 릴랙스 브러시 (draggerContext)
  ui.py                     도킹 가능한 툴 창
tests/                      geometry 단위 테스트
```

## 테스트

```
python3 -m unittest discover -s tests
```
