# certs/

SSL inspection 이 있는 사내망에서만 필요한 **사설 Root CA** 를 두는 위치입니다.

- 이 디렉토리의 `*.crt` 는 Docker 빌드 시 컨테이너의 시스템 신뢰 번들에 병합됩니다
  (`Dockerfile` → `update-ca-certificates`).
- 비어 있어도 정상 빌드됩니다. 공개 CA 만으로 동작하는 환경에서는 아무것도 두지 않아도 됩니다.
- **실제 인증서 파일은 Git 에 커밋하지 마세요.** 조직의 CA 인증서는 내부 네트워크 구성을
  드러낼 수 있습니다. `.gitignore` 가 `certs/*.crt` 를 제외하고 있습니다.

사용법: 발급받은 CA 파일을 `certs/` 아래에 `.crt` 확장자로 복사한 뒤 이미지를 다시 빌드하세요.
