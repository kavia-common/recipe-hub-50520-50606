#!/bin/bash
cd /home/kavia/workspace/code-generation/recipe-hub-50520-50606/recipe_backend
source venv/bin/activate
flake8 .
LINT_EXIT_CODE=$?
if [ $LINT_EXIT_CODE -ne 0 ]; then
  exit 1
fi

