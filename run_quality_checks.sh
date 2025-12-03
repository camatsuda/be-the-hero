#!/bin/bash
#
# Quality checks script for WebApp Analytics ETL Pipeline
# This script runs all code quality checks needed for SonarQube analysis
#

set -e  # Exit on error

echo "========================================="
echo "WebApp Analytics - Quality Checks"
echo "========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if running in virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${YELLOW}Warning: Not running in a virtual environment${NC}"
    echo "Consider activating venv: source venv/bin/activate"
    echo ""
fi

# Install dependencies if needed
echo -e "${GREEN}[1/5] Checking dependencies...${NC}"
pip install -q pytest pytest-cov pylint bandit 2>/dev/null || echo "Dependencies already installed"
echo ""

# Run pytest with coverage
echo -e "${GREEN}[2/5] Running tests with coverage...${NC}"
pytest test_ingestion_final.py \
    -v \
    --cov=notebooks.dataproducts.webapp.ingestion \
    --cov-report=term-missing \
    --cov-report=html \
    --cov-report=xml:coverage.xml \
    --junitxml=test-results.xml
echo ""

# Check test results
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Tests passed${NC}"
else
    echo -e "${RED}✗ Tests failed${NC}"
    exit 1
fi
echo ""

# Run pylint
echo -e "${GREEN}[3/5] Running pylint code analysis...${NC}"
pylint notebooks/dataproducts/webapp/ingestion.py \
    --output-format=text \
    --reports=y \
    --score=y \
    > pylint-report.txt 2>&1 || true

PYLINT_SCORE=$(grep "Your code has been rated" pylint-report.txt | grep -oP '\d+\.\d+' | head -1)
echo "Pylint score: ${PYLINT_SCORE}/10.00"
echo ""

# Run bandit security check
echo -e "${GREEN}[4/5] Running bandit security analysis...${NC}"
bandit -r notebooks/dataproducts/webapp/ingestion.py \
    -f json \
    -o bandit-report.json \
    2>/dev/null || true

BANDIT_ISSUES=$(python3 -c "import json; print(len(json.load(open('bandit-report.json'))['results']))" 2>/dev/null || echo "0")
echo "Bandit found ${BANDIT_ISSUES} potential security issues"
echo ""

# Generate summary
echo -e "${GREEN}[5/5] Generating summary...${NC}"
echo ""
echo "========================================="
echo "Quality Checks Summary"
echo "========================================="

# Test coverage
COVERAGE=$(grep -oP 'TOTAL.*\K\d+%' coverage.xml 2>/dev/null | head -1 || echo "N/A")
echo "Test Coverage:    ${COVERAGE}"

# Pylint score
echo "Pylint Score:     ${PYLINT_SCORE}/10.00"

# Bandit issues
echo "Security Issues:  ${BANDIT_ISSUES}"

# Test results
TEST_COUNT=$(grep -oP 'tests="\K\d+' test-results.xml 2>/dev/null || echo "N/A")
TEST_FAILURES=$(grep -oP 'failures="\K\d+' test-results.xml 2>/dev/null || echo "0")
echo "Tests Run:        ${TEST_COUNT}"
echo "Test Failures:    ${TEST_FAILURES}"

echo "========================================="
echo ""

# Check if reports exist
echo "Generated reports:"
[ -f "coverage.xml" ] && echo -e "${GREEN}✓${NC} coverage.xml"
[ -f "htmlcov/index.html" ] && echo -e "${GREEN}✓${NC} htmlcov/index.html"
[ -f "test-results.xml" ] && echo -e "${GREEN}✓${NC} test-results.xml"
[ -f "pylint-report.txt" ] && echo -e "${GREEN}✓${NC} pylint-report.txt"
[ -f "bandit-report.json" ] && echo -e "${GREEN}✓${NC} bandit-report.json"
echo ""

echo -e "${GREEN}Quality checks complete!${NC}"
echo "Run 'sonar-scanner' to push results to SonarQube"
echo ""
