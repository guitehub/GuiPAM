# Cibles de développement GuiPAM (le build Docker n'en dépend pas).

TAILWIND := .cache/tailwindcss
TW_URL := https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64

.PHONY: css i18n test run

$(TAILWIND):
	mkdir -p .cache
	curl -sSL -o $(TAILWIND) $(TW_URL)
	chmod +x $(TAILWIND)

css: $(TAILWIND)
	$(TAILWIND) -i app/static/src/input.css -o app/static/app.css --minify

i18n:
	pybabel extract -F babel.cfg -o messages.pot .
	python scripts/gen_fr_po.py messages.pot
	pybabel compile -d app/locale -D messages
	rm -f messages.pot

test:
	pytest tests/ -q

run:
	python -m app.main
