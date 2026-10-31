PYTHON ?= python
FEED ?= .local/feed
RUN ?= .local/run
START ?= 2025-11-01
DAYS ?= 365
IMAGE ?= trainyard-ml:local
PORT ?= 5001
GIT_SHA ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo local)
MODEL_DIR := /var/azureml-app/azureml-models/trainyard-risk/local
export MLFLOW_TRACKING_URI ?= .local/mlruns
export MLFLOW_EXPERIMENT_NAME ?= train-local
export MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR ?= false
export MSYS_NO_PATHCONV := 1

.PHONY: check train-local score-local

check:
	ruff check . && ruff format --check . && mypy && pytest -q

$(FEED):
	$(PYTHON) -m ops.feed --out $(FEED) --start $(START) --days $(DAYS)

train-local: $(FEED)
	$(PYTHON) -m ml.steps local --feed $(FEED) --out $(RUN) --git-sha $(GIT_SHA)

score-local:
	test -f $(RUN)/model/MLmodel || $(MAKE) train-local
	docker build -t $(IMAGE) ml/environment
	docker run -d --rm --name trainyard-score -p $(PORT):5001 -w /var/azureml-app \
	  -v "$(CURDIR)/ml:/var/azureml-app/ml:ro" -v "$(CURDIR)/$(RUN)/model:$(MODEL_DIR):ro" \
	  -e AZUREML_MODEL_DIR=$(MODEL_DIR) -e AZUREML_MDC_ENABLED=true -e AZUREML_MDC_LOCAL_CAPTURE=true \
	  $(IMAGE) azmlinfsrv --entry_script ml/score.py --port 5001
	for i in $$(seq 60); do curl -sf http://localhost:$(PORT)/ >/dev/null && break; sleep 2; done
	SCORING_URL=http://localhost:$(PORT)/score $(PYTHON) -m pytest -q tests/test_scoring.py; status=$$?; \
	  echo "payloads collected: $$(docker logs trainyard-score 2>&1 | grep -c -E 'model_(inputs|outputs) [|]')"; \
	  docker stop trainyard-score >/dev/null; exit $$status
