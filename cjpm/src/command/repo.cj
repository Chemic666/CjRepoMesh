// Copyright (c) 2026 CjRepoMesh contributors.
// Licensed under the Apache License, Version 2.0.

package cjpm.command

import cjpm.implement.*

let REPO_USAGE: String = """
Explain repository routing and package source selection.

Usage:
  cjpm repo explain <package>

Examples:
  cjpm repo explain meshdep
  cjpm repo explain company::auth"""

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
        if (this.arguments.size != 2 || this.arguments[0] != "explain") {
            eprintln("Error: usage is 'cjpm repo explain <package>'")
            return false
        }
        return doRepoExplain(this.arguments[1])
    }
}
