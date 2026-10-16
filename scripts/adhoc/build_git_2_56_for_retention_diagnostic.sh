#!/usr/bin/env bash
# Purpose: build the CI Git version for #906's disposable-fixture diagnostic.
# Input: a new scratch directory; upstream git/git tag v2.56.0 (network required).
# Output: an uninstalled Git executable and source in that directory. 2026-10-16.
set -euo pipefail

build_root="${1:?Usage: $0 NEW_SCRATCH_DIRECTORY}"
if [[ -e "$build_root" ]]; then
    echo "Refusing to reuse an existing build directory: $build_root" >&2
    exit 1
fi
git clone --quiet --depth 1 --branch v2.56.0 https://github.com/git/git.git "$build_root"
expected_head=a018953688f1b10bddf91bff8747068f5f4746a4
actual_head=$(git -C "$build_root" rev-parse HEAD)
if [[ "$actual_head" != "$expected_head" ]]; then
    echo "Release commit differs from the inspected source: $actual_head" >&2
    exit 1
fi
make -C "$build_root" -j4 NO_GETTEXT=YesPlease NO_TCLTK=YesPlease \
    NO_PERL=YesPlease NO_CURL=YesPlease git
"$build_root/git" --version
git -C "$build_root" rev-parse HEAD
