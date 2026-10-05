# Run inside Ubuntu from the repo root (`wsl`, then `cd /mnt/e/Github/local-ai-platform`).
# From Windows use infra/scripts/platform.ps1 instead; it can also shut Ubuntu down.
# up/down need sudo (systemctl).

.PHONY: up local-up up-docker down local-down restart status deploy images test llm-reload rag-index train s3-credentials headlamp-token teardown

up:        ## start Ollama + k3s and wait until every pod is Ready
	bash infra/scripts/platform.sh up

local-up: up  ## alias of up, same name as .\local-up on Windows

up-docker: ## same as up, plus Docker
	bash infra/scripts/platform.sh up --docker

down:      ## stop all pods, k3s, Ollama and Docker
	bash infra/scripts/platform.sh down

local-down: down  ## alias of down, same name as .\local-down on Windows

restart:   ## down, then up (fresh pods)
	bash infra/scripts/platform.sh restart

status:    ## health check of services, pods, models, ingress
	bash infra/scripts/status.sh

deploy:    ## apply every manifest under infra/k3s
	bash infra/scripts/deploy.sh

images:    ## build the agent, MCP server and UI images and load them into k3s
	bash infra/scripts/build-images.sh

test:      ## run the unit tests in a throwaway python container (pip cache kept in a volume)
	docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v "$(CURDIR)":/src -v local-ai-pip-cache:/root/.cache/pip -w /src python:3.13-slim \
	  sh -c "pip install -q --root-user-action=ignore -r tests/requirements.txt && python -m pytest -q -p no:cacheprovider tests"

llm-reload: ## apply llm/litellm.yaml and restart LiteLLM to load its model list
	kubectl apply -f infra/k3s/llm/litellm.yaml
	kubectl -n llm rollout restart deploy/litellm
	kubectl -n llm rollout status deploy/litellm --timeout=5m

rag-index: ## index the shared folder into Qdrant now (ARGS=--rebuild to start over)
	bash infra/scripts/rag-index.sh $(ARGS)

train:     ## run the message-triage training now (queued; watch it at http://dagster.local)
	kubectl -n mlops exec deploy/dagster-daemon -- dagster job launch -j triage_training -w workspace.yaml

s3-credentials: ## print the SeaweedFS admin UI password (user admin) and the S3 key pair
	@printf 'admin UI (http://s3.local): admin / %s\n' "$$(kubectl -n storage get secret seaweedfs-secret -o jsonpath='{.data.admin-password}' | base64 -d)"
	@printf 'S3 access key: %s\nS3 secret key: %s\n' "$$(kubectl -n storage get secret seaweedfs-secret -o jsonpath='{.data.access-key}' | base64 -d)" "$$(kubectl -n storage get secret seaweedfs-secret -o jsonpath='{.data.secret-key}' | base64 -d)"

headlamp-token: ## print the Headlamp login token (cluster-admin; README §6.11)
	@kubectl -n ui get secret headlamp-token -o jsonpath='{.data.token}' | base64 -d; echo

teardown:  ## delete every workload AND its volumes (chat history, vectors); asks first
	bash infra/scripts/teardown.sh
