"""Parse Visual3D pipeline scripts (.v3s) into structured commands.

A .v3s file is a list of commands, each written as:

    Command_Name
    /PARAMETER=value
    ! /COMMENTED_PARAMETER=value      <- ignored (V3D default is used)
    ;

This module turns each block into a `Command` and tracks the For_Each loops and
pipeline parameters that are active at that point, so templated names such as
`::TRIAL_TYPE&_L_KNEE` can be reported along with the values they take.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# `::NAME` is a pipeline parameter only when it is not glued to a preceding word;
# `LINK_MODEL_BASED::ORIGINAL::L_HEEL` is a signal path, not a parameter.
PARAM_REF = re.compile(r"(?<![A-Za-z0-9_])::([A-Za-z0-9_]+)")


@dataclass
class Command:
    name: str
    params: dict[str, str]
    file: Path
    line: int
    # pipeline parameter name -> known values at this point in the script
    param_values: dict[str, list[str]] = field(default_factory=dict)

    def get(self, key: str, default: str = "") -> str:
        return self.params.get(key, default)

    def template_values(self, text: str) -> str:
        """Describe the known values of any ::PARAM used in `text`."""
        parts = []
        for p in dict.fromkeys(PARAM_REF.findall(text)):
            vals = self.param_values.get(p)
            parts.append(f"{p}={'|'.join(vals) if vals else '?'}")
        return "; ".join(parts)


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _split_items(value: str) -> list[str]:
    return [v.strip() for v in value.split("+") if v.strip()]


def parse_v3s(path: Path) -> list[Command]:
    """Parse one .v3s file into a list of commands (comments removed)."""
    commands: list[Command] = []
    loop_stack: list[tuple[str, list[str]]] = []
    globals_: dict[str, list[str]] = {}

    name: str | None = None
    params: dict[str, str] = {}
    start = 0
    last_key: str | None = None

    def known_values() -> dict[str, list[str]]:
        vals = dict(globals_)
        for pname, items in loop_stack:  # innermost loop wins
            vals[pname] = items
        return vals

    def finish() -> None:
        nonlocal name, params, last_key
        if name is None:
            return
        cmd = Command(name, params, path, start, known_values())
        commands.append(cmd)

        if name == "For_Each":
            pname = cmd.get("ITERATION_PARAMETER_NAME").strip()
            items = _split_items(cmd.get("ITEMS"))
            # A list held in another parameter (e.g. ::FOLDER_LIST) is only
            # known at run time.
            if len(items) == 1 and items[0].startswith("::"):
                items = []
            loop_stack.append((pname, items))
        elif name == "End_For_Each" and loop_stack:
            loop_stack.pop()
        elif name == "Set_Pipeline_Parameter":
            pname = cmd.get("PARAMETER_NAME").strip()
            items = _split_items(cmd.get("PARAMETER_VALUE"))
            if pname and items and not items[0].startswith("::"):
                globals_[pname] = items

        name, params, last_key = None, {}, None

    for lineno, raw_line in enumerate(read_text(path).splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("!"):
            continue

        ends = line.endswith(";")
        if ends:
            line = line[:-1].strip()

        if line.startswith("/"):
            key, _, value = line[1:].partition("=")
            last_key = key.strip().upper()
            params[last_key] = value.strip()
        elif line:
            if name is None:
                name = line.split()[0]
                start = lineno
            elif last_key is not None:
                # wrapped continuation of the previous parameter value
                params[last_key] += line

        if ends:
            finish()

    finish()
    return commands
