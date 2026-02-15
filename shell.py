#!/opt/homebrew/bin/python3

import os
import sys
import re

def find_executable(cmd: str) -> str | None:
    #if command includes a slash, treat it as a path
    if "/" in cmd:
        return cmd if os.access(cmd, os.X_OK) else None

    path = os.environ.get("PATH", "")
    for directory in path.split(":"):
        if directory == "":
            directory = "."
        candidate = os.path.join(directory, cmd)
        if os.access(candidate, os.X_OK) and os.path.isfile(candidate):
            return candidate
    return None

def run_command(argv: list[str]) -> None:
    prog = argv[0]
    exe = find_executable(prog)
    if exe is None:
        print(f"{prog}: command not found", file=sys.stdout)
        return

    pid = os.fork()
    if pid == 0:
        try: 
            os.execve(exe, argv, os.environ)
        except OSError:
            #if exec fails exit with non zero
            os._exit(127)
    else:
        #parent wait for child
        _, status = os.wait()
        if os.WIFEXITED(status):
            code = os.WEXITSTATUS(status)
            if code != 0:
                print(f"Program terminated with exit code {code}.", file=sys.stdout)
        elif os.WIFSIGNALED(status):
            #if killed by signal treat as non zero
            sig = os.WTERMSIG(status)
            print(f"Program terminated with exit code {128 + sig}.", file=sys.stdout)

def main():
    while True:
        try:
            prompt = os.environ.get("PS1", "$ ")
            line = input(prompt)
        except EOFError:
            print()
            break

        if not line.strip():
            continue

        if line == "exit":
            break
        
        #simple tokenization
        argv = line.split()

        #built in CD
        if argv[0] == "cd":
            target = argv[1] if len(argv) > 1 else os.environ.get("HOME", "/")
            try:
                os.chdir(target)
            except OSError as e:
                print(f"cd: {e}", file=sys.stdout)
            continue

        run_command(argv)

if __name__ == "__main__":
    main()
