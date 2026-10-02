# Run inside Ubuntu from the repo root (`wsl`, then `cd /mnt/e/Github/local-ai-platform`).
# From Windows use infra/scripts/platform.ps1 instead; it can also shut Ubuntu down.
# up/down need sudo (systemctl).

.PHONY: up up-docker down restart status deploy images test llm-reload teardown

up:        ## start Ollama + k3s and wait until every pod is Ready
	bash infra/scripts/platform.sh up

up-docker: ## same as up, plus Docker
	bash infra/scripts/platform.sh up --docker

down:      ## stop all pods, k3s, Ollama and Docker
	bash infra/scripts/platform.sh down

restart:
	bash infra/scripts/platform.sh restart

status:    ## health check of services, pods, models, ingress
	bash infra/scripts/status.sh

deploy:    ## apply every manifest under infra/k3s
	bash infra/scripts/deploy.sh

images:    ## build the agent, MCP server and UI images and load them into k3s
	bash infra/scripts/build-images.sh

test:      ## run the unit tests in a throwaway python container
	docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v "$(CURDIR)":/src -w /src python:3.13-slim \
	  sh -c "pip install -q --root-user-action=ignore -r tests/requirements.txt && python -m pytest -q -p no:cacheprovider tests"

llm-reload: ## apply llm/litellm.yaml and restart LiteLLM to load its model list
	kubectl apply -f infra/k3s/llm/litellm.yaml
	kubectl -n llm rollout restart deploy/litellm
	kubectl -n llm rollout status deploy/litellm --timeout=5m

teardown:  ## delete every workload AND its volumes (chat history, vectors); asks first
	bash infra/scripts/teardown.sh
