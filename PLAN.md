# Modernization plan

Research date: 2026-09-30. This plan does not change runtime code. A later implementer should follow the phases below. Do not treat library versions here as a reason to reopen the dependency bump that already landed.

## 1. Idea

This is a small poller for one local router. Every 30 seconds it downloads the Oxygen gateway’s web “call log” page with HTTP basic auth, scrapes the second `main_table`, and writes a semicolon CSV under `logs/` when that table changed. At 16:30 local time it concatenates those CSVs, drops duplicate and empty rows, inserts them into a SQL Server table named `Phonecalls`, deletes `logs/` and `cache/`, and exits.

The README line is “Monitors all the phones in the router's log page.” The module docstring matches that: keep a day’s phone calls, then store them once.

What is uncertain:

- No captured page from an HDI24201 is in the repo. Public Cosmote/Oxygen manuals for the sibling models HDV24201 and HDI34201 describe a **Call Records** screen: totals for local, incoming, and outgoing calls, the last incoming and last outgoing call per line, and a short list of recent calls (the HDV24201 guide says the last 10). The code assumes the second `table.main_table` is that list, with columns `Source`, `Destination`, `Start Time`, and `Duration`. Those names are what `file_manager.py` inserts, and what `tests/test_smoke.py` now uses as a synthetic page. They are not confirmed against a real HDI24201.
- “All the phones” may mean every extension on this one gateway. Nothing in the code talks to handsets or to more than one URL (`PAGE_SRC`).
- The 16:30 stop is hard-coded. It looks like an office-hours batch, not a product requirement. The author’s original commit was in UTC+2.

The product to keep is: **from the LAN, record each voice call shown on this gateway’s call log, once, into a database the operator already has.** It should not become a PBX, a call recorder, or a general scraper.

## 2. Current stack

Language and layout: Python, four flat scripts, no package, no `pyproject.toml`. Entry point is `python main.py` from the repo root (relative `logs/`, `cache/`, `queries/` paths).

| Piece | Role today |
| --- | --- |
| `main.py` | Infinite loop, 30s sleep, exit at `16:30:00` local time |
| `connections.py` | `requests` basic auth to `PAGE_SRC`; `pyodbc` to SQL Server; `python-dotenv` |
| `call_parser.py` | Beautiful Soup on the HTML, pandas compare, CSV in `logs/` |
| `file_manager.py` | pandas concat, `INSERT` into `Phonecalls`, delete the working directories |
| `tests/test_smoke.py` | Pytest smoke tests with the router and the database stubbed |
| `.github/workflows/ci.yml` | Ubuntu, Python 3.12, `unixodbc`, `pip-audit`, pytest |

Pins already current as of 2026-09-30 (`requirements.txt`, comment says Python 3.12 / Ubuntu 24.04):

- `beautifulsoup4==4.15.0`, `lxml==6.1.3` (declared; the parser still uses `html.parser`)
- `pandas==3.0.6`, `numpy==2.5.3`
- `requests==2.34.2`, `urllib3==2.8.0`, `certifi==2026.7.22`
- `pyodbc==5.3.0`, `python-dotenv==1.2.3`
- Dev: `pytest==9.1.1`, `pip-audit==2.10.1`

How it runs: a machine on the same network as the gateway, with a `.env` (gitignored) and a working ODBC driver. CI installs unixODBC headers so `pyodbc` imports. It does not install Microsoft ODBC Driver 18, and it does not start SQL Server. There is no scheduler service, no Docker, and no sample `.env`.

Behavior the smoke tests already lock, and that a later change must update on purpose:

- Two `table.main_table` elements; index `[1]` becomes `Source;Destination;Start Time;Duration` CSV.
- An unchanged page does not write another log. A changed page writes a CSV named with the current timestamp.
- Merge drops duplicate rows and rows with empty fields, writes `queries/<dd-mm-YYYY>/query.csv` only when that directory is new, then deletes `logs/` and `cache/`.
- Inserts are literal SQL strings into `Phonecalls (Source, Destination, StartTime, Durations)`.
- `USERNAME=Admin` is sent as `admin`.
- `connectDB` returns `None` on `pyodbc.InterfaceError`.

Bugs still in the tree (the dependency bump did not touch them):

- `main.py` creates `logs` and `cache` whenever either is missing, so the existing one raises `FileExistsError`. `queries/` is never created; `os.mkdir("queries/<date>")` fails if the parent is absent. If the directory exists, the merged CSV is not refreshed, but the database write still runs.
- `os.listdir('logs')[-1]` is not “newest file”.
- `requests.get` has no timeout and does not check status. Any exception becomes a printed `None` page, and the parser then crashes.
- The class filter is the set `{'class', 'main_table'}`, not the documented `class_='main_table'`. The smoke fixture shows the current call matches that HTML. Keep the fixture green if the call is rewritten.
- Table text is rebuilt by splitting on newlines and writing a semicolon per line. A minified page, or a cell that contains a newline, will not survive. `lxml` is pinned and unused; switching the parser backend can change `.text` whitespace, so do that only together with cell-based parsing.
- `write_to_db` calls itself forever when `connectDB()` returns `None`, and it ignores the recursive return, so a later success would still use the failed connection.
- SQL is interpolated. A destination containing a quote breaks or rewrites the statement. There is no `commit()`. pyodbc’s default is a transaction that disappears when the connection closes. `delete_files()` still runs after per-row errors. The success count is `len(file) - 1`, which under-counts a DataFrame (the header is not a row).
- The 16:30 check uses naive local `strftime`. A UTC host stops at the wrong wall time. The process then exits instead of waiting for the next day.

## 3. Modern fit

Stay a single-process Python poller. The page is one authenticated HTML document every half minute, and the interesting table is about ten rows. That rules out a rewrite around Scrapy, Playwright, FastAPI, Polars, or a message queue.

Versions below are stable releases checked on 2026-09-30. Python 3.15 was still a prerelease (first release scheduled 2026-10-01). APScheduler 4.0.0a6 (April 2025) is still a pre-release with no stable 4.0; do not use it.

| Candidate | Status | Why it fits | Why it is not the default |
| --- | --- | --- | --- |
| **Python 3.12** | Security fixes through 2028-10. Already the CI interpreter. Ubuntu 24.04’s default. | Matches the host this script already documents. Pandas 3.0.6 and pyodbc 5.3.0 both ship 3.12 wheels. | 3.13 (bugfix through 2029-10) and 3.14 (bugfix through 2030-10) are newer and fine later. Moving now does not fix the data-loss bugs. |
| **requests 2.34.2** | Already pinned. Maintained; 2.34.2 was 2026-05-14. | Sync basic auth, one call per poll. Session, timeout, and urllib3 retries cover this job. | **httpx 0.28.1** is a solid sync client, but this program never needs HTTP/2 or async. |
| **beautifulsoup4 4.15.0 + lxml 6.1.3** | Already pinned. | The log is a static HTML table. Soup’s table API is the readable tool, and the smoke fixture is written for it. Use `lxml` as the Soup backend once cells are parsed, so the unused pin does some work. | **selectolax 0.4.x (Lexbor)** is the faster HTML5 parser. A ten-row admin page does not need it, and the Modest backend is unmaintained. |
| **stdlib `sqlite3`** | In the 3.12 standard library. | Local source of truth with a unique constraint. No ODBC driver on the poller. | A second SQL Server is the wrong place to *discover* new calls. Keep it as a sink. |
| **SQLAlchemy 2.1.1** | Stable, 2026-09-25. Python >=3.11. MSSQL dialect uses pyodbc. | One parameterized insert for SQLite and for SQL Server. Replaces the f-string and gives an explicit transaction. | Hand-written `sqlite3` plus raw pyodbc is fewer dependencies if SQL Server is abandoned. |
| **pyodbc 5.3.0** | Already pinned. Wheels for 3.9–3.14. | The existing SQL Server path. Still needs **Microsoft ODBC Driver 18** (or whichever driver the host already has) installed outside pip. | **pymssql** avoids ODBC on some platforms and is a SQLAlchemy dialect, but it is a second driver for a database we only want as an export. |
| **pydantic-settings 2.15.0** | Stable, 2026-08-07. Uses pydantic 2 and python-dotenv. | Fails at startup when `PAGE_SRC` or the SQL variables are missing, instead of `None.lower()` mid-loop. Can keep today’s env names. | A short required-key check is enough while the only knobs are the current `.env` names. |
| **APScheduler 3.11.2** | Stable line. Latest 3.x release 2025-12-22. | Interval poll plus a daily export, with misfire handling. | One 30-second loop does not need a scheduler library. The 4.x alpha is out. |
| **pandas 3.0.6** | Already pinned. | The smoke tests round-trip CSVs through it. Safe to leave until the row model exists. | After that, ten rows do not justify pandas and numpy. **Polars** is the wrong size. |
| **pytest 9.1.1** | Already the test runner. | Extend the current tests. | No second framework. |
| **ruff 0.16.8** | Stable, 2026-09-16. | Lint and format in CI with no Black/Flake8 pair. | Not required to fix the database bug. |
| **pip-audit 2.10.1** | Already in CI. | Keep the audit step. | Do not add Dependabot config in the same breath as a behavior change. |

Libraries that do not belong: Playwright (only if a real capture is a JS shell, which the current `r.text` scrape contradicts), Scrapy, FastAPI, Polars, APScheduler 4, a cloud call-detail API. This gateway is not a public API.

## 4. Proposed direction

Keep the operator-facing job and the env var names. Change the shape of the program.

**Default architecture**

1. **Runtime.** Python 3.12, as CI already does. Revisit 3.13 only when the host image moves.
2. **Config.** `pydantic-settings` 2.15 on top of the existing `python-dotenv`. Same names: `PAGE_SRC`, `USERNAME`, `USER_PWD`, `SQL_SERVER`, `SQL_NAME`, `SQL_DB`, `SQL_USER`, `SQL_PWD`, `SQL_TRUST`. Add `POLL_SECONDS` (default 30), `STOP_AT` (default `16:30:00`, empty means run until killed), `SQLITE_PATH` (default `calls.sqlite`), and `SQLSERVER_ENABLED` (default true only when the SQL variables are all set). Do not lowercase `USERNAME` until someone confirms the gateway wants that; the smoke test currently requires it, so change the test in the same commit if the lowercasing goes away.
3. **Fetch.** `requests.Session` with a connect/read timeout (5s / 20s is enough on a LAN), `raise_for_status()`, and a small urllib3 retry for 502/503/504 only. Basic auth stays. Do not log the password or the full URL if it embeds credentials.
4. **Parse.** `BeautifulSoup(html, "lxml")`, `find_all("table", class_="main_table")`. Read the second table’s `<tr>/<td>` text into a `CallRecord` (`source`, `destination`, `start_time`, `duration`), all strings, stripped. Ignore the summary table. If a real HDI24201 capture has a different second table, fix the selector from that capture, not from the HDV manual.
5. **Store.** SQLite is the source of truth. Unique key `(source, destination, start_time, duration)`. Each poll inserts only new rows and commits. CSV under `queries/` becomes an export, not the database.
6. **SQL Server.** Optional sink, same unique key, via SQLAlchemy 2.1.1 and the already pinned pyodbc. Parameterized `INSERT`. Commit. On failure, leave SQLite and the export files alone and retry next poll. Keep the column name `Durations`. A live database may already have that spelling; renaming it is a migration, not a cleanup.
7. **Schedule.** A normal loop is enough: poll, upsert, sleep. If `STOP_AT` is set, finish the current poll, export, and exit 0. Do not add APScheduler until there is a second job (for example a monthly purge).
8. **Pandas.** Remove it after `CallRecord` and SQLite cover the smoke cases. Until then, leave the pin.

**Alternatives, if a constraint shows up**

- No SQL Server anymore: skip SQLAlchemy and use `sqlite3` only.
- The live page is not the smoke-test table: stop and adjust the parser to the sanitized capture before writing more storage code.
- Ubuntu 24.04 is replaced by a 3.13/3.14 image: move the CI version in the same change as the host. Do not float the version.

## 5. Phased implementation

Each step should leave `python -m pytest` green on Python 3.12. Update `tests/test_smoke.py` in the same change when a locked behavior is intentionally fixed. Do not commit a real call log or a `.env`.

### Phase 1 — quick wins

The dependency pins, smoke tests, and CI are already done. These steps are the failures those tests do not cover.

1. **Directory setup.** Create `logs/`, `cache/`, and `queries/` with `exist_ok`. Test: start with only `logs/` present and assert the poller function does not raise; start with `queries/<today>` already present and assert a second merge still replaces `query.csv`.
2. **Compare the newest log.** Choose the previous CSV by mtime, not `listdir()[-1]`. Test: two logs, the lexicographically last name is older, and the parser compares against the newer file.
3. **Router errors stay errors.** Timeout on `requests.get`. Non-200 and connection errors must not be parsed as HTML. Test: a stubbed 500 and a stubbed timeout leave `logs/` unchanged and do not call `BeautifulSoup`.
4. **Stop the recursive database connect.** One attempt, return a clear failure, no second call. Test: `connectDB` returning `None` does not recurse (recursion depth stays flat) and does not delete `logs/`.
5. **Parameterized insert and a real commit.** Build the `Phonecalls` statement with placeholders. `commit()` after the batch; `rollback()` on failure. Test: the fake cursor receives a SQL string with `?` (or a bound parameter) and a tuple `('1001', '2002', ...)`; a destination value `O'Brien` is a bound parameter, not a broken string; a cursor that throws on the second row means `delete_files` is not called.
6. **Row count.** Report `len(frame)` inserted attempts, not `len(frame) - 1`. Test: three data rows log 3.
7. **Document the env file.** Add `.env.example` with empty values and the variable names only. No passwords, no real hostnames.

Phase 1 is done when the existing smoke tests, plus the tests above, pass, and a failed database write leaves `logs/` on disk.

### Phase 2 — core

1. **Cell parser.** Replace newline splitting with `<td>` extraction into `CallRecord`. Feed the current `LOG_HTML` fixture and assert the same four columns and two calls. Add a minified one-line table fixture and assert it parses too.
2. **SQLite upsert.** On each poll, insert new records and commit. Test: the same HTML twice inserts two rows total; changing one number inserts exactly one more; restarting against the same file inserts zero.
3. **SQL Server as an export.** Move the pyodbc string behind SQLAlchemy `URL.create` (`mssql+pyodbc`), still using the operator’s `SQL_SERVER` driver string. Insert from SQLite rows that have not been exported; store a watermark or a `exported` flag. Test with a fake engine or a stubbed connection: a second export inserts nothing; a failed export does not mark rows exported and does not delete SQLite.
4. **Configurable loop.** `POLL_SECONDS` and `STOP_AT`. Default `STOP_AT=16:30:00` so today’s behavior stays. Empty `STOP_AT` keeps running. Test: a frozen clock before 16:30 sleeps; a frozen clock at 16:30 exports once and returns; empty `STOP_AT` does not export just because the clock passed 16:30.
5. **Startup config.** Load settings once. Missing `PAGE_SRC` / `USERNAME` / `USER_PWD` fails before the loop. Test: unset `USERNAME` raises a settings error and does not call `requests`.
6. **Logging.** `logging` instead of `print`. Logs may show extension counts and timestamps, not full numbers, once Phase 3 redaction is in; until then, do not log the password. Test: caplog contains the connect failure and does not contain `USER_PWD`.
7. **Drop pandas and numpy** from `requirements.txt` when no production import remains. Test: `pytest` and `pip-audit -r requirements.txt --disable-pip --no-deps` still pass. Keep CI’s unixODBC install.

Phase 2 is done when a repeated poll of one fixture is idempotent in SQLite, and SQL Server failure cannot erase that file.

### Phase 3 — polish

1. **`pyproject.toml`.** Package the modules and add a `phone-parser` console script that runs the loop. Test: `python -m` entry imports without depending on the current working directory for *code* (data paths may still default to cwd, but they must be configurable via `SQLITE_PATH`).
2. **Ruff.** Add `ruff==0.16.8` to `requirements-dev.txt` and a CI step for `ruff check`. Fix only what it flags in files this work touched.
3. **Redaction and retention.** Log the last four digits of a number at most. Keep SQLite; delete CSV exports older than a configurable number of days. Test: a log record of a call to `2101234567` does not contain that full string; a fake old export file is removed and the SQLite row is not.
4. **Service file.** Add an example user systemd unit that runs `phone-parser` with `EnvironmentFile=` and `STOP_AT=` empty. Do not install it from tests.
5. **One sanitized device capture.** The owner saves the Call Records HTML from their own HDI24201, replaces every phone number, and commits that fixture. Adjust the “second main_table” rule if the real page differs. Test: parser output equals the sanitized expected CSV. If the page is a JS shell, stop and revisit httpx-versus-browser; do not add Playwright speculatively.
6. **CI.** Keep Python 3.12 and `pip-audit`. Add the ruff step. Do not add a SQL Server service container.

## 6. Out of scope / risks

- **Secrets.** Router password and SQL password belong in `.env` or the service manager. `.gitignore` already ignores `.env`. Never commit it, a core dump, or CI logs that print `connect()` strings.
- **Personal data.** Call records are personal data. This tool is for the person who administers this gateway. Greek/EU use means GDPR applies to stored numbers. Do not publish live logs, screenshots, or unsanitized HTML.
- **Terms.** Reading the admin page of a gateway you administer, on your LAN, with your own credentials, is the intended use. Do not point `PAGE_SRC` at an ISP portal, a neighbor’s router, or anything that requires bypassing authentication.
- **Dead or mismatched page.** HDI24201 HTML is not in the repo. HDV24201 / HDI34201 manuals are the closest public description and may not match this model’s markup. If the second table is a totals table, Phase 2 will faithfully store the wrong rows until the sanitized capture lands.
- **SQL Server coupling.** The table and the `Durations` column are external. This repo cannot migrate them safely. Driver name comes from `SQL_SERVER`; the smoke test uses `ODBC Driver 17 for SQL Server`, while current Microsoft installs are often Driver 18. Do not hard-code either.
- **Hardware and network.** Useful runs need the gateway reachable at `PAGE_SRC`. CI will never see that device. Basic auth on `http://` crosses the LAN in the clear; prefer the gateway’s HTTPS URL if it has one, without disabling certificate checks.
- **Data loss already in the code.** Uncommitted inserts plus `shutil.rmtree('logs')` can drop the only copy of the day. Phase 1 step 5 is the fix. Do not “clean up” by deleting SQLite on export.
- **Legal/product limits.** No call audio, no handset control, no multi-tenant service, no other router brands, no cloud sync.
- **Dependency churn.** `requirements.txt` was refreshed on 2026-09-30. Do not bump those pins again unless `pip-audit` reports a fix. Do not introduce APScheduler 4, Pandas nightlies, or Python 3.15 pre-releases.

## 7. Success criteria

The modernization worked when all of the following are true:

- `pytest` passes on Python 3.12 in CI, including the Phase 1 failure cases and the Phase 2 idempotency cases.
- `pip-audit` on `requirements.txt` reports no known vulnerabilities.
- Polling the same page twice stores each call once.
- A new row on the page is stored once and survives a process restart.
- A down router or a down SQL Server does not delete local data, does not recurse, and does not insert a partial export marked as done.
- An inserted number that contains a quote is stored as that number.
- The repo contains no `.env`, no live phone numbers, and no unsanitized router HTML.
- On a machine that can see the gateway, one poll’s parsed rows match the Call Records table on screen, using a sanitized fixture committed afterward. That last check is manual and needs the owner’s network. CI does not replace it.
