# Order import feedback

Approved intent: make saved settings, completed scans and failures unmistakable.

- Show Saving, Saved with timestamp, unsaved edits, and persistent save errors.
- Preserve a scan result separately from transient browser-refresh messages: completion time, checked, imported, already present, ready (preview), review and failed counts. A preview must never claim orders were imported.
- Show Scan in progress and a live next-scan countdown using the server's actual completion-based five-minute schedule. Disabled imports show Automatic import off; sign-in expiry must not show a countdown.
- Refresh displayed order results after completion without losing unsaved settings or restarting the embedded browser.
- Clear displayed results hides results only; never delete imported-order identities, claims or duplicate protection.

Approach: extend the existing status endpoint and polling UI with persisted run summaries, rather than replacing the application or adding a separate monitor. Keep existing import eligibility and scheduling unchanged.
