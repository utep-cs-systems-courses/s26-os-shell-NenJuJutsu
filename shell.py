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

def run_command(argv: list[str], infile: str | None = None, outfile: str | None = None, background: bool = False) -> None:
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
        if background:
            return
        _, status = os.waitpid(pid, 0)
        if os.WIFEXITED(status):
            code = os.WEXITSTATUS(status)
            if code != 0:
                print(f"Program terminated with exit code {code}.", file=sys.stderr)
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

def split_pipeline(tokens: list[str]) -> list[list[str]]:
    segs: list[list[str]] = []
    cur: list[str] = []
    for t in tokens:
        if t == "|":
            if not cur:
                raise ValueError("missing command before |")
            segs.append(cur)
            cur = []
        else:
            cur.append(t)
    if not cur:
        raise ValueError("missing command after |")
    segs.append(cur)
    return segs

def run_pipeline(segments: list[list[str]], background : bool = False) -> None:
    """
    list of token list, each segement may contain < or >
    rule: allow < only on first segment, > only on last segment 
    """
    n = len(segments)
    pids: list[int] = []
    prev_read: int | None = None

    for i in range(n):
        #parse redirections per segment 
        argv, infile, outfile = parse_redirections(segments[i])
        if not argv:
            raise ValueError("empty command in pipeline")
        
        if i != 0 and infile is not None:
            raise ValueError("input redirection only allowed on first command of pipeline")
        if i != n - 1 and outfile is not None:
            raise ValueError("output redirection only allowed on last command of pipeline")

        #set up pipe to next command unless last
        if i != n - 1:
            r, w = os.pipe()
        else:
            r, w = None, None

        pid = os.fork()
        if pid == 0:
            #child 
            try:
                #if there is a previous pipe connect to stdin
                if prev_read is not None:
                    os.dup2(prev_read, 0)
            
                #if there is a next pipe connect stdout to it
                if w is not None:
                    os.dup2(w, 1)

                #apply < on first command
                if infile is not None:
                    fd_in = os.open(infile, os.O_RDONLY)
                    os.dup2(fd_in, 0)
                    os.close(fd_in)

                #apply > on last command
                if outfile is not None:
                    fd_out = os.open(outfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
                    os.dup2(fd_out, 1)
                    os.close(fd_out)

                #close fd's we dont need
                if prev_read is not None:
                    os.close(prev_read)
                if r is not None:
                    os.close(r)
                if w is not None:
                    os.close(w)

                #exec
                exe = find_executable(argv[0])
                if exe is None:
                    print(f"{argv[0]}: command not found", file=sys.stderr)
                    os._exit(127)

                os.execve(exe, argv, os.environ)

            except OSError as e:
                print(e, file=sys.stderr)
                os._exit(1)

        else:
            #parent
            pids.append(pid)

            #parent closes ends not needed
            if prev_read is not None:
                os.close(prev_read)
            if w is not None:
                os.close(w)

            prev_read = r #next child will read from here

    #after forking all, parent closes any remaining read end
    if prev_read is not None:
        os.close(prev_read)
    
    if background:
        return
    #wait for all children; report exit code of the last command
    last_status = 0
    for pid in pids:
        _, status = os.waitpid(pid, 0)
        last_status = status

    if os.WIFEXITED(last_status):
        code = os.WEXITSTATUS(last_status)
        if code != 0:
            print(f"Program terminated with exit code {code}.", file=sys.stderr)
    elif os.WIFSIGNALED(last_status):
        sig = os.WTERMSIG(last_status)
        print(f"Program terminated with exit code {128 + sig}.", file=sys.stdout)

def reap_background() -> None:
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return #no children
        if pid ==0:
            return #none finished yet

def logical_pwd_update(target: str) -> None:
    old = os.environ.get("PWD", os.getcwd())

    if os.path.isabs(target):
        new = os.path.normpath(target)
    else:
        new = os.path.normpath(os.path.join(old, target))

    os.environ["PWD"] = new

def main():

    while True:
        reap_background()

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

        background = False
        if tokens and tokens[-1] == "&":
            background = True
            tokens = tokens[:-1]
            if not tokens:
                continue

        if "|" in tokens:
            try:
                segement = split_pipeline(tokens)
                run_pipeline(segement, background=background)
            except ValueError as e:
                print(f"Syntax error: {e}", file=sys.stdout)
            continue

        #parse < and >
        try:
            argv, infile, outfile = parse_redirections(tokens)
        except ValueError as e:
            print(f"Syntax error: {e}", file=sys.stdout)
            continue

        if not argv:
            continue 

        #built in CD
        if argv[0] == "cd":
            target = argv[1] if len(argv) > 1 else os.environ.get("HOME", "/")
            try:
                os.chdir(target)
                logical_pwd_update(target)
            except OSError as e:
                print(f"cd: {e}", file=sys.stdout)
            continue

        run_command(argv, infile=infile, outfile=outfile, background=background)

if __name__ == "__main__":
    main()
