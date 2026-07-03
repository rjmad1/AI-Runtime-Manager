# core/manager.py
# Thin backward-compatibility re-export layer.
# All logic has been decomposed into focused modules:
#   - config.py     : Constants, YAML I/O, env vars, cmd_configure
#   - process.py    : PID/port management, cmd_start/stop/status
#   - diagnostics.py: Benchmarking, report generation
#   - backup.py     : Backup/restore
#   - validation.py : Provider API key validation
#   - cli.py        : CLI argparse entry point, repair/upgrade/uninstall

import os
import sys

# Ensure core/ is on the import path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Re-export everything that prompt_server.py and .bat scripts depend on
from config import (  # noqa: F401
    CORE_DIR, ROOT_DIR, CONFIG_DIR, GENERATED_DIR, LOGS_DIR,
    SETTINGS_PATH, PROVIDERS_PATH, MODELS_PATH,
    LITELLM_CONFIG_PATH, OPENCLAW_CONFIG_PATH, SERVICES_STATE_PATH,
    LOG_FILE,
    log, load_yaml, save_yaml,
    get_windows_env, set_windows_env,
    cmd_configure,
)
from process import (  # noqa: F401
    load_services_state, save_services_state,
    get_pids_on_port, is_pid_running, kill_process_tree, scavenge_ports,
    cmd_start, cmd_stop, cmd_status,
)
from diagnostics import cmd_diagnose  # noqa: F401
from backup import cmd_backup, cmd_restore  # noqa: F401
from cli import cmd_install, cmd_repair, cmd_upgrade, cmd_uninstall, main  # noqa: F401

if __name__ == "__main__":
    main()
