from __future__ import annotations

import re
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
MAKEFILE = (AGENT_DIR / "Makefile").read_text(encoding="utf-8")
DOCKERFILE = (AGENT_DIR / "Dockerfile").read_text(encoding="utf-8")
NORMALIZED_MAKEFILE = re.sub(r"\s+", " ", MAKEFILE)
NORMALIZED_DOCKERFILE = re.sub(r"\s+", " ", DOCKERFILE)


def test_makefile_stages_auth_component_for_container_builds() -> None:
    build_context_pattern = (
        r"BUILD_CONTEXT=\$\$\(mktemp -d \./\.build-context\.XXXXXX\)"
    )
    copy_pattern = (
        r'mkdir -p "\$\$BUILD_CONTEXT"/components && cp -r '
        r'\.\./\.\./\.\./\.\./components/auth "\$\$BUILD_CONTEXT"/components/auth'
    )
    cleanup_pattern = r"trap 'rm -rf \"\$\$BUILD_CONTEXT\"' EXIT"

    assert len(re.findall(build_context_pattern, NORMALIZED_MAKEFILE)) == 2
    assert len(re.findall(copy_pattern, NORMALIZED_MAKEFILE)) == 2
    assert len(re.findall(cleanup_pattern, NORMALIZED_MAKEFILE)) == 2


def test_makefile_preserves_tracked_images_during_container_builds() -> None:
    shared_stage_pattern = (
        r'cp -r \.\./\.\./\.\./\.\./images "\$\$BUILD_CONTEXT"/images'
    )
    merge_pattern = r'if \[ -d \./images \]; then cp -r \./images/\. "\$\$BUILD_CONTEXT"/images/; fi'

    assert len(re.findall(shared_stage_pattern, NORMALIZED_MAKEFILE)) == 2
    assert len(re.findall(merge_pattern, NORMALIZED_MAKEFILE)) == 2


def test_makefile_builds_from_temporary_context() -> None:
    local_build_pattern = (
        r'\$\(CONTAINER_CLI\) build --platform linux/amd64 -t "\$\$\{CONTAINER_IMAGE\}" '
        r'-f "\$\$BUILD_CONTEXT/Dockerfile" "\$\$BUILD_CONTEXT"'
    )
    openshift_build_pattern = (
        r'oc start-build \$\(AGENT_NAME\) --from-dir="\$\$BUILD_CONTEXT" --follow'
    )

    assert re.search(local_build_pattern, NORMALIZED_MAKEFILE)
    assert re.search(openshift_build_pattern, NORMALIZED_MAKEFILE)


def test_dockerfile_consumes_staged_auth_component() -> None:
    assert re.search(
        r"COPY components/auth/ \./components/auth/", NORMALIZED_DOCKERFILE
    )
    assert re.search(
        r"RUN uv pip install --no-cache \./components/auth", NORMALIZED_DOCKERFILE
    )
