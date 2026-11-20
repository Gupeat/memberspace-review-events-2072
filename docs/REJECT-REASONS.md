# Reject-reason dictionary

The dictionary is global (org_id = all-zero) and seeded by migration
`0001_ai_review_events`. Application code treats it as read-only; adding a code
is a new migration, not an admin write.

| Sort | Code | 中文 | English | Requires note |
| --- | --- | --- | --- | --- |
| 10 | factual_error | 事实错误 | Factual error | no |
| 20 | off_tone | 语气不符 | Off tone | no |
| 30 | missing_info | 信息缺失 | Missing information | no |
| 40 | policy_violation | 违反规范 | Policy violation | no |
| 50 | duplicate | 重复 | Duplicate | no |
| 60 | not_needed | 不需要 | Not needed | no |
| 70 | other | 其他 | Other | yes |

Rules:

- `other` requires a non-empty `reject_reason_note` of at most 500 characters.
- Every other code keeps `reject_reason_note` null; the combination is
  enforced by CHECK constraints.
- A code may be deactivated by setting `active = false`; existing events keep
  their historical code, and new submissions with that code are rejected with
  `REJECT_REASON_INVALID`.
- The migration seed is deterministic, so a fresh database always gets the
  same seven rows and UUIDs.

Adding a code:

1. Add it to `app/eval/constants.py` and the model CHECK list.
2. Add a migration that drops and recreates the CHECK constraint and inserts
   the row.
3. Add the label to this table and a test for the new active code.
