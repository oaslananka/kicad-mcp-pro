#!/usr/bin/env bash
# Sourced by the protected main-only production watcher.
# Network cutover is a separate operator-accepted action.
select_production_compose_files() {
  production_compose_files=(-f infra/compose.production.yml)
  case "${KICAD_CLOUD_PRODUCTION_INGRESS:-shared}" in
    shared) ;;
    isolated)
      [[ -f infra/compose.isolated-ingress.candidate.yml ]] || {
        echo "Isolated ingress Compose overlay is missing" >&2
        return 1
      }
      production_compose_files+=(-f infra/compose.isolated-ingress.candidate.yml)
      ;;
    *)
      echo "Unknown production ingress mode; refusing deployment" >&2
      return 1
      ;;
  esac
}
