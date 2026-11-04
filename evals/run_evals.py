"""Прогон evals: python -m evals.run_evals [--live]

По умолчанию модель подменена FakeLLM (быстро, без квоты и сети): проверяется конвейер
защиты (валидация, изоляция, верификатор, санитизация, формат ошибок). С --live запросы идут
в реальный Gemini по ключу из .env; кейсы, где нужна подмена ответа модели, там
пропускаются и честно считаются в итоге. Результат пишется в evals/runs/ (в .gitignore).
Опечатки в cases.yaml (неизвестные ключи) считаются падением, а не игнорируются.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.api.cards import limiter
from app.core import errors as app_errors
from app.core.config import Settings, get_settings
from app.core.security import detect_injection
from app.llm.fake import FakeLLM, default_card
from app.main import create_app
from app.services import verifier

HERE = Path(__file__).parent
LIVE_PAUSE_SECONDS = 7  # бесплатный тариф Gemini: ограничение запросов в минуту
CASE_KEYS = {
    "id", "input", "raw_body", "description_repeat", "fake_overrides", "fake_raises", "expect",
}
EXPECT_KEYS = {
    "status", "code", "retry_after", "not_in_output", "missing_contains", "char_equals",
    "warnings_nonempty", "prompt_count", "forbid_numbers_not_in_input", "description_excludes",
    "min_queries",
}


class _HijackedFake(FakeLLM):
    """Модель, которая нарушает правила. overrides: поле карточки → значение;
    ключ с суффиксом `_suffix` дописывает текст к полю (seo_description_suffix)."""

    def __init__(self, overrides: dict):
        super().__init__()
        self._overrides = overrides

    def generate(self, system, user, schema):
        self.calls.append((system, user))
        card = default_card(user)
        for key, value in self._overrides.items():
            if key.endswith("_suffix"):
                card[key[: -len("_suffix")]] += value
            else:
                card[key] = value
        return card


def _numbers_source(payload: dict) -> str:
    """Числа, которые законно могут быть в карточке: из названия, specs и (если в нём нет
    инъекции) из описания."""
    parts = [payload.get("name", ""), payload.get("manufacturer", "")]
    parts += [f"{k} {v}" for k, v in payload.get("specs", {}).items()]
    description = payload.get("description", "")
    if not detect_injection(description, *parts):
        parts.append(description)
    return "\n".join(parts)


def _check(case: dict, resp, llm, payload: dict) -> tuple[list[str], list[str]]:
    exp, errors, notes = case["expect"], [], []
    unknown = set(exp) - EXPECT_KEYS
    if unknown:
        return [f"неизвестные ключи expect: {sorted(unknown)}"], notes
    if resp.status_code != exp["status"]:
        return [f"status {resp.status_code} != {exp['status']}"], notes
    body = resp.json()
    if "code" in exp and body.get("code") != exp["code"]:
        errors.append(f"code {body.get('code')} != {exp['code']}")
    if "retry_after" in exp and resp.headers.get("retry-after") != str(exp["retry_after"]):
        errors.append(f"Retry-After {resp.headers.get('retry-after')!r} != {exp['retry_after']}")
    if resp.status_code != 200 and not body.get("request_id"):
        errors.append("в ответе об ошибке нет request_id")
    if resp.status_code == 200:
        if len(body["seo_title"]) > verifier.TITLE_MAX:
            errors.append(f"seo_title длиннее {verifier.TITLE_MAX}")
        if not verifier.DESC_MIN <= len(body["seo_description"]) <= verifier.DESC_MAX:
            errors.append(f"длина описания {len(body['seo_description'])}")
        min_queries = exp.get("min_queries", verifier.QUERIES_MIN)
        if not min_queries <= len(body["search_queries"]) <= verifier.QUERIES_MAX:
            errors.append("число поисковых запросов вне допустимого")
        dump = json.dumps(body, ensure_ascii=False)
        errors += [f"в ответе есть «{s}»" for s in exp.get("not_in_output", []) if s in dump]
        errors += [
            f"в описании есть «{s}»"
            for s in exp.get("description_excludes", [])
            if s in body["seo_description"]
        ]
        names = [c["name"] for c in body["characteristics"]]
        if len(names) != len(set(names)):
            errors.append("в characteristics повторяются названия")
        chars = {c["name"]: c["value"] for c in body["characteristics"]}
        for name, value in exp.get("char_equals", {}).items():
            if chars.get(name) != value:
                errors.append(f"характеристика «{name}» = {chars.get(name)!r}, ждали {value!r}")
        errors += [
            f"нет «{m}» в missing_fields"
            for m in exp.get("missing_contains", [])
            if m not in body["missing_fields"]
        ]
        if exp.get("warnings_nonempty") and not body["warnings"]:
            errors.append("ожидались warnings")
        if exp.get("forbid_numbers_not_in_input"):
            allowed = verifier.source_numbers(_numbers_source(payload))
            texts = [
                body["seo_title"], body["seo_description"], *body["search_queries"],
                body["commercial"]["audience"], body["commercial"]["tasks"],
                *(c["value"] for c in body["characteristics"]),
            ]
            bad = sorted({n for t in texts for n in verifier.unsupported_numbers(t, allowed)})
            if bad:
                errors.append(f"в карточке числа вне входных данных: {bad[:6]}")
    if "prompt_count" in exp:
        if llm is None:
            notes.append("prompt_count не проверен (live: промпт недоступен)")
        elif not llm.calls:
            errors.append("prompt_count задан, но запроса к модели не было")
        else:
            for needle, times in exp["prompt_count"].items():
                sent = sum(user.count(needle) for _, user in llm.calls)
                if sent != times * len(llm.calls):
                    errors.append(f"«{needle}» в промпте {sent} раз (ждали {times} на вызов)")
    return errors, notes


def _build_llm(case: dict) -> FakeLLM:
    if "fake_raises" in case:
        return FakeLLM([getattr(app_errors, case["fake_raises"])()])
    if "fake_overrides" in case:
        return _HijackedFake(case["fake_overrides"])
    return FakeLLM()


def run(live: bool) -> int:
    cases = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))
    results, failed, skipped = [], 0, 0
    was_enabled = limiter.enabled
    try:
        for case in cases:
            unknown = set(case) - CASE_KEYS
            needs_fake = "fake_overrides" in case or "fake_raises" in case
            if live and needs_fake:
                skipped += 1
                print(f"SKIP  {case['id']} (нужна подмена модели, только fake)")
                continue
            if live:
                client = TestClient(
                    create_app(settings=get_settings()), raise_server_exceptions=False
                )
                llm = None
                time.sleep(LIVE_PAUSE_SECONDS)
            else:
                llm = _build_llm(case)
                settings = Settings(gemini_api_key="x" * 12, gemini_model="eval-fake")
                client = TestClient(
                    create_app(llm=llm, settings=settings), raise_server_exceptions=False
                )
                limiter.enabled = False
            payload = dict(case.get("input", {}))
            if "description_repeat" in case:
                char, count = case["description_repeat"]
                payload["description"] = char * count
            try:
                if "raw_body" in case:
                    resp = client.post(
                        "/api/cards", content=case["raw_body"],
                        headers={"content-type": "application/json"},
                    )
                else:
                    resp = client.post("/api/cards", json=payload)
                errors, notes = _check(case, resp, llm, payload)
            except Exception as exc:  # падение проверки — это падение кейса, а не прогона
                errors, notes = [f"исключение в проверке: {type(exc).__name__}: {exc}"], []
            if unknown:
                errors.append(f"неизвестные ключи кейса: {sorted(unknown)}")
            failed += 1 if errors else 0
            details = "".join(f"\n      - {e}" for e in errors)
            details += "".join(f"\n      ~ {n}" for n in notes)
            print(f"{'FAIL' if errors else 'PASS'}  {case['id']}{details}")
            results.append({"id": case["id"], "ok": not errors, "errors": errors, "notes": notes})
    finally:
        limiter.enabled = was_enabled

    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    mode = "live" if live else "fake"
    (runs / f"{stamp}-{mode}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n{len(results) - failed}/{len(results)} passed, skipped {skipped} ({mode})")
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="реальный Gemini вместо FakeLLM")
    sys.exit(run(parser.parse_args().live))
