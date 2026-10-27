#!/usr/bin/env bash
set -euo pipefail
task_source="$1"
task_action="${2:-demo}"
shift 2
task_root="${H2_PORTABLE_ROOT:-$HOME/projects/harness2_portable_core}"
if [[ "$task_action" == setup ]]; then
    mkdir -p "$task_root/.tools"
    if [[ ! -x "$task_root/.tools/bin/uv" ]]; then
        curl -LsSf https://astral.sh/uv/0.13.6/install.sh -o "$task_root/.tools/uv-installer.sh"
        UV_INSTALL_DIR="$task_root/.tools/bin" UV_NO_MODIFY_PATH=1 sh "$task_root/.tools/uv-installer.sh"
    fi
    python3 "$task_source/scripts/prepare_wsl.py" --root "$task_root" --setup --build
    exit
fi
python3 "$task_source/scripts/prepare_wsl.py" --root "$task_root"
cd "$task_root/project"
case "$task_action" in
    test) H2_TEST_DOCKER_IMAGE=h2portable:offline .venv/bin/python -m unittest discover -s tests -v ;;
    demo) .venv/bin/python scripts/validate_core.py --root "$task_root" "$@" ;;
    reliability) .venv/bin/python scripts/check_reliability.py --root "$task_root" "$@" ;;
    run|status|stop) .venv/bin/python -m h2portable "$task_action" "$@" ;;
esac
