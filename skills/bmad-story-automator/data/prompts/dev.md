Execute the BMAD dev-story workflow for story {{story_id}}.

{{skill_line}}{{workflow_line}}{{instructions_line}}{{checklist_line}}Story file: `{{implementation_artifacts}}/{{story_prefix}}-*.md`
Implement all tasks marked [ ]. Run tests. Update checkboxes.
Emit a JUnit XML report from the test run if the runner supports it, and always
print the full test summary (total / failures / errors / skipped). Do NOT
transcribe test counts into the story prose — the orchestrator records them in a
machine-owned section from the JUnit report.
