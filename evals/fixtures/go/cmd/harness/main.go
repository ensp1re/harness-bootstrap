package main

import (
	"os"

	"harness-eval-go/harness"
)

func main() {
	os.Exit(harness.Main(os.Args[1:], os.Stdout, os.Stderr))
}
