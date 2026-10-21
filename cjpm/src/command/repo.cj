// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjpm.command

import cjpm.implement.*

let REPO_USAGE: String = """
Explain repository routing and package source selection.

Usage:
  cjpm repo explain <package>
  cjpm repo explain <package> --recorded
  cjpm repo doctor [package]

Examples:
  cjpm repo explain meshdep
  cjpm repo explain company::auth"""

// Stored provenance inspection does not invoke the compiler or resolve packages.
// Keep the match exact so online/invalid command forms retain normal preflight.
public func isRecordedRepositoryExplain(handler: Handle): Bool {
    let args = handler.arguments
    return handler.cmdName == "repo" && args.size == 3 &&
        args[0] == "explain" && args[2] == "--recorded"
}

class RepoCommand <: Handle {
    init(args: Array<String>) {
        this.cmdName = args[0]
        this.arguments = args[1..]
    }

    public override func printHelp(): Unit {
        println(REPO_USAGE)
    }

    public override func printPass(): Unit {
        return
    }

    public override func handleCommand(): Bool {
        if (!this.arguments.isEmpty() && this.arguments[0] == "doctor") {
            if (this.arguments.size == 1) {
                return doRepoDoctor(None)
            }
            if (this.arguments.size == 2) {
                return doRepoDoctor(Some(this.arguments[1]))
            }
            eprintln("Error: usage is 'cjpm repo doctor [package]'")
            return false
        }
        if (!this.arguments.isEmpty() && this.arguments[0] == "explain") {
            if (this.arguments.size == 2) {
                return doRepoExplain(this.arguments[1])
            }
            if (this.arguments.size == 3 && this.arguments[2] == "--recorded") {
                return doRepoExplainRecorded(this.arguments[1])
            }
            eprintln("Error: usage is 'cjpm repo explain <package> [--recorded]'")
            return false
        }
        eprintln("Error: usage is 'cjpm repo explain <package> [--recorded]' or 'cjpm repo doctor [package]'")
        return false
    }
}
