package harness

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func writeFixture(t *testing.T, root string, tasks TasksFile, config Config) {
	t.Helper()
	if err := os.MkdirAll(filepath.Join(root, "src"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "src", "input.txt"), []byte("v1\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := saveJSON(root, stateFile, tasks); err != nil {
		t.Fatal(err)
	}
	if err := saveJSON(root, configFile, config); err != nil {
		t.Fatal(err)
	}
}

func fixtureConfig() Config {
	return Config{
		SchemaVersion:    1,
		FingerprintPaths: []string{"src"},
		Checks: []Check{
			{ID: "pass", Argv: []string{"/bin/sh", "-c", "exit 0"}, CWD: ".", TimeoutSeconds: 2, Required: true},
			{ID: "fail", Argv: []string{"/bin/sh", "-c", "exit 7"}, CWD: ".", TimeoutSeconds: 2, Required: true},
		},
		Delivery: Delivery{Provider: "fixture", DefaultBranch: "main", RequirePR: true},
	}
}

func fixtureTasks() TasksFile {
	return TasksFile{
		SchemaVersion: 1,
		NextID:        3,
		Tasks: []Task{
			{ID: "F001", Behavior: "first", Acceptance: []string{"first passes"}, State: "not_started", Verification: []string{"pass"}},
			{ID: "F002", Behavior: "second", Acceptance: []string{"second fails cleanly"}, DependsOn: []string{"F001"}, State: "not_started", Verification: []string{"fail"}},
		},
	}
}

func invoke(t *testing.T, root string, args ...string) (int, map[string]interface{}) {
	t.Helper()
	var out, errOut bytes.Buffer
	code := Main(append([]string{"--root", root}, args...), &out, &errOut)
	var result map[string]interface{}
	if err := json.Unmarshal(out.Bytes(), &result); err != nil {
		t.Fatalf("invalid JSON (exit %d, stderr %q): %v; output=%q", code, errOut.String(), err, out.String())
	}
	return code, result
}

func TestValidationRejectsMalformedDuplicateAndCycle(t *testing.T) {
	root := t.TempDir()
	writeFixture(t, root, fixtureTasks(), fixtureConfig())
	if err := os.WriteFile(filepath.Join(root, "docs/tasks.json"), []byte("{invalid"), 0o644); err != nil {
		t.Fatal(err)
	}
	code, result := invoke(t, root, "validate")
	if code == 0 || result["ok"] != false {
		t.Fatalf("malformed state accepted: code=%d result=%v", code, result)
	}
	writeFixture(t, root, fixtureTasks(), fixtureConfig())
	var tasks TasksFile
	if err := loadJSON(root, stateFile, &tasks); err != nil {
		t.Fatal(err)
	}
	tasks.Tasks = append(tasks.Tasks, tasks.Tasks[0])
	if err := saveJSON(root, stateFile, tasks); err != nil {
		t.Fatal(err)
	}
	code, _ = invoke(t, root, "validate")
	if code == 0 {
		t.Fatal("duplicate ID accepted")
	}
	tasks.Tasks = fixtureTasks().Tasks
	tasks.Tasks[0].DependsOn = []string{"F002"}
	if err := saveJSON(root, stateFile, tasks); err != nil {
		t.Fatal(err)
	}
	code, _ = invoke(t, root, "validate")
	if code == 0 {
		t.Fatal("dependency cycle accepted")
	}
}

func TestTransitionsFailedChecksFreshnessAndHandoff(t *testing.T) {
	root := t.TempDir()
	writeFixture(t, root, fixtureTasks(), fixtureConfig())
	if code, _ := invoke(t, root, "validate"); code != 0 {
		t.Fatalf("valid fixture rejected: %d", code)
	}
	if code, _ := invoke(t, root, "transition", "F001", "active"); code != 0 {
		t.Fatalf("activation failed: %d", code)
	}
	if code, _ := invoke(t, root, "transition", "F001", "verified"); code == 0 {
		t.Fatal("direct verified transition accepted")
	}
	if code, result := invoke(t, root, "verify", "F001"); code != 0 || result["ok"] != true {
		t.Fatalf("passing verification failed: code=%d result=%v", code, result)
	}
	if code, _ := invoke(t, root, "transition", "F002", "active"); code != 0 {
		t.Fatalf("dependent activation failed: %d", code)
	}
	if code, result := invoke(t, root, "verify", "F002"); code != 1 || result["ok"] != false {
		t.Fatalf("failed check did not fail cleanly: code=%d result=%v", code, result)
	}
	var tasks TasksFile
	if err := loadJSON(root, stateFile, &tasks); err != nil {
		t.Fatal(err)
	}
	if tasks.Tasks[1].State != "active" || tasks.Tasks[1].Evidence == nil || tasks.Tasks[1].Evidence.Status != "failed" {
		t.Fatalf("failed evidence/state not retained: %+v", tasks.Tasks[1])
	}
	if err := os.WriteFile(filepath.Join(root, "src", "input.txt"), []byte("changed\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, context := invoke(t, root, "context")
	if context["fresh"] != false {
		t.Fatalf("source mutation did not invalidate freshness: %v", context)
	}
	handoff := Handoff{SchemaVersion: 1, Decisions: []string{"keep native"}, Rejected: []string{"node shim"}, Blockers: []string{"failed check"}, NextAction: "fix check", TaskID: "F002"}
	if err := saveJSON(root, handoffFile, handoff); err != nil {
		t.Fatal(err)
	}
	if code, result := invoke(t, root, "handoff"); code != 0 || result["ok"] != true {
		t.Fatalf("handoff failed: code=%d result=%v", code, result)
	}
	var saved Handoff
	if err := loadJSON(root, handoffFile, &saved); err != nil {
		t.Fatal(err)
	}
	if len(saved.Decisions) != 1 || saved.Decisions[0] != "keep native" || saved.NextAction != "fix check" {
		t.Fatalf("handoff prose was not preserved: %+v", saved)
	}
}
