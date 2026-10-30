"""Tokens SQL propios; las cadenas aceptan comillas escapadas como 'O''Brien'."""

import re

TOKEN = re.compile(
    r"(?P<SPACE>\s+|--[^\n]*)|(?P<STRING>'(?:''|[^'])*')|"
    r"(?P<NUMBER>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|"
    r"(?P<ID>[A-Za-z_][A-Za-z0-9_]*)|(?P<SYMBOL><=>|<->|>=|<=|!=|<>|[.(),;*=<>])"
)


def tokenize(sql):
    tokens = []
    position = 0
    while position < len(sql):
        match = TOKEN.match(sql, position)
        if not match:
            raise ValueError(
                f"SQL no soportado cerca de posición {position}: {sql[position : position + 20]}"
            )
        if match.lastgroup != "SPACE":
            tokens.append((match.lastgroup, match.group()))
        position = match.end()
    return tokens
