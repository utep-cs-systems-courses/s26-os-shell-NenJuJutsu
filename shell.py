#!/opt/homebrew/bin/python3

import os
import sys
import re

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

        #print(f"debug: got command: {line}")

if __name__ == "__main__":
    main()
