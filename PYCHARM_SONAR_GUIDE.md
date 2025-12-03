# PyCharm & SonarQube Testing Guide

Complete guide for running tests in PyCharm and pushing results to SonarQube.

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install test dependencies
pip install -r requirements-test.txt
```

### 2. Run Tests in PyCharm

**Method 1: Using PyCharm UI**
1. Open `test_webapp_analytics.py` in PyCharm
2. Right-click anywhere in the file
3. Select "Run 'pytest in test_webapp_analytics.py'"

**Method 2: Using Terminal in PyCharm**
```bash
pytest test_webapp_analytics.py -v
```

### 3. Run All Quality Checks

```bash
chmod +x run_quality_checks.sh
./run_quality_checks.sh
```

This generates all reports needed for SonarQube.

### 4. Push to SonarQube

```bash
sonar-scanner
```

---

## 📋 Detailed Setup

### A. PyCharm Configuration

#### 1. Configure Python Interpreter

1. Go to: **File → Settings → Project → Python Interpreter**
2. Click the gear icon → **Add**
3. Select **Virtualenv Environment** → **New Environment**
4. Set location to: `./venv`
5. Click **OK**

#### 2. Install Dependencies in PyCharm

Open PyCharm terminal and run:
```bash
pip install -r requirements-test.txt
```

Dependencies installed:
- `pytest>=7.4.0` - Test framework
- `pytest-cov>=4.1.0` - Coverage plugin
- `pytest-mock>=3.11.1` - Mocking support
- `pylint>=2.17.0` - Code analysis
- `black>=23.7.0` - Code formatting
- `mypy>=1.4.1` - Type checking
- `bandit>=1.7.5` - Security analysis

#### 3. Configure Pytest in PyCharm

1. Go to: **File → Settings → Tools → Python Integrated Tools**
2. Set **Default test runner** to: **pytest**
3. Click **Apply** and **OK**

#### 4. Set Up Run Configuration

1. Click **Run → Edit Configurations**
2. Click **+** → **Python tests → pytest**
3. Configure:
   - **Name**: `WebApp Analytics Tests`
   - **Target**: `test_webapp_analytics.py`
   - **Additional Arguments**: `-v --cov=webapp_analytics_refactored --cov-report=html`
4. Click **Apply** and **OK**

---

## 🧪 Running Tests

### In PyCharm GUI

**Run All Tests:**
- Right-click `test_webapp_analytics.py` → **Run 'pytest in test_webapp...'**

**Run Specific Test Class:**
- Right-click class name (e.g., `TestDataAnonymizer`) → **Run**

**Run Single Test:**
- Click the green play icon next to test function
- Or right-click test function → **Run**

**With Coverage:**
- Right-click → **Run 'pytest in test_webapp...' with Coverage**

### In Terminal

```bash
# All tests
pytest test_webapp_analytics.py -v

# With coverage report
pytest test_webapp_analytics.py --cov=webapp_analytics_refactored --cov-report=html

# Specific test class
pytest test_webapp_analytics.py::TestDataAnonymizer -v

# Specific test
pytest test_webapp_analytics.py::TestDataAnonymizer::test_anonymize_dataframe -v

# Stop on first failure
pytest test_webapp_analytics.py -x

# Show print statements
pytest test_webapp_analytics.py -v -s
```

---

## 📊 Coverage Reports

### View Coverage in PyCharm

1. Run tests with coverage (right-click → **Run with Coverage**)
2. Coverage panel appears at bottom
3. Click file names to see covered/uncovered lines
4. Green = covered, Red = not covered

### View HTML Coverage Report

```bash
# Generate report
pytest test_webapp_analytics.py --cov=webapp_analytics_refactored --cov-report=html

# Open in browser
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

### Coverage Thresholds

Current coverage: **~95%**

SonarQube quality gates typically require:
- ✅ Coverage > 80%
- ✅ Duplications < 3%
- ✅ Maintainability Rating A
- ✅ Reliability Rating A
- ✅ Security Rating A

---

## 🔍 Code Quality Checks

### Run All Checks (Automated)

```bash
./run_quality_checks.sh
```

This script runs:
1. **Pytest** with coverage
2. **Pylint** code analysis
3. **Bandit** security checks
4. Generates all reports for SonarQube

### Manual Quality Checks

#### 1. Pylint (Code Quality)

```bash
# Run pylint
pylint webapp_analytics_refactored.py

# Generate report for SonarQube
pylint webapp_analytics_refactored.py \
    --output-format=text \
    --reports=y \
    > pylint-report.txt
```

**Score interpretation:**
- 10.0: Perfect
- 8.0-9.9: Excellent
- 7.0-7.9: Good
- 6.0-6.9: Acceptable
- < 6.0: Needs improvement

#### 2. Bandit (Security)

```bash
# Run security check
bandit -r webapp_analytics_refactored.py

# Generate JSON report for SonarQube
bandit -r webapp_analytics_refactored.py \
    -f json \
    -o bandit-report.json
```

#### 3. Mypy (Type Checking)

```bash
# Check types
mypy webapp_analytics_refactored.py
```

#### 4. Black (Code Formatting)

```bash
# Check formatting
black webapp_analytics_refactored.py --check

# Auto-format
black webapp_analytics_refactored.py
```

---

## 📈 SonarQube Integration

### Prerequisites

1. **SonarQube Server**: Running instance (local or cloud)
2. **Sonar Scanner**: Install from https://docs.sonarqube.org/latest/analysis/scan/sonarscanner/

Install Sonar Scanner:
```bash
# macOS
brew install sonar-scanner

# Linux
wget https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-4.8.0.2856-linux.zip
unzip sonar-scanner-cli-4.8.0.2856-linux.zip
export PATH=$PATH:$(pwd)/sonar-scanner-4.8.0.2856-linux/bin

# Verify installation
sonar-scanner --version
```

### Configuration

The project includes `sonar-project.properties` with:
- Project key: `webapp-analytics-etl`
- Project name: `WebApp Analytics ETL Pipeline`
- Coverage reports: `coverage.xml`
- Test reports: `test-results.xml`

**Edit `sonar-project.properties`** if needed:
```properties
sonar.host.url=http://localhost:9000
sonar.login=your_sonar_token_here
```

### Run Analysis

#### Step 1: Generate Reports

```bash
./run_quality_checks.sh
```

This creates:
- `coverage.xml` - Test coverage
- `test-results.xml` - Test results
- `pylint-report.txt` - Code quality
- `bandit-report.json` - Security analysis

#### Step 2: Run Sonar Scanner

```bash
sonar-scanner \
  -Dsonar.projectKey=webapp-analytics-etl \
  -Dsonar.sources=webapp_analytics_refactored.py \
  -Dsonar.host.url=http://localhost:9000 \
  -Dsonar.login=your_token_here
```

Or if `sonar-project.properties` is configured:
```bash
sonar-scanner
```

#### Step 3: View Results

1. Open SonarQube: http://localhost:9000
2. Find project: **WebApp Analytics ETL Pipeline**
3. Review:
   - **Overview**: Quality gate status
   - **Issues**: Code smells, bugs, vulnerabilities
   - **Measures**: Coverage, duplications, complexity
   - **Code**: Annotated source code

---

## 🐛 Troubleshooting

### Issue: Import Errors in PyCharm

**Problem:**
```
ModuleNotFoundError: No module named 'pyspark'
```

**Solution:**
The test file mocks PySpark modules. If PyCharm shows import errors:
1. The tests will still run (mocks are in place)
2. To remove warnings, install PySpark: `pip install pyspark`
3. Or mark warnings as expected in PyCharm settings

### Issue: Coverage Not Showing in PyCharm

**Problem:** Coverage panel doesn't appear

**Solution:**
1. Ensure pytest-cov is installed: `pip install pytest-cov`
2. Right-click → **Run with Coverage** (not just Run)
3. Or run with coverage from terminal:
   ```bash
   pytest --cov=webapp_analytics_refactored --cov-report=html
   ```

### Issue: Tests Pass Locally But Fail in CI

**Problem:** Tests fail in CI/CD pipeline

**Solution:**
1. Check Python version matches (tests support 3.8+)
2. Ensure all dependencies installed
3. Check that mocks are properly configured
4. Verify no environment-specific assumptions

### Issue: SonarQube Not Finding Coverage

**Problem:** SonarQube shows 0% coverage

**Solution:**
1. Verify `coverage.xml` exists: `ls -la coverage.xml`
2. Check `sonar-project.properties`:
   ```properties
   sonar.python.coverage.reportPaths=coverage.xml
   ```
3. Ensure tests ran successfully before running sonar-scanner
4. Check SonarQube logs for import errors

### Issue: Pylint Score Too Low

**Problem:** Pylint score < 8.0

**Solution:**
1. Review pylint output: `cat pylint-report.txt`
2. Common issues:
   - **Line too long**: Wrap at 100 characters
   - **Missing docstrings**: Add docstrings to functions
   - **Too many arguments**: Refactor functions
   - **Complexity too high**: Break down complex functions
3. Disable specific checks if needed:
   ```python
   # pylint: disable=line-too-long
   ```

---

## 📁 Generated Files

After running quality checks, you'll have:

```
.
├── coverage.xml              # Coverage data (SonarQube)
├── htmlcov/                  # HTML coverage report
│   └── index.html           # Open in browser
├── test-results.xml          # JUnit test results (SonarQube)
├── pylint-report.txt         # Code quality report
├── bandit-report.json        # Security analysis
└── .coverage                 # Coverage data file
```

---

## ✅ Pre-Push Checklist

Before pushing to SonarQube:

- [ ] All tests pass: `pytest test_webapp_analytics.py`
- [ ] Coverage > 90%: Check `htmlcov/index.html`
- [ ] Pylint score > 8.0: Check `pylint-report.txt`
- [ ] No critical security issues: Check `bandit-report.json`
- [ ] Code formatted: `black webapp_analytics_refactored.py --check`
- [ ] Types valid: `mypy webapp_analytics_refactored.py`
- [ ] All reports generated: `ls coverage.xml test-results.xml`

Run all at once:
```bash
./run_quality_checks.sh && sonar-scanner
```

---

## 🔗 Additional Resources

### Documentation
- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest Coverage](https://pytest-cov.readthedocs.io/)
- [SonarQube Python](https://docs.sonarqube.org/latest/analysis/languages/python/)
- [Pylint Documentation](https://pylint.pycqa.org/)
- [Bandit Documentation](https://bandit.readthedocs.io/)

### PyCharm Tips
- **Keyboard Shortcuts**:
  - Run tests: `Ctrl+Shift+F10` (Windows/Linux) or `Cmd+Shift+R` (macOS)
  - Run with coverage: `Ctrl+Shift+F10` → Select "with Coverage"
  - Jump to test: `Ctrl+Shift+T`

### SonarQube Best Practices
- Run analysis on every commit
- Fix issues as they appear (don't accumulate technical debt)
- Maintain coverage above 80%
- Address security vulnerabilities immediately
- Review code smells regularly

---

## 🎯 Summary

### For Development in PyCharm:
```bash
# 1. Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements-test.txt

# 2. Run tests (use PyCharm UI or terminal)
pytest test_webapp_analytics.py -v --cov=webapp_analytics_refactored

# 3. View coverage
open htmlcov/index.html
```

### For SonarQube Analysis:
```bash
# 1. Generate all reports
./run_quality_checks.sh

# 2. Push to SonarQube
sonar-scanner

# 3. View results
open http://localhost:9000
```

---

**Happy Testing! 🧪**
