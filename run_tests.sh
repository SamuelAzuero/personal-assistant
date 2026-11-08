#!/usr/bin/env bash
# ==============================================================================
# Autonomous Cloud-Based Personal Assistant — Test Suite Runner
# ==============================================================================
# Runs the opaque-box comprehensive test suite across Tiers 1 to 4 and unit tests.
#
# Usage:
#   ./run_tests.sh            # Run all 4 E2E tiers (72 tests)
#   ./run_tests.sh --tier1    # Run Tier 1: Feature Coverage (30 tests)
#   ./run_tests.sh --tier2    # Run Tier 2: Boundary & Corner Cases (30 tests)
#   ./run_tests.sh --tier3    # Run Tier 3: Cross-Feature Interactions (8 tests)
#   ./run_tests.sh --tier4    # Run Tier 4: Real-World Scenarios (4 tests)
#   ./run_tests.sh --all      # Run all tests (including unit tests: 200 tests)
#   ./run_tests.sh --unit     # Run unit tests only
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Determine python/pytest binary
if [ -x "$SCRIPT_DIR/.venv/bin/pytest" ]; then
    PYTEST_BIN="$SCRIPT_DIR/.venv/bin/pytest"
elif command -v pytest >/dev/null 2>&1; then
    PYTEST_BIN="$(command -v pytest)"
else
    echo "ERROR: pytest not found. Please activate virtual environment or install dependencies."
    exit 1
fi

# Always isolate PYTHONPATH and disable ROS plugins
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"
ROS_FLAGS="-p no:launch_testing -p no:launch_testing_ros"

TARGETS=()
EXTRA_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --tier1)
            TARGETS+=("tests/tier1_feature_coverage/")
            ;;
        --tier2)
            TARGETS+=("tests/tier2_boundary_corner/")
            ;;
        --tier3)
            TARGETS+=("tests/tier3_combinations/")
            ;;
        --tier4)
            TARGETS+=("tests/tier4_real_world/")
            ;;
        --e2e)
            TARGETS+=("tests/tier1_feature_coverage/" "tests/tier2_boundary_corner/" "tests/tier3_combinations/" "tests/tier4_real_world/")
            ;;
        --unit)
            TARGETS+=("tests/unit/")
            ;;
        --all)
            TARGETS+=("tests/")
            ;;
        -h|--help)
            echo "Usage: $0 [--tier1] [--tier2] [--tier3] [--tier4] [--unit] [--all] [pytest-options]"
            exit 0
            ;;
        *)
            EXTRA_ARGS+=("$arg")
            ;;
    esac
done

# If no specific targets specified, default to all 4 E2E tiers (72 tests)
if [ ${#TARGETS[@]} -eq 0 ]; then
    TARGETS=("tests/tier1_feature_coverage/" "tests/tier2_boundary_corner/" "tests/tier3_combinations/" "tests/tier4_real_world/")
fi

echo "=============================================================================="
echo "Running Personal Assistant Test Runner"
echo "Targets: ${TARGETS[*]}"
echo "Interpreter: $PYTEST_BIN"
echo "=============================================================================="

exec "$PYTEST_BIN" $ROS_FLAGS "${TARGETS[@]}" "${EXTRA_ARGS[@]}"
