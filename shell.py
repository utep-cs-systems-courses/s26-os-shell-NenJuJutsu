#!/usr/bin/env python3

import os
import sys
import re

_TOKEN_RE = re.compile(r'''(?x)
\s*(
    "(?:\\.|[^"\\])*"   |   #double quotes
    '(?:\\.|[^'\\])*'   |   #single quotes
    [^\s]+                  #unquoted
    )
''')

def split_cmdline(s: str) -> list[str]:
    tokens = [m.group(1) for m in _TOKEN_RE.finditer(s)]
    out = []
    for t in tokens:
        if len(t) >= 2 and ((t[0] == '"' and t[-1] == '"')  or (t[0] == "'" and t[-1] == "'")):
            t = t[1:-1] #strip surrounding quotes
        #minimal unescape for \" and \'
        t = t.replace(r'\"', '"').replace(r"\'", "'").replace(r"\\", "\\")
        out.append(t)
    return out

def find_executable(cmd: str) -> str | None:
    #if command includes a slash, treat it as a path
    if "/" in cmd:
        return cmd if os.path.isfile(cmd) and os.access(cmd, os.X_OK) else None

    path = os.environ.get("PATH", "")
    for directory in path.split(":"):
        if directory == "":
            directory = "."
        candidate = os.path.join(directory, cmd)
        if os.access(candidate, os.X_OK) and os.path.isfile(candidate):
            return candidate
    return None

def run_command(argv: list[str], infile: str | None = None, outfile: str | None = None) -> None:
    prog = argv[0]
    exe = find_executable(prog)
    if exe is None:
        print(f"{prog}: command not found", file=sys.stdout)
        return

    pid = os.fork()
    if pid == 0:
        try:
            if infile is not None:
                fd_in = os.open(infile, os.O_RDONLY)
                os.dup2(fd_in, 0)
                os.close(fd_in)
            
            if outfile is not None:
                fd_out = os.open(outfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
                os.dup2(fd_out, 1)
                os.close(fd_out)

            os.execve(exe, argv, os.environ)
        except OSError as e:
            #if exec fails exit with non zero
            print(e, file=sys.stderr)
            os._exit(1)
    else:
        #parent wait for child
        _, status = os.waitpid(pid, 0)
        if os.WIFEXITED(status):
            code = os.WEXITSTATUS(status)
            if code != 0:
                print(f"Program terminated with exit code {code}.", file=sys.stdout)
        elif os.WIFSIGNALED(status):
            #if killed by signal treat as non zero
            sig = os.WTERMSIG(status)
            print(f"Program terminated with exit code {128 + sig}.", file=sys.stdout)

def parse_redirections(tokens: list[str]) -> tuple[list[str], str | None, str | None]:
    """Parse < infile and > outfile. Returns (argv, infile, outfile)"""
    argv: list[str] = []
    infile: str | None = None
    outfile: str | None = None

    i = 0
    while i < len(tokens): 
        t = tokens[i]
        if t == "<":
            if i + 1 >= len(tokens):
                raise ValueError("missing file name after <")
            infile = tokens[i + 1]
            i += 2
        elif t == ">":
            if i + 1 >= len(tokens):
                raise ValueError("missing file name after >")
            outfile = tokens[i + 1]
            i += 2
        else:
            argv.append(t)
            i += 1

    return argv, infile, outfile

def main():

    while True:
        try:
            prompt = os.environ.get("PS1", "$ ")
            line = input(prompt)
        except EOFError:
            if sys.stdin.isatty():
                print()
            break

        if not line.strip():
            continue
        
        line = line.strip()
        if line == "exit":
            break
        
        #simple tokenization
        tokens = split_cmdline(line)
        if not tokens:
            continue

        #parse < and >
        try:
            argv, infile, outfile = parse_redirections(tokens)
        except ValueError as e:
            print(f"syntax error: {e}", file=sys.stdout)
            continue

        if not argv:
            continue 

        #built in CD
        if argv[0] == "cd":
            target = argv[1] if len(argv) > 1 else os.environ.get("HOME", "/")
            try:
                os.chdir(target)
            except OSError as e:
                print(f"cd: {e}", file=sys.stdout)
                os._exit(1)
            continue

        run_command(argv, infile=infile, outfile=outfile)

if __name__ == "__main__":
    main()
