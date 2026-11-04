"""Генерация примеров карточек реальным Gemini.

Запуск: uv run python -m scripts.generate_examples [папка_с_json] [папка_результата]
По умолчанию читает examples/inputs/*.json и пишет examples/<имя>.json и .md.
Нужен заполненный .env (GEMINI_API_KEY, GEMINI_MODEL). Для собственных данных (например,
из private/) передайте путь к папке первым аргументом: результат тогда пишется в
evals/runs/examples/ (в .gitignore), а не в отслеживаемый examples/.
"""

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import AppError
from app.llm.gemini import GeminiClient
from app.prompts.loader import load_prompt
from app.schemas.product import ProductIn
from app.services.card_service import CardService


def main(src: Path, dst: Path) -> int:
    files = sorted(src.glob("*.json"))
    if not files:
        print(f"В {src} нет *.json: проверьте путь.")
        return 1
    settings = get_settings()
    service = CardService(GeminiClient(settings), load_prompt(), settings.gemini_model)
    dst.mkdir(parents=True, exist_ok=True)
    failed = 0
    for path in files:
        try:
            product = ProductIn.model_validate_json(path.read_text(encoding="utf-8"))
            card = service.generate(product)
        except (AppError, ValidationError) as exc:
            # Один неудачный файл не должен ронять весь пакет; итоговый код возврата не 0.
            failed += 1
            print(f"{path.name}: ОШИБКА {getattr(exc, 'code', type(exc).__name__)}")
            continue
        (dst / f"{path.stem}.json").write_text(
            json.dumps(card.model_dump(exclude={"markdown", "text"}), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (dst / f"{path.stem}.md").write_text(card.markdown, encoding="utf-8")
        print(f"{path.name}: ок, предупреждений {len(card.warnings)}")
        for warning in card.warnings:
            print(f"    - {warning}")
    return 1 if failed else 0


if __name__ == "__main__":
    repo = Path(__file__).resolve().parent.parent
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else repo / "examples" / "inputs"
    # Результат по чужим (private) данным по умолчанию уходит в игнорируемую папку:
    # в отслеживаемый examples/ попадают только карточки по нашим синтетическим входам.
    default_dst = repo / "examples" if src.resolve() == repo / "examples" / "inputs" \
        else repo / "evals" / "runs" / "examples"
    sys.exit(main(src, Path(sys.argv[2]) if len(sys.argv) > 2 else default_dst))
