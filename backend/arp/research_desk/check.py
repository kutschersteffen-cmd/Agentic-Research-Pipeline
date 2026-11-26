"""The model's answer shape, the calculator and the sentence check. The model never decides a sentence's status."""

from __future__ import annotations

import ast
import re

from pydantic import BaseModel, Field

from arp.grounding import _find_match, _page_for_offset, is_grounded

MAX_CALCULATIONS = 10
MAX_EXPRESSION_CHARS = 200
NO_SCALE = {100.0, 1000.0, 1000000.0}  # percent and unit scaling need no source
NOT_ALLOWED = "Only numbers and + - * / ( ) are allowed."
_ALLOWED_CHARS = re.compile(r"[\d.+\-*/() ]*")
_NUMBER = re.compile(r"\d+(?:\.\d*)?")


class DeskCitation(BaseModel):
    source: int
    quote: str


class DeskSentence(BaseModel):
    text: str
    citations: list[DeskCitation] = []
    calculation: str | None = None


class DeskCalculation(BaseModel):
    id: str
    label: str
    expression: str
    decimals: int = Field(default=1, ge=0, le=6)
    unit: str = ""


class DeskAnswer(BaseModel):
    sentences: list[DeskSentence]
    calculations: list[DeskCalculation] = []


class DeskSubQuestions(BaseModel):
    questions: list[str]


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ZeroDivisionError
            return left / right
        return left + right if isinstance(node.op, ast.Add) else left - right if isinstance(node.op, ast.Sub) else left * right
    raise ValueError


def calculate(c: DeskCalculation) -> dict:
    """The stored calculation: the expression parsed and walked node by node (never eval)."""
    out = {"id": c.id, "label": c.label, "expression": c.expression, "result": None, "display": None, "unit": c.unit,
           "formula": None, "error": None}
    if len(c.expression) > MAX_EXPRESSION_CHARS:
        return {**out, "error": "The formula is longer than 200 characters."}
    try:
        if not _ALLOWED_CHARS.fullmatch(c.expression):
            raise ValueError
        result = _eval(ast.parse(c.expression, mode="eval").body)
    except ZeroDivisionError:
        return {**out, "error": "Division by zero."}
    except (ValueError, SyntaxError, RecursionError):
        return {**out, "error": NOT_ALLOWED}
    display = f"{result:.{c.decimals}f}"
    return {**out, "result": result, "display": display, "formula": f"{c.label} = {c.expression} = {display}{c.unit}"}


def check_answer(answer: DeskAnswer, sources: dict[int, tuple[str, list[int], int]]) -> dict:
    """`sources`: n -> (text, its document's page breaks, the text's offset in the document). Every sentence gets
    `calculated`, `found` or `to_check`; nothing can turn this off."""
    calculations = [calculate(c) for c in answer.calculations[:MAX_CALCULATIONS]]
    by_id = {c["id"]: c for c in calculations}
    sentences, quoted = [], set()
    for n, sentence in enumerate(answer.sentences, 1):
        citations = []
        for c in sentence.citations:
            src = sources.get(c.source)
            grounded = src is not None and is_grounded(c.quote, src[0])
            page = None
            if grounded:
                quoted.update(float(x) for x in _NUMBER.findall(c.quote.replace(",", "")))
                page = _page_for_offset(src[1], src[2] + _find_match(c.quote, src[0], 0.92).char_start)
            citations.append({"source": c.source, "quote": c.quote, "grounded": grounded, "page": page})
        sentences.append({"n": n, "text": sentence.text, "citations": citations, "calculation": sentence.calculation})
    for s in sentences:  # after every citation: a calculation may use a number quoted in any sentence
        calc = by_id.get(s["calculation"]) if s["calculation"] else None
        if calc is not None and calc["error"] is None and calc["display"] in s["text"] and all(
                float(x) in quoted for x in _NUMBER.findall(calc["expression"]) if float(x) not in NO_SCALE):
            s["status"] = "calculated"
        elif s["calculation"] is None and s["citations"] and all(c["grounded"] for c in s["citations"]):
            s["status"] = "found"
        else:
            s["status"] = "to_check"
    check = {k: sum(s["status"] == k for s in sentences) for k in ("found", "calculated", "to_check")}
    return {"sentences": sentences, "calculations": calculations, "check": check}
