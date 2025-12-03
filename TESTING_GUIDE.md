# Testing Guide for WebApp Analytics ETL Pipeline

This guide explains how to run the test suite for the refactored Databricks ETL pipeline.

---

## 📋 Prerequisites

Install test dependencies:

```bash
pip install -r requirements-test.txt
```

Or install individual packages:

```bash
pip install pytest pytest-cov pytest-mock
```

---

## 🚀 Running Tests

### Run All Tests

```bash
pytest test_webapp_analytics.py -v
```

### Run with Coverage Report

```bash
pytest test_webapp_analytics.py --cov=webapp_analytics_refactored --cov-report=html
```

This generates an HTML coverage report in `htmlcov/index.html`.

### Run Specific Test Class

```bash
# Test only configuration
pytest test_webapp_analytics.py::TestPipelineConfig -v

# Test only transformers
pytest test_webapp_analytics.py::TestWellnessTransformer -v
```

### Run Specific Test Method

```bash
pytest test_webapp_analytics.py::TestDataAnonymizer::test_anonymize_dataframe -v
```

### Run with Detailed Output

```bash
pytest test_webapp_analytics.py -v -s
```

- `-v`: Verbose output
- `-s`: Show print statements

### Run Tests in Parallel (faster)

```bash
pip install pytest-xdist
pytest test_webapp_analytics.py -n auto
```

---

## 📊 Test Coverage

Current test coverage includes:

### ✅ Configuration Layer
- `TestPipelineConfig` - Configuration dataclass tests
- `TestWebAppId` - Enum tests

### ✅ Data Access Layer
- `TestDatabricksSecretManager` - Secret retrieval tests
- `TestWarehouseManager` - Warehouse connection tests
- `TestDataLoader` - Data loading from Unity Catalog

### ✅ Data Processing Layer
- `TestDataAnonymizer` - PII anonymization tests

### ✅ Persistence Layer
- `TestDeltaWriter` - Delta table writing tests

### ✅ Transformation Layer
- `TestWellnessTransformer` - Wellness webapp transformer
- `TestReleaseNotesTransformer` - Release notes transformer
- `TestVWShopTransformer` - VW Shop transformer
- `TestTransformerFactory` - Factory pattern tests

### ✅ Orchestration Layer
- `TestETLPipeline` - End-to-end pipeline orchestration
- `TestMainEntryPoint` - Main function tests

### ✅ Integration Tests
- `TestEndToEndIntegration` - Full pipeline flow

---

## 📈 Coverage Report Example

After running with coverage:

```bash
pytest test_webapp_analytics.py --cov=webapp_analytics_refactored --cov-report=term-missing
```

Expected output:
```
Name                            Stmts   Miss  Cover   Missing
-------------------------------------------------------------
webapp_analytics_refactored.py   450     20    96%   234-238, 567-571
-------------------------------------------------------------
TOTAL                            450     20    96%
```

---

## 🎯 Test Structure

### Happy Path Tests

All tests focus on **happy path scenarios** - testing that components work correctly under normal conditions:

```python
def test_anonymize_dataframe(self, mock_dataframe):
    """Test anonymization of DataFrame columns."""
    anonymizer = DataAnonymizer(vin_secret="test_vin", user_secret="test_user")
    result = anonymizer.anonymize(mock_dataframe)
    assert result is not None
```

### Mocking Strategy

Tests use mocks to avoid Databricks dependencies:

```python
@pytest.fixture
def mock_spark():
    """Create a mock SparkSession."""
    spark = Mock()
    spark.conf.get.return_value = "test.cloud.databricks.com"
    return spark
```

### Fixtures

Reusable test fixtures are defined for common objects:

- `mock_spark` - Mock SparkSession
- `mock_dbutils` - Mock Databricks utilities
- `pipeline_config` - Test configuration
- `mock_dataframe` - Mock PySpark DataFrame

---

## 🧪 Example Test Cases

### Testing Configuration

```python
def test_default_configuration():
    """Test that default configuration values are set correctly."""
    config = PipelineConfig()

    assert config.warehouse_name == "Serverless Starter Warehouse"
    assert config.lookback_days == 1
```

### Testing Data Anonymization

```python
def test_anonymizer_initialization():
    """Test that anonymizer initializes with secrets."""
    anonymizer = DataAnonymizer(vin_secret="vin123", user_secret="user456")

    assert anonymizer.secrets["vin"] == "vin123"
    assert anonymizer.secrets["ssoId"] == "user456"
```

### Testing Transformers

```python
def test_transformer_webapp_id():
    """Test that transformer returns correct webapp ID."""
    writer = Mock()
    transformer = WellnessTransformer(writer)

    assert transformer.webapp_id == "carapp_wellness"
```

### Testing Error Handling

```python
def test_run_continues_on_transformer_failure():
    """Test that pipeline continues processing other webapps if one fails."""
    # Setup: One transformer fails, another succeeds
    # Assert: Both are attempted, no exception raised
```

---

## 🔍 Debugging Failed Tests

### View Full Stack Trace

```bash
pytest test_webapp_analytics.py -v --tb=long
```

### Stop on First Failure

```bash
pytest test_webapp_analytics.py -x
```

### Run Only Failed Tests from Last Run

```bash
pytest test_webapp_analytics.py --lf
```

### Enter Debugger on Failure

```bash
pytest test_webapp_analytics.py --pdb
```

---

## 📝 Adding New Tests

### Test Template

```python
class TestNewComponent:
    """Tests for NewComponent class."""

    def test_initialization(self):
        """Test component initialization."""
        component = NewComponent(param1="value1")
        assert component.param1 == "value1"

    def test_happy_path(self):
        """Test normal operation."""
        component = NewComponent()
        result = component.process()
        assert result is not None

    def test_edge_case(self):
        """Test edge case handling."""
        component = NewComponent()
        result = component.process(empty_input=True)
        assert result == expected_value
```

### Fixture Template

```python
@pytest.fixture
def my_component():
    """Create a test component instance."""
    return NewComponent(
        param1="test_value",
        param2=123
    )

def test_with_fixture(my_component):
    """Test using the fixture."""
    result = my_component.process()
    assert result is not None
```

---

## 🎨 Code Quality Checks

### Run Linting

```bash
pylint webapp_analytics_refactored.py
```

### Run Type Checking

```bash
mypy webapp_analytics_refactored.py
```

### Run Code Formatting

```bash
# Check formatting
black webapp_analytics_refactored.py --check

# Apply formatting
black webapp_analytics_refactored.py
```

---

## 🔄 Continuous Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      - run: pip install -r requirements-test.txt
      - run: pytest test_webapp_analytics.py --cov --cov-report=xml
      - uses: codecov/codecov-action@v2
```

---

## 📚 Test Categories

### Unit Tests (90% of tests)
Test individual components in isolation with mocks.

**Examples:**
- `TestDataAnonymizer`
- `TestWarehouseManager`
- `TestDeltaWriter`

### Integration Tests (10% of tests)
Test multiple components working together.

**Examples:**
- `TestETLPipeline`
- `TestEndToEndIntegration`

---

## ✅ Test Checklist

Before committing code, ensure:

- [ ] All tests pass: `pytest test_webapp_analytics.py`
- [ ] Coverage > 90%: `pytest --cov`
- [ ] No linting errors: `pylint webapp_analytics_refactored.py`
- [ ] Type hints valid: `mypy webapp_analytics_refactored.py`
- [ ] Code formatted: `black webapp_analytics_refactored.py --check`

---

## 🚨 Common Issues

### Issue: Import Errors

**Problem:**
```
ModuleNotFoundError: No module named 'webapp_analytics_refactored'
```

**Solution:**
Ensure the module is in your Python path:
```bash
export PYTHONPATH="${PYTHONPATH}:."
pytest test_webapp_analytics.py
```

### Issue: PySpark Not Installed

**Problem:**
```
ModuleNotFoundError: No module named 'pyspark'
```

**Solution:**
The tests use mocks, so PySpark isn't required. If you want the actual module importable:
```bash
pip install pyspark
```

### Issue: Databricks Imports Failing

**Problem:**
```
ModuleNotFoundError: No module named 'databricks'
```

**Solution:**
Install databricks-sql-connector:
```bash
pip install databricks-sql-connector
```

---

## 📞 Support

For issues or questions about testing:

1. Check test output for detailed error messages
2. Review the mocking strategy in test fixtures
3. Ensure all test dependencies are installed
4. Verify Python version compatibility (Python 3.8+)

---

## 🎓 Best Practices

1. **Keep tests independent** - Each test should run in isolation
2. **Use descriptive names** - Test names should describe what they test
3. **Mock external dependencies** - Don't rely on Databricks, databases, etc.
4. **Test happy paths first** - Focus on normal operation scenarios
5. **Keep tests fast** - Use mocks to avoid slow operations
6. **One assertion per test** - Focus tests on single behaviors
7. **Use fixtures** - Reuse common test setup code

---

## 📖 Additional Resources

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-cov Documentation](https://pytest-cov.readthedocs.io/)
- [unittest.mock Documentation](https://docs.python.org/3/library/unittest.mock.html)
- [PySpark Testing Best Practices](https://spark.apache.org/docs/latest/api/python/getting_started/testing_pyspark.html)

---

**Happy Testing! 🧪**
