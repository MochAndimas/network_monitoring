"""Reconcile known legacy MySQL index drift without changing domain rows.

Revision ID: 20260908_0028
Revises: 20260908_0027
"""

from alembic import op
import sqlalchemy as sa

revision = "20260908_0028"
down_revision = "20260908_0027"
branch_labels = None
depends_on = None

# Fixed schema contract, independent of future ORM changes.
_REQUIRED = (
    ("latest_metrics", "uq_latest_metrics_metric_id", ("metric_id",), True),
    ("thresholds", "key", ("key",), True),
    (
        "metric_cold_archives",
        "ix_metric_cold_archives_month_metric_site_lookup",
        ("archive_month", "metric_name", "device_id"),
        False,
    ),
    ("metric_daily_rollups", "ix_metric_daily_rollups_date_device_lookup", ("rollup_date", "device_id"), False),
)
_REPLACED = (
    ("latest_metrics", "ix_latest_metrics_metric_id", ("metric_id",)),
    ("thresholds", "ix_thresholds_key", ("key",)),
)
# A surviving prefix index/primary key must cover each redundant index.
_REDUNDANT = (
    ("auth_login_attempts", "ix_auth_login_attempts_id", ("id",)),
    ("latest_metrics", "ix_latest_metrics_id", ("id",)),
    ("incident_timeline_events", "ix_incident_timeline_events_incident_id", ("incident_id",)),
    ("maintenance_windows", "ix_maintenance_windows_device_id", ("device_id",)),
    ("threshold_overrides", "ix_threshold_overrides_device_id", ("device_id",)),
    ("metric_site_type_daily_summaries", "ix_metric_site_type_daily_summaries_summary_date", ("summary_date",)),
)


def _indexes(table):
    return {item["name"]: item for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _validate(index, columns, unique=None):
    if tuple(index["column_names"]) != columns or (unique is not None and bool(index["unique"]) != unique):
        raise RuntimeError(f"Unexpected definition for index {index['name']}; reconcile manually before retrying")


def upgrade() -> None:
    if op.get_bind().dialect.name != "mysql":
        raise RuntimeError("Legacy index reconciliation requires a live MySQL connection")
    # Validate all known names before any non-transactional DDL. Never silently
    # delete an unfamiliar index merely because its name resembles legacy drift.
    for table, name, columns, unique in _REQUIRED:
        existing = _indexes(table).get(name)
        if existing:
            _validate(existing, columns, unique)
    for table, name, columns in _REPLACED:
        existing = _indexes(table).get(name)
        if existing:
            _validate(existing, columns)
    for table, name, columns in _REDUNDANT:
        indexes = _indexes(table)
        if name not in indexes:
            continue
        _validate(indexes[name], columns, False)
        prefixes = [tuple(item["column_names"]) for key, item in indexes.items() if key != name]
        prefixes.append(tuple(sa.inspect(op.get_bind()).get_pk_constraint(table)["constrained_columns"]))
        if not any(prefix[: len(columns)] == columns for prefix in prefixes):
            raise RuntimeError(f"Cannot remove {name} without a surviving prefix index")
    # Ensure uniqueness and FK support before replacing any unique legacy index.
    for table, name, columns, unique in _REQUIRED:
        if name not in _indexes(table):
            op.create_index(name, table, list(columns), unique=unique)
    for table, name, columns in _REPLACED:
        existing = _indexes(table).get(name)
        if existing and existing["unique"]:
            op.drop_index(name, table_name=table)
            existing = None
        if existing is None:
            op.create_index(name, table, list(columns), unique=False)
    for table, name, _ in _REDUNDANT:
        if name in _indexes(table):
            op.drop_index(name, table_name=table)


def downgrade() -> None:
    # Revision 0027's canonical schema already requires these indexes. Restoring
    # environment-specific drift would break that schema and can lose uniqueness.
    pass
