# Verilator lint policy and waivers

Upload a project file named `chipsutra.lint.json`. ChipSutra applies it after
Verilator lint and stores the active/waived/blocking report on the simulation.

```json
{
  "fail_on_warning": false,
  "fatal_warnings": ["WIDTH", "CASEINCOMPLETE"],
  "waivers": [
    {
      "code": "UNUSED",
      "file_glob": "rtl/*.sv",
      "line": null,
      "message_contains": "Signal is not used",
      "reason": "Reserved CSR bit for the next revision",
      "owner": "dv-team"
    }
  ]
}
```

Waivers require `reason` and `owner`. Matching supports warning-code and file
globs, optional exact line, and optional message substring.

This is a governance layer over Verilator—not a Spyglass rule-deck replacement.
