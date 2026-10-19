# Safety

Each rule, where it's enforced, and the test that covers it.

| Rule | Enforced in | Test |
|---|---|---|
| Never permanently delete | `actions.recycle` uses send2trash only | `test_core_never_calls_permanent_delete`, `test_only_actions_deletes_and_only_via_send2trash` |
| No silent permanent delete by Windows | `actions.recycle_bin_problem`. The drive must be DRIVE_FIXED. Refused when the `NoRecycleFiles` policy or the volume's `NukeOnDelete` is set, or when the file is bigger than the volume's `MaxCapacity` (HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume\{guid}). Assumes 5% of the drive if no value is set. | `test_bin_check_refuses_files_bigger_than_the_bin`, `test_files_windows_would_delete_for_good_are_refused` |
| Never follow symlinks or junctions | `scan._is_link` (`is_symlink()` or `is_junction()`) | `test_scan_never_follows_junctions`, `test_scan_never_follows_symlinks` |
| Protected paths refused | `rules.Guard`: trees from env vars; exact matches for the profile root and C:\Users; the names AppData, $Recycle.Bin and System Volume Information anywhere; top-level Windows, ProgramData and Program Files*; drive roots. Checked on the picked folder, on every subfolder during the scan, and on every file before an action (both as given and with links resolved). | `test_guard_rules`, `test_real_protected_paths_are_refused`, `test_protected_paths_are_refused` |
| Skip files changed since the scan | `actions.stale_reason` compares size and `st_mtime_ns` | `test_stale_files_are_skipped_and_reported`, `test_same_size_but_touched_file_is_stale` |
| Moves never overwrite | `actions.unique_path` plus `os.rename`, which fails on Windows if the target exists. Never `shutil.move`, which can copy and then delete. | `test_move_never_overwrites_and_undo_puts_files_back`, `test_plan_by_type_resolves_name_clashes` |
| Undo never overwrites | `actions.undo` skips a file if its original spot is taken or the file changed | `test_undo_never_overwrites_a_new_file` |
| Keep at least one copy | `dupes.can_mark` (UI) and `dupes.selected_for_removal` (raises) | `test_must_keep_at_least_one_copy` |
| Confirm every batch | `widgets.confirm` before recycle and move; undo also confirms | manual, plus `scripts/screenshots.py` |
| One bad file never crashes the job | Every per-file OS call is wrapped; reasons come from `errors.friendly_os_error` | `test_scan_counts_unreadable_folders`, `test_unreadable_file_is_counted_not_fatal`, `test_trash_failure_is_reported_not_raised` |

`os.rmdir` is used once, in undo, to remove folders that a move batch created. It only succeeds on empty folders.

Recycle batches can't be undone automatically. The Recycle Bin's own Restore is the reliable way, so the UI points there and has an "Open Recycle Bin" button.
