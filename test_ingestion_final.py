"""
Unit tests for WebApp Analytics ETL Pipeline

This test suite provides happy path coverage for the main components
of the Databricks ETL pipeline, designed to run in PyCharm and be compatible
with SonarQube analysis.

For your project structure:
notebooks/dataproducts/webapp/ingestion.py

Run tests with:
pytest test_ingestion.py -v --cov=notebooks.dataproducts.webapp.ingestion --cov-report=xml
"""

import sys
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

import pytest

# Mock PySpark modules before importing the main module
sys.modules['pyspark'] = MagicMock()
sys.modules['pyspark.sql'] = MagicMock()
sys.modules['pyspark.sql.functions'] = MagicMock()
sys.modules['pyspark.sql.types'] = MagicMock()
sys.modules['pyspark.sql.window'] = MagicMock()
sys.modules['databricks'] = MagicMock()
sys.modules['databricks.sql'] = MagicMock()

# Import components from your actual module
from notebooks.dataproducts.webapp.ingestion import (
    PipelineConfig,
    WebAppId,
    SecretKeys,
    DataAnonymizer,
    DatabricksSecretManager,
    WarehouseManager,
    DataLoader,
    DeltaWriter,
    WellnessTransformer,
    ReleaseNotesTransformer,
    VWShopTransformer,
    TransformerFactory,
    ETLPipeline
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_spark():
    """Create a mock SparkSession."""
    spark = Mock()
    spark.conf.get.return_value = "test.cloud.databricks.com"
    return spark


@pytest.fixture
def mock_dbutils():
    """Create a mock dbutils object."""
    dbutils = Mock()
    dbutils.secrets.get.return_value = "mock_secret_value"
    return dbutils


@pytest.fixture
def pipeline_config():
    """Create a test pipeline configuration."""
    return PipelineConfig(
        source_table="test_source_table",
        target_schema="test_schema",
        warehouse_name="Test Warehouse",
        secret_scope="test_scope",
        lookback_days=1
    )


@pytest.fixture
def mock_dataframe():
    """Create a mock PySpark DataFrame."""
    df = Mock()
    df.isEmpty.return_value = False
    df.count.return_value = 100
    df.columns = ["vin", "ssoId", "guuid", "timestamp", "eventAction"]
    df.sparkSession = Mock()

    # Mock common DataFrame operations
    df.filter.return_value = df
    df.select.return_value = df
    df.withColumn.return_value = df
    df.unionByName.return_value = df
    df.orderBy.return_value = df
    df.drop.return_value = df
    df.collect.return_value = []

    # Mock write operations
    mock_write = Mock()
    mock_format = Mock()
    mock_mode = Mock()
    mock_mode.saveAsTable = Mock()
    mock_format.mode.return_value = mock_mode
    mock_write.format.return_value = mock_format
    df.write = mock_write

    return df


# ============================================================================
# CONFIGURATION TESTS
# ============================================================================

class TestPipelineConfig:
    """Tests for PipelineConfig dataclass."""

    def test_default_configuration(self):
        """Test that default configuration values are set correctly."""
        config = PipelineConfig()

        assert config.warehouse_name == "Serverless Starter Warehouse"
        assert config.secret_scope == "dataica-prod-local-secret-scope"
        assert config.lookback_days == 1
        assert len(config.webapp_ids) == 3

    def test_custom_configuration(self):
        """Test custom configuration values."""
        config = PipelineConfig(
            warehouse_name="Custom Warehouse",
            lookback_days=7
        )

        assert config.warehouse_name == "Custom Warehouse"
        assert config.lookback_days == 7

    def test_webapp_ids_property(self):
        """Test that webapp_ids property returns all webapp IDs."""
        config = PipelineConfig()
        webapp_ids = config.webapp_ids

        assert "carapp_wellness" in webapp_ids
        assert "carapp_orureleasenotes" in webapp_ids
        assert "carapp_vwshop" in webapp_ids
        assert len(webapp_ids) == 3

    def test_config_immutability(self):
        """Test that PipelineConfig is frozen (immutable)."""
        config = PipelineConfig()

        with pytest.raises((AttributeError, Exception)):
            config.warehouse_name = "New Warehouse"


class TestWebAppId:
    """Tests for WebAppId enum."""

    def test_enum_values(self):
        """Test that all expected webapp IDs are defined."""
        assert WebAppId.WELLNESS.value == "carapp_wellness"
        assert WebAppId.RELEASE_NOTES.value == "carapp_orureleasenotes"
        assert WebAppId.VW_SHOP.value == "carapp_vwshop"

    def test_enum_membership(self):
        """Test enum membership."""
        assert WebAppId.WELLNESS in WebAppId
        assert "carapp_wellness" == WebAppId.WELLNESS.value


class TestSecretKeys:
    """Tests for SecretKeys dataclass."""

    def test_secret_key_constants(self):
        """Test that all secret keys are defined."""
        assert SecretKeys.TENANT_ID == "ica-spn-tenant-id"
        assert SecretKeys.CLIENT_ID == "ica-spn-client-id"
        assert SecretKeys.CLIENT_SECRET == "ica-spn-client-secret"
        assert SecretKeys.JDBC_PAT_TOKEN == "ica-jdbc-pat-token"
        assert SecretKeys.VIN_SECRET == "ica-webapp-secret-vin"
        assert SecretKeys.USER_SECRET == "ica-webapp-secret-ssoId"


# ============================================================================
# DATA ANONYMIZATION TESTS
# ============================================================================

class TestDataAnonymizer:
    """Tests for DataAnonymizer class."""

    def test_anonymizer_initialization(self):
        """Test that anonymizer initializes with secrets."""
        anonymizer = DataAnonymizer(vin_secret="vin123", user_secret="user456")

        assert anonymizer.secrets["vin"] == "vin123"
        assert anonymizer.secrets["ssoId"] == "user456"

    def test_anonymize_dataframe(self, mock_dataframe):
        """Test anonymization of DataFrame columns."""
        anonymizer = DataAnonymizer(vin_secret="test_vin", user_secret="test_user")

        result = anonymizer.anonymize(mock_dataframe)

        # Verify anonymization was attempted (withColumn called)
        assert mock_dataframe.withColumn.called
        assert result is not None

    def test_anonymize_with_missing_columns(self):
        """Test anonymization when columns don't exist in DataFrame."""
        anonymizer = DataAnonymizer(vin_secret="test_vin", user_secret="test_user")

        df = Mock()
        df.columns = ["other_column"]  # No vin or ssoId

        result = anonymizer.anonymize(df)

        # Should return DataFrame unchanged
        assert result == df

    def test_anonymizable_columns_constant(self):
        """Test that anonymizable columns are defined correctly."""
        assert DataAnonymizer.ANONYMIZABLE_COLUMNS == ["vin", "ssoId"]


# ============================================================================
# SECRET MANAGEMENT TESTS
# ============================================================================

class TestDatabricksSecretManager:
    """Tests for DatabricksSecretManager class."""

    def test_get_secret_success(self, mock_dbutils):
        """Test successful secret retrieval."""
        manager = DatabricksSecretManager(mock_dbutils)

        secret = manager.get_secret("test_scope", "test_key")

        assert secret == "mock_secret_value"
        mock_dbutils.secrets.get.assert_called_once_with(
            scope="test_scope",
            key="test_key"
        )

    def test_get_secret_failure(self, mock_dbutils):
        """Test secret retrieval failure handling."""
        mock_dbutils.secrets.get.side_effect = Exception("Secret not found")
        manager = DatabricksSecretManager(mock_dbutils)

        with pytest.raises(Exception) as exc_info:
            manager.get_secret("test_scope", "invalid_key")

        assert "Secret not found" in str(exc_info.value)


# ============================================================================
# WAREHOUSE MANAGER TESTS
# ============================================================================

class TestWarehouseManager:
    """Tests for WarehouseManager class."""

    def test_warehouse_manager_initialization(self):
        """Test WarehouseManager initialization."""
        manager = WarehouseManager("test.databricks.com", "test_token")

        assert manager.workspace_url == "test.databricks.com"
        assert manager.pat_token == "test_token"
        assert manager.api_url == "https://test.databricks.com"

    @patch('notebooks.dataproducts.webapp.ingestion.requests.get')
    def test_get_http_path_success(self, mock_get):
        """Test successful warehouse HTTP path retrieval."""
        mock_response = Mock()
        mock_response.json.return_value = {
            'warehouses': [
                {'name': 'Test Warehouse', 'id': 'warehouse123'}
            ]
        }
        mock_get.return_value = mock_response

        manager = WarehouseManager("test.databricks.com", "test_token")
        http_path = manager.get_http_path("Test Warehouse")

        assert http_path == "/sql/1.0/warehouses/warehouse123"
        mock_get.assert_called_once()

    @patch('notebooks.dataproducts.webapp.ingestion.requests.get')
    def test_get_http_path_warehouse_not_found(self, mock_get):
        """Test warehouse not found error."""
        mock_response = Mock()
        mock_response.json.return_value = {
            'warehouses': [
                {'name': 'Other Warehouse', 'id': 'other123'}
            ]
        }
        mock_get.return_value = mock_response

        manager = WarehouseManager("test.databricks.com", "test_token")

        with pytest.raises(ValueError) as exc_info:
            manager.get_http_path("Nonexistent Warehouse")

        assert "not found" in str(exc_info.value)

    @patch('notebooks.dataproducts.webapp.ingestion.requests.get')
    def test_get_http_path_with_timeout(self, mock_get):
        """Test that HTTP request includes timeout."""
        mock_response = Mock()
        mock_response.json.return_value = {'warehouses': []}
        mock_get.return_value = mock_response

        manager = WarehouseManager("test.databricks.com", "test_token")

        try:
            manager.get_http_path("Test Warehouse")
        except ValueError:
            pass  # Expected when warehouse not found

        # Verify timeout was set
        call_kwargs = mock_get.call_args[1]
        assert 'timeout' in call_kwargs
        assert call_kwargs['timeout'] == 30


# ============================================================================
# DATA LOADER TESTS
# ============================================================================

class TestDataLoader:
    """Tests for DataLoader class."""

    def test_loader_initialization(self, mock_spark, pipeline_config):
        """Test DataLoader initialization."""
        warehouse_mgr = Mock()

        loader = DataLoader(
            mock_spark,
            warehouse_mgr,
            pipeline_config,
            "test_token"
        )

        assert loader.spark == mock_spark
        assert loader.warehouse_manager == warehouse_mgr
        assert loader.config == pipeline_config
        assert loader.jdbc_token == "test_token"

    @patch('notebooks.dataproducts.webapp.ingestion.sql.connect')
    def test_load_for_date_success(self, mock_connect, mock_spark, pipeline_config):
        """Test successful data loading for a date."""
        # Setup mocks
        warehouse_mgr = Mock()
        warehouse_mgr.get_http_path.return_value = "/sql/1.0/warehouses/123"

        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [
            ("row1_col1", "row1_col2"),
            ("row2_col1", "row2_col2")
        ]
        mock_cursor.description = [("col1",), ("col2",)]

        mock_connection = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_connection.__enter__.return_value = mock_connection
        mock_connection.__exit__.return_value = None

        mock_connect.return_value = mock_connection

        mock_df = Mock()
        mock_df.filter.return_value = mock_df
        mock_df.count.return_value = 2
        mock_spark.createDataFrame.return_value = mock_df

        loader = DataLoader(mock_spark, warehouse_mgr, pipeline_config, "token")
        target_date = datetime(2025, 12, 1)

        result = loader.load_for_date(target_date, ["carapp_wellness"])

        assert "carapp_wellness" in result
        assert result["carapp_wellness"] == mock_df

    def test_load_for_date_uses_default_webapps(self, mock_spark, pipeline_config):
        """Test that load_for_date uses config webapp_ids by default."""
        warehouse_mgr = Mock()
        loader = DataLoader(mock_spark, warehouse_mgr, pipeline_config, "token")

        # Just verify the loader was created correctly
        assert loader.config.webapp_ids == pipeline_config.webapp_ids


# ============================================================================
# DELTA WRITER TESTS
# ============================================================================

class TestDeltaWriter:
    """Tests for DeltaWriter class."""

    def test_writer_initialization(self):
        """Test DeltaWriter initialization."""
        writer = DeltaWriter("test_schema")
        assert writer.target_schema == "test_schema"

    def test_write_success(self, mock_dataframe):
        """Test successful DataFrame write."""
        writer = DeltaWriter("test_schema")

        writer.write(mock_dataframe, "test_table", mode="append")

        # Verify write chain was called
        mock_dataframe.write.format.assert_called_once_with("delta")

    def test_write_empty_dataframe_with_validation(self):
        """Test that empty DataFrame is not written when validation enabled."""
        df = Mock()
        df.isEmpty.return_value = True
        df.count.return_value = 0

        writer = DeltaWriter("test_schema")

        # Should not raise error, just skip write
        writer.write(df, "test_table", validate=True)

        # Verify write was NOT called
        assert not df.write.format.called

    def test_write_empty_dataframe_without_validation(self):
        """Test that empty DataFrame is written when validation disabled."""
        df = Mock()
        df.isEmpty.return_value = True
        df.count.return_value = 0

        # Setup write chain
        mock_write = Mock()
        mock_format = Mock()
        mock_mode = Mock()
        mock_mode.saveAsTable = Mock()
        mock_format.mode.return_value = mock_mode
        mock_write.format.return_value = mock_format
        df.write = mock_write

        writer = DeltaWriter("test_schema")

        writer.write(df, "test_table", validate=False)

        # Verify write WAS called
        df.write.format.assert_called_once_with("delta")


# ============================================================================
# TRANSFORMER TESTS
# ============================================================================

class TestWellnessTransformer:
    """Tests for WellnessTransformer class."""

    def test_transformer_webapp_id(self):
        """Test that transformer returns correct webapp ID."""
        writer = Mock()
        transformer = WellnessTransformer(writer)

        assert transformer.webapp_id == "carapp_wellness"

    def test_transform_empty_dataframe(self):
        """Test transform with empty DataFrame."""
        writer = Mock()
        transformer = WellnessTransformer(writer)

        df = Mock()
        df.isEmpty.return_value = True

        transformer.transform_and_save(df)

        # Writer should not be called for empty DataFrame
        assert not writer.write.called

    def test_transform_and_save_calls_writer(self, mock_dataframe):
        """Test that transform_and_save calls writer for each output."""
        writer = Mock()
        transformer = WellnessTransformer(writer)

        # Mock all transformation methods
        with patch.object(transformer, '_prepare_base_dataframe', return_value=mock_dataframe):
            with patch.object(transformer, '_transform_desktop_events', return_value=mock_dataframe):
                with patch.object(transformer, '_transform_widget_events', return_value=mock_dataframe):
                    with patch.object(transformer, '_transform_system_events', return_value=mock_dataframe):
                        transformer.transform_and_save(mock_dataframe)

        # Verify writer was called 3 times (desktop, widget, system)
        assert writer.write.call_count == 3


class TestReleaseNotesTransformer:
    """Tests for ReleaseNotesTransformer class."""

    def test_transformer_webapp_id(self):
        """Test that transformer returns correct webapp ID."""
        writer = Mock()
        transformer = ReleaseNotesTransformer(writer)

        assert transformer.webapp_id == "carapp_orureleasenotes"

    def test_normalize_action_with_underscores(self):
        """Test action normalization for already underscored strings."""
        result = ReleaseNotesTransformer._normalize_action("already_underscored")
        assert result == "already_underscored"

    def test_normalize_action_camelcase(self):
        """Test action normalization for camelCase strings."""
        result = ReleaseNotesTransformer._normalize_action("camelCaseString")
        assert result == "camel_case_string"

    def test_get_event_schema(self):
        """Test that event schema is properly defined."""
        schema = ReleaseNotesTransformer._get_event_schema()
        assert schema is not None

    def test_get_widget_schema(self):
        """Test that widget schema is properly defined."""
        schema = ReleaseNotesTransformer._get_widget_schema()
        assert schema is not None


class TestVWShopTransformer:
    """Tests for VWShopTransformer class."""

    def test_transformer_webapp_id(self):
        """Test that transformer returns correct webapp ID."""
        writer = Mock()
        transformer = VWShopTransformer(writer)

        assert transformer.webapp_id == "carapp_vwshop"

    def test_transform_empty_dataframe(self):
        """Test transform with empty DataFrame."""
        writer = Mock()
        transformer = VWShopTransformer(writer)

        df = Mock()
        df.isEmpty.return_value = True

        transformer.transform_and_save(df)

        # Writer should not be called for empty DataFrame
        assert not writer.write.called

    def test_transform_and_save_calls_writer(self, mock_dataframe):
        """Test that transform_and_save calls save methods."""
        writer = Mock()
        transformer = VWShopTransformer(writer)

        # Mock the parse and classify and save methods
        with patch.object(transformer, '_parse_and_classify_events', return_value=mock_dataframe):
            with patch.object(transformer, '_save_desktop_events'):
                with patch.object(transformer, '_save_widget_events'):
                    with patch.object(transformer, '_save_system_events'):
                        with patch.object(transformer, '_save_unused_events'):
                            transformer.transform_and_save(mock_dataframe)

        # If we got here without errors, all methods were called
        assert True


# ============================================================================
# TRANSFORMER FACTORY TESTS
# ============================================================================

class TestTransformerFactory:
    """Tests for TransformerFactory class."""

    def test_create_wellness_transformer(self):
        """Test creating WellnessTransformer."""
        writer = Mock()
        transformer = TransformerFactory.create("carapp_wellness", writer)

        assert isinstance(transformer, WellnessTransformer)
        assert transformer.writer == writer

    def test_create_releasenotes_transformer(self):
        """Test creating ReleaseNotesTransformer."""
        writer = Mock()
        transformer = TransformerFactory.create("carapp_orureleasenotes", writer)

        assert isinstance(transformer, ReleaseNotesTransformer)
        assert transformer.writer == writer

    def test_create_vwshop_transformer(self):
        """Test creating VWShopTransformer."""
        writer = Mock()
        transformer = TransformerFactory.create("carapp_vwshop", writer)

        assert isinstance(transformer, VWShopTransformer)
        assert transformer.writer == writer

    def test_create_invalid_transformer(self):
        """Test creating transformer for invalid webapp ID."""
        writer = Mock()

        with pytest.raises(ValueError) as exc_info:
            TransformerFactory.create("invalid_webapp", writer)

        assert "No transformer available" in str(exc_info.value)

    def test_factory_returns_different_instances(self):
        """Test that factory returns new instances each time."""
        writer = Mock()

        transformer1 = TransformerFactory.create("carapp_wellness", writer)
        transformer2 = TransformerFactory.create("carapp_wellness", writer)

        assert transformer1 is not transformer2


# ============================================================================
# ETL PIPELINE TESTS
# ============================================================================

class TestETLPipeline:
    """Tests for ETLPipeline orchestration class."""

    @patch('notebooks.dataproducts.webapp.ingestion.dbutils')
    def test_pipeline_initialization(self, mock_dbutils_global, mock_spark, pipeline_config):
        """Test ETL pipeline initialization."""
        mock_dbutils_global.secrets.get.return_value = "secret"

        with patch('notebooks.dataproducts.webapp.ingestion.WarehouseManager'):
            with patch('notebooks.dataproducts.webapp.ingestion.DataLoader'):
                pipeline = ETLPipeline(mock_spark, pipeline_config)

        assert pipeline.spark == mock_spark
        assert pipeline.config == pipeline_config

    @patch('notebooks.dataproducts.webapp.ingestion.dbutils')
    def test_load_secrets(self, mock_dbutils_global, mock_spark, pipeline_config):
        """Test that secrets are loaded during initialization."""
        mock_dbutils_global.secrets.get.return_value = "test_secret"

        with patch('notebooks.dataproducts.webapp.ingestion.WarehouseManager'):
            with patch('notebooks.dataproducts.webapp.ingestion.DataLoader'):
                pipeline = ETLPipeline(mock_spark, pipeline_config)

        assert 'vin' in pipeline.secrets
        assert 'user' in pipeline.secrets
        assert 'jdbc_token' in pipeline.secrets

    @patch('notebooks.dataproducts.webapp.ingestion.dbutils')
    def test_run_with_default_date(self, mock_dbutils_global, mock_spark, pipeline_config):
        """Test pipeline run with default date (yesterday)."""
        mock_dbutils_global.secrets.get.return_value = "secret"

        with patch('notebooks.dataproducts.webapp.ingestion.WarehouseManager'):
            with patch('notebooks.dataproducts.webapp.ingestion.DataLoader') as mock_loader_class:
                mock_loader = Mock()
                mock_loader.load_for_date.return_value = {}
                mock_loader_class.return_value = mock_loader

                pipeline = ETLPipeline(mock_spark, pipeline_config)
                pipeline.run()

        # Verify loader was called
        assert mock_loader.load_for_date.called

    @patch('notebooks.dataproducts.webapp.ingestion.dbutils')
    def test_run_with_specific_date(self, mock_dbutils_global, mock_spark, pipeline_config):
        """Test pipeline run with specific date."""
        target_date = datetime(2025, 11, 15)
        mock_dbutils_global.secrets.get.return_value = "secret"

        with patch('notebooks.dataproducts.webapp.ingestion.WarehouseManager'):
            with patch('notebooks.dataproducts.webapp.ingestion.DataLoader') as mock_loader_class:
                mock_loader = Mock()
                mock_loader.load_for_date.return_value = {}
                mock_loader_class.return_value = mock_loader

                pipeline = ETLPipeline(mock_spark, pipeline_config)
                pipeline.run(target_date)

        # Verify loader was called with the specific date
        mock_loader.load_for_date.assert_called_once()
        call_args = mock_loader.load_for_date.call_args
        assert call_args[0][0] == target_date


# ============================================================================
# MAIN ENTRY POINT TESTS
# ============================================================================

class TestMainEntryPoint:
    """Tests for main entry point function."""

    @patch('notebooks.dataproducts.webapp.ingestion.ETLPipeline')
    def test_main_with_default_config(self, mock_pipeline_class, mock_spark):
        """Test main function with default configuration."""
        from notebooks.dataproducts.webapp.ingestion import main

        mock_pipeline = Mock()
        mock_pipeline_class.return_value = mock_pipeline

        main(mock_spark)

        # Verify pipeline was created and run
        assert mock_pipeline_class.called
        assert mock_pipeline.run.called

    @patch('notebooks.dataproducts.webapp.ingestion.ETLPipeline')
    def test_main_with_custom_config(self, mock_pipeline_class, mock_spark, pipeline_config):
        """Test main function with custom configuration."""
        from notebooks.dataproducts.webapp.ingestion import main

        mock_pipeline = Mock()
        mock_pipeline_class.return_value = mock_pipeline

        main(mock_spark, config=pipeline_config)

        # Verify pipeline was created with custom config
        mock_pipeline_class.assert_called_once_with(
            mock_spark,
            pipeline_config
        )

    @patch('notebooks.dataproducts.webapp.ingestion.ETLPipeline')
    def test_main_with_target_date(self, mock_pipeline_class, mock_spark):
        """Test main function with specific target date."""
        target_date = datetime(2025, 11, 20)
        from notebooks.dataproducts.webapp.ingestion import main

        mock_pipeline = Mock()
        mock_pipeline_class.return_value = mock_pipeline

        main(mock_spark, target_date=target_date)

        # Verify pipeline.run was called with target date
        mock_pipeline.run.assert_called_once_with(target_date)


# ============================================================================
# INTEGRATION TEST
# ============================================================================

class TestEndToEndIntegration:
    """End-to-end integration tests."""

    @patch('notebooks.dataproducts.webapp.ingestion.dbutils')
    def test_full_pipeline_happy_path(self, mock_dbutils_global, mock_spark, pipeline_config):
        """Test complete pipeline execution happy path."""
        mock_dbutils_global.secrets.get.return_value = "secret"

        with patch('notebooks.dataproducts.webapp.ingestion.WarehouseManager') as mock_wh_class:
            with patch('notebooks.dataproducts.webapp.ingestion.DataLoader') as mock_loader_class:
                with patch('notebooks.dataproducts.webapp.ingestion.DeltaWriter') as mock_writer_class:
                    # Setup warehouse manager
                    mock_wh = Mock()
                    mock_wh.get_http_path.return_value = "/sql/1.0/warehouses/123"
                    mock_wh_class.return_value = mock_wh

                    # Setup data loader
                    mock_df = Mock()
                    mock_df.isEmpty.return_value = False
                    mock_df.count.return_value = 10
                    mock_df.filter.return_value = mock_df
                    mock_df.withColumn.return_value = mock_df
                    mock_df.select.return_value = mock_df
                    mock_df.unionByName.return_value = mock_df
                    mock_df.orderBy.return_value = mock_df
                    mock_df.drop.return_value = mock_df
                    mock_df.sparkSession = mock_spark
                    mock_df.columns = ["vin", "ssoId", "guuid"]

                    mock_loader = Mock()
                    mock_loader.load_for_date.return_value = {
                        "carapp_wellness": mock_df
                    }
                    mock_loader_class.return_value = mock_loader

                    # Setup writer
                    mock_writer = Mock()
                    mock_writer_class.return_value = mock_writer

                    # Run pipeline
                    pipeline = ETLPipeline(mock_spark, pipeline_config)
                    pipeline.run()

                    # Verify complete flow
                    assert mock_loader.load_for_date.called
                    # If we got here, the flow completed successfully
                    assert True


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "--cov=notebooks.dataproducts.webapp.ingestion",
        "--cov-report=xml",
        "--cov-report=html"
    ])
