#!/usr/bin/env bash
# Падает, если в индексе оказались секреты или локальные материалы (private/, документы).
# Имена читаются через -z и core.quotepath=off: иначе git квотирует не-ASCII имена
# («Схема.pdf» превращается в "\320\241..."), и проверки по расширению их пропускают.
set -euo pipefail
shopt -s nocasematch  # «spec.PDF», «.ENV» и «КЛЮЧ.PEM» тоже запрещены
cd "$(git rev-parse --show-toplevel)"

bad=()
while IFS= read -r -d '' f; do
  case "$f" in
    .env.example|*/.env.example) ;;
    .env|.env.*|*/.env|*/.env.*|*.env|.envrc|*/.envrc) bad+=("$f") ;;
    *.pdf|*.doc|*.docx|*.pem|*.key|*.p12|*.pfx|.netrc|.pypirc|.mcp.json) bad+=("$f") ;;
    private/*|*/private/*|.claude/*|.serena/*|CLAUDE.md|*/CLAUDE.md) bad+=("$f") ;;
    credentials*.json|*/credentials*.json|service-account*.json) bad+=("$f") ;;
  esac
done < <(git -c core.quotepath=off ls-files -z --cached)

if [ "${#bad[@]}" -gt 0 ]; then
  echo "ЗАПРЕЩЁННЫЕ файлы в репозитории:"; printf '  %s\n' "${bad[@]}"; exit 1
fi

# Содержимое индекса (а не рабочей копии): ключи Google/OpenAI и присваивания *_API_KEY.
pattern='AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9]{20,}|(API_KEY|api_key)["'\'']?[[:space:]]*[:=][[:space:]]*["'\'']?[A-Za-z0-9_-]{16,}'
if git grep --cached -nIE "$pattern" -- . ':!.env.example' ':!scripts/check_repo.sh'; then
  echo "Похоже на секрет (см. выше)."; exit 1
fi
echo "check_repo: ок"
