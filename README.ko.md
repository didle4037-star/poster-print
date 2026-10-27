# Print & Pin · Poster Print

[English](README.md)

## 소개 영상

[![Print & Pin introduction video](https://i.ytimg.com/vi/AwLWuNOE6Js/hqdefault.jpg)](https://youtu.be/AwLWuNOE6Js)

[Watch: I Made 2 Blender Add-ons That Turn Images Into a Poster Wall | Print & Pin](https://youtu.be/AwLWuNOE6Js)

Poster Print는 Blender에서 이미지를 잘라 배치하고 종이 효과·UV·머티리얼이 적용된 포스터를 만드는 애드온입니다.

**Print & Pin** 시리즈의 도구로, 단독으로 사용하거나 **[Poster Pin](https://github.com/didle4037-star/poster-pin)**와 함께 사용할 수 있습니다. Poster Print로 원본 포스터를 만들고 Poster Pin으로 장면에 배치하는 흐름을 구성할 수 있습니다.

## 주요 기능

- 이미지를 불러오고 이미지 시트를 여러 이미지로 잘라냅니다.
- 아틀라스 레이아웃을 편집하고 UV와 머티리얼이 적용된 포스터 평면을 만듭니다.
- 사진 테두리, 즉석사진 형식, 캡션과 포토 스트립을 구성합니다.
- 종이 텍스처, 색감, 낡음, 구멍, 찢김과 구김 효과를 적용합니다.
- 이미 만든 포스터 배치를 다시 편집할 수 있습니다.
- 두 애드온을 활성화한 경우 결과 컬렉션을 Poster Pin으로 연결할 수 있습니다.

## 버전과 환경

- 제작자: **G_ni**
- 코드에 기록된 버전: **1.81.0**
- 패키지에 선언된 최소 Blender 버전: **5.2.0**
- UI 언어: **영어 / 한국어**

위 Blender 버전은 소스 메타데이터 기준이며 실제 호환성 테스트 결과를 의미하지 않습니다.

## 설치

1. 이 저장소의 **Releases**에서 **`Poster_Print_v1.81.zip`**를 내려받습니다.
2. Blender에서 **Edit → Preferences → Add-ons**를 열고 메뉴의 **Install from Disk**를 선택합니다.
3. 파일을 선택해 설치한 다음 **Print & Pin · Poster Print**을 활성화합니다.
4. 3D 뷰포트에서 **N**을 눌러 사이드바의 **Poster Print** 탭을 엽니다.

현재 배포본은 기존 애드온 형식입니다. GitHub에서 자동 생성하는 소스 ZIP과 구분하여, 릴리스에 첨부된 설치용 ZIP을 사용하세요.

## 빠른 시작

1. **Poster Print**에서 결과를 저장할 폴더를 지정합니다.
2. **Add Images**로 이미지를 추가합니다.
3. **Layout Editor · Build**를 열어 배치와 효과를 조정합니다.
4. **Apply · Build Posters**로 포스터 배치를 생성합니다.
5. 결과를 장면에서 사용하거나 Poster Pin으로 컬렉션을 연결합니다.

## 선택 기능: Substance 파일 베이크

**Bake from Substance File** 기능은 Substance Designer 명령줄 도구를 사용합니다. `sbsrender`가 필요하며 `.sbs` 입력에는 `sbscooker`도 필요합니다. 도구 경로와 추가 종이 텍스처 폴더를 지정해 사용합니다. 패키지에는 미리 베이크한 종이 텍스처도 포함되어 있습니다.

## 피드백과 오류 제보

오류와 개선 아이디어는 이 저장소의 **Issues**에 남겨 주세요. 애드온 버전, Blender 버전, 운영체제, 재현 순서와 오류 메시지를 함께 적어 주시면 도움이 됩니다. 필요한 경우 스크린샷이나 간단한 예제 파일도 첨부해 주세요.


개인 프로젝트이므로 답변과 수정에 시간이 걸릴 수 있습니다. 양해해 주셔서 감사합니다!
