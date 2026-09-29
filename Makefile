# Run inside Ubuntu from the repo root (`wsl`, then `cd /mnt/e/Github/local-ai-platform`).
# From Windows use infra/scripts/platform.ps1 instead; it can also shut Ubuntu down.
# up/down need sudo (systemctl).

.PHONY: up up-docker down restart status deploy

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
