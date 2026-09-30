"""Smoke checks for the router log parser and CSV merge.

The production loop in main.py polls a router and a SQL Server, so these tests
stub those edges and exercise the file parsing path on the upgraded stack.
"""

import compileall
from pathlib import Path

import pyodbc

import call_parser
import connections
import file_manager

LOG_HTML = """<html><body>
<table class="main_table"><tr><td>summary</td></tr></table>
<table class="main_table">
<tr>
<td>Source</td>
<td>Destination</td>
<td>Start Time</td>
<td>Duration</td>
</tr>
<tr>
<td>1001</td>
<td>2002</td>
<td>30-09-20 10:00:00</td>
<td>00:01:05</td>
</tr>
<tr>
<td>1003</td>
<td>2004</td>
<td>30-09-20 11:00:00</td>
<td>00:02:05</td>
</tr>
</table>
</body></html>
"""

EXPECTED_LOG = (
    "Source;Destination;Start Time;Duration\n"
    "1001;2002;30-09-20 10:00:00;00:01:05\n"
    "1003;2004;30-09-20 11:00:00;00:02:05\n"
)


class _FrozenDatetimeModule:
    def __init__(self, stamp):
        self.stamp = stamp
        outer = self

        class _Datetime:
            @staticmethod
            def now():
                stamp = outer.stamp

                class _Stamp:
                    def strftime(self, _fmt):
                        return stamp

                return _Stamp()

        self.datetime = _Datetime


def test_sources_compile():
    root = Path(__file__).resolve().parents[1]
    for name in ("main.py", "call_parser.py", "connections.py", "file_manager.py"):
        assert compileall.compile_file(str(root / name), quiet=1)


def test_runtime_imports():
    import bs4
    import certifi
    import dotenv
    import lxml
    import numpy
    import pandas
    import requests
    import urllib3

    assert all(
        module is not None
        for module in (
            bs4,
            certifi,
            dotenv,
            lxml,
            numpy,
            pandas,
            pyodbc,
            requests,
            urllib3,
        )
    )


def test_router_parser_writes_log_and_skips_duplicates(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "cache").mkdir()
    clock = _FrozenDatetimeModule("30-09-20 12_00_00")
    pages = {"html": LOG_HTML}

    monkeypatch.setattr(call_parser, "datetime", clock)
    monkeypatch.setattr(call_parser, "connectRouter", lambda: pages["html"])

    call_parser._router_parser()
    log_path = tmp_path / "logs" / "30-09-20 12_00_00.csv"
    assert log_path.read_text() == EXPECTED_LOG
    assert list((tmp_path / "cache").iterdir()) == []

    call_parser._router_parser(log_path.name)
    assert list((tmp_path / "logs").iterdir()) == [log_path]
    assert "Created new log" not in capsys.readouterr().out

    pages["html"] = LOG_HTML.replace("1003", "1009")
    call_parser._router_parser(log_path.name)
    updated = (
        "Source;Destination;Start Time;Duration\n"
        "1001;2002;30-09-20 10:00:00;00:01:05\n"
        "1009;2004;30-09-20 11:00:00;00:02:05\n"
    )
    assert log_path.read_text() == updated
    assert "Created new log with name 30-09-20 12_00_00.csv" in capsys.readouterr().out


def test_merge_files_dedupes_and_inserts(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "cache").mkdir()
    (tmp_path / "queries").mkdir()
    (tmp_path / "logs" / "a.csv").write_text(
        "Source;Destination;Start Time;Duration\n"
        "1001;2002;30-09-20 10:00:00;00:01:05\n"
        "1003;2004;30-09-20 11:00:00;00:02:05\n"
    )
    (tmp_path / "logs" / "b.csv").write_text(
        "Source;Destination;Start Time;Duration\n"
        "1001;2002;30-09-20 10:00:00;00:01:05\n"
        "1009;2010;30-09-20 12:00:00;00:03:05\n"
        ";;30-09-20 13:00:00;\n"
    )

    monkeypatch.setattr(file_manager, "datetime", _FrozenDatetimeModule("30-09-2020"))
    executed = []

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query):
            executed.append(query)

    class _Connection:
        def cursor(self):
            return _Cursor()

    monkeypatch.setattr(file_manager, "connectDB", lambda: _Connection())

    file_manager.merge_files("logs")

    assert set(executed) == {
        "INSERT INTO Phonecalls (Source, Destination, StartTime, Durations) "
        "VALUES ('1001', '2002', '30-09-20 10:00:00', '00:01:05')",
        "INSERT INTO Phonecalls (Source, Destination, StartTime, Durations) "
        "VALUES ('1003', '2004', '30-09-20 11:00:00', '00:02:05')",
        "INSERT INTO Phonecalls (Source, Destination, StartTime, Durations) "
        "VALUES ('1009', '2010', '30-09-20 12:00:00', '00:03:05')",
    }
    saved = (tmp_path / "queries" / "30-09-2020" / "query.csv").read_text().splitlines()
    assert saved[0] == "Source;Destination;Start Time;Duration"
    assert set(saved[1:]) == {
        "1001;2002;30-09-20 10:00:00;00:01:05",
        "1003;2004;30-09-20 11:00:00;00:02:05",
        "1009;2010;30-09-20 12:00:00;00:03:05",
    }
    assert not (tmp_path / "logs").exists()
    assert not (tmp_path / "cache").exists()
    assert "Connection Established" in capsys.readouterr().out


def test_connect_router_and_db_use_environment(monkeypatch):
    monkeypatch.setenv("PAGE_SRC", "http://router.local/log")
    monkeypatch.setenv("USERNAME", "Admin")
    monkeypatch.setenv("USER_PWD", "secret")
    captured = {}

    class _Response:
        text = "<html>ok</html>"

    def _get(url, auth):
        captured["url"] = url
        captured["auth"] = auth
        return _Response()

    monkeypatch.setattr(connections.requests, "get", _get)
    assert connections.connectRouter() == "<html>ok</html>"
    assert captured == {
        "url": "http://router.local/log",
        "auth": ("admin", "secret"),
    }

    monkeypatch.setenv("SQL_SERVER", "{ODBC Driver 17 for SQL Server}")
    monkeypatch.setenv("SQL_NAME", "db.example")
    monkeypatch.setenv("SQL_DB", "phones")
    monkeypatch.setenv("SQL_USER", "sa")
    monkeypatch.setenv("SQL_PWD", "pw")
    monkeypatch.setenv("SQL_TRUST", "no")
    seen = {}

    def _connect(connection_string):
        seen["connection_string"] = connection_string
        return object()

    monkeypatch.setattr(connections.pyodbc, "connect", _connect)
    assert connections.connectDB() is not None
    assert seen["connection_string"] == (
        "Driver={ODBC Driver 17 for SQL Server};"
        "Server=db.example;"
        "Database=phones;"
        "UID=sa;"
        "PWD=pw;"
        "Trusted_Connection=no;"
    )


def test_connect_db_reports_interface_error(monkeypatch, capsys):
    def _connect(_connection_string):
        raise pyodbc.InterfaceError("08001", "unavailable")

    monkeypatch.setattr(connections.pyodbc, "connect", _connect)
    assert connections.connectDB() is None
    assert "Couldn't connect to DB" in capsys.readouterr().out
