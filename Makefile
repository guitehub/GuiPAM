# Cibles de développement GuiPAM (le build Docker n'en dépend pas).

TAILWIND := .cache/tailwindcss
TW_URL := https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64

# Version figée de guitestyle (le style du Hub de la Guite). Mise à jour :
#   make guitestyle VERSION=x.y.z && make css
VERSION ?= 1.0.0
GUITESTYLE_URL := https://cdn.jsdelivr.net/gh/guitehub/guitehub.github.io@guitestyle-v$(VERSION)/assets/guitestyle/tokens.css

.PHONY: css i18n test run guitestyle

$(TAILWIND):
	mkdir -p .cache
	curl -sSL -o $(TAILWIND) $(TW_URL)
	chmod +x $(TAILWIND)

css: $(TAILWIND)
	$(TAILWIND) -i app/static/src/input.css -o app/static/app.css --minify

guitestyle:
	mkdir -p app/static/vendor/guitestyle
	curl -sSfL -o app/static/vendor/guitestyle/tokens.css $(GUITESTYLE_URL)
	@head -3 app/static/vendor/guitestyle/tokens.css
	@echo "→ relancer 'make css', vérifier clair et sombre, puis committer."

i18n:
	pybabel extract -F babel.cfg -o messages.pot .
	python scripts/gen_fr_po.py messages.pot
	pybabel compile -d app/locale -D messages
	rm -f messages.pot

test:
	pytest tests/ -q

run:
	python -m app.main
