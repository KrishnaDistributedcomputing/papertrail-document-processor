#!/usr/bin/env bash
#
# Installs and starts Papertrail with Docker Compose.

set -euo pipefail

INSTALL_DIRECTORY=""
SOURCE_BUILD=false
NO_BROWSER=false
TEMP_DIRECTORY=""
readonly PUBLISHED_API_IMAGE="ghcr.io/krishnadistributedcomputing/papertrail-document-processor-api:latest"
readonly PUBLISHED_WEB_IMAGE="ghcr.io/krishnadistributedcomputing/papertrail-document-processor-web:latest"

usage() {
  echo "Usage: ${0##*/} [OPTIONS]"
  echo ""
  echo "Options:"
  echo "  --directory PATH  Install or run Papertrail in PATH"
  echo "  --source          Build application images from source"
  echo "  --no-browser      Do not open the portal after startup"
  echo "  --help, -h        Show this help message"
}

err() {
  printf "ERROR: %s\n" "$1" >&2
  exit 1
}

cleanup() {
  if [[ -n "${TEMP_DIRECTORY}" && -d "${TEMP_DIRECTORY}" ]]; then
    rm -rf "${TEMP_DIRECTORY}"
  fi
}

resolve_papertrail_root() {
  if [[ -n "${INSTALL_DIRECTORY}" ]]; then
    printf "%s\n" "${INSTALL_DIRECTORY}"
    return
  fi

  local script_path="${BASH_SOURCE[0]:-}"
  if [[ -n "${script_path}" && -f "${script_path}" ]]; then
    local script_directory
    script_directory="$(cd "$(dirname "${script_path}")" && pwd)"
    local local_root
    local_root="$(cd "${script_directory}/.." && pwd)"
    if [[ -f "${local_root}/compose.yaml" ]]; then
      printf "%s\n" "${local_root}"
      return
    fi
  fi

  printf "%s\n" "${HOME}/.papertrail"
}

assert_docker_ready() {
  if ! command -v docker &>/dev/null; then
    err "Docker is not installed. Install and start Docker Desktop or Docker Engine, then run this command again."
  fi

  if ! docker info --format '{{.ServerVersion}}' &>/dev/null; then
    err "Docker is installed but is not running. Start Docker, then run this command again."
  fi

  if ! docker compose version --short &>/dev/null; then
    err "Docker Compose v2 is required. Update Docker or install the Docker Compose plugin."
  fi
}

install_papertrail_source() {
  local destination="$1"
  if [[ -f "${destination}/compose.yaml" ]]; then
    return
  fi

  local -a existing_entries=()
  if [[ -d "${destination}" ]]; then
    shopt -s nullglob dotglob
    existing_entries=("${destination}"/*)
    shopt -u nullglob dotglob
  fi
  if (( ${#existing_entries[@]} > 0 )); then
    err "The installation directory is not empty: ${destination}"
  fi

  if ! command -v curl &>/dev/null; then
    err "curl is required to download Papertrail."
  fi
  if ! command -v tar &>/dev/null; then
    err "tar is required to unpack Papertrail."
  fi

  printf "Downloading Papertrail to %s ...\n" "${destination}"
  TEMP_DIRECTORY="$(mktemp -d)"
  local archive_path="${TEMP_DIRECTORY}/papertrail.tar.gz"
  local archive_url="https://github.com/KrishnaDistributedcomputing/papertrail-document-processor/archive/refs/heads/main.tar.gz"
  curl --fail --location --retry 3 --output "${archive_path}" \
    "${archive_url}"
  tar -xzf "${archive_path}" -C "${TEMP_DIRECTORY}"

  local source_root=""
  local candidate
  for candidate in "${TEMP_DIRECTORY}"/*; do
    if [[ -d "${candidate}" && -f "${candidate}/compose.yaml" ]]; then
      source_root="${candidate}"
      break
    fi
  done
  if [[ -z "${source_root}" ]]; then
    err "The downloaded archive does not contain a Papertrail deployment."
  fi

  mkdir -p "${destination}"
  cp -a "${source_root}/." "${destination}/"
  cleanup
  TEMP_DIRECTORY=""
}

run_compose() {
  local project_directory="$1"
  local manifest="$2"
  shift 2
  docker compose \
    --project-directory "${project_directory}" \
    -f "${project_directory}/${manifest}" \
    "$@"
}

run_published_compose() {
  local project_directory="$1"
  local manifest="$2"
  shift 2
  env \
    PAPERTRAIL_API_IMAGE="${PUBLISHED_API_IMAGE}" \
    PAPERTRAIL_WEB_IMAGE="${PUBLISHED_WEB_IMAGE}" \
    docker compose \
      --project-directory "${project_directory}" \
      -f "${project_directory}/${manifest}" \
      "$@"
}

get_papertrail_url() {
  local project_directory="$1"
  local manifest="$2"
  local port_output
  port_output="$(run_compose "${project_directory}" "${manifest}" port web 8080)"
  port_output="${port_output%%$'\n'*}"
  if [[ ! "${port_output}" =~ :([0-9]+)$ ]]; then
    err "Papertrail started, but its published web port could not be determined."
  fi
  printf "http://localhost:%s\n" "${BASH_REMATCH[1]}"
}

open_portal() {
  local portal_url="$1"
  case "$(uname -s)" in
    Darwin)
      open "${portal_url}" >/dev/null 2>&1 || true
      ;;
    MINGW*|MSYS*|CYGWIN*)
      cmd.exe /c start "" "${portal_url}" >/dev/null 2>&1 || true
      ;;
    *)
      if command -v xdg-open &>/dev/null; then
        xdg-open "${portal_url}" >/dev/null 2>&1 || true
      fi
      ;;
  esac
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --directory)
        if [[ -z "${2:-}" || "$2" == --* ]]; then
          err "--directory requires a path."
        fi
        INSTALL_DIRECTORY="$2"
        shift 2
        ;;
      --source)
        SOURCE_BUILD=true
        shift
        ;;
      --no-browser)
        NO_BROWSER=true
        shift
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        usage >&2
        err "Unknown option: $1"
        ;;
    esac
  done

  trap cleanup EXIT
  local project_directory
  project_directory="$(resolve_papertrail_root)"
  assert_docker_ready
  install_papertrail_source "${project_directory}"

  local source_manifest="compose.yaml"
  local published_manifest="compose.deploy.yaml"
  local active_manifest="${source_manifest}"

  if [[ "${SOURCE_BUILD}" == "false" ]]; then
    echo "Checking published application images ..."
    run_published_compose "${project_directory}" "${published_manifest}" \
      config --quiet
    if run_published_compose "${project_directory}" "${published_manifest}" \
      pull --quiet web api worker >/dev/null 2>&1; then
      active_manifest="${published_manifest}"
    else
      echo "Published images are unavailable. Building from public source instead ..."
    fi
  fi

  if [[ "${active_manifest}" == "${source_manifest}" ]]; then
    run_compose "${project_directory}" "${source_manifest}" config --quiet
    echo "Building and starting Papertrail ..."
    run_compose "${project_directory}" "${source_manifest}" \
      up --detach --build --wait --remove-orphans
  else
    echo "Starting Papertrail from published images ..."
    run_published_compose "${project_directory}" "${published_manifest}" \
      up --detach --wait --remove-orphans
  fi

  local portal_url
  portal_url="$(get_papertrail_url \
    "${project_directory}" "${active_manifest}")"
  if command -v curl &>/dev/null; then
    curl --fail --silent --show-error \
      "${portal_url}/api/v1/health/live" >/dev/null
  fi

  echo ""
  printf "Papertrail is ready: %s\n" "${portal_url}"
  printf "Installation: %s\n" "${project_directory}"
  echo "Run this launcher again at any time to start or repair the deployment."

  if [[ "${NO_BROWSER}" == "false" ]]; then
    open_portal "${portal_url}"
  fi
}

main "$@"
