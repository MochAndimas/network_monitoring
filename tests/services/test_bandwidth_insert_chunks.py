import pytest

from backend.app.services.bandwidth_ingestion_service import insert_flow_rows
from tests.test_utils import run


@pytest.mark.parametrize("width,expected", [(0, [123]), (50, [50, 50, 23]), (1000, [123])])
def test_chunking_keeps_order_and_never_commits(width, expected):
    rows = [{"record_offset": i} for i in range(123)]

    class DB:
        def __init__(self):
            self.calls = []

        async def execute(self, statement, values):
            self.calls.append(values)

    db = DB()
    assert run(insert_flow_rows(db, rows, chunk_size=width)) == len(expected)
    assert [len(values) for values in db.calls] == expected
    assert [row for values in db.calls for row in values] == rows


@pytest.mark.parametrize("width", [-1, 10001, True, 1.5])
def test_invalid_chunk_sizes_fail_before_database_access(width):
    with pytest.raises(ValueError):
        run(insert_flow_rows(None, [{}], chunk_size=width))


def test_failure_propagates_to_caller_transaction_without_commit():
    class DB:
        calls = 0

        async def execute(self, statement, values):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("fixture failure")

    db = DB()
    with pytest.raises(RuntimeError, match="fixture failure"):
        run(insert_flow_rows(db, [{"record_offset": i} for i in range(6)], chunk_size=2))
    assert db.calls == 2
