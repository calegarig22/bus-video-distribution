# Atalhos de desenvolvimento (Mac/Linux). Requer uv (https://docs.astral.sh/uv/).
PY := .venv/bin/python

.PHONY: setup test demo videos clean

setup:            ## cria o ambiente virtual e instala servidor + cliente (modo desenvolvimento)
	uv venv --python 3.12 .venv
	uv pip install -p $(PY) -e "server[dev]" -e "client[dev]"

test:             ## roda toda a suíte (servidor, cliente, integração)
	$(PY) -m pytest

videos:           ## gera vídeos de demonstração em demo/videos/
	./demo/make_videos.sh

demo:             ## sobe servidor + ônibus simulados em http://localhost:8080 (admin/demo)
	./demo/run_demo.sh

clean:
	rm -rf demo/data .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
