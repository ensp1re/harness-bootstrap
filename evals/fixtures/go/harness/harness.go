package harness

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	schemaVersion = 1
	stateFile     = "docs/harness/tasks.json"
	configFile    = "docs/harness/config.json"
	handoffFile   = "docs/harness/handoff.json"
)

type Check struct {
	ID             string   `json:"id"`
	Argv           []string `json:"argv"`
	CWD            string   `json:"cwd"`
	TimeoutSeconds int      `json:"timeoutSeconds"`
	Required       bool     `json:"required"`
}

type Delivery struct {
	Provider      string `json:"provider"`
	DefaultBranch string `json:"defaultBranch"`
	RequirePR     bool   `json:"requirePR"`
}

type Config struct {
	SchemaVersion    int      `json:"schemaVersion"`
	Checks           []Check  `json:"checks"`
	FingerprintPaths []string `json:"fingerprintPaths"`
	Delivery         Delivery `json:"delivery"`
}

type TasksFile struct {
	SchemaVersion int    `json:"schemaVersion"`
	NextID        int    `json:"nextId"`
	Tasks         []Task `json:"tasks"`
}

type Task struct {
	ID            string      `json:"id"`
	Behavior      string      `json:"behavior"`
	Acceptance    []string    `json:"acceptance"`
	DependsOn     []string    `json:"dependsOn"`
	State         string      `json:"state"`
	Spec          interface{} `json:"spec"`
	Plan          interface{} `json:"plan"`
	Verification  []string    `json:"verification"`
	BlockedReason string      `json:"blockedReason"`
	Evidence      *Evidence   `json:"evidence"`
	Delivery      interface{} `json:"delivery"`
}

type Evidence struct {
	AttemptID         string         `json:"attemptId"`
	Status            string         `json:"status"`
	StartedAt         string         `json:"startedAt"`
	CompletedAt       string         `json:"completedAt"`
	Checks            []CheckOutcome `json:"checks"`
	FingerprintBefore string         `json:"fingerprintBefore"`
	FingerprintAfter  string         `json:"fingerprintAfter"`
	Fresh             bool           `json:"fresh"`
}

type CheckOutcome struct {
	ID          string `json:"id"`
	Status      string `json:"status"`
	ExitCode    int    `json:"exitCode"`
	Error       string `json:"error,omitempty"`
	TimedOut    bool   `json:"timedOut,omitempty"`
	Interrupted bool   `json:"interrupted,omitempty"`
}

type Handoff struct {
	SchemaVersion int      `json:"schemaVersion"`
	TaskID        string   `json:"taskId"`
	Revision      string   `json:"revision"`
	Branch        string   `json:"branch"`
	Dirty         bool     `json:"dirty"`
	EvidenceFresh bool     `json:"evidenceFresh"`
	Decisions     []string `json:"decisions"`
	Rejected      []string `json:"rejectedApproaches"`
	Blockers      []string `json:"blockers"`
	NextAction    string   `json:"nextAction"`
	UpdatedAt     string   `json:"updatedAt"`
}

var (
	idPattern = regexp.MustCompile(`^F[0-9]{3,}$`)
	stateMu   sync.Mutex
)

// Main is the native command entrypoint used by the fixture binary.
func Main(args []string, stdout, stderr io.Writer) int {
	root, command, commandArgs, err := parseArgs(args)
	if err != nil {
		writeJSON(stdout, map[string]interface{}{"ok": false, "error": err.Error()})
		return 2
	}
	var result interface{}
	var code int
	switch command {
	case "context":
		result, err = contextCommand(root)
	case "tasks":
		result, err = tasksCommand(root)
	case "validate":
		result, err = validateCommand(root)
	case "verify":
		if len(commandArgs) != 1 {
			err = errors.New("verify requires a task ID")
		} else {
			result, code, err = verifyCommand(root, commandArgs[0])
		}
	case "handoff":
		if len(commandArgs) != 0 {
			err = errors.New("handoff takes no arguments")
		} else {
			result, err = handoffCommand(root)
		}
	case "archive":
		if len(commandArgs) != 0 {
			err = errors.New("archive takes no arguments")
		} else {
			result, err = archiveCommand(root)
		}
	case "transition":
		result, code, err = transitionCommand(root, commandArgs)
	default:
		err = fmt.Errorf("unsupported command %q", command)
	}
	if err != nil {
		if result == nil {
			result = map[string]interface{}{"ok": false, "error": err.Error()}
		} else if object, ok := result.(map[string]interface{}); ok && object != nil {
			if _, exists := object["error"]; !exists {
				object["error"] = err.Error()
			}
		}
		writeJSON(stdout, result)
		if code == 0 {
			code = 1
		}
		return code
	}
	if result == nil {
		result = map[string]interface{}{"ok": true}
	}
	writeJSON(stdout, result)
	return code
}

func parseArgs(args []string) (string, string, []string, error) {
	if len(args) < 3 || args[0] != "--root" {
		return "", "", nil, errors.New("usage: --root PATH COMMAND [arguments]")
	}
	root, err := filepath.Abs(args[1])
	if err != nil {
		return "", "", nil, fmt.Errorf("invalid root: %w", err)
	}
	if info, statErr := os.Stat(root); statErr != nil || !info.IsDir() {
		return "", "", nil, fmt.Errorf("root is not a directory: %s", root)
	}
	return root, args[2], args[3:], nil
}

func writeJSON(w io.Writer, value interface{}) {
	_ = json.NewEncoder(w).Encode(value)
}

func loadJSON(root, rel string, target interface{}) error {
	path, err := safePath(root, rel)
	if err != nil {
		return err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("read %s: %w", rel, err)
	}
	if err := json.Unmarshal(data, target); err != nil {
		return fmt.Errorf("malformed %s: %w", rel, err)
	}
	return nil
}

func saveJSON(root, rel string, value interface{}) error {
	path, err := safePath(root, rel)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	tmp, err := os.CreateTemp(filepath.Dir(path), ".harness-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if err := tmp.Chmod(0o644); err != nil {
		_ = tmp.Close()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmpName, path)
}

func safePath(root, rel string) (string, error) {
	if filepath.IsAbs(rel) {
		return "", fmt.Errorf("absolute path is not allowed: %s", rel)
	}
	clean := filepath.Clean(rel)
	if clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("path escapes root: %s", rel)
	}
	rootAbs, _ := filepath.Abs(root)
	if resolvedRoot, err := filepath.EvalSymlinks(rootAbs); err == nil {
		rootAbs = resolvedRoot
	}
	path := filepath.Join(rootAbs, clean)
	resolved, err := filepath.EvalSymlinks(filepath.Dir(path))
	if err == nil {
		path = filepath.Join(resolved, filepath.Base(path))
	}
	if !within(rootAbs, path) {
		return "", fmt.Errorf("path escapes root: %s", rel)
	}
	return path, nil
}

func within(root, path string) bool {
	rel, err := filepath.Rel(root, path)
	return err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}

func loadState(root string) (TasksFile, Config, error) {
	var tasks TasksFile
	var config Config
	if err := loadJSON(root, stateFile, &tasks); err != nil {
		return tasks, config, err
	}
	if err := loadJSON(root, configFile, &config); err != nil {
		return tasks, config, err
	}
	return tasks, config, nil
}

func validateCommand(root string) (map[string]interface{}, error) {
	tasks, config, err := loadState(root)
	if err != nil {
		return map[string]interface{}{"ok": false, "errors": []string{err.Error()}}, err
	}
	errs := validateConfig(config)
	errs = append(errs, validateTasks(root, tasks, config)...)
	fresh := true
	for _, task := range tasks.Tasks {
		if task.Evidence != nil && task.Evidence.Status == "passed" {
			current, fpErr := fingerprint(root, config.FingerprintPaths)
			if fpErr != nil || current != task.Evidence.FingerprintAfter {
				fresh = false
			}
		}
	}
	if len(errs) > 0 {
		return map[string]interface{}{"ok": false, "errors": errs, "fresh": fresh}, fmt.Errorf("validation failed")
	}
	return map[string]interface{}{"ok": true, "errors": []string{}, "fresh": fresh}, nil
}

func validateConfig(config Config) []string {
	var errs []string
	if config.SchemaVersion != schemaVersion {
		errs = append(errs, fmt.Sprintf("unsupported config schemaVersion %d", config.SchemaVersion))
	}
	seen := map[string]bool{}
	for i, check := range config.Checks {
		if check.ID == "" {
			errs = append(errs, fmt.Sprintf("checks[%d] has empty id", i))
		} else if seen[check.ID] {
			errs = append(errs, "duplicate check id: "+check.ID)
		}
		seen[check.ID] = true
		if len(check.Argv) == 0 {
			errs = append(errs, "check "+check.ID+" has empty argv")
		}
		if check.CWD != "" {
			if _, err := safeRelative(check.CWD); err != nil {
				errs = append(errs, "check "+check.ID+" cwd: "+err.Error())
			}
		}
		if check.TimeoutSeconds <= 0 {
			errs = append(errs, "check "+check.ID+" timeoutSeconds must be positive")
		}
	}
	for _, path := range config.FingerprintPaths {
		if _, err := safeRelative(path); err != nil {
			errs = append(errs, "fingerprint path: "+err.Error())
		}
	}
	return errs
}

func validateTasks(root string, tasks TasksFile, config Config) []string {
	var errs []string
	if tasks.SchemaVersion != schemaVersion {
		errs = append(errs, fmt.Sprintf("unsupported tasks schemaVersion %d", tasks.SchemaVersion))
	}
	if tasks.NextID < 1 {
		errs = append(errs, "nextId must be positive")
	}
	ids := map[string]bool{}
	max := 0
	states := map[string]string{}
	checkIDs := map[string]bool{}
	for _, check := range config.Checks {
		checkIDs[check.ID] = true
	}
	active := 0
	for i, task := range tasks.Tasks {
		if !idPattern.MatchString(task.ID) {
			errs = append(errs, fmt.Sprintf("tasks[%d] has invalid id %q", i, task.ID))
		}
		if ids[task.ID] {
			errs = append(errs, "duplicate task id: "+task.ID)
		}
		ids[task.ID] = true
		if n, parseErr := strconv.Atoi(strings.TrimPrefix(task.ID, "F")); parseErr == nil && n >= max {
			max = n
		}
		if task.Behavior == "" {
			errs = append(errs, task.ID+" behavior is empty")
		}
		if len(task.Acceptance) == 0 {
			errs = append(errs, task.ID+" acceptance is empty")
		}
		switch task.State {
		case "not_started", "active", "blocked", "verified", "passing":
		default:
			errs = append(errs, task.ID+" has invalid state "+task.State)
		}
		if task.State == "active" {
			active++
		}
		if task.State == "blocked" && strings.TrimSpace(task.BlockedReason) == "" {
			errs = append(errs, task.ID+" blocked task needs blockedReason")
		}
		if task.Evidence != nil && task.Evidence.Status == "passed" && task.State != "verified" && task.State != "passing" {
			errs = append(errs, task.ID+" has passed evidence in state "+task.State)
		}
		states[task.ID] = task.State
		for _, checkID := range task.Verification {
			if !checkIDs[checkID] {
				errs = append(errs, task.ID+" references unknown check "+checkID)
			}
		}
	}
	if tasks.NextID <= max {
		errs = append(errs, fmt.Sprintf("nextId %d must be greater than allocated id %d", tasks.NextID, max))
	}
	if active > 1 {
		errs = append(errs, "more than one active task")
	}
	for _, task := range tasks.Tasks {
		for _, dependency := range task.DependsOn {
			if !ids[dependency] {
				if archiveExists(root, dependency) {
					continue
				}
				errs = append(errs, task.ID+" references missing dependency "+dependency)
			}
		}
	}
	if cycle := dependencyCycle(tasks.Tasks); cycle != "" {
		errs = append(errs, "dependency cycle: "+cycle)
	}
	return errs
}

func safeRelative(path string) (string, error) {
	if filepath.IsAbs(path) {
		return "", errors.New("absolute path is not allowed")
	}
	clean := filepath.Clean(path)
	if clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", errors.New("path escapes root")
	}
	return clean, nil
}

func dependencyCycle(tasks []Task) string {
	byID := map[string]Task{}
	for _, task := range tasks {
		byID[task.ID] = task
	}
	visiting := map[string]bool{}
	done := map[string]bool{}
	var visit func(string) string
	visit = func(id string) string {
		if visiting[id] {
			return id
		}
		if done[id] {
			return ""
		}
		visiting[id] = true
		for _, dep := range byID[id].DependsOn {
			if _, ok := byID[dep]; !ok {
				continue
			}
			if result := visit(dep); result != "" {
				return result
			}
		}
		delete(visiting, id)
		done[id] = true
		return ""
	}
	for _, task := range tasks {
		if result := visit(task.ID); result != "" {
			return result
		}
	}
	return ""
}

func archiveExists(root, id string) bool {
	path, err := safePath(root, filepath.Join("docs/harness/archive", id+".json"))
	if err != nil {
		return false
	}
	_, err = os.Stat(path)
	return err == nil
}

func contextCommand(root string) (map[string]interface{}, error) {
	tasks, config, err := loadState(root)
	if err != nil {
		return nil, err
	}
	validation := append([]string{}, validateConfig(config)...)
	validation = append(validation, validateTasks(root, tasks, config)...)
	active := ""
	blockers := []string{}
	for _, task := range tasks.Tasks {
		if task.State == "active" {
			active = task.ID
		}
		if task.State == "blocked" {
			blockers = append(blockers, task.ID+": "+task.BlockedReason)
		}
	}
	ready := readyIDs(root, tasks)
	fresh := true
	for _, task := range tasks.Tasks {
		if task.Evidence != nil && task.Evidence.Status == "passed" {
			fp, fpErr := fingerprint(root, config.FingerprintPaths)
			if fpErr != nil || fp != task.Evidence.FingerprintAfter {
				fresh = false
			}
		}
	}
	result := map[string]interface{}{
		"schemaVersion":    1,
		"activeTask":       active,
		"readyTaskIDs":     ready,
		"blockers":         blockers,
		"fresh":            fresh,
		"nextAction":       readyAction(active, ready),
		"validationErrors": validation,
	}
	if branch, revision, dirty := gitFacts(root); branch != "" || revision != "" {
		result["branch"] = branch
		result["revision"] = revision
		result["dirty"] = dirty
	}
	return result, nil
}

func tasksCommand(root string) (map[string]interface{}, error) {
	tasks, config, err := loadState(root)
	if err != nil {
		return nil, err
	}
	if errs := append(validateConfig(config), validateTasks(root, tasks, config)...); len(errs) > 0 {
		return map[string]interface{}{"ok": false, "errors": errs}, fmt.Errorf("invalid state")
	}
	return map[string]interface{}{"schemaVersion": tasks.SchemaVersion, "nextId": tasks.NextID, "tasks": tasks.Tasks, "readyTaskIDs": readyIDs(root, tasks)}, nil
}

func readyIDs(root string, tasks TasksFile) []string {
	states := map[string]string{}
	for _, task := range tasks.Tasks {
		states[task.ID] = task.State
	}
	ready := []string{}
	for _, task := range tasks.Tasks {
		if task.State != "not_started" {
			continue
		}
		ok := true
		for _, dep := range task.DependsOn {
			state, found := states[dep]
			if found {
				if state != "passing" && state != "verified" {
					ok = false
				}
			} else if !archiveExists(root, dep) {
				ok = false
			}
		}
		if ok {
			ready = append(ready, task.ID)
		}
	}
	sort.Slice(ready, func(i, j int) bool { return numericID(ready[i]) < numericID(ready[j]) })
	return ready
}

func numericID(id string) int {
	n, _ := strconv.Atoi(strings.TrimPrefix(id, "F"))
	return n
}

func readyAction(active string, ready []string) string {
	if active != "" {
		return "verify " + active
	}
	if len(ready) > 0 {
		return "transition " + ready[0] + " active"
	}
	return "resolve blockers or queue product work"
}

func transitionCommand(root string, args []string) (map[string]interface{}, int, error) {
	if len(args) < 2 {
		return nil, 2, errors.New("transition requires ID STATE")
	}
	id, target := args[0], args[1]
	reason := ""
	for i := 2; i < len(args); i++ {
		if args[i] == "--reason" && i+1 < len(args) {
			reason = strings.TrimSpace(args[i+1])
			i++
		} else {
			return nil, 2, errors.New("unknown transition argument")
		}
	}
	stateMu.Lock()
	defer stateMu.Unlock()
	tasks, config, err := loadState(root)
	if err != nil {
		return nil, 2, err
	}
	if errs := append(validateConfig(config), validateTasks(root, tasks, config)...); len(errs) > 0 {
		return map[string]interface{}{"ok": false, "errors": errs}, 2, errors.New("invalid state")
	}
	index := -1
	for i := range tasks.Tasks {
		if tasks.Tasks[i].ID == id {
			index = i
			break
		}
	}
	if index < 0 {
		return nil, 2, fmt.Errorf("unknown task %s", id)
	}
	from := tasks.Tasks[index].State
	if target == "blocked" && reason == "" {
		return nil, 2, errors.New("blocked transition requires --reason")
	}
	if !legalTransition(from, target) {
		return map[string]interface{}{"ok": false, "error": fmt.Sprintf("illegal transition %s -> %s", from, target)}, 1, fmt.Errorf("illegal transition %s -> %s", from, target)
	}
	if target == "active" {
		if len(activeIDs(tasks)) > 0 {
			return map[string]interface{}{"ok": false, "error": "only one active task is allowed"}, 1, errors.New("WIP limit")
		}
		if !dependenciesSatisfied(root, tasks.Tasks[index]) {
			return map[string]interface{}{"ok": false, "error": "dependencies are not passing"}, 1, errors.New("unsatisfied dependencies")
		}
	}
	if target == "verified" {
		return nil, 2, errors.New("active -> verified requires verify command")
	}
	if target == "passing" {
		return nil, 2, errors.New("delivery integration is unavailable in fixture")
	}
	tasks.Tasks[index].State = target
	if target == "blocked" {
		tasks.Tasks[index].BlockedReason = reason
	} else {
		tasks.Tasks[index].BlockedReason = ""
	}
	if err := saveJSON(root, stateFile, tasks); err != nil {
		return nil, 1, err
	}
	return map[string]interface{}{"ok": true, "id": id, "from": from, "to": target}, 0, nil
}

func legalTransition(from, to string) bool {
	switch from {
	case "not_started":
		return to == "active"
	case "active":
		return to == "blocked" || to == "verified"
	case "blocked":
		return to == "active"
	case "verified":
		return to == "active" || to == "passing"
	default:
		return false
	}
}

func activeIDs(tasks TasksFile) []string {
	ids := []string{}
	for _, task := range tasks.Tasks {
		if task.State == "active" {
			ids = append(ids, task.ID)
		}
	}
	return ids
}

func dependenciesSatisfied(root string, task Task) bool {
	for _, dep := range task.DependsOn {
		found := false
		var tasks TasksFile
		if loadJSON(root, stateFile, &tasks) == nil {
			for _, candidate := range tasks.Tasks {
				if candidate.ID == dep {
					found = candidate.State == "passing" || candidate.State == "verified"
				}
			}
		}
		if !found && !archiveExists(root, dep) {
			return false
		}
	}
	return true
}

func verifyCommand(root, id string) (map[string]interface{}, int, error) {
	stateMu.Lock()
	defer stateMu.Unlock()
	tasks, config, err := loadState(root)
	if err != nil {
		return nil, 2, err
	}
	if errs := append(validateConfig(config), validateTasks(root, tasks, config)...); len(errs) > 0 {
		return map[string]interface{}{"ok": false, "errors": errs}, 2, errors.New("invalid state")
	}
	index := -1
	for i := range tasks.Tasks {
		if tasks.Tasks[i].ID == id {
			index = i
		}
	}
	if index < 0 {
		return nil, 2, fmt.Errorf("unknown task %s", id)
	}
	if tasks.Tasks[index].State != "active" {
		return nil, 2, errors.New("verify requires an active task")
	}
	checks := map[string]Check{}
	for _, check := range config.Checks {
		checks[check.ID] = check
	}
	ids := tasks.Tasks[index].Verification
	if len(ids) == 0 {
		return map[string]interface{}{"ok": false, "error": "task has no verification checks"}, 1, errors.New("empty verification")
	}
	before, fpErr := fingerprint(root, config.FingerprintPaths)
	if fpErr != nil {
		return nil, 1, fpErr
	}
	started := time.Now().UTC()
	attemptID := started.Format("20060102T150405.000000000Z")
	evidence := &Evidence{AttemptID: attemptID, Status: "running", StartedAt: started.Format(time.RFC3339Nano), FingerprintBefore: before}
	tasks.Tasks[index].Evidence = evidence
	if err := saveJSON(root, stateFile, tasks); err != nil {
		return nil, 1, err
	}
	allPassed := true
	for _, checkID := range ids {
		check, ok := checks[checkID]
		outcome := CheckOutcome{ID: checkID}
		if !ok {
			outcome.Status = "missing"
			outcome.Error = "check is not configured"
			allPassed = false
			evidence.Checks = append(evidence.Checks, outcome)
			continue
		}
		ctx, cancel := context.WithTimeout(context.Background(), time.Duration(check.TimeoutSeconds)*time.Second)
		cmd := exec.CommandContext(ctx, check.Argv[0], check.Argv[1:]...)
		cwd := root
		if check.CWD != "" {
			cwd, err = safePath(root, check.CWD)
			if err != nil {
				cancel()
				outcome.Status = "failed"
				outcome.Error = err.Error()
				evidence.Checks = append(evidence.Checks, outcome)
				allPassed = false
				continue
			}
		}
		cmd.Dir = cwd
		cmd.Env = os.Environ()
		runErr := cmd.Run()
		if ctx.Err() == context.DeadlineExceeded {
			outcome.Status = "timeout"
			outcome.TimedOut = true
			outcome.Error = "timeout"
			allPassed = false
		} else if runErr != nil {
			outcome.Status = "failed"
			outcome.Error = runErr.Error()
			if exitErr, ok := runErr.(*exec.ExitError); ok {
				outcome.ExitCode = exitErr.ExitCode()
			}
			allPassed = false
		} else {
			outcome.Status = "passed"
		}
		cancel()
		evidence.Checks = append(evidence.Checks, outcome)
	}
	after, afterErr := fingerprint(root, config.FingerprintPaths)
	if afterErr != nil {
		allPassed = false
		after = ""
	}
	evidence.FingerprintAfter = after
	evidence.Fresh = before == after && after != ""
	if !evidence.Fresh {
		allPassed = false
	}
	evidence.CompletedAt = time.Now().UTC().Format(time.RFC3339Nano)
	evidence.Status = "failed"
	if allPassed {
		evidence.Status = "passed"
		tasks.Tasks[index].State = "verified"
	}
	if err := saveJSON(root, stateFile, tasks); err != nil {
		return nil, 1, err
	}
	result := map[string]interface{}{"ok": allPassed, "task": id, "state": tasks.Tasks[index].State, "evidence": evidence}
	if !allPassed {
		return result, 1, errors.New("verification failed")
	}
	return result, 0, nil
}

func fingerprint(root string, paths []string) (string, error) {
	hash := sha256.New()
	cleaned := append([]string(nil), paths...)
	sort.Strings(cleaned)
	for _, rel := range cleaned {
		path, err := safePath(root, rel)
		if err != nil {
			return "", err
		}
		info, err := os.Lstat(path)
		if err != nil {
			return "", fmt.Errorf("fingerprint input %s: %w", rel, err)
		}
		if info.IsDir() {
			entries := []string{}
			err = filepath.Walk(path, func(current string, fileInfo os.FileInfo, walkErr error) error {
				if walkErr != nil {
					return walkErr
				}
				relative, relErr := filepath.Rel(root, current)
				if relErr != nil {
					return relErr
				}
				entries = append(entries, relative)
				if fileInfo.Mode().IsRegular() {
					content, readErr := os.ReadFile(current)
					if readErr != nil {
						return readErr
					}
					entries = append(entries, hex.EncodeToString(sha256Bytes(content)))
				}
				return nil
			})
			if err != nil {
				return "", err
			}
			sort.Strings(entries)
			_, _ = io.WriteString(hash, strings.Join(entries, "\x00"))
		} else {
			content, readErr := os.ReadFile(path)
			if readErr != nil {
				return "", readErr
			}
			_, _ = io.WriteString(hash, rel+"\x00")
			_, _ = hash.Write(content)
		}
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func sha256Bytes(data []byte) []byte {
	sum := sha256.Sum256(data)
	return sum[:]
}

func handoffCommand(root string) (map[string]interface{}, error) {
	stateMu.Lock()
	defer stateMu.Unlock()
	tasks, config, err := loadState(root)
	if err != nil {
		return nil, err
	}
	if errs := append(validateConfig(config), validateTasks(root, tasks, config)...); len(errs) > 0 {
		return map[string]interface{}{"ok": false, "errors": errs}, errors.New("invalid state")
	}
	var handoff Handoff
	if err := loadJSON(root, handoffFile, &handoff); err != nil {
		if !strings.Contains(err.Error(), "read ") {
			return nil, err
		}
	}
	if handoff.SchemaVersion == 0 {
		handoff.SchemaVersion = schemaVersion
	}
	active := ""
	for _, task := range tasks.Tasks {
		if task.State == "active" {
			active = task.ID
		}
	}
	if active != "" {
		handoff.TaskID = active
	} else if handoff.TaskID != "" {
		known := false
		for _, task := range tasks.Tasks {
			known = known || task.ID == handoff.TaskID
		}
		if !known {
			return nil, errors.New("handoff taskId is unknown")
		}
	}
	if branch, revision, dirty := gitFacts(root); branch != "" || revision != "" {
		handoff.Branch, handoff.Revision, handoff.Dirty = branch, revision, dirty
	}
	handoff.EvidenceFresh = true
	for _, task := range tasks.Tasks {
		if task.Evidence != nil && task.Evidence.Status == "passed" {
			fp, fpErr := fingerprint(root, config.FingerprintPaths)
			if fpErr != nil || fp != task.Evidence.FingerprintAfter {
				handoff.EvidenceFresh = false
			}
		}
	}
	handoff.UpdatedAt = time.Now().UTC().Format(time.RFC3339Nano)
	if err := saveJSON(root, handoffFile, handoff); err != nil {
		return nil, err
	}
	return map[string]interface{}{"ok": true, "handoff": handoff}, nil
}

func archiveCommand(root string) (map[string]interface{}, error) {
	stateMu.Lock()
	defer stateMu.Unlock()
	tasks, config, err := loadState(root)
	if err != nil {
		return nil, err
	}
	if errs := append(validateConfig(config), validateTasks(root, tasks, config)...); len(errs) > 0 {
		return map[string]interface{}{"ok": false, "errors": errs}, errors.New("invalid state")
	}
	remaining := []Task{}
	archived := []string{}
	for _, task := range tasks.Tasks {
		if task.State != "passing" {
			remaining = append(remaining, task)
			continue
		}
		if err := saveJSON(root, filepath.Join("docs/harness/archive", task.ID+".json"), task); err != nil {
			return nil, err
		}
		archived = append(archived, task.ID)
	}
	tasks.Tasks = remaining
	if err := saveJSON(root, stateFile, tasks); err != nil {
		return nil, err
	}
	return map[string]interface{}{"ok": true, "archived": archived}, nil
}

func gitFacts(root string) (string, string, bool) {
	branch := runGit(root, "branch", "--show-current")
	revision := runGit(root, "rev-parse", "HEAD")
	status := runGit(root, "status", "--porcelain")
	return strings.TrimSpace(branch), strings.TrimSpace(revision), strings.TrimSpace(status) != ""
}

func runGit(root string, args ...string) string {
	cmd := exec.Command("git", args...)
	cmd.Dir = root
	out, err := cmd.Output()
	if err != nil {
		return ""
	}
	return string(out)
}
