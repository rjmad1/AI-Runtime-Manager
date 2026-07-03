# core/manager.py
# Thin backward-compatibility re-export layer.
# All logic has been decomposed into focused modules:
#   - config.py     : Constants, YAML I/O, env vars, cmd_configure
#   - process.py    : PID/port management, cmd_start/stop/status
#   - diagnostics.py: Benchmarking, report generation
#   - backup.py     : Backup/restore
#   - validation.py : Provider API key validation
#   - cli.py        : CLI argparse entry point, repair/upgrade/uninstall

# Re-export everything that prompt_server.py and .bat scripts depend on
from .backup import cmd_backup, cmd_restore  # noqa: F401
from .cli import cmd_install, cmd_repair, cmd_uninstall, cmd_upgrade, main  # noqa: F401
from .config import (  # noqa: F401
    CONFIG_DIR,
    CORE_DIR,
    GENERATED_DIR,
    LITELLM_CONFIG_PATH,
    LOG_FILE,
    LOGS_DIR,
    MODELS_PATH,
    OPENCLAW_CONFIG_PATH,
    PROVIDERS_PATH,
    ROOT_DIR,
    SERVICES_STATE_PATH,
    SETTINGS_PATH,
    cmd_configure,
    ensure_runtime_dirs,
    get_windows_env,
    load_yaml,
    log,
    save_yaml,
    set_windows_env,
)
from .diagnostics import cmd_diagnose  # noqa: F401
from .process import (  # noqa: F401
    cmd_start,
    cmd_status,
    cmd_stop,
    get_pids_on_port,
    is_pid_running,
    kill_process_tree,
    load_services_state,
    save_services_state,
    scavenge_ports,
)

if __name__ == "__main__":
    main()
