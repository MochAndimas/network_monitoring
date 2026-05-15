"""Runtime startup configuration tests for scheduler and observability setup."""

from scripts.prepare_prometheus_multiproc_dir import main as prepare_prometheus_multiproc_dir


def test_production_rejects_auto_create_tables(monkeypatch):
    import backend.app.main as main_module

    monkeypatch.setattr(main_module.settings, "database_auto_create_tables", True)
    monkeypatch.setattr(main_module.settings, "app_env", "production")

    try:
        main_module._should_auto_create_tables()
    except RuntimeError as exc:
        assert "DATABASE_AUTO_CREATE_TABLES" in str(exc)
    else:
        assert False, "production startup must reject auto table creation"


def test_development_create_all_requires_explicit_opt_in(monkeypatch):
    import backend.app.main as main_module

    monkeypatch.setattr(main_module.settings, "app_env", "development")
    monkeypatch.setattr(main_module.settings, "database_auto_create_tables", False)

    assert main_module._should_auto_create_tables() is False

    monkeypatch.setattr(main_module.settings, "database_auto_create_tables", True)

    assert main_module._should_auto_create_tables() is True


def test_scheduler_timezone_is_config_driven(monkeypatch):
    import backend.app.scheduler.scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module.settings, "scheduler_timezone", "UTC")

    scheduler = scheduler_module.create_scheduler()

    assert str(scheduler.timezone) == "UTC"


def test_prometheus_multiproc_prepare_preserves_files_unless_cleanup_enabled(monkeypatch, tmp_path):
    metric_file = tmp_path / "counter_123.db"
    other_file = tmp_path / "note.txt"
    metric_file.write_text("metric", encoding="utf-8")
    other_file.write_text("keep", encoding="utf-8")

    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_CLEAN_ON_STARTUP", raising=False)

    prepare_prometheus_multiproc_dir()

    assert metric_file.exists()
    assert other_file.exists()

    monkeypatch.setenv("PROMETHEUS_MULTIPROC_CLEAN_ON_STARTUP", "true")

    prepare_prometheus_multiproc_dir()

    assert not metric_file.exists()
    assert other_file.exists()
