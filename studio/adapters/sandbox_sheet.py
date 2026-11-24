"""Adapter for the bundled Studio Sandbox Sheet test application.

The sandbox is a self-contained local HTML spreadsheet with synthetic data. It
exists to prove the complete pipeline in a reproducible, isolated environment
with no accounts, network access or private data.
"""
from __future__ import annotations

import json
import platform
from pathlib import Path

from ..contracts import Check, EnvironmentRecord, Source, StepSpec, WorkflowSpec
from .base import AppAdapter

SANDBOX_FILE = Path(__file__).resolve().parent.parent / "sandbox" / "sheet.html"

SOURCES = [
    Source(
        id="sandbox-manual",
        title="Studio Sandbox Sheet behaviour (bundled test application source)",
        url="studio/sandbox/sheet.html",
        kind="bundled_test_app",
        note="The sandbox's own source code is the authoritative reference for its behaviour.",
    ),
]

REMOVE_DUPLICATES = WorkflowSpec(
    id="sandbox-sheet.remove-duplicates",
    app_id="sandbox-sheet",
    title="How to Remove Duplicate Rows from a Spreadsheet",
    summary="Select a data range, open Data > Remove duplicates, confirm the header setting and remove exact duplicate rows.",
    prerequisites=[
        "A sheet containing a data range with a header row.",
        "Know which columns define a duplicate (here: all columns).",
    ],
    sources=SOURCES,
    verification="After execution the sheet must contain no duplicate rows, the row count must equal the independently "
                 "computed number of unique rows, and the confirmation message must report the same counts.",
    intro="In this tutorial you'll learn how to remove duplicate rows from a spreadsheet. "
          "Here is a customer list with {initial_rows} data rows, and some customers appear more than once.",
    outro="And that's it. The list went from {initial_rows} rows to {final_rows} unique rows, "
          "with {removed} duplicates removed. You can use the same steps on any list with a header row.",
    steps=[
        StepSpec(id="select-range", title="Select the data range", action="click", selector="#select-all",
                 expected="The whole data range is selected.", expect_selector=".sheet.selected",
                 narration="First, select the data. Click the corner of the sheet to select the whole range.",
                 beginner_note="Selecting the range tells the app which cells to check.",
                 source_ids=["sandbox-manual"]),
        StepSpec(id="open-data-menu", title="Open the Data menu", action="click", selector="#data-menu",
                 expected="The Data menu is open.", expect_selector="#menu-remove-duplicates",
                 narration="Next, open the Data menu in the menu bar.", zoom=True, source_ids=["sandbox-manual"]),
        StepSpec(id="choose-remove-duplicates", title="Choose Remove duplicates", action="click",
                 selector="#menu-remove-duplicates", expected="The Remove duplicates dialog opens.",
                 expect_selector="#dlg-remove.show",
                 narration="Choose Remove duplicates.", zoom=True, source_ids=["sandbox-manual"]),
        StepSpec(id="confirm-header", title="Confirm the header row setting", action="check", selector="#has-header",
                 expected="'Data has header row' is checked.", expect_selector="#has-header:checked",
                 narration="Because the first row contains column names, make sure Data has header row is checked. "
                           "All {columns} columns are selected, so a row only counts as a duplicate if every value matches.",
                 beginner_note="If you leave this unchecked, the header row is treated like ordinary data.",
                 zoom=True, pause_after_ms=1800, source_ids=["sandbox-manual"]),
        StepSpec(id="run-remove", title="Remove the duplicates", action="click", selector="#dlg-confirm",
                 expected="A confirmation reports how many rows were removed.", expect_selector="#dlg-result.show",
                 narration="Now click Remove duplicates. The app reports that {removed} duplicate rows were removed "
                           "and {final_rows} unique rows remain.", pause_after_ms=2200, source_ids=["sandbox-manual"]),
        StepSpec(id="close-result", title="Close the confirmation", action="click", selector="#result-ok",
                 expected="The confirmation closes and the cleaned list is visible.", expect_selector="#rows",
                 narration="Click OK to return to the sheet, where each customer now appears only once.",
                 pause_after_ms=2000, source_ids=["sandbox-manual"]),
    ],
)


def _dedupe(rows: list[list[str]]) -> list[list[str]]:
    seen, out = set(), []
    for r in rows:
        key = tuple(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


class SandboxSheetAdapter(AppAdapter):
    app_id = "sandbox-sheet"
    automation = "playwright"

    def workflows(self) -> dict[str, WorkflowSpec]:
        return {REMOVE_DUPLICATES.id: REMOVE_DUPLICATES}

    def environment_url(self) -> str:
        return SANDBOX_FILE.as_uri()

    def wait_ready(self, page) -> None:
        page.wait_for_function("() => window.sandboxSheet && document.querySelectorAll('#rows tr').length > 0", timeout=10000)

    def detect_environment(self, page, browser) -> EnvironmentRecord:
        meta = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('meta[name^="app-"]')]
                               .map(m => [m.name, m.content]))""")
        return EnvironmentRecord(
            app_name=meta.get("app-name", "Studio Sandbox Sheet"),
            app_edition=meta.get("app-edition"),
            app_version=meta.get("app-version"),
            app_build=meta.get("app-build"),
            os=f"{platform.system()} {platform.release()}",
            platform=f"Web (local file) via {browser.browser_type.name}",
            browser_name=browser.browser_type.name,
            browser_version=browser.version,
            observed_ui_state=f"Title '{page.title()}'; menu bar: "
                              + ", ".join(page.locator(".menubar .menu > button").all_inner_texts()),
        )

    def observe_before(self, page, workflow: WorkflowSpec) -> dict:
        rows = page.evaluate("() => window.sandboxSheet.getRows()")
        header, body = rows[0], rows[1:]
        unique = _dedupe(body)
        return {
            "initial_table": rows,
            "initial_rows": len(body),
            "columns": len(header),
            "expected_final_rows": len(unique),
            "expected_removed": len(body) - len(unique),
        }

    def verify(self, page, workflow: WorkflowSpec, observations: dict) -> list[Check]:
        rows = page.evaluate("() => window.sandboxSheet.getRows()")
        header, body = rows[0], rows[1:]
        initial = observations["initial_table"]
        expected = _dedupe(initial[1:])
        observations.update(final_table=rows, final_rows=len(body), removed=observations["initial_rows"] - len(body))
        result_text = page.locator("#result-text").inner_text()
        observations["result_message"] = result_text
        tuples = [tuple(r) for r in body]
        return [
            Check(name="Header row preserved", passed=header == initial[0], detail=json.dumps(header)),
            Check(name="No duplicate rows remain", passed=len(tuples) == len(set(tuples)),
                  detail=f"{len(tuples)} rows, {len(set(tuples))} distinct"),
            Check(name="Unique rows match independent computation", passed=body == expected,
                  detail=f"expected {len(expected)} rows, observed {len(body)}"),
            Check(name="Confirmation message matches observed counts",
                  passed=result_text == f"{observations['expected_removed']} duplicate rows found and removed. "
                                        f"{len(expected)} unique rows remain.",
                  detail=result_text),
        ]
